"""Tests for the plan checks `plans.schema` and `plans.graph`."""

import contextlib
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

from deterministic_controls.checks.plans import graph_entry, schema_entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "plans"
MANIFEST = (
    'schema_version = 1\nprofile = "ci"\n'
    'enabled = ["plans.schema", "plans.graph"]\n'
)

# fixture name -> (rule ID, path of the finding)
BAD = {
    "missing-gate": ("plans.schema.missing-gate", "plans/demo/steps/s1.md"),
    "done-without-evidence": ("plans.schema.done-without-evidence", "plans/demo/steps/s1.md"),
    "id-mismatch": ("plans.schema.id-mismatch", "plans/demo/steps/s1.md"),
    "unknown-dependency": ("plans.graph.unknown-dependency", "plans/demo"),
    "cycle": ("plans.graph.cycle", "plans/demo"),
    "touch-overlap": ("plans.graph.touch-overlap", "plans/demo"),
    "shared-lane": ("plans.graph.shared-lane", "plans/demo"),
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


def library_findings(root: Path):
    context = Context(root)
    return schema_entry(context) + graph_entry(context)


def template_script_passes(root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_plan.py"), str(root)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


class ValidPlanTests(unittest.TestCase):
    def test_valid_plan_passes(self):
        root = materialize(self, "valid")
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")
        for check in result["checks"]:
            self.assertEqual(check["findings"], [])


class BadPlanTests(unittest.TestCase):
    def test_each_bad_plan_fails_with_its_rule(self):
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

    def test_missing_goal_and_plan_files(self):
        root = materialize(self, "valid")
        (root / "plans" / "demo" / "goal.md").unlink()
        (root / "plans" / "demo" / "plan.md").unlink()
        rules = {f.rule_id for f in schema_entry(Context(root))}
        self.assertEqual(
            rules, {"plans.schema.missing-goal-file", "plans.schema.missing-plan-file"}
        )

    def test_template_and_archive_plans_are_skipped(self):
        root = materialize(self, "missing-gate")
        shutil.copytree(root / "plans" / "demo", root / "plans" / "for-each-plan")
        shutil.copytree(root / "plans" / "demo", root / "plans" / "archive")
        paths = {f.path for f in schema_entry(Context(root))}
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith("plans/demo/") for p in paths))


class CompatibilityTests(unittest.TestCase):
    def test_library_agrees_with_template_script_on_fixtures(self):
        for name in ["valid", *BAD]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                self.assertEqual(
                    not library_findings(root), template_script_passes(root)
                )

    def test_library_agrees_with_template_script_on_this_repository(self):
        self.assertEqual(
            not library_findings(REPO), template_script_passes(REPO)
        )


if __name__ == "__main__":
    unittest.main()
