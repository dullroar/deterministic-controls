"""Consumer test: install the package, run the CLI on consumer fixtures, check the workflow text."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

FIXTURES = REPO / "tests" / "fixtures" / "consumer"
WORKFLOW = REPO / ".github" / "workflows" / "controls.yml"


def materialize(test: unittest.TestCase, name: str) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    return root


def build_environment():
    """Build a virtual environment with the package installed. Return (python, error)."""
    tmp = tempfile.TemporaryDirectory()
    work = Path(tmp.name)
    # Build from a copy, so the build leaves no files in the repository.
    source = work / "source"
    source.mkdir()
    shutil.copy(REPO / "pyproject.toml", source / "pyproject.toml")
    shutil.copytree(
        REPO / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    venv = work / "venv"
    # Share the system site packages, so an offline build finds setuptools.
    steps = [
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return tmp, None, proc.stderr.strip()
    python = venv / "bin" / "python"
    if not python.exists():
        python = venv / "Scripts" / "python.exe"
    proc = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "--no-build-isolation",
         "--disable-pip-version-check", "--quiet", str(source)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return tmp, None, proc.stderr.strip()
    return tmp, python, ""


class ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp, cls.python, cls.error = build_environment()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_cli(self, root: Path):
        if self.python is None:
            self.skipTest("no build tool")
        proc = subprocess.run(
            [str(self.python), "-I", "-m", "deterministic_controls", "check",
             "--root", str(root), "--profile", "ci", "--format", "json"],
            capture_output=True, text=True, check=False, cwd=str(root),
        )
        return proc

    def test_good_consumer_passes(self):
        proc = self.run_cli(materialize(self, "good"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "passed")

    def test_bad_consumer_fails_with_missing_gate(self):
        proc = self.run_cli(materialize(self, "bad"))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        rules = {f["rule_id"] for c in result["checks"] for f in c["findings"]}
        self.assertIn("plans.schema.missing-gate", rules)


class WorkflowTextTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_every_action_is_pinned_to_a_full_sha(self):
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", self.text, re.MULTILINE)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)

    def test_permissions_are_read_only(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")

    def test_no_path_filter(self):
        self.assertNotRegex(self.text, r"(?m)^\s*paths(-ignore)?:")

    def test_triggers(self):
        for trigger in ("pull_request:", "push:", "workflow_dispatch:"):
            self.assertIn(trigger, self.text)

    def test_source_tree_is_on_the_python_path(self):
        self.assertRegex(self.text, r"(?m)^\s+PYTHONPATH: src$")


if __name__ == "__main__":
    unittest.main()
