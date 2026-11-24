"""Tests for the check `markdown.document-ids`."""

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

from deterministic_controls.checks.markdown_document_ids import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "markdown_document_ids"
CHECK = "markdown.document-ids"
PARAMS = {"glob": "docs/**/*.md", "registry": "registry.toml"}

BAD = {
    "docs/missing.md": ["missing"],
    "docs/empty.md": ["empty"],
    "docs/space.md": ["bad-id"],
    "docs/two/x.md": ["duplicate"],
    "docs/changed.md": ["changed"],
    "docs/gone.md": ["orphan"],
}


def materialize(test: unittest.TestCase, name: str, **parameters) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    write_manifest(root, **(PARAMS | parameters))
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
    def test_good_fixture_passes_with_registry(self):
        root = materialize(self, "good")
        code, result = run_cli(root)
        self.assertEqual(code, 0, findings_of(result))
        self.assertEqual(entry(Context(root, PARAMS)), [])

    def test_good_fixture_passes_without_registry(self):
        root = materialize(self, "good", registry="")
        code, _ = run_cli(root)
        self.assertEqual(code, 0)

    def test_other_key(self):
        root = materialize(self, "good", key="uid")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual({f["rule_id"] for f in findings_of(result)}, {f"{CHECK}.missing"})


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        root = materialize(self, "bad")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        found: dict[str, list[str]] = {}
        for finding in findings_of(result):
            self.assertEqual(finding["severity"], "error")
            found.setdefault(finding["path"], []).append(finding["rule_id"][len(CHECK) + 1:])
        self.assertEqual(found, BAD)

    def test_duplicate_names_the_first_file(self):
        root = materialize(self, "bad")
        dup = [f for f in entry(Context(root, PARAMS)) if f.rule_id.endswith(".duplicate")]
        self.assertEqual(len(dup), 1)
        self.assertIn("docs/one/x.md", dup[0].message)

    def test_changed_and_orphan_need_the_registry(self):
        root = materialize(self, "bad", registry="")
        _, result = run_cli(root)
        rules = {f["rule_id"][len(CHECK) + 1:] for f in findings_of(result)}
        self.assertEqual(rules, {"missing", "empty", "bad-id", "duplicate"})

    def test_unicode_duplicate_after_normalization(self):
        root = materialize(self, "good")
        (root / "docs" / "c.md").write_text(
            "---\nid: dok-ñandú-β\n---\n",
            encoding="utf-8")
        findings = entry(Context(root, {"glob": "docs/**/*.md"}))
        self.assertEqual([(f.rule_id, f.path) for f in findings], [(f"{CHECK}.duplicate", "docs/sub/b.md")])


class ConfigTests(unittest.TestCase):
    def test_no_parameters_pass(self):
        root = materialize(self, "bad")
        write_manifest(root)
        code, _ = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(entry(Context(root, {})), [])

    def test_missing_registry_is_bad_config(self):
        root = materialize(self, "good", registry="nope.toml")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])

    def test_bad_registry_is_bad_config(self):
        root = materialize(self, "good")
        (root / "registry.toml").write_text("[other]\nx = 1\n", encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])

    def test_registry_without_glob_is_bad_config(self):
        root = materialize(self, "good", glob="")
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])


class ReadOnlyTests(unittest.TestCase):
    def test_check_does_not_change_the_tree(self):
        root = materialize(self, "bad")
        before = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        entry(Context(root, PARAMS))
        after = sorted((p.relative_to(root), p.read_bytes()) for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
