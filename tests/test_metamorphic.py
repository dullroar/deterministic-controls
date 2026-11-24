"""Metamorphic tests: changes that must not change the findings.

File creation order, repeated runs and the name of the root directory do not
change the findings.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_mutation import FILES, build_repo, fake_token, run  # noqa: E402

# A repository with several defects, so the comparison is not empty.
DEFECTS = {
    **FILES,
    "plans/demo/steps/s2.md": FILES["plans/demo/steps/s1.md"].replace("id: s1", "id: other"),
    "plans/demo/steps/s3.md": FILES["plans/demo/steps/s1.md"].replace(
        "id: s1", "id: s3").replace("depends_on: []", "depends_on: [missing]"),
    "docs/README.md": "# Docs\n\n[a](./nope.md) and [b](../plans/demo/plan.md#gone)\n",
    "docs/notes.md": f"Key: {fake_token()}\n",
}


def stable(result: dict) -> list:
    """Return the findings of a result, without time and revision fields."""
    return [
        (c["check_id"], c["status"], c.get("reason"), c["findings"])
        for c in result["checks"]
    ]


class MetamorphicTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_the_defect_repository_has_findings(self):
        result = run(build_repo(self.base, "repo", DEFECTS))
        self.assertEqual(result["status"], "failed")
        ids = {f["rule_id"] for c in result["checks"] for f in c["findings"]}
        self.assertGreaterEqual(len(ids), 5)

    def test_repeated_runs_give_the_same_findings(self):
        root = build_repo(self.base, "repo", DEFECTS)
        first = run(root)
        for _ in range(3):
            again = run(root)
            self.assertEqual(stable(first), stable(again))
            self.assertEqual(first["config_digest"], again["config_digest"])
            self.assertEqual(first["control_revision"], again["control_revision"])

    def test_file_creation_order_does_not_change_the_findings(self):
        forward = build_repo(self.base, "forward", DEFECTS)
        backward = build_repo(self.base, "backward", dict(reversed(list(DEFECTS.items()))))
        shuffled = dict(sorted(DEFECTS.items(), key=lambda kv: (len(kv[0]) * 7) % 11))
        other = build_repo(self.base, "other", shuffled)
        expected = stable(run(forward))
        self.assertEqual(expected, stable(run(backward)))
        self.assertEqual(expected, stable(run(other)))

    def test_root_directory_name_does_not_change_the_findings(self):
        root = build_repo(self.base, "first-name", DEFECTS)
        expected = stable(run(root))
        renamed = self.base / "a-very-different-root-name"
        shutil.copytree(root, renamed)
        self.assertEqual(expected, stable(run(renamed)))
        moved = self.base / "deeper" / "level" / "x"
        moved.parent.mkdir(parents=True)
        shutil.copytree(root, moved)
        self.assertEqual(expected, stable(run(moved)))

    def test_findings_hold_no_absolute_path_of_the_root(self):
        root = build_repo(self.base, "repo", DEFECTS)
        text = repr(run(root)["checks"])
        self.assertNotIn(str(root), text)
        self.assertNotIn(str(self.base), text)

    def test_findings_are_sorted(self):
        result = run(build_repo(self.base, "repo", DEFECTS))
        self.assertEqual([c["check_id"] for c in result["checks"]],
                         sorted(c["check_id"] for c in result["checks"]))
        for check in result["checks"]:
            keys = [(f["path"] or "", f["line"] or 0, f["rule_id"], f["message"])
                    for f in check["findings"]]
            self.assertEqual(keys, sorted(keys))

    def test_an_unrelated_file_does_not_change_the_findings(self):
        root = build_repo(self.base, "repo", DEFECTS)
        expected = stable(run(root))
        (root / "src").mkdir()
        (root / "src" / "tool.py").write_text("print('hello')\n", encoding="utf-8")
        self.assertEqual(expected, stable(run(root)))


if __name__ == "__main__":
    unittest.main()
