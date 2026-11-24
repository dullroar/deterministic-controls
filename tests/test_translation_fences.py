"""Tests for the check `translation.fences`."""

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

from deterministic_controls.checks.translation_fences import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_fences"
CHECK = "translation.fences"
MAP = 'source_root = "en"\ntarget_root = "es"\n'

# fixtures that pass, with extra parameters
GOOD = {
    "good": "",
    "tilde": "",
    "nested": "",
    "indented": "",
    "attributes": "",
    "empty": "",
    "inline-fence-text": "inline_code = true\n",
    "translatable": "",
    "inline-good": "inline_code = true\n",
}

# fixture name -> (extra parameters, rule ID, path of the finding)
BAD = {
    "count-bad": ("", f"{CHECK}.count", "es/a.md"),
    "kind-char-bad": ("", f"{CHECK}.kind", "es/a.md"),
    "kind-lang-bad": ("", f"{CHECK}.kind", "es/a.md"),
    "code-differs-bad": ("", f"{CHECK}.code-differs", "es/a.md"),
    "unclosed-bad": ("", f"{CHECK}.unclosed", "es/a.md"),
    "unclosed-source-bad": ("", f"{CHECK}.unclosed", "en/a.md"),
    "missing-target-bad": ("", f"{CHECK}.missing-target", "es/a.md"),
    "inline-code-bad": ("inline_code = true\n", f"{CHECK}.inline-code", "es/a.md"),
}


def materialize(test: unittest.TestCase, name: str, extra: str = "", configured: bool = True) -> Path:
    """Copy a fixture tree to a temporary directory. Remove the `.fixture` suffix."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root)
    for path in sorted(root.rglob("*.fixture")):
        path.rename(path.with_suffix(""))
    (root / "map.toml").write_text(MAP, encoding="utf-8")
    manifest = f'schema_version = 1\nprofile = "ci"\nenabled = ["{CHECK}"]\n'
    if configured:
        manifest += f'\n[parameters."{CHECK}"]\nmapping = "map.toml"\n{extra}'
    (root / "controls.toml").write_text(manifest, encoding="utf-8")
    (root / ".git").mkdir()
    return root


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    try:
        return code, json.loads(out.getvalue())
    except json.JSONDecodeError as error:
        raise AssertionError(f"no JSON output (exit {code}): {err.getvalue()}") from error


def findings_of(result):
    return [f for c in result["checks"] for f in c["findings"]]


class GoodFixtureTests(unittest.TestCase):
    def test_each_good_fixture_passes(self):
        for name, extra in GOOD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name, extra)
                code, result = run_cli(root)
                self.assertEqual(code, 0, findings_of(result))
                self.assertEqual(result["status"], "passed")


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_with_its_rule(self):
        for name, (extra, rule_id, path) in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name, extra)
                code, result = run_cli(root)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                findings = findings_of(result)
                # An inline code change gives one finding for the dropped span
                # and one for the invented span. Both have the same rule.
                self.assertEqual({f["rule_id"] for f in findings}, {rule_id})
                self.assertEqual({f["path"] for f in findings}, {path})
                self.assertEqual({f["severity"] for f in findings}, {"error"})

    def test_line_ending_difference_is_a_difference(self):
        root = materialize(self, "good")
        target = root / "es" / "a.md"
        target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        findings = findings_of(result)
        self.assertEqual({f["rule_id"] for f in findings}, {f"{CHECK}.code-differs"})
        self.assertEqual({f["path"] for f in findings}, {"es/a.md"})

    def test_inline_code_is_off_by_default(self):
        root = materialize(self, "inline-code-bad")
        code, _ = run_cli(root)
        self.assertEqual(code, 0)

    def test_translatable_kind_is_compared_when_not_listed(self):
        root = materialize(self, "translatable", 'translatable_kinds = []\n')
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.code-differs"])

    def test_bad_parameter_is_a_finding(self):
        root = materialize(self, "good", 'inline_code = "yes"\n')
        code, result = run_cli(root)
        self.assertEqual(code, 1)
        self.assertEqual([f["rule_id"] for f in findings_of(result)], [f"{CHECK}.bad-config"])


class NotConfiguredTests(unittest.TestCase):
    def test_no_mapping_parameter_gives_no_findings(self):
        for name in ["good", "count-bad"]:
            with self.subTest(fixture=name):
                root = materialize(self, name, configured=False)
                code, result = run_cli(root)
                self.assertEqual(code, 0)
                self.assertEqual(entry(Context(root, {})), [])


if __name__ == "__main__":
    unittest.main()
