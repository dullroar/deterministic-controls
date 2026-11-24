"""Tests for the check `markdown.local-links`."""

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.markdown_links import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "markdown_links"
MANIFEST = 'schema_version = 1\nprofile = "ci"\nenabled = ["markdown.local-links"]\n'

# fixtures that pass
GOOD = ["good", "unicode", "percent", "duplicate", "reference", "fenced", "spaces", "archive"]

# fixture name -> (rule ID, path of the finding)
BAD = {
    "missing-file": ("markdown.local-links.missing-file", "README.md"),
    "missing-anchor": ("markdown.local-links.missing-anchor", "README.md"),
    "unicode-bad": ("markdown.local-links.missing-anchor", "README.md"),
    "percent-bad": ("markdown.local-links.missing-file", "README.md"),
    "duplicate-bad": ("markdown.local-links.missing-anchor", "README.md"),
    "reference-bad": ("markdown.local-links.missing-file", "README.md"),
    "absolute": ("markdown.local-links.missing-file", "README.md"),
    "archive-bad": ("markdown.local-links.missing-file", "README.md"),
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
        [sys.executable, str(REPO / "scripts" / "check_links.py"), str(root)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class GoodFixtureTests(unittest.TestCase):
    def test_each_good_fixture_passes(self):
        for name in GOOD:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 0)
                self.assertEqual(result["status"], "passed")
                self.assertEqual(entry(Context(root)), [])


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        for name, (rule_id, path) in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                findings = [f for c in result["checks"] for f in c["findings"]]
                self.assertEqual([f["rule_id"] for f in findings], [rule_id])
                self.assertEqual(findings[0]["path"], path)
                self.assertEqual(findings[0]["severity"], "error")
                self.assertIsInstance(findings[0]["line"], int)

    def test_finding_line_ignores_fenced_blocks(self):
        root = materialize(self, "missing-file")
        readme = root / "README.md"
        readme.write_text("```\ncode\n```\n\n[x](docs/nope.md)\n", encoding="utf-8")
        self.assertEqual([f.line for f in entry(Context(root))], [5])


class ReadOnlyTests(unittest.TestCase):
    def test_check_does_not_change_the_tree(self):
        for name in ["good", "missing-file"]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                before = tree_digest(root)
                entry(Context(root))
                self.assertEqual(before, tree_digest(root))


class CompatibilityTests(unittest.TestCase):
    def test_library_agrees_with_template_script_on_fixtures(self):
        for name in [*GOOD, *BAD]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                self.assertEqual(
                    not entry(Context(root)), template_script_passes(root)
                )

    def test_library_agrees_with_template_script_on_this_repository(self):
        self.assertEqual(not entry(Context(REPO)), template_script_passes(REPO))


if __name__ == "__main__":
    unittest.main()
