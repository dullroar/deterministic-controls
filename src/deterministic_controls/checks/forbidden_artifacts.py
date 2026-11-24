"""Forbidden artifacts: tracked files that must not be committed.

Runtime output belongs outside the repository. This check reports each
tracked file that matches a forbidden pattern. Untracked files are not findings.

Pattern rules:

- A pattern without `/` matches the file name at any depth.
- A pattern with `/` matches the path from the repository root.
- `*` and `?` do not cross a `/`. `**` matches zero or more folders.
- A pattern is data. It is never run as a command.
"""

from __future__ import annotations

import re
import subprocess

from deterministic_controls.core.api import Context, Finding
from deterministic_controls.core.errors import ConfigError

RULE_ID = "repo.forbidden-artifacts.tracked"

DEFAULT_PATTERNS = (
    "driver.out",
    "ledger.jsonl",
    "plans/**/*.lock",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".env",
)


def _translate(pattern: str) -> re.Pattern[str]:
    """Translate a glob pattern with path rules to a regular expression."""
    parts = pattern.split("/")
    out = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            # Zero or more folders. A trailing `**` matches everything below.
            out.append(".+" if last else "(?:[^/]+/)*")
            continue
        piece = ""
        for char in part:
            if char == "*":
                piece += "[^/]*"
            elif char == "?":
                piece += "[^/]"
            else:
                piece += re.escape(char)
        out.append(piece if last else piece + "/")
    return re.compile("".join(out))


def _matches(pattern: str, relpath: str) -> bool:
    if "/" not in pattern:
        return _translate(pattern).fullmatch(relpath.rsplit("/", 1)[-1]) is not None
    return _translate(pattern).fullmatch(relpath) is not None


def _extra_patterns(context: Context) -> list[str]:
    value = context.parameters.get("extra_patterns", [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError("parameter 'extra_patterns' must be a list of non-empty strings")
    return value


def _file_list(context: Context) -> list[str]:
    """Return the tracked files. Without a usable Git index, return the file tree."""
    root = context.root
    if (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z"],
                capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            pass
        else:
            text = proc.stdout.decode("utf-8", errors="surrogateescape")
            return sorted(p for p in text.split("\0") if p)
    return context.list_files()


def entry(context: Context) -> list[Finding]:
    """Report each tracked file that matches a forbidden pattern."""
    patterns = list(DEFAULT_PATTERNS) + _extra_patterns(context)
    findings: list[Finding] = []
    for relpath in _file_list(context):
        for pattern in patterns:
            if _matches(pattern, relpath):
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity="error",
                        path=relpath,
                        line=None,
                        message=f"tracked file matches forbidden pattern '{pattern}'",
                        evidence=pattern,
                    )
                )
                break
    return findings
