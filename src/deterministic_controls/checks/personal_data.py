"""Personal data check: `security.personal-data`.

Port of `scripts/scan_secrets.py`. It scans the Markdown of the context folders
for personal paths, e-mail addresses and credential-like text.
Add `<!-- scan:ignore -->` to a line that is a reviewed placeholder.
A finding never holds the matched text. It holds the first four characters and the length.
"""

from __future__ import annotations

import re

from deterministic_controls.core.api import Context, Finding

SCOPES = ("AGENTS.md", "CLAUDE.md", "docs/", "memory/", "references/", "plans/")
SKIP_DIRS = {".git", ".venv", "node_modules", "build", "dist", "__pycache__", ".hypothesis"}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "token": re.compile(r"\b(ghp_|gho_|github_pat_|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|xox[bap]-)"),
    "credential-in-url": re.compile(r"://[^/\s:@]+:[^/\s@]+@"),
    "connection-string": re.compile(r"(?i)\b(password|pwd|accountkey|sharedaccesskey)\s*=\s*[^;\s]{3,}"),
    "personal-path": re.compile(r"(/home/[a-z][\w.-]*/|/Users/[A-Za-z][\w.-]*/|[A-Za-z]:\\Users\\[A-Za-z][\w.-]*)"),
    "email": re.compile(r"\b[\w.+-]+@(?!example\.|users\.noreply)[\w-]+\.[\w.-]+\b"),
}


def entry(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for rel in context.list_files("**/*.md"):
        if SKIP_DIRS & set(rel.split("/")) or not rel.startswith(SCOPES):
            continue
        for number, line in enumerate(context.read_text(rel).split("\n"), 1):
            if "scan:ignore" in line:
                continue
            for label, pattern in PATTERNS.items():
                match = pattern.search(line)
                if match:
                    text = match.group(0)
                    findings.append(Finding(
                        rule_id=f"security.personal-data.{label}",
                        severity="error",
                        path=rel,
                        line=number,
                        message=f"possible {label.replace('-', ' ')}",
                        evidence=f"{text[:4]}…{len(text)}",
                    ))
    return findings
