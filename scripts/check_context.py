#!/usr/bin/env python3
"""Run every context check through deterministic-controls. Usage: check_context.py [ROOT]

Run me when: I changed any context file, and before every pull request.

deterministic-controls shim. It keeps the output lines and exit codes of the old template script:
one line "ok   <script>" or "FAIL <script>" for each old check, exit 0 if all pass, exit 1 if a check fails.
In this repository the package source is here. The shim runs the library from `src/` with
PYTHONPATH. It does not use a cached environment. If the library cannot run, this script exits 2.
It never passes then.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "src"
GROUPS = [
    ("build_indexes.py", ["context.index-freshness"]),
    ("check_plan.py", ["plans.schema", "plans.graph"]),
    ("check_links.py", ["markdown.local-links"]),
    ("scan_secrets.py", ["security.secrets", "security.personal-data"]),
]
EXIT_CONFIG = 2


def fail(message: str) -> int:
    print(f"check_context: {message}", file=sys.stderr)
    return EXIT_CONFIG


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else HERE.parent
    env = {**os.environ, "PYTHONPATH": str(SOURCE)}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "deterministic_controls", "check", "--root", str(root),
             "--profile", "ci", "--format", "json"],
            capture_output=True, text=True, check=False, env=env,
        )
    except OSError as exc:
        return fail(f"cannot run the library: {type(exc).__name__}")
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        return fail(f"the library failed with exit code {proc.returncode}")
    try:
        status = {c["check_id"]: c["status"] for c in json.loads(proc.stdout)["checks"]}
    except (ValueError, KeyError, TypeError):
        return fail("the library gave no valid result")
    failed = False
    seen: set[str] = set()
    for script, ids in GROUPS:
        present = [i for i in ids if i in status]
        if not present:
            continue
        seen.update(present)
        ok = all(status[i] in ("passed",) for i in present)
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {script}")
    for check_id in sorted(set(status) - seen):
        ok = status[check_id] == "passed"
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {check_id}")
    if proc.returncode == 1 and not failed:
        print("FAIL deterministic-controls")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
