"""Check `translation.chunks`: the chunks of a target match the source manifest.

The check is generic. It works on any translation that has a source manifest.
It needs no Markdown parser. It compares two JSONL files.

Parameters (paths inside the repository):

- `source_manifest`: one JSON object on each line. Fields: `id` (stable chunk
  ID), `path` (source file) and `digest` (SHA-256 hex digest of the source text).
- `target_manifest`: one JSON object on each line. Fields: `id`, `path` (target
  file), `source_digest` (the source digest the translator used). Optional
  fields: `status`, `text` or `text_digest` (SHA-256 hex digest of the text),
  and `custom_id`.
- `custom_id_digits` (default `12`): length of the digest prefix in `custom_id`.

Blank lines are ignored. IDs are compared exactly: case and Unicode form count.

Rules (the rule ID is `translation.chunks.<rule>`):

- `missing`: a source ID has no target row.
- `orphan`: a target ID is not in the source manifest.
- `duplicate`: an ID appears twice in one manifest.
- `stale`: `source_digest` of the target differs from `digest` of the source.
- `empty`: a target row has an empty text.
- `fuzzy`: a target row has status `fuzzy` or `needs-review`.
- `custom-id`: `custom_id` is not `<id>` plus the first N digest digits.
  The rule runs only if at least one target row has `custom_id`.
- `bad-manifest`: a row is not valid JSON, lacks `id` or its digest, or a
  manifest file is missing. This is never a pass.

No `source_manifest` parameter: no findings. A parameter with a wrong value
gives `bad-config`. A finding names the target path and the line in the
target manifest. If no target row exists, the path is the target manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.chunks"
FUZZY_STATUSES = {"fuzzy", "needs-review"}
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class Row:
    line: int
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]


def _param(context: Context, name: str) -> Any:
    value = context.parameters.get(name)
    return None if value == "" else value


def _load_manifest(
    context: Context, rel: str, digest_key: str, role: str
) -> tuple[list[Row], list[Finding]]:
    """Read a JSONL manifest. Bad rows give `bad-manifest` findings."""
    try:
        path = context.resolve(rel)
    except ValueError:
        return [], [tc.make_finding(
            CHECK_ID, "bad-manifest", rel, None, f"{role} manifest leaves the repository")]
    if not path.is_file():
        return [], [tc.make_finding(
            CHECK_ID, "bad-manifest", rel, None, f"{role} manifest file is missing")]
    try:
        text = context.read_text(rel)
    except (OSError, UnicodeDecodeError) as error:
        return [], [tc.make_finding(
            CHECK_ID, "bad-manifest", rel, None, f"cannot read {role} manifest: {error}")]
    rows: list[Row] = []
    findings: list[Finding] = []

    def bad(number: int, message: str) -> None:
        findings.append(tc.make_finding(
            CHECK_ID, "bad-manifest", rel, number, f"{role} manifest: {message}"))

    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            bad(number, f"row is not valid JSON: {error}")
            continue
        if not isinstance(data, dict):
            bad(number, "row is not a JSON object")
            continue
        chunk_id = data.get("id")
        if not isinstance(chunk_id, str) or not chunk_id:
            bad(number, "row has no 'id'")
            continue
        digest = data.get(digest_key)
        if not isinstance(digest, str) or not digest:
            bad(number, f"row has no '{digest_key}'")
            continue
        rows.append(Row(number, data))
    return rows, findings


def _unique(
    rows: list[Row], rel: str, role: str
) -> tuple[dict[str, Row], list[Finding]]:
    """Index rows by ID. The first row of an ID wins. Others are `duplicate`."""
    index: dict[str, Row] = {}
    findings: list[Finding] = []
    for row in rows:
        if row.id in index:
            path = row.data.get("path")
            findings.append(tc.make_finding(
                CHECK_ID, "duplicate", path if isinstance(path, str) and role == "target" else rel,
                row.line,
                f"ID appears twice in the {role} manifest (first on line {index[row.id].line})",
                evidence=row.id))
        else:
            index[row.id] = row
    return index, findings


def _row_path(row: Row, fallback: str) -> str:
    path = row.data.get("path")
    return path if isinstance(path, str) and path else fallback


def _is_empty(data: dict[str, Any]) -> bool:
    if "text" in data:
        text = data["text"]
        return not isinstance(text, str) or not text.strip()
    digest = data.get("text_digest")
    return isinstance(digest, str) and digest.lower() == EMPTY_DIGEST


def _custom_digits(context: Context) -> int:
    value = context.parameters.get("custom_id_digits", 12)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 64:
        raise tc.ConfigError("parameter 'custom_id_digits' must be an integer from 1 to 64")
    return value


def entry(context: Context) -> list[Finding]:
    source_rel = _param(context, "source_manifest")
    if source_rel is None:
        return []
    target_rel = _param(context, "target_manifest")
    try:
        digits = _custom_digits(context)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]
    if not isinstance(source_rel, str):
        return [tc.make_finding(
            CHECK_ID, "bad-config", None, None, "parameter 'source_manifest' must be a path")]
    if not isinstance(target_rel, str):
        return [tc.make_finding(
            CHECK_ID, "bad-manifest", source_rel, None,
            "parameter 'target_manifest' is missing: no target to compare")]

    source_rows, findings = _load_manifest(context, source_rel, "digest", "source")
    target_rows, target_bad = _load_manifest(context, target_rel, "source_digest", "target")
    findings += target_bad
    sources, dup = _unique(source_rows, source_rel, "source")
    targets, dup_target = _unique(target_rows, target_rel, "target")
    findings += dup + dup_target
    if any(f.rule_id == f"{CHECK_ID}.bad-manifest" for f in findings):
        # A manifest that cannot be read is no basis for a comparison.
        return findings

    for chunk_id, source in sources.items():
        if chunk_id not in targets:
            findings.append(tc.make_finding(
                CHECK_ID, "missing", target_rel, None,
                "source chunk has no target row", source=_row_path(source, source_rel),
                evidence=chunk_id))
    use_custom = any("custom_id" in row.data for row in targets.values())
    for chunk_id, row in targets.items():
        path = _row_path(row, target_rel)
        source = sources.get(chunk_id)
        if source is None:
            findings.append(tc.make_finding(
                CHECK_ID, "orphan", path, row.line,
                "target chunk is not in the source manifest", evidence=chunk_id))
            continue
        source_path = _row_path(source, source_rel)
        source_digest = source.data["digest"].lower()
        if row.data["source_digest"].lower() != source_digest:
            findings.append(tc.make_finding(
                CHECK_ID, "stale", path, row.line,
                "target source_digest differs from the source digest",
                source=source_path, evidence=chunk_id))
        if _is_empty(row.data):
            findings.append(tc.make_finding(
                CHECK_ID, "empty", path, row.line, "target chunk text is empty",
                source=source_path, evidence=chunk_id))
        if row.data.get("status") in FUZZY_STATUSES:
            findings.append(tc.make_finding(
                CHECK_ID, "fuzzy", path, row.line,
                f"target chunk status is '{row.data['status']}'",
                source=source_path, evidence=chunk_id))
        if use_custom:
            expected = chunk_id + source_digest[:digits]
            if row.data.get("custom_id") != expected:
                findings.append(tc.make_finding(
                    CHECK_ID, "custom-id", path, row.line,
                    f"custom_id must be the ID plus the first {digits} digest digits",
                    source=source_path, evidence=chunk_id))
    return findings
