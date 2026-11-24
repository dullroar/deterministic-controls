"""Tests for the check `translation.links`."""

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.translation_links import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_links"
SOURCE_URL = "https://example.org/source-repo"
DEFAULT_MAP = 'source_root = "en"\ntarget_root = "es"\n'
MANIFEST = (
    'schema_version = 1\nprofile = "ci"\nenabled = ["translation.links"]\n\n'
    '[parameters."translation.links"]\n'
    f'mapping = "map.toml"\nsource_repository_url = "{SOURCE_URL}"\n'
)

# fixtures that pass
GOOD = [
    "good", "unicode", "percent", "reference", "fenced", "anchor-rename", "path-rename",
]

# fixture name -> sorted rule IDs of the findings (all in the target `es/a.md`)
BAD = {
    "destination-differs": ["translation.links.destination-differs"],
    "count-differs": ["translation.links.destination-differs"],
    "external-differs": ["translation.links.external-differs"],
    "missing-file": ["translation.links.missing-file"],
    "missing-anchor": ["translation.links.missing-anchor"],
    "line-anchor-past-end": ["translation.links.line-anchor"],
    "line-anchor-range": ["translation.links.line-anchor"],
    "foreign-link": ["translation.links.foreign-repository"],
    "foreign-image": ["translation.links.foreign-repository"],
    "unicode-bad": ["translation.links.missing-anchor"],
    "percent-bad": ["translation.links.missing-file"],
    "reference-bad": ["translation.links.missing-file"],
    "anchor-rename-unmapped": ["translation.links.destination-differs"],
    "heading-renamed-stale": ["translation.links.missing-anchor"],
    "path-rename-stale": ["translation.links.destination-differs"],
    "path-rename-unmapped": ["translation.links.destination-differs"],
}


def materialize(test: unittest.TestCase, name: str, manifest: str = MANIFEST) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    if not (root / "map.toml").exists():
        (root / "map.toml").write_text(DEFAULT_MAP, encoding="utf-8")
    (root / "controls.toml").write_text(manifest, encoding="utf-8")
    (root / ".git").mkdir()
    return root


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def library_context(root: Path, **extra) -> Context:
    return Context(root, {"mapping": "map.toml", "source_repository_url": SOURCE_URL, **extra})


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
                self.assertEqual(entry(library_context(root)), [])


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        for name, rules in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                findings = [f for c in result["checks"] for f in c["findings"]]
                self.assertEqual(sorted(f["rule_id"] for f in findings), rules)
                for finding in findings:
                    self.assertEqual(finding["path"], "es/a.md")
                    self.assertEqual(finding["severity"], "error")
                    self.assertIsInstance(finding["line"], int)
                    self.assertIn("en/a.md", finding["message"])

    def test_foreign_rule_needs_the_parameter(self):
        root = materialize(self, "foreign-link")
        context = Context(root, {"mapping": "map.toml"})
        self.assertEqual(entry(context), [])

    def test_missing_target_is_a_finding(self):
        root = materialize(self, "good")
        (root / "es" / "b.md").unlink()
        findings = entry(library_context(root))
        missing = [f for f in findings if f.rule_id == "translation.links.missing-target"]
        self.assertEqual([f.path for f in missing], ["es/b.md"])

    def test_unclosed_fence_is_a_finding(self):
        root = materialize(self, "good")
        target = root / "es" / "b.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n```\ncode\n", encoding="utf-8")
        rules = [f.rule_id for f in entry(library_context(root))]
        self.assertEqual(rules, ["translation.links.unclosed-fence"])


class ConfigurationTests(unittest.TestCase):
    def test_without_mapping_there_are_no_findings(self):
        root = materialize(self, "destination-differs")
        self.assertEqual(entry(Context(root, {})), [])

    def test_enabled_without_parameters_passes(self):
        manifest = 'schema_version = 1\nprofile = "ci"\nenabled = ["translation.links"]\n'
        root = materialize(self, "destination-differs", manifest)
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")

    def test_bad_mapping_is_a_finding(self):
        root = materialize(self, "good")
        findings = entry(Context(root, {"mapping": "nope.toml"}))
        self.assertEqual([f.rule_id for f in findings], ["translation.links.bad-config"])

    def test_bad_source_repository_url_is_a_finding(self):
        root = materialize(self, "good")
        findings = entry(Context(root, {"mapping": "map.toml", "source_repository_url": 3}))
        self.assertEqual([f.rule_id for f in findings], ["translation.links.bad-config"])

    def test_exception_waives_a_finding(self):
        root = materialize(self, "missing-file")
        (root / "exceptions.toml").write_text(
            '[[exception]]\nrule = "translation.links.missing-file"\n'
            'path = "es/a.md"\nreason = "The file comes later."\n',
            encoding="utf-8")
        self.assertEqual(entry(library_context(root, exceptions="exceptions.toml")), [])

    def test_stale_exception_is_a_finding(self):
        root = materialize(self, "good")
        (root / "exceptions.toml").write_text(
            '[[exception]]\nrule = "translation.links.missing-file"\n'
            'path = "es/a.md"\nreason = "Not needed."\n',
            encoding="utf-8")
        findings = entry(library_context(root, exceptions="exceptions.toml"))
        self.assertEqual([f.rule_id for f in findings], ["translation.links.stale-exception"])


class ReadOnlyTests(unittest.TestCase):
    def test_check_does_not_change_the_tree(self):
        for name in ["good", "missing-file"]:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                before = tree_digest(root)
                entry(library_context(root))
                self.assertEqual(before, tree_digest(root))


if __name__ == "__main__":
    unittest.main()
