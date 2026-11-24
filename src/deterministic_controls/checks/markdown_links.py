"""Check `markdown.local-links`.

Port of `scripts/check_links.py`. The pass or fail result must stay the same.
The check is read-only. It checks each relative link target (not image targets)
in Markdown files of the default scope: a target file must exist, and a
`#heading` anchor must match a heading of the target Markdown file.
It skips links with a scheme (`https:`, `mailto:` and the like) and link-like
text in fenced code and in inline code.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from deterministic_controls.core.api import Context, Finding

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|^\[[^\]]+\]:\s*(\S+)", re.M)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
INLINE = re.compile(r"`[^`\n]*`")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
SCOPES = ("README.md", "AGENTS.md", "CLAUDE.md", "docs/", "memory/", "references/", "plans/", "scripts/")
SKIP_DIRS = {".git", ".venv", "node_modules", "build", "dist", "__pycache__", ".hypothesis"}


def slug(heading: str) -> str:
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    result: set[str] = set()
    headings = re.finditer(r"^#{1,6}\s+(.*?)\s*#*\s*$|^(\S.*?)\n(?:=+|-{2,})\s*$", text, re.M)
    for match in headings:
        title = match.group(1) if match.group(1) is not None else match.group(2)
        explicit = re.search(r"\{[^}]*#([\w-]+)[^}]*\}\s*$", title)
        if explicit:
            result.add(explicit.group(1))
        base = slug(re.sub(r"\s*\{[^}]*\}\s*$", "", title))
        n = seen.get(base, 0)
        seen[base] = n + 1
        result.add(base if n == 0 else f"{base}-{n}")
    return result


def _blank_fence(match: re.Match[str]) -> str:
    """Replace a fenced block with newlines only. Line numbers stay the same."""
    return "\n" * match.group(0).count("\n")


def _markdown_files(root: Path) -> list[Path]:
    files = [
        p for p in root.rglob("*.md")
        if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts)
    ]
    return sorted(files)


def entry(context: Context) -> list[Finding]:
    root = context.root
    everything = bool(context.parameters.get("all", False))
    findings: list[Finding] = []
    anchor_cache: dict[Path, set[str]] = {}
    for path in _markdown_files(root):
        rel = path.relative_to(root).as_posix()
        if not everything and not rel.startswith(SCOPES):
            continue
        text = INLINE.sub("", FENCE.sub(_blank_fence, path.read_text(encoding="utf-8")))
        for match in LINK.finditer(text):
            target = (match.group(1) or match.group(2)).strip("<>")
            if SCHEME.match(target):
                continue
            line = text.count("\n", 0, match.start()) + 1
            file_part, _, frag = target.partition("#")
            dest = path if not file_part else (path.parent / unquote(file_part))
            if not dest.exists():
                findings.append(Finding(
                    "markdown.local-links.missing-file", "error", rel, line,
                    f"link target does not exist: {target}", target))
            elif frag and dest.suffix == ".md":
                if dest not in anchor_cache:
                    anchor_cache[dest] = anchors(dest)
                if slug(unquote(frag)) not in anchor_cache[dest]:
                    findings.append(Finding(
                        "markdown.local-links.missing-anchor", "error", rel, line,
                        f"no heading matches the anchor: {target}", target))
    return findings
