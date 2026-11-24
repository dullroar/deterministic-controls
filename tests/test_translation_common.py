"""Tests for the shared helpers of the translation pack."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks import translation_common as tc  # noqa: E402
from deterministic_controls.core.api import Context, Finding  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_common"
CHECK = "translation.demo"


def materialize(test: unittest.TestCase, name: str) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    return root


def scan_fixture(name: str) -> tc.Scan:
    text = (FIXTURES / "scanner" / f"{name}.fixture").read_text(encoding="utf-8")
    return tc.scan_markdown(text)


class MappingTest(unittest.TestCase):
    def test_missing_parameter_is_not_configured(self):
        root = materialize(self, "good")
        self.assertIsNone(tc.load_mapping(Context(root, {})))
        self.assertEqual(tc.load_exceptions(Context(root, {})), [])

    def test_good_mapping(self):
        root = materialize(self, "good")
        mapping = tc.load_mapping(Context(root, {"mapping": "map.toml"}))
        self.assertEqual(mapping.source_root, "en")
        self.assertEqual(mapping.target_root, "es")
        self.assertEqual(mapping.path_renames, {"sub/b.md": "sub/renamed.md"})
        self.assertEqual(tc.map_anchor(mapping, "first-title"), "primer-titulo")
        self.assertEqual(tc.map_anchor(mapping, "other"), "other")

    def test_missing_file(self):
        root = materialize(self, "good")
        with self.assertRaises(tc.ConfigError) as caught:
            tc.load_mapping(Context(root, {"mapping": "nope.toml"}))
        self.assertEqual(caught.exception.path, "nope.toml")

    def test_bad_toml(self):
        root = materialize(self, "bad-toml")
        with self.assertRaises(tc.ConfigError):
            tc.load_mapping(Context(root, {"mapping": "map.toml"}))

    def test_bad_values(self):
        root = materialize(self, "good")
        cases = {
            "unknown key": 'source_root = "en"\ntarget_root = "es"\nextra = 1\n',
            "no target": 'source_root = "en"\n',
            "same roots": 'source_root = "en"\ntarget_root = "en"\n',
            "renames not table": 'source_root = "en"\ntarget_root = "es"\npath_renames = 3\n',
        }
        for label, text in cases.items():
            with self.subTest(label):
                (root / "bad.toml").write_text(text, encoding="utf-8")
                with self.assertRaises(tc.ConfigError):
                    tc.load_mapping(Context(root, {"mapping": "bad.toml"}))

    def test_path_that_leaves_the_root(self):
        root = materialize(self, "good")
        for text in (
            'source_root = "../en"\ntarget_root = "es"\n',
            'source_root = "en"\ntarget_root = "/abs"\n',
            'source_root = "en"\ntarget_root = "es"\n[path_renames]\n"a.md" = "../../x.md"\n',
        ):
            with self.subTest(text):
                (root / "bad.toml").write_text(text, encoding="utf-8")
                with self.assertRaises(tc.ConfigError):
                    tc.load_mapping(Context(root, {"mapping": "bad.toml"}))
        with self.assertRaises(tc.ConfigError):
            tc.load_mapping(Context(root, {"mapping": "../map.toml"}))

    def test_pairing_with_rename(self):
        root = materialize(self, "good")
        context = Context(root, {"mapping": "map.toml"})
        pairs, findings = tc.pair_documents(context, tc.load_mapping(context), CHECK)
        self.assertEqual(findings, [])
        self.assertEqual(
            [(p.source, p.target, p.target_exists) for p in pairs],
            [("en/a.md", "es/a.md", True), ("en/sub/b.md", "es/sub/renamed.md", True)],
        )

    def test_missing_target_is_a_finding(self):
        root = materialize(self, "missing-target")
        context = Context(root, {"mapping": "map.toml"})
        pairs, findings = tc.pair_documents(context, tc.load_mapping(context), CHECK)
        self.assertEqual([(f.rule_id, f.path) for f in findings],
                         [("translation.demo.missing-target", "es/a.md")])
        self.assertIn("en/a.md", findings[0].message)
        self.assertFalse(pairs[0].target_exists)

    def test_two_sources_one_target(self):
        root = materialize(self, "duplicate-target")
        context = Context(root, {"mapping": "map.toml"})
        _, findings = tc.pair_documents(context, tc.load_mapping(context), CHECK)
        self.assertEqual([(f.rule_id, f.path) for f in findings],
                         [("translation.demo.duplicate-target", "es/a.md")])

    def test_empty_source_root_is_a_finding(self):
        root = materialize(self, "good")
        (root / "m.toml").write_text('source_root = "none"\ntarget_root = "es"\n', encoding="utf-8")
        context = Context(root, {"mapping": "m.toml"})
        _, findings = tc.pair_documents(context, tc.load_mapping(context), CHECK)
        self.assertEqual([f.rule_id for f in findings], ["translation.demo.missing-source-root"])

    def test_bad_config_finding(self):
        finding = tc.bad_config_finding(CHECK, tc.ConfigError("boom", "map.toml"))
        self.assertEqual((finding.rule_id, finding.path, finding.severity),
                         ("translation.demo.bad-config", "map.toml", "error"))


class ScannerTest(unittest.TestCase):
    def kinds(self, scan: tc.Scan) -> dict[int, str]:
        return {line.number: line.kind for line in scan.lines}

    def test_every_line_class(self):
        scan = scan_fixture("all-classes.md")
        kinds = self.kinds(scan)
        self.assertEqual(kinds[1], tc.FRONT_MATTER)
        self.assertEqual(kinds[3], tc.FRONT_MATTER)
        self.assertEqual(kinds[4], tc.PROSE)
        self.assertEqual(kinds[5], tc.BLANK)
        self.assertEqual(kinds[6], tc.HTML_COMMENT)
        self.assertEqual({kinds[7], kinds[8]}, {tc.HTML_COMMENT})
        self.assertEqual({kinds[9], kinds[10]}, {tc.TABLE_ROW})
        self.assertEqual({kinds[n] for n in range(11, 14)}, {tc.FENCE})
        self.assertEqual(set(kinds.values()), set(tc.LINE_CLASSES))
        self.assertEqual(scan.problems, ())

    def test_fence_details(self):
        scan = scan_fixture("all-classes.md")
        self.assertEqual(len(scan.fences), 3)
        first, long_tilde, indented = scan.fences
        self.assertEqual((first.char, first.length, first.info, first.language),
                         ("`", 3, "python", "python"))
        self.assertEqual(first.body, ("x = 1",))
        self.assertEqual((long_tilde.char, long_tilde.length, long_tilde.info), ("~", 4, "text"))
        # a shorter `~~~` line does not close a `~~~~` fence
        self.assertEqual(long_tilde.body, ("~~~", "still inside"))
        self.assertEqual((indented.char, indented.info, indented.body), ("`", "sh", ("   indented",)))

    def test_unclosed_fence_is_reported(self):
        scan = tc.scan_markdown("text\n\n```python\ncode\nmore\n")
        self.assertEqual([(p.rule, p.line) for p in scan.problems], [("unclosed-fence", 3)])
        self.assertIsNone(scan.fences[0].close_line)
        self.assertEqual({line.kind for line in scan.lines if line.number >= 3}, {tc.FENCE})
        findings = tc.scan_findings(CHECK, "es/a.md", scan, source="en/a.md")
        self.assertEqual([(f.rule_id, f.path, f.line) for f in findings],
                         [("translation.demo.unclosed-fence", "es/a.md", 3)])

    def test_shorter_or_other_char_does_not_close(self):
        scan = tc.scan_markdown("````\ncode\n```\n~~~~\n")
        self.assertEqual([p.rule for p in scan.problems], ["unclosed-fence"])

    def test_four_space_indent_is_not_a_fence(self):
        scan = tc.scan_markdown("    ```\n    code\n")
        self.assertEqual(scan.fences, ())
        self.assertEqual({line.kind for line in scan.lines}, {tc.PROSE})

    def test_backtick_fence_info_cannot_hold_backtick(self):
        scan = tc.scan_markdown("```a`b\ntext\n")
        self.assertEqual(scan.fences, ())

    def test_unclosed_front_matter_and_comment(self):
        self.assertEqual([p.rule for p in tc.scan_markdown("---\na: b\n").problems],
                         ["unclosed-front-matter"])
        self.assertEqual([p.rule for p in tc.scan_markdown("<!-- open\ntext\n").problems],
                         ["unclosed-comment"])

    def test_dashes_after_line_one_are_not_front_matter(self):
        scan = tc.scan_markdown("text\n---\nmore\n")
        self.assertNotIn(tc.FRONT_MATTER, {line.kind for line in scan.lines})

    def test_table_row_cells(self):
        self.assertEqual(tc.split_table_row("| a | b |"), ["a", "b"])
        self.assertEqual(tc.split_table_row("|a|b|c"), ["a", "b", "c"])
        # an escaped pipe is cell text
        self.assertEqual(tc.split_table_row(r"| a \| b | c |"), [r"a \| b", "c"])
        # a pipe inside a code span is cell text
        self.assertEqual(tc.split_table_row("| `a|b` | c |"), ["`a|b`", "c"])
        # an empty cell stays
        self.assertEqual(tc.split_table_row("| a | | c |"), ["a", "", "c"])


class ExceptionTest(unittest.TestCase):
    def finding(self, rule="translation.demo.missing-target", path="es/a.md"):
        return Finding(rule, "error", path, None, "x")

    def test_waived_finding_toml_and_jsonl(self):
        root = materialize(self, "good")
        for name in ("exceptions.toml", "exceptions.jsonl"):
            with self.subTest(name):
                rows = tc.load_exceptions(Context(root, {"exceptions": name}))
                self.assertEqual(len(rows), 1)
                self.assertEqual(tc.apply_exceptions(CHECK, [self.finding()], rows), [])

    def test_other_findings_stay(self):
        root = materialize(self, "good")
        rows = tc.load_exceptions(Context(root, {"exceptions": "exceptions.toml"}))
        other_path = self.finding(path="es/b.md")
        other_rule = self.finding(rule="translation.demo.other")
        result = tc.apply_exceptions(CHECK, [other_path, other_rule], rows)
        self.assertIn(other_path, result)
        self.assertIn(other_rule, result)

    def test_stale_row_is_a_finding(self):
        root = materialize(self, "good")
        rows = tc.load_exceptions(Context(root, {"exceptions": "exceptions.toml"}))
        result = tc.apply_exceptions(CHECK, [], rows)
        self.assertEqual([(f.rule_id, f.path) for f in result],
                         [("translation.demo.stale-exception", "exceptions.toml")])

    def test_row_of_another_check_is_ignored(self):
        root = materialize(self, "good")
        rows = tc.load_exceptions(Context(root, {"exceptions": "exceptions.toml"}))
        self.assertEqual(tc.apply_exceptions("translation.other", [], rows), [])

    def test_bad_config_cannot_be_waived(self):
        row = tc.ExceptionRow("translation.demo.bad-config", "map.toml", "why", "e.toml")
        finding = tc.bad_config_finding(CHECK, tc.ConfigError("boom", "map.toml"))
        result = tc.apply_exceptions(CHECK, [finding], [row])
        self.assertIn(finding, result)
        self.assertIn("translation.demo.stale-exception", [f.rule_id for f in result])

    def test_row_without_reason(self):
        root = materialize(self, "good")
        cases = {
            "exceptions.toml": '[[exception]]\nrule = "translation.demo.x"\npath = "a.md"\nreason = " "\n',
            "exceptions.jsonl": '{"rule": "translation.demo.x", "path": "a.md"}\n',
        }
        for name, text in cases.items():
            with self.subTest(name):
                (root / name).write_text(text, encoding="utf-8")
                with self.assertRaises(tc.ConfigError):
                    tc.load_exceptions(Context(root, {"exceptions": name}))

    def test_bad_exception_files(self):
        root = materialize(self, "good")
        (root / "bad.toml").write_text("[[exception\n", encoding="utf-8")
        (root / "bad.jsonl").write_text("{not json}\n", encoding="utf-8")
        for name in ("bad.toml", "bad.jsonl", "missing.toml"):
            with self.subTest(name):
                with self.assertRaises(tc.ConfigError):
                    tc.load_exceptions(Context(root, {"exceptions": name}))


class FindingTest(unittest.TestCase):
    def test_rule_id_and_source(self):
        finding = tc.make_finding("translation.fences", "code-differs", "es/a.md", 4,
                                  "code block differs", source="en/a.md")
        self.assertEqual(finding.rule_id, "translation.fences.code-differs")
        self.assertEqual((finding.path, finding.line, finding.severity), ("es/a.md", 4, "error"))
        self.assertIn("en/a.md", finding.message)

    def test_advisory_severity(self):
        finding = tc.make_finding("translation.untranslated-heuristic", "x", "a.md", 1, "m",
                                  severity="info")
        self.assertEqual(finding.severity, "info")


if __name__ == "__main__":
    unittest.main()
