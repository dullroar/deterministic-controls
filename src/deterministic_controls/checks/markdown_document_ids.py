"""Check `markdown.document-ids`.

Run me when: each Markdown file must have a stable, unique ID in its front matter.

Parameters:

- `glob`: the files to check (repository-relative pattern).
- `key`: the front matter key that holds the ID (default `id`).
- `registry`: optional TOML file with a table `[ids]` that maps a path to its ID.

Rules: every matching file has a non-empty ID. IDs are unique (compared after
Unicode NFC). An ID has no spaces. With a registry, an ID that differs from
its registry entry is `changed`. A registry path that has no file is `orphan`.

Rule IDs: `missing`, `empty`, `bad-id`, `duplicate`, `changed`, `orphan`,
`bad-config`. The rule `bad-id` covers an ID with a space and an ID that is a
list.

The check works on any Markdown repository. It has no project name in its code.
Without the parameter `glob`, the check passes with no findings.
"""

from __future__ import annotations

import tomllib
import unicodedata

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.checks.markdown_front_matter import parse_front_matter
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "markdown.document-ids"

RULES = ("missing", "empty", "bad-id", "duplicate", "changed", "orphan")


def _load_registry(context: Context) -> tuple[str, dict[str, str]] | None:
    value = context.parameters.get("registry")
    if value is None or value == "":
        return None
    rel = tc._clean_relpath(value, "parameter 'registry'")
    try:
        path = context.resolve(rel)
    except ValueError as error:
        raise tc.ConfigError(str(error), rel) from error
    if not rel or not path.is_file():
        raise tc.ConfigError(f"parameter 'registry' names a missing file: {value}", rel)
    try:
        data = tomllib.loads(context.read_text(rel))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise tc.ConfigError(f"registry is not readable TOML: {error}", rel) from error
    unknown = sorted(set(data) - {"ids"})
    if unknown or not isinstance(data.get("ids"), dict):
        raise tc.ConfigError("registry must hold only the table [ids]", rel)
    ids: dict[str, str] = {}
    for key, ident in data["ids"].items():
        if not isinstance(ident, str):
            raise tc.ConfigError(f"registry ID of '{key}' must be a string", rel)
        ids[tc._clean_relpath(key, "registry path")] = ident
    return rel, ids


def entry(context: Context) -> list[Finding]:
    glob = context.parameters.get("glob")
    key = context.parameters.get("key", "id")
    try:
        if glob is None or glob == "":
            if context.parameters.get("registry") not in (None, ""):
                raise tc.ConfigError("parameter 'registry' needs the parameter 'glob'")
            return []
        if not isinstance(glob, str):
            raise tc.ConfigError("parameter 'glob' must be a string")
        if not isinstance(key, str) or not key.strip():
            raise tc.ConfigError("parameter 'key' must be a non-empty string")
        registry = _load_registry(context)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]

    findings: list[Finding] = []
    seen: dict[str, str] = {}
    registry_ids = registry[1] if registry else {}
    for path in context.list_files(glob):
        fm = parse_front_matter(context.read_text(path))
        value = fm.values.get(key) if fm.present and fm.closed else None
        if value is None:
            reason = (
                "the file has no front matter" if not fm.present
                else "the front matter is not closed" if not fm.closed
                else f"front matter has no key '{key}'"
            )
            findings.append(tc.make_finding(CHECK_ID, "missing", path, 1, reason))
            continue
        line = fm.lines[key]
        if isinstance(value, list):
            findings.append(tc.make_finding(
                CHECK_ID, "bad-id", path, line, "the ID must be one value, not a list"))
            continue
        if not value.strip():
            findings.append(tc.make_finding(
                CHECK_ID, "empty", path, line, f"the key '{key}' has an empty value"))
            continue
        if any(ch.isspace() for ch in value):
            findings.append(tc.make_finding(
                CHECK_ID, "bad-id", path, line, "the ID has a space", evidence=value))
            continue
        ident = unicodedata.normalize("NFC", value)
        if ident in seen:
            findings.append(tc.make_finding(
                CHECK_ID, "duplicate", path, line,
                f"the ID is also used by {seen[ident]}", evidence=value))
        else:
            seen[ident] = path
        expected = registry_ids.get(path)
        if expected is not None and unicodedata.normalize("NFC", expected) != ident:
            findings.append(tc.make_finding(
                CHECK_ID, "changed", path, line,
                f"the ID differs from the registry ({registry[0]})",
                evidence=f"registry: {expected}; file: {value}"))
    for reg_path in sorted(registry_ids):
        if not context.resolve(reg_path).is_file():
            findings.append(tc.make_finding(
                CHECK_ID, "orphan", reg_path, None,
                f"the registry ({registry[0]}) lists a path with no file"))
    return findings
