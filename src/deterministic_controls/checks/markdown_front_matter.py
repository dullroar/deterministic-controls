"""Check `markdown.front-matter`.

Run me when: Markdown files must have front matter with fixed keys and values.

The parameter `rules` is a list of tables. Each table has:

- `glob`: the files to check (repository-relative pattern).
- `required_keys`: keys that must exist in the front matter (optional).
- `allowed`: a table of key to list of allowed values (optional).

Only the simple forms `key: value` and `key: [a, b]` are read. A front matter
line that the reader does not understand is a finding. It is never a skip.
Only the first line of a file can start front matter.

Rule IDs: `missing-file-block`, `missing-key`, `bad-value`, `unterminated`,
`unreadable`, `bad-config`.

The check works on any Markdown repository. It has no project name in its code.
Without the parameter `rules`, the check passes with no findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "markdown.front-matter"

RULES = (
    "missing-file-block",
    "missing-key",
    "bad-value",
    "unterminated",
    "unreadable",
)

_KEY_LINE = re.compile(r"^(\w[\w.-]*)\s*:(?:\s+(.*))?$")


@dataclass
class FrontMatter:
    """The result of reading the front matter of one file."""

    present: bool = False
    closed: bool = False
    values: dict[str, str | list[str]] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)  # key -> line number
    unreadable: list[tuple[int, str]] = field(default_factory=list)


def _unquote(value: str) -> str | None:
    """Remove one pair of quotes. Return None if a quote is not closed."""
    if value[:1] in ("'", '"'):
        if len(value) >= 2 and value[-1] == value[0]:
            return value[1:-1]
        return None
    return value


def _parse_value(raw: str) -> str | list[str] | None:
    value = raw.strip()
    if value.startswith("["):
        if not value.endswith("]"):
            return None
        items = []
        for part in value[1:-1].split(","):
            part = part.strip()
            if not part:
                continue
            item = _unquote(part)
            if item is None:
                return None
            items.append(item)
        return items
    return _unquote(value)


def parse_front_matter(text: str) -> FrontMatter:
    """Read the front matter block of a Markdown text (first line only)."""
    scan = tc.scan_markdown(text)
    block = scan.lines_of(tc.FRONT_MATTER)
    result = FrontMatter()
    if not block:
        return result
    result.present = True
    result.closed = not any(p.rule == "unclosed-front-matter" for p in scan.problems)
    body = block[1:-1] if result.closed else block[1:]
    for line in body:
        stripped = line.text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _KEY_LINE.match(line.text)
        value = _parse_value(match.group(2) or "") if match else None
        if match is None or value is None:
            result.unreadable.append((line.number, line.text))
            continue
        result.values[match.group(1)] = value
        result.lines[match.group(1)] = line.number
    return result


def load_rules(context: Context) -> list[dict[str, Any]]:
    """Read and check the parameter `rules`. Raise ConfigError if it is wrong."""
    raw = context.parameters.get("rules")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise tc.ConfigError("parameter 'rules' must be a list of tables")
    rules = []
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict):
            raise tc.ConfigError(f"rules entry {index} must be a table")
        extra = sorted(set(row) - {"glob", "required_keys", "allowed"})
        if extra:
            raise tc.ConfigError(f"rules entry {index} has unknown key: {', '.join(extra)}")
        glob = row.get("glob")
        if not isinstance(glob, str) or not glob.strip():
            raise tc.ConfigError(f"rules entry {index} needs a non-empty 'glob'")
        required = row.get("required_keys", [])
        if not isinstance(required, list) or not all(
            isinstance(k, str) and k for k in required
        ):
            raise tc.ConfigError(f"rules entry {index}: 'required_keys' must be a list of strings")
        allowed = row.get("allowed", {})
        if not isinstance(allowed, dict) or not all(
            isinstance(v, list) and all(isinstance(i, str) for i in v)
            for v in allowed.values()
        ):
            raise tc.ConfigError(
                f"rules entry {index}: 'allowed' must map a key to a list of strings")
        rules.append({"glob": glob, "required_keys": required, "allowed": allowed})
    return rules


def entry(context: Context) -> list[Finding]:
    try:
        rules = load_rules(context)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]
    findings: list[Finding] = []
    for rule in rules:
        for path in context.list_files(rule["glob"]):
            fm = parse_front_matter(context.read_text(path))
            if not fm.present:
                findings.append(tc.make_finding(
                    CHECK_ID, "missing-file-block", path, 1,
                    "the file has no front matter block on its first line"))
                continue
            if not fm.closed:
                findings.append(tc.make_finding(
                    CHECK_ID, "unterminated", path, 1,
                    "the front matter block is never closed"))
                continue
            for number, text in fm.unreadable:
                findings.append(tc.make_finding(
                    CHECK_ID, "unreadable", path, number,
                    "front matter line is not 'key: value' or 'key: [a, b]'",
                    evidence=text.strip()))
            for key in rule["required_keys"]:
                if key not in fm.values:
                    findings.append(tc.make_finding(
                        CHECK_ID, "missing-key", path, 1,
                        f"front matter has no key '{key}'"))
            for key, allowed in rule["allowed"].items():
                if key not in fm.values:
                    continue
                value = fm.values[key]
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if item not in allowed:
                        findings.append(tc.make_finding(
                            CHECK_ID, "bad-value", path, fm.lines[key],
                            f"value '{item}' of key '{key}' is not allowed "
                            f"(allowed: {', '.join(allowed)})"))
    return findings
