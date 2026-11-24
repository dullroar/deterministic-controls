"""Tests for the check `repo.forbidden-artifacts`.

Each test repository is built at run time in a temporary directory.
No forbidden file is stored in this repository.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.forbidden_artifacts import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402
from deterministic_controls.core.errors import ConfigError  # noqa: E402

RULE_ID = "repo.forbidden-artifacts.tracked"
CHECK_ID = "repo.forbidden-artifacts"

# case name -> path of a tracked forbidden file
BAD = {
    "driver-out": "driver.out",
    "driver-out-nested": "work/driver.out",
    "ledger": "ledger.jsonl",
    "lock": "plans/x.lock",
    "lock-nested": "plans/x/y.lock",
    "claude-settings": ".claude/settings.json",
    "claude-settings-local": ".claude/settings.local.json",
    "env": ".env",
}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def build_repo(test: unittest.TestCase, files: dict[str, str], ignore: str = "") -> Path:
    """Create a Git repository. Write and track the files."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    root.mkdir()
    git(root, "init", "-q")
    if ignore:
        (root / ".gitignore").write_text(ignore, encoding="utf-8")
    for relpath, text in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    # A global ignore file on the host can hide some paths. Force only the unignored case off.
    git(root, "add", "-A" if ignore else "-Af")
    return root


def run_cli(root: Path, extra: list[str] | None = None):
    manifest = root / "controls.toml"
    lines = ['schema_version = 1', 'profile = "ci"', f'enabled = ["{CHECK_ID}"]']
    if extra is not None:
        lines += [f"[parameters.\"{CHECK_ID}\"]", f"extra_patterns = {json.dumps(extra)}"]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def findings_of(result):
    return [f for c in result["checks"] for f in c["findings"]]


class GoodTests(unittest.TestCase):
    def test_repository_without_forbidden_file_passes(self):
        root = build_repo(self, {"README.md": "x\n", "src/app.py": "x = 1\n"})
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(findings_of(result), [])

    def test_untracked_ignored_driver_out_passes(self):
        root = build_repo(self, {"README.md": "x\n"}, ignore="driver.out\n")
        (root / "driver.out").write_text("log\n", encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(findings_of(result), [])

    def test_untracked_file_is_not_a_finding(self):
        root = build_repo(self, {"README.md": "x\n"})
        (root / ".env").write_text("A=1\n", encoding="utf-8")
        self.assertEqual(entry(Context(root)), [])


class BadTests(unittest.TestCase):
    def test_each_default_pattern_fails(self):
        for name, relpath in BAD.items():
            with self.subTest(case=name):
                root = build_repo(self, {"README.md": "x\n", relpath: "data\n"})
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                found = findings_of(result)
                self.assertEqual([f["path"] for f in found], [relpath])
                self.assertEqual(found[0]["rule_id"], RULE_ID)
                self.assertEqual(found[0]["severity"], "error")

    def test_extra_pattern_fails(self):
        root = build_repo(self, {"review/packets/a/b.json": "{}\n", "README.md": "x\n"})
        code, result = run_cli(root, extra=["review/packets/**"])
        self.assertEqual(code, 1)
        found = findings_of(result)
        self.assertEqual([f["path"] for f in found], ["review/packets/a/b.json"])
        self.assertEqual(found[0]["rule_id"], RULE_ID)

    def test_extra_pattern_is_off_by_default(self):
        root = build_repo(self, {"review/packets/a.json": "{}\n"})
        code, _ = run_cli(root)
        self.assertEqual(code, 0)

    def test_lock_outside_plans_is_not_forbidden(self):
        root = build_repo(self, {"src/x.lock": "x\n"})
        self.assertEqual(entry(Context(root)), [])

    def test_pattern_is_data_not_command(self):
        root = build_repo(self, {"a.txt": "x\n"})
        self.assertEqual(
            entry(Context(root, {"extra_patterns": ["$(touch pwned)", "; rm -rf x"]})), []
        )
        self.assertFalse((root / "pwned").exists())


class FallbackTests(unittest.TestCase):
    def test_without_git_the_file_tree_is_used(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "ledger.jsonl").write_text("x\n", encoding="utf-8")
        found = entry(Context(root))
        self.assertEqual([f.path for f in found], ["ledger.jsonl"])


class ConfigErrorTests(unittest.TestCase):
    def test_bad_extra_patterns_raise_config_error(self):
        root = build_repo(self, {"a.txt": "x\n"})
        for value in ("review/**", ["ok", 3], [""], {"a": "b"}, 5):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError):
                    entry(Context(root, {"extra_patterns": value}))


if __name__ == "__main__":
    unittest.main()
