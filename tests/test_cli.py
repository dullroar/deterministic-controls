"""CLI tests: exit codes, messages, list, explain, check and adopt."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.cli import main  # noqa: E402

FAKE_MODULE = '''
from deterministic_controls.core.api import Finding


def ok(context):
    return []


def bad(context):
    return [Finding("fake.rule", "error", "a.txt", 3, "bad thing", "x")]


def boom(context):
    raise RuntimeError("boom")
'''


def run_cli(argv, catalog_dir=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, catalog_dir=catalog_dir)
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.catalog = self.base / "catalog"
        self.catalog.mkdir()
        (self.base / "code").mkdir()
        (self.base / "code" / "fake_checks_b01.py").write_text(FAKE_MODULE, encoding="utf-8")
        sys.path.insert(0, str(self.base / "code"))
        self.addCleanup(sys.path.remove, str(self.base / "code"))

    def add_check(self, check_id, entry="ok", module="fake_checks_b01", mandatory=False):
        (self.catalog / f"{check_id}.toml").write_text(
            f'id = "{check_id}"\nsummary = "Fake check."\nversion = "1"\n'
            f'status = "advisory"\nseverity = "error"\nmodule = "{module}"\n'
            f'entry = "{entry}"\nmandatory = {str(mandatory).lower()}\n',
            encoding="utf-8",
        )

    def write_manifest(self, text):
        (self.root / "controls.toml").write_text(text, encoding="utf-8")

    def check(self, *extra):
        return run_cli(["check", "--root", str(self.root), *extra], self.catalog)


class CheckCommandTests(CliCase):
    def test_missing_manifest(self):
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("manifest not found", err)

    def test_bad_manifest_unknown_key(self):
        self.write_manifest("schema_version = 1\nbogus = true\n")
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("unknown keys: bogus", err)

    def test_bad_manifest_schema_version(self):
        self.write_manifest("schema_version = 9\n")
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("schema_version", err)

    def test_unknown_check_id(self):
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.nope"]\n')
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("unknown check ID", err)

    def test_pass(self):
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.ok"]\n')
        code, out, _ = self.check()
        self.assertEqual(code, 0)
        self.assertIn("fake.ok: passed", out)

    def test_finding_gives_1(self):
        self.add_check("fake.bad", entry="bad")
        self.write_manifest('schema_version = 1\nenabled = ["fake.bad"]\n')
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("fake.rule a.txt:3 bad thing", out)

    def test_crash_gives_3(self):
        self.add_check("fake.boom", entry="boom")
        self.write_manifest('schema_version = 1\nenabled = ["fake.boom"]\n')
        code, out, _ = self.check()
        self.assertEqual(code, 3)
        self.assertIn("fake.boom: error", out)

    def test_mandatory_runs_in_quick(self):
        self.add_check("fake.must", entry="bad", mandatory=True)
        self.write_manifest("schema_version = 1\n")
        code, _, _ = self.check("--profile", "quick")
        self.assertEqual(code, 1)

    def test_disabling_mandatory_gives_2(self):
        self.add_check("fake.must", mandatory=True)
        self.write_manifest('schema_version = 1\ndisabled = ["fake.must"]\n')
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("mandatory", err)

    def test_json_output_is_identical_between_runs(self):
        self.add_check("fake.bad", entry="bad")
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.ok", "fake.bad"]\n')

        def strip(text):
            data = json.loads(text)
            for c in data["checks"]:
                c.pop("duration_ms")
            return data

        first = strip(self.check("--format", "json")[1])
        second = strip(self.check("--format", "json")[1])
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "failed")

    def test_report_file(self):
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.ok"]\n')
        report = self.base / "report.json"
        code, _, _ = self.check("--report", str(report))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "passed")

    def test_report_inside_repository_is_rejected(self):
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.ok"]\n')
        code, _, err = self.check("--report", str(self.root / "report.json"))
        self.assertEqual(code, 2)
        self.assertIn("outside the checked repository", err)
        self.assertFalse((self.root / "report.json").exists())

    def test_check_does_not_write_into_repository(self):
        self.add_check("fake.ok")
        self.write_manifest('schema_version = 1\nenabled = ["fake.ok"]\n')
        self.check()
        self.assertEqual([p.name for p in self.root.iterdir()], ["controls.toml"])


class ListExplainTests(CliCase):
    def test_list_and_explain_import_no_check_module(self):
        self.add_check("fake.lazy", module="lazy_module_never_imported_b01")
        code, out, _ = run_cli(["list"], self.catalog)
        self.assertEqual(code, 0)
        self.assertIn("fake.lazy", out)
        code, out, _ = run_cli(["explain", "fake.lazy"], self.catalog)
        self.assertEqual(code, 0)
        self.assertIn("module: lazy_module_never_imported_b01", out)
        self.assertNotIn("lazy_module_never_imported_b01", sys.modules)

    def test_explain_unknown_id(self):
        code, _, err = run_cli(["explain", "fake.nope"], self.catalog)
        self.assertEqual(code, 2)
        self.assertIn("unknown check ID", err)

    def test_bad_catalog_gives_2(self):
        (self.catalog / "fake.bad.toml").write_text('id = "fake.bad"\n', encoding="utf-8")
        code, _, err = run_cli(["list"], self.catalog)
        self.assertEqual(code, 2)
        self.assertIn("lacks keys", err)


class OtherCommandTests(unittest.TestCase):
    def run_module(self, *args):
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        return subprocess.run(
            [sys.executable, "-m", "deterministic_controls", *args],
            capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), check=False,
        )

    def test_version(self):
        proc = self.run_module("version")
        self.assertEqual(proc.returncode, 0)
        import deterministic_controls
        import tomllib

        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(proc.stdout.strip(), deterministic_controls.__version__)
        self.assertEqual(proc.stdout.strip(), pyproject["project"]["version"])

    def test_adopt_missing_root_fails(self):
        missing = os.path.join(tempfile.gettempdir(), "dc-no-such-dir-for-adopt-test")
        proc = self.run_module("adopt", "plan", "--root", missing, "--commit", "0" * 40)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("root is not a directory", proc.stderr)

    def test_unknown_command(self):
        proc = self.run_module("frobnicate")
        self.assertEqual(proc.returncode, 2)

    def test_missing_manifest_via_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_module("check", "--root", tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("manifest not found", proc.stderr)


if __name__ == "__main__":
    unittest.main()
