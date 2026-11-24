"""Tests for the check `translation.glossary`.

Each fixture directory is an overlay. The test copies `good` first. Then it
copies the files of the named fixture over it.
"""

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

from deterministic_controls.checks import translation_glossary as tg  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_glossary"
CHECK = "translation.glossary"

# fixtures that pass
GOOD = ["good", "waived"]

# fixture name -> (rule ID, path of the finding)
BAD = {
    "missing-rendering": (f"{CHECK}.missing-rendering", "es/a.md"),
    "banned-term": (f"{CHECK}.banned-term", "es/a.md"),
    "dnt-missing": (f"{CHECK}.dnt-missing", "es/a.md"),
    "stale-exception": (f"{CHECK}.stale-exception", "exceptions.toml"),
    "bad-missing-id": (f"{CHECK}.bad-glossary", "glossary.toml"),
    "bad-duplicate-id": (f"{CHECK}.bad-glossary", "glossary.toml"),
    "bad-empty-banned": (f"{CHECK}.bad-glossary", "glossary.toml"),
    "bad-own-banned": (f"{CHECK}.bad-glossary", "glossary.toml"),
    "bad-banned-is-other": (f"{CHECK}.bad-glossary", "glossary.toml"),
    "bad-toml": (f"{CHECK}.bad-glossary", "glossary.toml"),
}


def materialize(test: unittest.TestCase, name: str) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / "good", root)
    if name != "good":
        shutil.copytree(FIXTURES / name, root, dirs_exist_ok=True)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    write_manifest(root)
    (root / ".git").mkdir()
    return root


def write_manifest(root: Path) -> None:
    lines = [
        "schema_version = 1", 'profile = "ci"', f'enabled = ["{CHECK}"]', "",
        f'[parameters."{CHECK}"]', 'glossary = "glossary.toml"', 'mapping = "map.toml"',
    ]
    if (root / "dnt.txt").exists():
        lines.append('dnt = "dnt.txt"')
    if (root / "exceptions.toml").exists():
        lines.append('exceptions = "exceptions.toml"')
    (root / "controls.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue())


def findings_of(result) -> list[dict]:
    return [f for c in result["checks"] for f in c["findings"]]


class GoodFixtureTests(unittest.TestCase):
    def test_each_good_fixture_passes(self):
        for name in GOOD:
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 0, result)
                self.assertEqual(result["status"], "passed")


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        for name, (rule_id, path) in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                findings = findings_of(result)
                self.assertEqual({f["rule_id"] for f in findings}, {rule_id}, findings)
                self.assertEqual({f["path"] for f in findings}, {path})
                self.assertEqual(findings[0]["severity"], "error")

    def test_banned_term_line(self):
        root = materialize(self, "banned-term")
        found = tg.entry(Context(root, self.params(root)))
        self.assertEqual([f.line for f in found], [5])

    @staticmethod
    def params(root: Path) -> dict:
        return {"glossary": "glossary.toml", "mapping": "map.toml"}


class ConfigTests(unittest.TestCase):
    def test_no_glossary_parameter_gives_no_findings(self):
        root = materialize(self, "banned-term")
        self.assertEqual(tg.entry(Context(root, {})), [])
        self.assertEqual(tg.entry(Context(root, {"mapping": "map.toml"})), [])

    def test_missing_glossary_file_is_a_finding(self):
        root = materialize(self, "good")
        (root / "glossary.toml").unlink()
        found = tg.entry(Context(root, {"glossary": "glossary.toml", "mapping": "map.toml"}))
        self.assertEqual([f.rule_id for f in found], [f"{CHECK}.bad-glossary"])

    def test_missing_dnt_file_is_a_finding(self):
        root = materialize(self, "good")
        found = tg.entry(Context(root, {
            "glossary": "glossary.toml", "mapping": "map.toml", "dnt": "nope.txt"}))
        self.assertEqual([f.rule_id for f in found], [f"{CHECK}.bad-glossary"])

    def test_missing_target_file_is_a_finding(self):
        root = materialize(self, "good")
        (root / "es" / "a.md").unlink()
        found = tg.entry(Context(root, {"glossary": "glossary.toml", "mapping": "map.toml"}))
        self.assertEqual([f.rule_id for f in found], [f"{CHECK}.missing-target"])

    def test_json_glossary(self):
        root = materialize(self, "banned-term")
        data = {"terms": [{"id": "w", "en": "widget", "target": "artilugio", "banned": []}]}
        (root / "glossary.json").write_text(json.dumps(data), encoding="utf-8")
        found = tg.entry(Context(root, {"glossary": "glossary.json", "mapping": "map.toml"}))
        self.assertEqual(found, [])


class MatchTests(unittest.TestCase):
    def test_whole_word_and_case(self):
        self.assertTrue(tg.find_word("A Widget here", "widget"))
        self.assertFalse(tg.find_word("A widgetry here", "widget"))
        self.assertFalse(tg.find_word("A subwidget here", "widget"))

    def test_nfc(self):
        decomposed = "señal"
        self.assertTrue(tg.find_word(f"una {decomposed}.", "señal"))

    def test_accent_is_part_of_the_word(self):
        self.assertFalse(tg.find_word("una senal", "señal"))

    def test_skipped_text(self):
        text = "`code widget` and [x](widget.md) and <https://a.invalid/widget> ok\n"
        masked = " ".join(line for _, line in tg.prose_lines(text))
        self.assertFalse(tg.find_word(masked, "widget"))


if __name__ == "__main__":
    unittest.main()
