"""Tests for the check `context.index-freshness`."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.index_freshness import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "index_freshness"
MANIFEST = 'schema_version = 1\nprofile = "ci"\nenabled = ["context.index-freshness"]\n'

# fixture name -> (rule ID, path of the finding)
BAD = {
    "stale-plans": ("context.index-freshness.stale", "plans/AGENTS.md"),
    "stale-scripts": ("context.index-freshness.stale", "scripts/AGENTS.md"),
    "missing-marker": ("context.index-freshness.missing-markers", "memory/AGENTS.md"),
    "memory-no-gist": ("context.index-freshness.missing-gist", "memory/fact-one.md"),
    "script-no-run-me": ("context.index-freshness.missing-gist", "scripts/hello.sh"),
}


def materialize(test: unittest.TestCase, name: str) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    (root / "controls.toml").write_text(MANIFEST, encoding="utf-8")
    # The template script looks for a `.git` entry to find the root. Stop it here.
    (root / ".git").mkdir()
    return root


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def template_script_passes(root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_indexes.py"), "--check", str(root)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


class GoodTests(unittest.TestCase):
    def test_good_fixture_passes(self):
        root = materialize(self, "good")
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(entry(Context(root)), [])


class FolderReadmeTests(unittest.TestCase):
    # Regression (0.1.2): a README.md in memory/ or scripts/ is not an index entry.
    # The ten repositories of the 2026-11-22 rollout keep one in both folders.
    def test_readme_in_memory_and_scripts_is_not_an_entry(self):
        root = materialize(self, "good")
        (root / "memory" / "README.md").write_text("# About memory\n\nNo front matter here.\n", encoding="utf-8")
        (root / "scripts").mkdir(exist_ok=True)
        (root / "scripts" / "README.md").write_text("# About scripts\n\nNo run line here.\n", encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 0, result)
        self.assertEqual(entry(Context(root)), [])


class BadTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        for name, (rule_id, path) in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                findings = [f for c in result["checks"] for f in c["findings"]]
                matches = [f for f in findings if f["rule_id"] == rule_id]
                self.assertTrue(matches, f"{rule_id} not found in {findings}")
                self.assertEqual(matches[0]["path"], path)
                self.assertEqual(matches[0]["severity"], "error")


class ReadOnlyTests(unittest.TestCase):
    def test_check_changes_no_file(self):
        for name in ["good", *BAD]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                before = snapshot(root)
                os.utime(root, None)
                entry(Context(root))
                run_cli(root)
                self.assertEqual(snapshot(root), before)


class CompatibilityTests(unittest.TestCase):
    def test_library_agrees_with_template_script_on_fixtures(self):
        for name in ["good", *BAD]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                self.assertEqual(
                    not entry(Context(root)), template_script_passes(root)
                )

    def test_library_agrees_with_template_script_on_this_repository(self):
        self.assertEqual(not entry(Context(REPO)), template_script_passes(REPO))


if __name__ == "__main__":
    unittest.main()
