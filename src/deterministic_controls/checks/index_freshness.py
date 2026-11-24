"""Index freshness check: `context.index-freshness`.

Port of `scripts/build_indexes.py --check`. The check never writes a file.
It computes the expected text between the BEGIN and END markers of
`memory/AGENTS.md`, `plans/AGENTS.md` and `scripts/AGENTS.md`.
It compares the text with the file.

Rules:
- `context.index-freshness.stale`: the generated index differs from the file.
- `context.index-freshness.missing-markers`: an index file has no BEGIN or END marker.
- `context.index-freshness.missing-gist`: a memory, plan or script has no gist.
"""

from __future__ import annotations

import re
from pathlib import Path

from deterministic_controls.core.api import Context, Finding

BEGIN = "<!-- BEGIN GENERATED INDEX -->"
END = "<!-- END GENERATED INDEX -->"
SKIP_DIRS = {".git", ".venv", "node_modules", "build", "dist", "__pycache__", ".hypothesis"}
PLAN_SKIP = {"archive"}
FOLDERS = ("memory", "plans", "scripts")
RUN_ME = re.compile(r"Run me when:\s*(.+?)\s*(?:\*/|#>|-->|\"\"\")?\s*$")

RULE_STALE = "context.index-freshness.stale"
RULE_MARKERS = "context.index-freshness.missing-markers"
RULE_GIST = "context.index-freshness.missing-gist"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_frontmatter(text: str) -> dict[str, object]:
    """Parse a small YAML subset: scalars, inline lists and block lists."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data: dict[str, object] = {}
    key: str | None = None
    for raw in text[4:end].split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key is not None:
            lst = data.setdefault(key, [])
            if isinstance(lst, list):
                lst.append(_unquote(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value == "":
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [_unquote(v.strip()) for v in inner.split(",")] if inner else []
        else:
            data[key] = _unquote(value)
    return data


def _rel(context: Context, path: Path) -> str:
    return path.relative_to(context.root).as_posix()


def _gap(context: Context, path: Path, message: str) -> Finding:
    rel = _rel(context, path)
    return Finding(RULE_GIST, "error", rel, None, message, rel)


def _md_gist(context: Context, path: Path, gaps: list[Finding]) -> str | None:
    meta = _split_frontmatter(path.read_text(encoding="utf-8"))
    gist = meta.get("gist")
    if not isinstance(gist, str) or not gist.strip():
        gaps.append(_gap(context, path, "missing 'gist' front matter"))
        return None
    return gist.strip()


def _script_gist(context: Context, path: Path, gaps: list[Finding]) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").split("\n")[:25]
    except UnicodeDecodeError:
        gaps.append(_gap(context, path, "not a text file"))
        return None
    for line in lines:
        found = RUN_ME.search(line)
        if found:
            return "Run me when: " + found.group(1)
    gaps.append(_gap(context, path, "missing 'Run me when:' line in the first 25 lines"))
    return None


def _entries(context: Context, folder: Path, gaps: list[Finding]) -> list[tuple[str, str]]:
    """Return (name, gist) pairs for the items of one folder."""
    out: list[tuple[str, str]] = []
    if folder.name == "memory":
        for p in sorted(folder.glob("*.md")):
            if p.name != "AGENTS.md" and (g := _md_gist(context, p, gaps)):
                out.append((p.name, g))
    elif folder.name == "plans":
        skip = PLAN_SKIP | SKIP_DIRS
        for d in sorted(x for x in folder.iterdir() if x.is_dir() and x.name not in skip):
            if (d / "plan.md").exists():
                if g := _md_gist(context, d / "plan.md", gaps):
                    out.append((f"{d.name}/plan.md", g))
            else:
                gaps.append(_gap(context, d, "plan folder has no plan.md"))
    elif folder.name == "scripts":
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.name != "AGENTS.md" and not p.name.startswith("."):
                if g := _script_gist(context, p, gaps):
                    out.append((p.name, g))
    return out


def _render(items: list[tuple[str, str]]) -> str:
    if not items:
        return "<!-- Nothing to list yet. -->"
    return "\n".join(f"* [{name}](./{name})\n  {gist}" for name, gist in items)


def entry(context: Context) -> list[Finding]:
    """Compare each generated index with its expected text. Write nothing."""
    findings: list[Finding] = []
    for name in FOLDERS:
        folder = context.root / name
        index = folder / "AGENTS.md"
        if not index.is_file():
            continue
        rel = _rel(context, index)
        text = index.read_text(encoding="utf-8")
        if BEGIN not in text or END not in text:
            findings.append(Finding(
                RULE_MARKERS, "error", rel, None,
                f"missing BEGIN/END markers in {rel}", rel,
            ))
            continue
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        expected = f"{head}{BEGIN}\n\n{_render(_entries(context, folder, findings))}\n\n{END}{tail}"
        if expected != text:
            findings.append(Finding(
                RULE_STALE, "error", rel, None,
                f"index is stale: {rel}", rel,
            ))
    return sorted(findings, key=lambda f: f.sort_key())
