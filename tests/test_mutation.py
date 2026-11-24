"""Mutation tests: each mutation turns a good repository into the expected failure.

The good repository is built at run time in a temporary directory.
A check that never fails proves nothing. Each test starts from a pass, applies
one mutation and expects one rule ID.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deterministic_controls.checks import secrets as secrets_check  # noqa: E402
from deterministic_controls.core.catalog import load_catalog  # noqa: E402
from deterministic_controls.core.manifest import read_manifest  # noqa: E402
from deterministic_controls.core.runner import exit_code, run_checks  # noqa: E402

ALL_CHECKS = [
    "context.index-freshness",
    "markdown.local-links",
    "plans.graph",
    "plans.schema",
    "repo.forbidden-artifacts",
    "security.personal-data",
    "security.secrets",
]
GIST = "Read me when: you test the mutation repository."
INDEX_HEAD = "# Plans\n\n<!-- BEGIN GENERATED INDEX -->\n\n"
INDEX_TAIL = "\n\n<!-- END GENERATED INDEX -->\n"
INDEX_BODY = f"* [demo/plan.md](./demo/plan.md)\n  {GIST}"

STEP = (
    "---\nid: s1\nstatus: pending\ndepends_on: []\ntouches: [a.txt]\nlane: none\n"
    'gate: "true"\nevidence: ""\n---\n\n# Step\n'
)
FILES = {
    "controls.toml": (
        'schema_version = 1\nprofile = "ci"\nenabled = ['
        + ", ".join(f'"{c}"' for c in ALL_CHECKS)
        + "]\n"
    ),
    "plans/demo/goal.md": "# Goal\n\nDemo goal.\n",
    "plans/demo/plan.md": f'---\ngist: "{GIST}"\n---\n\n# Plan\n\nDemo plan.\n',
    "plans/demo/steps/s1.md": STEP,
    "plans/AGENTS.md": INDEX_HEAD + INDEX_BODY + INDEX_TAIL,
    "docs/README.md": "# Docs\n\nSee the [plan](../plans/demo/plan.md#plan).\n",
}


def fake_token() -> str:
    """Build a GitHub-like token at run time. The source holds no token."""
    return "gh" + "p_" + "Zk3Qm9Tv1Rw7Yb5Nc2Hd8Lf4Jg6Ps0Ax"


def build_repo(base: Path, name: str = "repo", files: dict | None = None) -> Path:
    root = base / name
    for rel, text in (FILES if files is None else files).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def run(root: Path, profile: str | None = None) -> dict:
    """Run the real checks in process. Return the result dictionary."""
    manifest, text = read_manifest(root)
    if profile:
        manifest = type(manifest)(profile=profile, enabled=manifest.enabled,
                                  disabled=manifest.disabled, parameters=manifest.parameters)
    return run_checks(root, manifest, text, load_catalog())


def rule_ids(result: dict) -> set[str]:
    return {f["rule_id"] for c in result["checks"] for f in c["findings"]}


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation target not found in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class MutationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_repo(Path(tmp.name))

    def assert_good(self):
        result = run(self.root)
        self.assertEqual(rule_ids(result), set())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(exit_code(result), 0)

    def assert_mutant_fails(self, rule: str):
        result = run(self.root)
        self.assertIn(rule, rule_ids(result))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code(result), 1)

    def test_baseline_passes_and_runs_all_checks(self):
        result = run(self.root)
        self.assertEqual([c["check_id"] for c in result["checks"]], ALL_CHECKS)
        self.assertTrue(all(c["status"] == "passed" for c in result["checks"]))
        self.assert_good()

    def test_remove_gate(self):
        self.assert_good()
        edit(self.root, "plans/demo/steps/s1.md", 'gate: "true"\n', "")
        self.assert_mutant_fails("plans.schema.missing-gate")

    def test_empty_gate(self):
        self.assert_good()
        edit(self.root, "plans/demo/steps/s1.md", 'gate: "true"', 'gate: ""')
        self.assert_mutant_fails("plans.schema.empty-gate")

    def test_rename_dependency(self):
        self.assert_good()
        edit(self.root, "plans/demo/steps/s1.md", "depends_on: []", "depends_on: [renamed-step]")
        self.assert_mutant_fails("plans.graph.unknown-dependency")

    def test_change_heading_target(self):
        self.assert_good()
        edit(self.root, "docs/README.md", "plan.md#plan", "plan.md#renamed-heading")
        self.assert_mutant_fails("markdown.local-links.missing-anchor")

    def test_change_link_file(self):
        self.assert_good()
        edit(self.root, "docs/README.md", "plan.md#plan", "gone.md#plan")
        self.assert_mutant_fails("markdown.local-links.missing-file")

    def test_drop_index_line(self):
        self.assert_good()
        edit(self.root, "plans/AGENTS.md", INDEX_BODY, "<!-- Nothing to list yet. -->")
        self.assert_mutant_fails("context.index-freshness.stale")

    def test_remove_index_markers(self):
        self.assert_good()
        edit(self.root, "plans/AGENTS.md", "<!-- END GENERATED INDEX -->", "")
        self.assert_mutant_fails("context.index-freshness.missing-markers")

    def test_secret_is_found(self):
        self.assert_good()
        (self.root / "docs" / "notes.md").write_text(f"Key: {fake_token()}\n", encoding="utf-8")
        self.assert_mutant_fails("security.secrets.github-token")

    def test_weakened_token_pattern_is_detected_by_the_oracle(self):
        """A weakened copy of a pattern misses the secret. The real pattern finds it."""
        (self.root / "docs" / "notes.md").write_text(f"Key: {fake_token()}\n", encoding="utf-8")
        self.assertIn("security.secrets.github-token", rule_ids(run(self.root)))
        weak = [
            (rule, re.compile(r"\b(?:ghp)_[A-Za-z0-9]{60,}") if rule == "github-token" else rx, grp)
            for rule, rx, grp in secrets_check.TOKEN_RULES
        ]
        with mock.patch.object(secrets_check, "TOKEN_RULES", weak):
            mutant = run(self.root)
        self.assertNotIn("security.secrets.github-token", rule_ids(mutant))
        # The secret check passes on the mutant where it fails on the real pattern:
        # the difference is the proof. The personal-data check still catches the token.
        status = {c["check_id"]: c["status"] for c in mutant["checks"]}
        self.assertEqual(status["security.secrets"], "passed")
        self.assertEqual(status["security.personal-data"], "failed")

    def test_personal_path_is_found(self):
        self.assert_good()
        home = "/ho" + "me/" + "alice"
        (self.root / "docs" / "notes.md").write_text(f"Path: {home}/work\n", encoding="utf-8")
        result = run(self.root)
        self.assertTrue(any(r.startswith("security.personal-data.") for r in rule_ids(result)))
        self.assertEqual(exit_code(result), 1)

    def test_forbidden_artifact_is_found(self):
        self.assert_good()
        (self.root / "id_rsa").write_text("not a key\n", encoding="utf-8")
        result = run(self.root)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            {"repo.forbidden-artifacts.tracked", "security.secrets.forbidden-file"} & rule_ids(result)
        )


if __name__ == "__main__":
    unittest.main()
