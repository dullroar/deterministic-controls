"""Tests for the check `translation.untranslated-heuristic` (advisory only)."""

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

from deterministic_controls.checks.translation_untranslated import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402
from deterministic_controls.core.catalog import load_catalog  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_untranslated"
CHECK = "translation.untranslated-heuristic"
RULE = f"{CHECK}.segment"


def materialize(test: unittest.TestCase, name: str, **parameters) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    write_manifest(root, **{"mapping": "map.toml", **parameters})
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
    def test_good_fixtures_give_no_finding(self):
        root = materialize(self, "good", dnt="dnt.txt")
        code, result = run_cli(root)
        self.assertEqual(code, 0, findings_of(result))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(findings_of(result), [])

    def test_dnt_phrase_is_not_counted(self):
        root = materialize(self, "good")  # no dnt: the phrase counts
        paths = [f["path"] for f in findings_of(run_cli(root)[1])]
        self.assertEqual(paths, ["es/short.md"])
        root = materialize(self, "good", dnt="dnt.txt")
        self.assertEqual(findings_of(run_cli(root)[1]), [])

    def test_short_segment_is_skipped(self):
        root = materialize(self, "good", dnt="dnt.txt")
        # With a low min_words the short English heading is reported.
        write_manifest(root, mapping="map.toml", dnt="dnt.txt", min_words=1)
        paths = {f["path"] for f in findings_of(run_cli(root)[1])}
        self.assertIn("es/short.md", paths)

    def test_no_mapping_gives_no_finding(self):
        root = materialize(self, "bad")
        write_manifest(root)
        code, result = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(findings_of(result), [])


class BadFixtureTests(unittest.TestCase):
    def test_bad_fixtures_are_reported_as_info(self):
        root = materialize(self, "bad")
        code, result = run_cli(root)
        found = findings_of(result)
        by_path = {f["path"]: f for f in found}
        self.assertEqual(sorted(by_path), ["es/paragraph.md", "es/table.md"])
        for finding in found:
            self.assertEqual(finding["rule_id"], RULE)
            self.assertEqual(finding["severity"], "info")
            self.assertIn("heuristic", finding["message"])
        self.assertEqual(by_path["es/paragraph.md"]["line"], 5)
        self.assertEqual(by_path["es/table.md"]["line"], 3)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")

    def test_target_stopwords_do_not_count(self):
        words = ["the", "of", "is", "that", "you", "can", "when", "it", "here", "one"]
        root = materialize(self, "bad", target_stopwords=words)
        self.assertEqual(findings_of(run_cli(root)[1]), [])

    def test_source_stopwords_are_a_parameter(self):
        root = materialize(self, "bad", source_stopwords=["primer", "pagina", "calma"],
                           threshold=0.1)
        found = findings_of(run_cli(root)[1])
        self.assertEqual([f["path"] for f in found], ["es/paragraph.md"])
        self.assertEqual(found[0]["line"], 3)

    def test_exception_waives_a_finding(self):
        root = materialize(self, "bad")
        (root / "waive.toml").write_text(
            f'[[exception]]\nrule = "{RULE}"\npath = "es/table.md"\nreason = "a name"\n',
            encoding="utf-8")
        write_manifest(root, mapping="map.toml", exceptions="waive.toml")
        paths = [f["path"] for f in findings_of(run_cli(root)[1])]
        self.assertEqual(paths, ["es/paragraph.md"])

    def test_bad_config_gives_a_finding(self):
        root = materialize(self, "bad", dnt="missing.txt")
        found = findings_of(run_cli(root)[1])
        self.assertEqual([f["rule_id"] for f in found], [f"{CHECK}.bad-config"])


class CatalogTests(unittest.TestCase):
    def test_entry_is_advisory_and_not_mandatory(self):
        catalog_entry = load_catalog()[CHECK]
        self.assertEqual(catalog_entry.status, "advisory")
        self.assertEqual(catalog_entry.severity, "info")
        self.assertFalse(catalog_entry.mandatory)
        self.assertIn("advisory heuristic, never required", catalog_entry.summary.lower())

    def test_entry_without_parameters_passes(self):
        self.assertEqual(entry(Context(REPO, {})), [])


if __name__ == "__main__":
    unittest.main()
