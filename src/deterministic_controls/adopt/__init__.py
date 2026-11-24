"""Adoption tools: audit, plan, apply, receipt.

They put the library into another repository. They never push, never change a Git remote or a
GitHub setting, and never commit. `apply` is idempotent.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

from deterministic_controls.core.catalog import load_catalog
from deterministic_controls.core.errors import (
    EXIT_CONFIG,
    EXIT_INTERNAL,
    EXIT_PASS,
    ConfigError,
)
from deterministic_controls.core.manifest import MANIFEST_NAME, read_manifest
from deterministic_controls.core.runner import run_checks

TEMPLATES = Path(__file__).resolve().parent / "templates"
SCHEMA_VERSION = 1
SHIM_MARKER = "deterministic-controls shim"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
OLD_SCRIPTS = ("build_indexes.py", "check_plan.py", "check_links.py", "scan_secrets.py")
# Managed files: path -> template name (None: built in code).
MANAGED = (
    "scripts/check_context.py",
    "scripts/controls-requirements.txt",
    "controls.toml",
    "scripts/secret_guard.py",
    "scripts/install_hooks.sh",
    ".github/workflows/context.yml",
)
EXECUTABLE = {"scripts/install_hooks.sh", "scripts/check_context.py", "scripts/secret_guard.py"}
LANGUAGES = {
    ".py": "python", ".ps1": "powershell", ".sh": "shell", ".js": "javascript",
    ".ts": "typescript", ".go": "go", ".rs": "rust", ".cs": "csharp", ".java": "java",
}
CI_FILES = (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", ".travis.yml")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=60
    )


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _check_commit(commit: str) -> None:
    if not COMMIT_RE.match(commit or ""):
        raise ConfigError("commit must be a full 40-character lowercase hexadecimal Git SHA")


def _check_root(root: Path) -> None:
    if not root.is_dir():
        raise ConfigError(f"root is not a directory: {root.name}")
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
        raise ConfigError("root is not the top directory of a Git repository")


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


# --- audit -----------------------------------------------------------------


def _files(root: Path) -> list[str]:
    out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(p for p in out.stdout.split("\0") if p) if out.returncode == 0 else []


def _case_collisions(files: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(f.lower(), []).append(f)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _job_names(text: str) -> list[str]:
    names, in_jobs = [], False
    for line in text.splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
        elif in_jobs and re.match(r"^\S", line):
            in_jobs = False
        elif in_jobs:
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                names.append(m.group(1))
    return names


def _test_commands(root: Path, files: list[str]) -> list[str]:
    cmds = []
    if any(f.startswith("tests/") and f.endswith(".py") for f in files):
        cmds.append("python3 -m unittest discover -s tests")
    pkg = _read(root, "package.json")
    if pkg:
        try:
            if "test" in json.loads(pkg).get("scripts", {}):
                cmds.append("npm test")
        except ValueError:
            pass
    makefile = _read(root, "Makefile")
    if makefile and re.search(r"^test:", makefile, re.M):
        cmds.append("make test")
    if "Dockerfile" in files:
        cmds.append("docker build (Dockerfile)")
    return cmds


def _artifacts(root: Path) -> dict[str, bool]:
    shim = _read(root, "scripts/check_context.py") or ""
    req = _read(root, "scripts/controls-requirements.txt") or ""
    workflow = _read(root, ".github/workflows/context.yml") or ""
    return {
        "shim": SHIM_MARKER in shim,
        "pin": bool(re.search(r"@[0-9a-f]{40}\"", req)),
        "manifest": (root / MANIFEST_NAME).is_file(),
        "secret_guard": (root / "scripts/secret_guard.py").is_file(),
        "hooks": (root / "scripts/install_hooks.sh").is_file(),
        "controls_job": "controls" in _job_names(workflow),
    }


def audit(root: Path) -> dict:
    root = root.resolve()
    result: dict = {
        "schema_version": SCHEMA_VERSION, "repository": root.name, "classification": "blocked",
        "reasons": [],
    }
    try:
        _check_root(root)
    except ConfigError as exc:
        result["reasons"].append(str(exc))
        return result
    files = _files(root)
    arts = _artifacts(root)
    collisions = _case_collisions(files)
    template_derived = (root / "plans").is_dir() and (root / "scripts").is_dir() and any(
        (root / "scripts" / n).is_file() for n in ("check_context.py", "build_indexes.py")
    )
    langs = sorted({LANGUAGES[Path(f).suffix] for f in files if Path(f).suffix in LANGUAGES})
    ci = [f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
    ci += [f for f in files if f in CI_FILES]
    result.update(
        template_derived=template_derived, languages=langs, ci_files=ci,
        test_commands=_test_commands(root, files),
        current_checks=[n for n in OLD_SCRIPTS if (root / "scripts" / n).is_file()],
        case_collisions=collisions, adoption_artifacts=arts,
    )
    manifest_error = None
    if arts["manifest"]:
        try:
            read_manifest(root)
        except ConfigError as exc:
            manifest_error = str(exc)
    if collisions:
        result["reasons"].append("two paths differ only by case")
    if manifest_error:
        result["reasons"].append(f"controls.toml is not valid: {manifest_error}")
    if result["reasons"]:
        return result
    if all(arts.values()):
        cls, reason = "compliant", "all adoption files are present"
    elif any(arts.values()):
        cls = "partial"
        reason = "missing: " + ", ".join(k for k, v in arts.items() if not v)
    elif template_derived:
        cls, reason = "needs-shims", "template layout without the adoption files"
    else:
        cls, reason = "not-suitable", "no template layout (scripts/ and plans/)"
    result["classification"] = cls
    result["reasons"].append(reason)
    return result


def _format_audit(r: dict) -> str:
    lines = [f"repository: {r['repository']}", f"classification: {r['classification']}"]
    for reason in r["reasons"]:
        lines.append(f"reason: {reason}")
    for key in ("template_derived", "languages", "ci_files", "test_commands", "current_checks",
                "case_collisions"):
        if key in r:
            lines.append(f"{key}: {json.dumps(r[key])}")
    return "\n".join(lines)


# --- plan and apply --------------------------------------------------------


def _insert_job(text: str) -> str:
    if "controls" in _job_names(text):
        return text
    if not re.search(r"^jobs:\s*$", text, re.M):
        raise ConfigError(".github/workflows/context.yml has no top-level 'jobs:' line")
    job = _template("controls-job.yml")
    return re.sub(r"^(jobs:[ \t]*\r?\n)", lambda m: m.group(1) + job, text, count=1, flags=re.M)


def compute_changes(root: Path, commit: str) -> dict[str, str]:
    """Return {relative path: new content} for each file that apply would write."""
    changes: dict[str, str] = {}

    def want(rel: str, content: str) -> None:
        if _read(root, rel) != content:
            changes[rel] = content

    want("scripts/check_context.py", _template("check_context.py"))
    want("scripts/controls-requirements.txt", _template("controls-requirements.txt").replace("<commit>", commit))
    if not (root / MANIFEST_NAME).is_file():
        ids = ", ".join(f'"{i}"' for i in sorted(load_catalog()))
        want(MANIFEST_NAME, f'schema_version = 1\nprofile = "ci"\nenabled = [{ids}]\n')
    want("scripts/secret_guard.py", _template("secret_guard.py"))
    want("scripts/install_hooks.sh", _template("install_hooks.sh"))
    workflow = _read(root, ".github/workflows/context.yml")
    if workflow is None:
        workflow = _template("context.yml")
    want(".github/workflows/context.yml", _insert_job(workflow))
    return changes


def _diff(root: Path, changes: dict[str, str]) -> str:
    out = []
    for rel in sorted(changes):
        old = _read(root, rel)
        out.extend(difflib.unified_diff(
            (old or "").splitlines(keepends=True), changes[rel].splitlines(keepends=True),
            fromfile="/dev/null" if old is None else f"a/{rel}", tofile=f"b/{rel}",
        ))
    return "".join(out)


def _require_ready(root: Path, commit: str) -> None:
    _check_commit(commit)
    _check_root(root)


def _require_clean_branch(root: Path) -> None:
    if _git(root, "symbolic-ref", "-q", "HEAD").returncode != 0:
        raise ConfigError("HEAD is detached. Check out a branch first")
    if _git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        raise ConfigError("the repository has no commit yet")
    status = _git(root, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        raise ConfigError("the working tree is not clean. Commit or stash your changes first")


def plan(root: Path, commit: str) -> str:
    root = root.resolve()
    _require_ready(root, commit)
    return _diff(root, compute_changes(root, commit))


def apply(root: Path, commit: str) -> list[str]:
    root = root.resolve()
    _require_ready(root, commit)
    _require_clean_branch(root)
    changes = compute_changes(root, commit)
    for rel in sorted(changes):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(changes[rel], encoding="utf-8", newline="")
        if rel in EXECUTABLE:
            path.chmod(0o755)
    return sorted(changes)


# --- receipt ---------------------------------------------------------------


def receipt(root: Path, commit: str) -> dict:
    root = root.resolve()
    _require_ready(root, commit)
    pin = _read(root, "scripts/controls-requirements.txt") or ""
    if f"@{commit}\"" not in pin:
        raise ConfigError("scripts/controls-requirements.txt is not pinned to this commit. Run apply first")
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise ConfigError("the repository has no commit yet")
    base = head.stdout.strip()
    manifest, text = read_manifest(root)
    added, changed = [], []
    for rel in MANAGED:
        if not (root / rel).is_file():
            continue
        old = _git(root, "show", f"HEAD:{rel}")
        if old.returncode != 0:
            added.append(rel)
        elif old.stdout != _read(root, rel):
            changed.append(rel)
    result = run_checks(root, manifest, text, load_catalog())
    checks_run = [{"check_id": c["check_id"], "status": c["status"]} for c in result["checks"]]
    files = _files(root)
    kept = [f for f in files if f.startswith("scripts/") and f not in MANAGED
            and Path(f).suffix in (".py", ".sh", ".ps1") and f.count("/") == 1]
    kept += [f"test: {c}" for c in _test_commands(root, files)]
    workflow = _read(root, ".github/workflows/context.yml") or ""
    kept += [f"ci-job: {n}" for n in _job_names(workflow) if n != "controls"]
    managed = [*added, *changed] or list(MANAGED)
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": root.name,
        "base_revision": base,
        "control_pin": commit,
        "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "profile": manifest.profile,
        "enabled_checks": sorted(manifest.enabled),
        "files_added": added,
        "files_changed": changed,
        "commands_kept": kept,
        "checks_run": checks_run,
        "enforcement_state": "advisory",
        "rollback": [
            "To restore the previous pin: edit scripts/controls-requirements.txt, put the previous "
            "commit in the install line, and run scripts/check_context.py once to build its environment.",
            f"To remove the adoption: run 'git revert' on the adoption commit, or restore these files "
            f"from the base revision {base} with 'git checkout {base} -- <file>' "
            f"and delete the files that were added: {', '.join(managed)}.",
            "The cached environment is in the user cache directory under deterministic-controls/<commit>/. "
            "It is safe to delete.",
        ],
    }


# --- command line ----------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_CONFIG, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="deterministic_controls adopt")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    a = sub.add_parser("audit", help="classify a repository (read only)")
    a.add_argument("--root", required=True)
    a.add_argument("--format", choices=("text", "json"), default="text")
    for name, text in (("plan", "print the diff that apply would make"),
                       ("apply", "write the adoption files (no commit, no push)"),
                       ("receipt", "write the adoption receipt as JSON")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--root", required=True)
        s.add_argument("--commit", required=True)
        if name == "receipt":
            s.add_argument("--output", default=None, metavar="FILE")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_CONFIG
    root = Path(args.root)
    try:
        if args.command == "audit":
            r = audit(root)
            print(json.dumps(r, indent=2, sort_keys=True) if args.format == "json" else _format_audit(r))
        elif args.command == "plan":
            print(plan(root, args.commit), end="")
        elif args.command == "apply":
            written = apply(root, args.commit)
            print("\n".join(f"wrote {p}" for p in written) if written else "nothing to change")
        else:
            text = json.dumps(receipt(root, args.commit), indent=2, sort_keys=True)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
        return EXIT_PASS
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - a crash never gives 0
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
