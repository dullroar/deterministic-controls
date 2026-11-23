"""Plan checks: `plans.schema` and `plans.graph`.

Port of `scripts/check_plan.py`. The pass or fail result must stay the same.
Layout: plans/<plan>/goal.md, plans/<plan>/plan.md, plans/<plan>/steps/<id>.md.
The folders `plans/for-each-plan` and `plans/archive` are skipped.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from deterministic_controls.core.api import Context, Finding

STATUSES = {"pending", "in_progress", "done", "blocked"}
REQUIRED = ("id", "status", "depends_on", "touches", "lane", "gate")
SKIPPED_PLANS = {"for-each-plan", "archive"}


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse a small YAML subset: scalars, inline lists and block lists."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 4:].lstrip("\n")
    data: dict[str, object] = {}
    key: str | None = None
    for raw in block.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key is not None:
            lst = data.setdefault(key, [])
            if isinstance(lst, list):
                lst.append(unquote(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value == "":
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [unquote(v.strip()) for v in inner.split(",")] if inner else []
        else:
            data[key] = unquote(value)
    return data, body


def as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return [str(value)] if value else []


def overlaps(a: str, b: str) -> bool:
    a, b = a.rstrip("/"), b.rstrip("/")
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True

    def stem(glob: str) -> str:
        return re.split(r"[*?\[]", glob)[0].rstrip("/")

    sa, sb = stem(a), stem(b)
    return bool(sa and sb and (sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/")))


def _plan_dirs(context: Context) -> list[Path]:
    plans = context.root / "plans"
    if not plans.is_dir():
        return []
    return sorted(p for p in plans.iterdir() if p.is_dir() and p.name not in SKIPPED_PLANS)


def _load_steps(context: Context, plan: Path) -> tuple[dict[str, dict], list[Finding]]:
    """Return the valid steps of a plan and the schema findings."""
    findings: list[Finding] = []
    steps: dict[str, dict] = {}
    plan_rel = plan.relative_to(context.root).as_posix()
    for path in sorted((plan / "steps").glob("*.md")):
        rel = f"{plan_rel}/steps/{path.name}"
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if k not in meta]
        for key in missing:
            findings.append(
                Finding(f"plans.schema.missing-{key}", "error", rel, None,
                        f"missing front matter key '{key}'", key)
            )
        if missing:
            continue
        if meta["id"] != path.stem:
            findings.append(
                Finding("plans.schema.id-mismatch", "error", rel, None,
                        f"id '{meta['id']}' must equal file name", str(meta["id"]))
            )
        if meta["status"] not in STATUSES:
            findings.append(
                Finding("plans.schema.bad-status", "error", rel, None,
                        f"bad status '{meta['status']}'", str(meta["status"]))
            )
        if meta["status"] == "done" and not meta.get("evidence"):
            findings.append(
                Finding("plans.schema.done-without-evidence", "error", rel, None,
                        "done step needs evidence")
            )
        if not meta["gate"]:
            findings.append(
                Finding("plans.schema.empty-gate", "error", rel, None, "empty gate")
            )
        steps[path.stem] = meta
    for required in ("goal.md", "plan.md"):
        if not (plan / required).exists():
            findings.append(
                Finding(f"plans.schema.missing-{required.removesuffix('.md')}-file", "error",
                        plan_rel, None, f"missing {required}", required)
            )
    return steps, findings


def schema_entry(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for plan in _plan_dirs(context):
        findings.extend(_load_steps(context, plan)[1])
    return findings


def _graph_findings(plan_rel: str, steps: dict[str, dict]) -> list[Finding]:
    findings: list[Finding] = []

    def add(rule: str, message: str, evidence: str = "") -> None:
        findings.append(Finding(rule, "error", plan_rel, None, message, evidence))

    for sid, meta in steps.items():
        for dep in as_list(meta["depends_on"]):
            if dep not in steps:
                add("plans.graph.unknown-dependency",
                    f"{sid} depends on unknown step '{dep}'", dep)

    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle = " -> ".join([*trail, node])
            add("plans.graph.cycle", f"dependency cycle {cycle}", cycle)
            return
        state[node] = 1
        for dep in as_list(steps[node]["depends_on"]):
            if dep in steps:
                visit(dep, [*trail, node])
        state[node] = 2

    for sid in steps:
        visit(sid, [])

    def ancestors(sid: str, seen: set[str] | None = None) -> set[str]:
        seen = seen if seen is not None else set()
        for dep in as_list(steps[sid]["depends_on"]):
            if dep in steps and dep not in seen:
                seen.add(dep)
                ancestors(dep, seen)
        return seen

    def derived(sid: str) -> str:
        meta = steps[sid]
        if meta["status"] != "pending":
            return str(meta["status"])
        done = all(steps.get(d, {}).get("status") == "done" for d in as_list(meta["depends_on"]))
        return "ready" if done else "waiting"

    live = [s for s in steps if derived(s) in {"ready", "in_progress"} and not state.get(s) == 1]
    try:
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if a in ancestors(b) or b in ancestors(a):
                    continue
                for ta in as_list(steps[a]["touches"]):
                    for tb in as_list(steps[b]["touches"]):
                        if overlaps(ta, tb):
                            add("plans.graph.touch-overlap",
                                f"{a} and {b} may run together but both touch '{ta}' / '{tb}'",
                                f"{ta} / {tb}")
                la, lb = steps[a]["lane"], steps[b]["lane"]
                if la and la == lb and la != "none":
                    add("plans.graph.shared-lane",
                        f"{a} and {b} share serial lane '{la}'", str(la))
    except RecursionError:
        add("plans.graph.too-deep", "dependency graph too deep to analyze")
    return findings


def graph_entry(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for plan in _plan_dirs(context):
        steps, _ = _load_steps(context, plan)
        findings.extend(_graph_findings(plan.relative_to(context.root).as_posix(), steps))
    return findings
