"""Tests for the check `translation.structure`."""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.translation_structure import RULES, entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_structure"
CHECK = "translation.structure"

# fixture file (target path) -> sorted rule IDs of the findings
BAD = {
    "es/headings.md": ["headings"],
    "es/tables.md": ["table-cells", "table-cells", "table-rows"],
    "es/footnotes.md": ["footnotes"],
    "es/bold.md": ["bold-count"],
    "es/front.md": ["front-matter"],
    "es/front-value.md": ["front-matter"],
    "es/mermaid-flow.md": [
        "mermaid-label", "mermaid-skeleton", "mermaid-skeleton", "mermaid-skeleton"],
    "es/mermaid-seq.md": ["mermaid-label", "mermaid-skeleton"],
    "es/mermaid-state.md": ["mermaid-label", "mermaid-skeleton"],
    "es/mermaid-unclosed.md": ["mermaid-unsupported"],
    "es/mermaid-unsupported.md": ["mermaid-unsupported"],
    "es/only.md": ["missing-target"],
}


def materialize(test: unittest.TestCase, name: str, **parameters) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    write_manifest(root, **{"mapping": "map.toml", "fixed_front_matter_keys": ["kind"], **parameters})
    (root / ".git").mkdir()
    return root


def write_manifest(root: Path, **parameters) -> None:
    lines = ["schema_version = 1", 'profile = "ci"', f'enabled = ["{CHECK}"]']
    if parameters:
        lines.append(f'[parameters."{CHECK}"]')
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in parameters.items())
    (root / "controls.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def findings_of(result) -> list[dict]:
    return [f for c in result["checks"] for f in c["findings"]]


class GoodFixtureTests(unittest.TestCase):
    def test_good_translation_passes(self):
        root = materialize(self, "good")
        code, result = run_cli(root)
        self.assertEqual(code, 0, findings_of(result))
        self.assertEqual(result["status"], "passed")
        params = {"mapping": "map.toml", "fixed_front_matter_keys": ["kind"]}
        self.assertEqual(entry(Context(root, params)), [])

    def test_each_good_pair_passes_alone(self):
        for name in ["markdown", "flowchart", "sequence", "state"]:
            with self.subTest(pair=name):
                root = materialize(self, "good")
                for other in ["markdown", "flowchart", "sequence", "state"]:
                    if other != name:
                        (root / "en" / f"{other}.md").unlink()
                        (root / "es" / f"{other}.md").unlink()
                code, _ = run_cli(root)
                self.assertEqual(code, 0)


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rules(self):
        root = materialize(self, "bad")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "failed")
        found: dict[str, list[str]] = {}
        for finding in findings_of(result):
            self.assertEqual(finding["severity"], "error")
            self.assertTrue(finding["rule_id"].startswith(CHECK + "."))
            found.setdefault(finding["path"], []).append(finding["rule_id"][len(CHECK) + 1:])
        self.assertEqual({p: sorted(r) for p, r in found.items()}, BAD)

    def test_each_bad_file_fails_alone(self):
        for path, rules in BAD.items():
            with self.subTest(path=path):
                root = materialize(self, "bad")
                name = Path(path).name
                for other in sorted((root / "en").iterdir()):
                    if other.name != name:
                        other.unlink()
                        twin = root / "es" / other.name
                        if twin.exists():
                            twin.unlink()
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                findings = findings_of(result)
                self.assertEqual(sorted(f["rule_id"][len(CHECK) + 1:] for f in findings), rules)
                self.assertEqual({f["path"] for f in findings}, {path})
                for finding in findings:
                    if finding["rule_id"] != f"{CHECK}.missing-target":
                        self.assertIsInstance(finding["line"], int)
                        self.assertIn("source:", finding["message"])

    def test_front_value_needs_the_parameter(self):
        root = materialize(self, "bad", fixed_front_matter_keys=[])
        findings = entry(Context(root, {"mapping": "map.toml"}))
        self.assertNotIn("es/front-value.md", {f.path for f in findings})

    def test_mermaid_label_lines(self):
        root = materialize(self, "bad")
        findings = entry(Context(root, {"mapping": "map.toml"}))
        label = [f for f in findings if f.rule_id.endswith("mermaid-label")]
        lines = {f.path: f.line for f in label}
        self.assertEqual(lines["es/mermaid-flow.md"], 28)
        self.assertEqual(lines["es/mermaid-seq.md"], 12)
        self.assertEqual(lines["es/mermaid-state.md"], 14)


class ConfigTests(unittest.TestCase):
    def test_no_mapping_gives_no_findings(self):
        root = materialize(self, "bad")
        write_manifest(root)
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(entry(Context(root, {})), [])

    def test_disabled_rules_drop_findings(self):
        root = materialize(self, "bad", disabled_rules=[r for r in RULES])
        findings = entry(Context(root, {"mapping": "map.toml", "disabled_rules": list(RULES)}))
        self.assertEqual([f.rule_id for f in findings], [f"{CHECK}.missing-target"])

    def test_one_disabled_rule(self):
        root = materialize(self, "bad", disabled_rules=["headings"])
        _, result = run_cli(root)
        self.assertNotIn("es/headings.md", {f["path"] for f in findings_of(result)})
        self.assertIn("es/bold.md", {f["path"] for f in findings_of(result)})

    def test_unknown_disabled_rule_is_bad_config(self):
        root = materialize(self, "good", disabled_rules=["no-such-rule"])
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])

    def test_missing_mapping_file_is_bad_config(self):
        root = materialize(self, "good", mapping="nope.toml")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])

    def test_exception_waives_and_stale_row_fails(self):
        root = materialize(self, "bad", exceptions="exc.toml")
        rows = ""
        for path, rules in BAD.items():
            for rule in sorted(set(rules)):
                rows += (
                    f'[[exception]]\nrule = "{CHECK}.{rule}"\npath = "{path}"\n'
                    'reason = "known difference"\n'
                )
        (root / "exc.toml").write_text(rows, encoding="utf-8")
        code, _ = run_cli(root)
        self.assertEqual(code, 0)
        (root / "exc.toml").write_text(
            rows + f'[[exception]]\nrule = "{CHECK}.bold-count"\npath = "es/good.md"\nreason = "x"\n',
            encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.stale-exception"])


class ReadOnlyTests(unittest.TestCase):
    def test_check_does_not_change_the_tree(self):
        root = materialize(self, "bad")
        before = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        entry(Context(root, {"mapping": "map.toml"}))
        after = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
