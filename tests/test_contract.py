"""Contract tests: manifest, catalog, runner, policy and result JSON."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deterministic_controls.core.api import Context, Finding  # noqa: E402
from deterministic_controls.core.catalog import load_catalog  # noqa: E402
from deterministic_controls.core.errors import ConfigError  # noqa: E402
from deterministic_controls.core.manifest import parse_manifest  # noqa: E402
from deterministic_controls.core.runner import exit_code, run_checks  # noqa: E402

FAKE_MODULE = '''
from deterministic_controls.core.api import Finding


def ok(context):
    return []


def bad(context):
    return [Finding("fake.rule", "error", "a.txt", 3, "bad thing", "x")]


def boom(context):
    raise RuntimeError("boom")
'''


def catalog_toml(check_id, entry="ok", status="advisory", mandatory=False, severity="error"):
    return (
        f'id = "{check_id}"\nsummary = "Fake check."\nversion = "1"\n'
        f'status = "{status}"\nseverity = "{severity}"\n'
        f'module = "fake_checks_b01"\nentry = "{entry}"\n'
        f"mandatory = {str(mandatory).lower()}\n"
        "[parameters]\nlimit = 1\n"
    )


class Fixture:
    """A temporary catalog, a fake check module and a repository root."""

    def __init__(self, test: unittest.TestCase, checks: dict):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.root = base / "repo"
        self.root.mkdir()
        self.catalog_dir = base / "catalog"
        self.catalog_dir.mkdir()
        (base / "code").mkdir()
        (base / "code" / "fake_checks_b01.py").write_text(FAKE_MODULE, encoding="utf-8")
        sys.path.insert(0, str(base / "code"))
        test.addCleanup(sys.path.remove, str(base / "code"))
        for check_id, kwargs in checks.items():
            (self.catalog_dir / f"{check_id}.toml").write_text(
                catalog_toml(check_id, **kwargs), encoding="utf-8"
            )
        self.catalog = load_catalog(self.catalog_dir)

    def run(self, manifest_text: str) -> dict:
        return run_checks(self.root, parse_manifest(manifest_text), manifest_text, self.catalog)


def manifest(enabled=(), disabled=(), profile="ci"):
    ids = ", ".join(f'"{i}"' for i in enabled)
    dis = ", ".join(f'"{i}"' for i in disabled)
    return f'schema_version = 1\nprofile = "{profile}"\nenabled = [{ids}]\ndisabled = [{dis}]\n'


class ManifestTests(unittest.TestCase):
    def test_unknown_key(self):
        with self.assertRaisesRegex(ConfigError, "unknown keys: extra"):
            parse_manifest("schema_version = 1\nextra = 1\n")

    def test_wrong_schema_version(self):
        with self.assertRaisesRegex(ConfigError, "schema_version must be 1"):
            parse_manifest("schema_version = 2\n")

    def test_invalid_toml(self):
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            parse_manifest("schema_version = = 1")

    def test_unknown_check_id(self):
        fx = Fixture(self, {"fake.ok": {}})
        with self.assertRaisesRegex(ConfigError, "unknown check ID: nope.id"):
            fx.run(manifest(enabled=["nope.id"]))

    def test_unknown_parameter(self):
        fx = Fixture(self, {"fake.ok": {}})
        text = manifest(enabled=["fake.ok"]) + "[parameters.'fake.ok']\nbogus = 1\n"
        with self.assertRaisesRegex(ConfigError, "unknown parameters"):
            fx.run(text)


class CatalogTests(unittest.TestCase):
    def test_bad_status_is_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fake.ok.toml").write_text(
                catalog_toml("fake.ok", status="wild"), encoding="utf-8"
            )
            with self.assertRaisesRegex(ConfigError, "bad status"):
                load_catalog(Path(tmp))

    def test_default_catalog_loads(self):
        self.assertEqual(load_catalog(), {})

    def test_loader_does_not_import_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = catalog_toml("fake.ok").replace("fake_checks_b01", "never_imported_b01")
            (Path(tmp) / "fake.ok.toml").write_text(text, encoding="utf-8")
            load_catalog(Path(tmp))
        self.assertNotIn("never_imported_b01", sys.modules)


class RunnerTests(unittest.TestCase):
    def test_pass_gives_exit_0(self):
        fx = Fixture(self, {"fake.ok": {}})
        result = fx.run(manifest(enabled=["fake.ok"]))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(exit_code(result), 0)

    def test_finding_gives_exit_1(self):
        fx = Fixture(self, {"fake.bad": {"entry": "bad"}})
        result = fx.run(manifest(enabled=["fake.bad"]))
        self.assertEqual(result["checks"][0]["status"], "failed")
        self.assertEqual(result["checks"][0]["findings"][0]["rule_id"], "fake.rule")
        self.assertEqual(exit_code(result), 1)

    def test_policy_severity(self):
        from deterministic_controls.core.policy import finding_fails

        self.assertFalse(finding_fails(Finding("r", "info", None, None, "m")))
        self.assertTrue(finding_fails(Finding("r", "warning", None, None, "m")))
        self.assertTrue(finding_fails(Finding("r", "error", None, None, "m")))

    def test_internal_exception_gives_exit_3(self):
        fx = Fixture(self, {"fake.boom": {"entry": "boom"}})
        result = fx.run(manifest(enabled=["fake.boom"]))
        self.assertEqual(result["checks"][0]["status"], "error")
        self.assertIn("RuntimeError", result["checks"][0]["reason"])
        self.assertEqual(exit_code(result), 3)

    def test_missing_entry_function_is_error(self):
        fx = Fixture(self, {"fake.none": {"entry": "does_not_exist"}})
        result = fx.run(manifest(enabled=["fake.none"]))
        self.assertEqual(result["checks"][0]["status"], "error")
        self.assertEqual(exit_code(result), 3)

    def test_required_check_not_enabled_fails(self):
        fx = Fixture(self, {"fake.req": {"status": "required"}})
        result = fx.run(manifest(enabled=[]))
        self.assertEqual(result["checks"][0]["status"], "skipped")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code(result), 1)

    def test_mandatory_runs_in_quick_profile(self):
        fx = Fixture(
            self,
            {"fake.must": {"entry": "bad", "status": "required", "mandatory": True},
             "fake.opt": {"entry": "bad"}},
        )
        result = fx.run(manifest(enabled=["fake.opt"], profile="quick"))
        by_id = {c["check_id"]: c for c in result["checks"]}
        self.assertEqual(by_id["fake.must"]["status"], "failed")
        self.assertEqual(by_id["fake.opt"]["status"], "skipped")
        self.assertEqual(exit_code(result), 1)

    def test_mandatory_runs_without_being_enabled(self):
        fx = Fixture(self, {"fake.must": {"status": "required", "mandatory": True}})
        result = fx.run(manifest(enabled=[]))
        self.assertEqual(result["checks"][0]["status"], "passed")

    def test_disabling_mandatory_is_config_error(self):
        fx = Fixture(self, {"fake.must": {"status": "required", "mandatory": True}})
        with self.assertRaisesRegex(ConfigError, "mandatory and cannot be disabled"):
            fx.run(manifest(disabled=["fake.must"]))

    def test_deterministic_json(self):
        fx = Fixture(self, {"fake.bad": {"entry": "bad"}, "fake.ok": {}})
        text = manifest(enabled=["fake.ok", "fake.bad"])

        def strip(result):
            for check in result["checks"]:
                check.pop("duration_ms")
            return json.dumps(result, sort_keys=True)

        self.assertEqual(strip(fx.run(text)), strip(fx.run(text)))

    def test_result_fields(self):
        fx = Fixture(self, {"fake.ok": {}})
        result = fx.run(manifest(enabled=["fake.ok"]))
        for key in ("schema_version", "tool_version", "repository_revision",
                    "control_revision", "config_digest", "profile", "status"):
            self.assertIn(key, result)
        for key in ("check_id", "status", "duration_ms", "findings"):
            self.assertIn(key, result["checks"][0])

    def test_run_does_not_write_into_repository(self):
        fx = Fixture(self, {"fake.ok": {}})
        fx.run(manifest(enabled=["fake.ok"]))
        self.assertEqual(list(fx.root.iterdir()), [])


class ContextTests(unittest.TestCase):
    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Context(Path(tmp))
            with self.assertRaises(ValueError):
                context.read_text("../outside.txt")

    def test_list_files_is_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("b.txt", "a.txt"):
                (Path(tmp) / name).write_text("x", encoding="utf-8")
            self.assertEqual(Context(Path(tmp)).list_files(), ["a.txt", "b.txt"])


if __name__ == "__main__":
    unittest.main()
