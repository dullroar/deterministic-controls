"""Check `markdown.required-headings`.

Run me when: Markdown files must have fixed headings in a fixed order.

The parameter `rules` is a list of tables. Each table has:

- `glob`: the files to check (repository-relative pattern).
- `headings`: the heading texts that must exist, in this order.
- `level`: the heading level of those headings (default 2).

A heading is an ATX heading (`## Text`, with an optional closing `#` run or an
explicit `{#id}`) or a setext heading (text with a `===` or `---` underline).
A heading-like line in a fenced block does not count. A fence that never
closes is a finding.

Rule IDs: `missing`, `order`, `unclosed-fence`, `bad-config`.

The check works on any Markdown repository. It has no project name in its code.
Without the parameter `rules`, the check passes with no findings.
"""

from __future__ import annotations

import re
from typing import Any

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "markdown.required-headings"

RULES = ("missing", "order", "unclosed-fence")

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
_ID_SUFFIX = re.compile(r"\s*\{#[^{}]*\}\s*$")
_CLOSING = re.compile(r"(?:^|\s+)#+\s*$")
_SETEXT_1 = re.compile(r"^ {0,3}=+\s*$")
_SETEXT_2 = re.compile(r"^ {0,3}-+\s*$")


def _clean(text: str) -> str:
    text = _ID_SUFFIX.sub("", text.strip())
    text = _CLOSING.sub("", text)
    text = _ID_SUFFIX.sub("", text)
    return " ".join(text.split())


def headings_of(scan: tc.Scan) -> list[tuple[int, int, str]]:
    """Return (line, level, text) for each heading outside fences and front matter."""
    lines = scan.lines
    result = []
    for index, line in enumerate(lines):
        if line.kind != tc.PROSE:
            continue
        atx = _ATX.match(line.text)
        if atx:
            result.append((line.number, len(atx.group(1)), _clean(atx.group(2) or "")))
            continue
        if index + 1 < len(lines) and lines[index + 1].kind == tc.PROSE:
            under = lines[index + 1].text
            if _SETEXT_1.match(under) and line.text.strip():
                result.append((line.number, 1, _clean(line.text)))
            elif _SETEXT_2.match(under) and line.text.strip():
                result.append((line.number, 2, _clean(line.text)))
    return result


def load_rules(context: Context) -> list[dict[str, Any]]:
    raw = context.parameters.get("rules")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise tc.ConfigError("parameter 'rules' must be a list of tables")
    rules = []
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict):
            raise tc.ConfigError(f"rules entry {index} must be a table")
        extra = sorted(set(row) - {"glob", "headings", "level"})
        if extra:
            raise tc.ConfigError(f"rules entry {index} has unknown key: {', '.join(extra)}")
        glob = row.get("glob")
        if not isinstance(glob, str) or not glob.strip():
            raise tc.ConfigError(f"rules entry {index} needs a non-empty 'glob'")
        headings = row.get("headings")
        if not isinstance(headings, list) or not headings or not all(
            isinstance(h, str) and h.strip() for h in headings
        ):
            raise tc.ConfigError(
                f"rules entry {index}: 'headings' must be a non-empty list of strings")
        level = row.get("level", 2)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            raise tc.ConfigError(f"rules entry {index}: 'level' must be an integer from 1 to 6")
        rules.append({"glob": glob, "headings": [" ".join(h.split()) for h in headings],
                      "level": level})
    return rules


def entry(context: Context) -> list[Finding]:
    try:
        rules = load_rules(context)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]
    findings: list[Finding] = []
    for rule in rules:
        for path in context.list_files(rule["glob"]):
            scan = tc.scan_markdown(context.read_text(path))
            findings.extend(
                tc.make_finding(CHECK_ID, p.rule, path, p.line, p.message)
                for p in scan.problems if p.rule == "unclosed-fence"
            )
            first: dict[str, int] = {}
            for number, level, text in headings_of(scan):
                if level == rule["level"]:
                    first.setdefault(text, number)
            last = 0
            for wanted in rule["headings"]:
                if wanted not in first:
                    findings.append(tc.make_finding(
                        CHECK_ID, "missing", path, 1,
                        f"no level {rule['level']} heading '{wanted}'"))
                    continue
                if first[wanted] < last:
                    findings.append(tc.make_finding(
                        CHECK_ID, "order", path, first[wanted],
                        f"heading '{wanted}' is out of order"))
                else:
                    last = first[wanted]
    return findings
