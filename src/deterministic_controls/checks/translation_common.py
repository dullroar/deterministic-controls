"""Shared helpers of the translation and Markdown pack.

This module is not a check. It has no catalog file and no `entry` function.
The checks of the pack (`translation.*`) use it. It uses the standard library
only. It reads files only through the `Context` helpers and never writes.

It gives four things:

- Loaders for the parameters `mapping` and `exceptions`.
- Pairing of source and target Markdown files from the mapping.
- A small Markdown scanner (line classes and fences).
- Helpers to build a `Finding` and to apply the exception file.

A parameter that is absent means "not configured". The loaders then return
`None` or an empty list, and the check passes. A parameter that names a
missing or bad file raises `ConfigError`. The check turns it into a finding
with the rule `<check-id>.bad-config` (see `bad_config_finding`).
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from deterministic_controls.core.api import Context, Finding

# --- Errors and findings ----------------------------------------------------


class ConfigError(Exception):
    """A pack parameter is present but wrong (missing file, bad syntax, bad key)."""

    def __init__(self, message: str, path: str | None = None):
        super().__init__(message)
        self.path = path


def make_finding(
    check_id: str,
    rule: str,
    path: str | None,
    line: int | None,
    message: str,
    *,
    source: str | None = None,
    severity: str = "error",
    evidence: str = "",
) -> Finding:
    """Build a `Finding` with rule ID `<check-id>.<rule>`.

    `path` and `line` are the TARGET path and line. `source` is the source
    path. It is added to the message.
    """
    if source:
        message = f"{message} (source: {source})"
    return Finding(f"{check_id}.{rule}", severity, path, line, message, evidence)


def bad_config_finding(check_id: str, error: ConfigError) -> Finding:
    return make_finding(check_id, "bad-config", error.path, None, str(error))


# --- Parameter loading ------------------------------------------------------


def _clean_relpath(value: Any, what: str) -> str:
    """Return a normalized repository-relative POSIX path or raise ConfigError."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{what} must be a non-empty string")
    text = value.replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", text) or ".." in pure.parts:
        raise ConfigError(f"{what} leaves the repository: {value}")
    clean = pure.as_posix()
    return "" if clean == "." else clean


def _read_parameter_file(context: Context, name: str) -> tuple[str, str] | None:
    """Return (relpath, text) for the parameter `name`, or None if it is absent."""
    value = context.parameters.get(name)
    if value is None:
        return None
    rel = _clean_relpath(value, f"parameter '{name}'")
    if not rel:
        raise ConfigError(f"parameter '{name}' must name a file", rel)
    try:
        target = context.resolve(rel)
    except ValueError as error:
        raise ConfigError(f"parameter '{name}' leaves the repository: {value}", rel) from error
    if not target.is_file():
        raise ConfigError(f"parameter '{name}' names a missing file: {rel}", rel)
    try:
        return rel, context.read_text(rel)
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read {rel}: {error}", rel) from error


@dataclass(frozen=True)
class Mapping:
    """The mapping file: source root, target root, path and anchor renames."""

    path: str
    source_root: str
    target_root: str
    path_renames: dict[str, str] = field(default_factory=dict)
    anchor_renames: dict[str, str] = field(default_factory=dict)


def _string_table(data: dict[str, Any], key: str, rel: str) -> dict[str, str]:
    table = data.get(key, {})
    if not isinstance(table, dict):
        raise ConfigError(f"'{key}' must be a table", rel)
    for k, v in table.items():
        if not isinstance(v, str) or not v:
            raise ConfigError(f"'{key}' value for '{k}' must be a non-empty string", rel)
    return dict(table)


def load_mapping(context: Context) -> Mapping | None:
    """Load the file named by the parameter `mapping`. Return None if not configured."""
    loaded = _read_parameter_file(context, "mapping")
    if loaded is None:
        return None
    rel, text = loaded
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"mapping file is not valid TOML: {error}", rel) from error
    allowed = {"source_root", "target_root", "path_renames", "anchor_renames"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"unknown mapping key: {', '.join(unknown)}", rel)
    for key in ("source_root", "target_root"):
        if key not in data:
            raise ConfigError(f"mapping file has no '{key}'", rel)
    try:
        source_root = _clean_relpath(data["source_root"], "source_root")
        target_root = _clean_relpath(data["target_root"], "target_root")
        path_renames = {
            _clean_relpath(k, "path_renames key"): _clean_relpath(v, "path_renames value")
            for k, v in _string_table(data, "path_renames", rel).items()
        }
    except ConfigError as error:
        raise ConfigError(str(error), rel) from error
    if source_root == target_root:
        raise ConfigError("source_root and target_root must differ", rel)
    anchor_renames = _string_table(data, "anchor_renames", rel)
    return Mapping(rel, source_root, target_root, path_renames, anchor_renames)


@dataclass(frozen=True)
class ExceptionRow:
    rule: str
    path: str
    reason: str
    origin: str  # path of the exception file


def _exception_rows(rel: str, text: str) -> list[Any]:
    if rel.endswith(".jsonl"):
        rows = []
        for number, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as error:
                raise ConfigError(f"line {number} is not valid JSON: {error}", rel) from error
        return rows
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"exception file is not valid TOML: {error}", rel) from error
    unknown = sorted(set(data) - {"exception"})
    if unknown:
        raise ConfigError(f"unknown exception file key: {', '.join(unknown)}", rel)
    rows = data.get("exception", [])
    if not isinstance(rows, list):
        raise ConfigError("'exception' must be an array of tables", rel)
    return rows


def load_exceptions(context: Context) -> list[ExceptionRow]:
    """Load the file named by the parameter `exceptions`. Return [] if not configured.

    A row needs a `rule`, a `path` and a non-empty `reason`. A row without a
    reason raises `ConfigError`.
    """
    loaded = _read_parameter_file(context, "exceptions")
    if loaded is None:
        return []
    rel, text = loaded
    result = []
    for index, row in enumerate(_exception_rows(rel, text), 1):
        if not isinstance(row, dict):
            raise ConfigError(f"exception row {index} must be a table", rel)
        extra = sorted(set(row) - {"rule", "path", "reason"})
        if extra:
            raise ConfigError(f"exception row {index} has unknown key: {', '.join(extra)}", rel)
        values = {}
        for key in ("rule", "path", "reason"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"exception row {index} has no '{key}'", rel)
            values[key] = value.strip()
        result.append(ExceptionRow(values["rule"], values["path"], values["reason"], rel))
    return result


def apply_exceptions(
    check_id: str, findings: list[Finding], rows: list[ExceptionRow]
) -> list[Finding]:
    """Remove the findings that a row waives. Add `stale-exception` for unused rows.

    A row waives a finding if its `rule` equals the rule ID and its `path`
    equals the finding path. Rows for rules of other checks are ignored.
    Findings `bad-config` and `stale-exception` cannot be waived.
    """
    prefix = f"{check_id}."
    unwaivable = {f"{check_id}.bad-config", f"{check_id}.stale-exception"}
    own_rows = [r for r in rows if r.rule.startswith(prefix)]
    used: set[int] = set()
    kept = []
    for finding in findings:
        waived = False
        if finding.rule_id not in unwaivable:
            for index, row in enumerate(own_rows):
                if row.rule == finding.rule_id and row.path == finding.path:
                    used.add(index)
                    waived = True
        if not waived:
            kept.append(finding)
    for index, row in enumerate(own_rows):
        if index not in used:
            kept.append(make_finding(
                check_id, "stale-exception", row.origin, None,
                f"exception row matches no finding: rule {row.rule}, path {row.path}",
                evidence=row.reason))
    return kept


# --- Pairing of source and target files -------------------------------------


@dataclass(frozen=True)
class Pair:
    source: str  # repository-relative path of the source file
    target: str  # repository-relative path of the target file
    target_exists: bool


def _join(root: str, rel: str) -> str:
    return f"{root}/{rel}" if root else rel


def pair_documents(
    context: Context, mapping: Mapping, check_id: str
) -> tuple[list[Pair], list[Finding]]:
    """Pair each source Markdown file with its target file.

    The target path is `target_root/<rename or same relative path>`.
    Findings: `missing-source-root`, `missing-target` and `duplicate-target`.
    A path that leaves the repository raises `ConfigError`.
    """
    findings: list[Finding] = []
    try:
        context.resolve(mapping.source_root or ".")
        context.resolve(mapping.target_root or ".")
    except ValueError as error:
        raise ConfigError(str(error), mapping.path) from error
    prefix = f"{mapping.source_root}/" if mapping.source_root else ""
    sources = [p for p in context.list_files("**/*.md") if p.startswith(prefix)]
    if not sources:
        findings.append(make_finding(
            check_id, "missing-source-root", mapping.path, None,
            f"no Markdown file under source_root: {mapping.source_root or '.'}"))
    pairs: list[Pair] = []
    by_target: dict[str, str] = {}
    for source in sources:
        rel = source[len(prefix):]
        target = _join(mapping.target_root, mapping.path_renames.get(rel, rel))
        try:
            context.resolve(target)
        except ValueError as error:
            raise ConfigError(f"renamed path leaves the repository: {target}", mapping.path) from error
        if target in by_target:
            findings.append(make_finding(
                check_id, "duplicate-target", target, None,
                "two source files map to one target", source=source))
            continue
        by_target[target] = source
        exists = context.resolve(target).is_file()
        pairs.append(Pair(source, target, exists))
        if not exists:
            findings.append(make_finding(
                check_id, "missing-target", target, None,
                "target file does not exist", source=source))
    return pairs, findings


def map_anchor(mapping: Mapping, anchor: str) -> str:
    """Return the target name of a source anchor (the same name if no rename)."""
    return mapping.anchor_renames.get(anchor, anchor)


# --- Markdown scanner --------------------------------------------------------

FRONT_MATTER = "front-matter"
FENCE = "fence"
HTML_COMMENT = "html-comment"
TABLE_ROW = "table-row"
PROSE = "prose"
BLANK = "blank"
LINE_CLASSES = (FRONT_MATTER, FENCE, HTML_COMMENT, TABLE_ROW, PROSE, BLANK)

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class Line:
    number: int  # 1-based
    text: str
    kind: str  # one of LINE_CLASSES


@dataclass(frozen=True)
class Fence:
    open_line: int
    close_line: int | None  # None: the fence never closes
    char: str
    length: int
    info: str  # info string of the opening line, stripped
    body: tuple[str, ...]  # lines between the open and close lines

    @property
    def language(self) -> str:
        return self.info.split()[0] if self.info.split() else ""


@dataclass(frozen=True)
class ScanProblem:
    rule: str  # unclosed-fence, unclosed-front-matter or unclosed-comment
    line: int
    message: str


@dataclass(frozen=True)
class Scan:
    lines: tuple[Line, ...]
    fences: tuple[Fence, ...]
    problems: tuple[ScanProblem, ...]

    def lines_of(self, kind: str) -> list[Line]:
        return [line for line in self.lines if line.kind == kind]


def _is_fence_close(text: str, char: str, length: int) -> bool:
    match = re.match(r"^ {0,3}(`+|~+)\s*$", text)
    return bool(match) and match.group(1)[0] == char and len(match.group(1)) >= length


def scan_markdown(text: str) -> Scan:
    """Classify each line of a Markdown text.

    Withheld lines (front matter, fenced blocks, whole-line HTML comments)
    have their own classes. An unclosed fence, front matter or comment is
    reported in `problems`. It is never ignored: the unclosed block takes all
    the lines to the end of the file.
    """
    raw = text.split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    raw = [line.rstrip("\r") for line in raw]
    lines: list[Line] = []
    fences: list[Fence] = []
    problems: list[ScanProblem] = []
    index = 0
    total = len(raw)

    if total and raw[0].strip() == "---":
        end = next((i for i in range(1, total) if raw[i].strip() in ("---", "...")), None)
        stop = total if end is None else end + 1
        lines.extend(Line(i + 1, raw[i], FRONT_MATTER) for i in range(stop))
        if end is None:
            problems.append(ScanProblem(
                "unclosed-front-matter", 1, "front matter is not closed"))
        index = stop

    while index < total:
        current = raw[index]
        number = index + 1
        opened = _FENCE_OPEN.match(current)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            marker = opened.group(1)
            char, length = marker[0], len(marker)
            close = next(
                (i for i in range(index + 1, total) if _is_fence_close(raw[i], char, length)),
                None,
            )
            stop = total if close is None else close + 1
            lines.extend(Line(i + 1, raw[i], FENCE) for i in range(index, stop))
            body_end = total if close is None else close
            fences.append(Fence(
                number, None if close is None else close + 1, char, length,
                opened.group(2).strip(), tuple(raw[index + 1:body_end])))
            if close is None:
                problems.append(ScanProblem(
                    "unclosed-fence", number,
                    f"fence opened with {marker} is not closed"))
            index = stop
            continue
        stripped = current.strip()
        if stripped.startswith("<!--"):
            end = next((i for i in range(index, total) if "-->" in raw[i]), None)
            if end is not None and raw[end].strip().endswith("-->"):
                lines.extend(Line(i + 1, raw[i], HTML_COMMENT) for i in range(index, end + 1))
                index = end + 1
                continue
            if end is None:
                lines.extend(Line(i + 1, raw[i], HTML_COMMENT) for i in range(index, total))
                problems.append(ScanProblem(
                    "unclosed-comment", number, "HTML comment is not closed"))
                index = total
                continue
        if not stripped:
            kind = BLANK
        elif stripped.startswith("|"):
            kind = TABLE_ROW
        else:
            kind = PROSE
        lines.append(Line(number, current, kind))
        index += 1
    return Scan(tuple(lines), tuple(fences), tuple(problems))


def scan_findings(
    check_id: str, path: str, scan: Scan, *, source: str | None = None
) -> list[Finding]:
    """Turn the problems of a scan into findings. A problem is never a skip."""
    return [
        make_finding(check_id, p.rule, path, p.line, p.message, source=source)
        for p in scan.problems
    ]


def split_table_row(text: str) -> list[str]:
    """Split a table row into cells.

    A separator is a `|` that is not escaped (`\\|`) and not inside a code span.
    The outer pipes do not make empty cells. Cells are stripped.
    """
    body = text.strip()
    cells: list[str] = []
    current: list[str] = []
    index = 0
    n = len(body)
    while index < n:
        ch = body[index]
        if ch == "\\" and index + 1 < n:
            current.append(body[index:index + 2])
            index += 2
        elif ch == "`":
            run = re.match(r"`+", body[index:]).group(0)  # type: ignore[union-attr]
            close = body.find(run, index + len(run))
            while close != -1 and body[close + len(run):close + len(run) + 1] == "`":
                close = body.find(run, close + 1)
            if close == -1:
                current.append(run)
                index += len(run)
            else:
                current.append(body[index:close + len(run)])
                index = close + len(run)
        elif ch == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
        else:
            current.append(ch)
            index += 1
    cells.append("".join(current).strip())
    if body.startswith("|"):
        cells = cells[1:]
    if body.endswith("|") and not body.endswith("\\|") and cells:
        cells = cells[:-1]
    return cells
