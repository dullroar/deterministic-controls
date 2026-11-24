"""Tests for the check `markdown.required-headings`."""

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

from deterministic_controls.checks.markdown_required_headings import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "markdown_required_headings"
CHECK = "markdown.required-headings"
RULES = [{"glob": "docs/*.md", "headings": ["Purpose", "Steps", "Checks"], "level": 2}]

# target path -> sorted rule IDs
BAD = {
    "docs/missing.md": ["missing"],
    "docs/order.md": ["order"],
    "docs/fence.md": ["missing"],
    "docs/level.md": ["missing"],
    "docs/unclosed.md": ["missing", "unclosed-fence"],
}


def materialize(test: unittest.TestCase, name: str, **parameters) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    write_manifest(root, **({"rules": RULES} | parameters))
    (root / ".git").mkdir()
    return root


def toml_value(value) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(value)


def write_manifest(root: Path, **parameters) -> None:
    lines = ["schema_version = 1", 'profile = "ci"', f'enabled = ["{CHECK}"]']
    if parameters:
        lines.append(f'[parameters."{CHECK}"]')
        lines.extend(f"{key} = {toml_value(value)}" for key, value in parameters.items())
    (root / "controls.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def findings_of(result) -> list[dict]:
    return [f for c in result["checks"] for f in c["findings"]]


class GoodFixtureTests(unittest.TestCase):
    def test_good_fixture_passes(self):
        root = materialize(self, "good")
        code, result = run_cli(root)
        self.assertEqual(code, 0, findings_of(result))
        self.assertEqual(entry(Context(root, {"rules": RULES})), [])


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        root = materialize(self, "bad")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        found: dict[str, list[str]] = {}
        for finding in findings_of(result):
            self.assertEqual(finding["severity"], "error")
            found.setdefault(finding["path"], []).append(finding["rule_id"][len(CHECK) + 1:])
        self.assertEqual({p: sorted(r) for p, r in found.items()}, BAD)

    def test_each_bad_file_fails_alone(self):
        for path, rules in BAD.items():
            with self.subTest(path=path):
                root = materialize(self, "bad")
                for other in sorted((root / "docs").iterdir()):
                    if f"docs/{other.name}" != path:
                        other.unlink()
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(
                    sorted(f["rule_id"][len(CHECK) + 1:] for f in findings_of(result)), rules)

    def test_order_finding_names_the_heading_line(self):
        root = materialize(self, "bad")
        findings = entry(Context(root, {"rules": RULES}))
        order = [f for f in findings if f.rule_id.endswith(".order")]
        self.assertEqual([(f.path, f.line) for f in order], [("docs/order.md", 5)])


class ConfigTests(unittest.TestCase):
    def test_no_parameters_pass(self):
        root = materialize(self, "bad")
        write_manifest(root)
        code, _ = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(entry(Context(root, {})), [])

    def test_bad_rules_give_bad_config(self):
        for rules in ("text", [1], [{"glob": "a"}], [{"glob": "a", "headings": ["x"], "level": 9}]):
            with self.subTest(rules=rules):
                root = materialize(self, "good", rules=rules)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(
                    [f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])

    def test_level_one_rule(self):
        root = materialize(self, "good", rules=[
            {"glob": "docs/edge.md", "headings": ["Title"], "level": 1}])
        code, _ = run_cli(root)
        self.assertEqual(code, 0)


class ReadOnlyTests(unittest.TestCase):
    def test_check_does_not_change_the_tree(self):
        root = materialize(self, "bad")
        before = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        entry(Context(root, {"rules": RULES}))
        after = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
