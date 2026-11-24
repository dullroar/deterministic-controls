"""Fail-closed tests: a fault never gives a pass.

A crash, a timeout or an unreadable file gives status `error` and a nonzero exit.
A skipped mandatory check fails. A crash never gives exit code 0.
"""

import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_mutation import ALL_CHECKS, build_repo, run  # noqa: E402

from deterministic_controls import cli  # noqa: E402
from deterministic_controls.core.catalog import load_catalog  # noqa: E402
from deterministic_controls.core.errors import EXIT_CONFIG, EXIT_DEFECTS, EXIT_INTERNAL  # noqa: E402
from deterministic_controls.core.runner import exit_code  # noqa: E402

BAD_BYTES = b"\xff\xfe\x00 not valid UTF-8 \xc3\x28\n"
# For each check, a repository file that the check reads.
READS = {
    "context.index-freshness": "plans/AGENTS.md",
    "markdown.local-links": "docs/README.md",
    "plans.graph": "plans/demo/steps/s1.md",
    "plans.schema": "plans/demo/steps/s1.md",
    "repo.forbidden-artifacts": None,
    "security.personal-data": "docs/README.md",
    "security.secrets": "docs/README.md",
}


def main_code(argv, **kwargs) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv, **kwargs)
    return code, out.getvalue(), err.getvalue()


class FailClosedBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = build_repo(self.base)

    def statuses(self, result) -> dict:
        return {c["check_id"]: c["status"] for c in result["checks"]}


class InternalErrorTests(FailClosedBase):
    def patch_entry(self, check_id: str, exc: BaseException):
        entry = load_catalog()[check_id]
        module = importlib.import_module(entry.module)
        return mock.patch.object(module, entry.entry, side_effect=exc)

    def test_exception_in_each_check_gives_error_and_nonzero_exit(self):
        for check_id in ALL_CHECKS:
            with self.subTest(check=check_id), self.patch_entry(check_id, RuntimeError("boom")):
                result = run(self.root)
                self.assertEqual(self.statuses(result)[check_id], "error")
                self.assertEqual(result["status"], "error")
                self.assertEqual(exit_code(result), EXIT_INTERNAL)

    def test_timeout_in_each_check_gives_error_and_nonzero_exit(self):
        for check_id in ALL_CHECKS:
            exc = subprocess.TimeoutExpired(cmd="git", timeout=1)
            with self.subTest(check=check_id), self.patch_entry(check_id, exc):
                result = run(self.root)
                self.assertEqual(self.statuses(result)[check_id], "error")
                self.assertNotEqual(exit_code(result), 0)

    def test_builtin_timeout_error_gives_error(self):
        with self.patch_entry("security.secrets", TimeoutError("late")):
            result = run(self.root)
        self.assertEqual(result["status"], "error")
        reason = next(c for c in result["checks"] if c["check_id"] == "security.secrets")["reason"]
        self.assertIn("TimeoutError", reason)

    def test_a_check_that_returns_garbage_gives_error(self):
        entry = load_catalog()["plans.schema"]
        module = importlib.import_module(entry.module)
        with mock.patch.object(module, entry.entry, return_value="not a list"):
            result = run(self.root)
        self.assertEqual(self.statuses(result)["plans.schema"], "error")
        self.assertEqual(exit_code(result), EXIT_INTERNAL)

    def test_error_in_one_check_does_not_hide_a_defect_in_another(self):
        (self.root / "plans/demo/steps/s1.md").write_text("---\nid: s1\n---\n", encoding="utf-8")
        with self.patch_entry("security.secrets", RuntimeError("boom")):
            result = run(self.root)
        status = self.statuses(result)
        self.assertEqual(status["security.secrets"], "error")
        self.assertEqual(status["plans.schema"], "failed")
        self.assertEqual(result["status"], "error")

    def test_cli_crash_never_gives_zero(self):
        with mock.patch.object(cli, "run_checks", side_effect=RuntimeError("crash")):
            code, _, err = main_code(["check", "--root", str(self.root)])
        self.assertEqual(code, EXIT_INTERNAL)
        self.assertIn("internal error", err)

    def test_cli_exit_code_for_a_check_error(self):
        with self.patch_entry("plans.graph", RuntimeError("boom")):
            code, out, _ = main_code(["check", "--root", str(self.root), "--format", "json"])
        self.assertEqual(code, EXIT_INTERNAL)
        self.assertIn('"status": "error"', out)


class FileFaultTests(FailClosedBase):
    def test_malformed_input_never_passes(self):
        """A file that is not valid UTF-8 gives `error` (or `failed`), never `passed`."""
        for check_id, rel in READS.items():
            if rel is None or check_id == "security.secrets":
                continue  # The secret scanner decodes leniently. See the next test.
            with self.subTest(check=check_id):
                root = build_repo(self.base, f"bad-{check_id}")
                (root / rel).write_bytes(BAD_BYTES)
                result = run(root)
                self.assertIn(self.statuses(result)[check_id], ("error", "failed"))
                self.assertNotEqual(exit_code(result), 0)

    def test_secret_scanner_still_finds_a_secret_in_a_malformed_file(self):
        from test_mutation import fake_token

        # No NUL byte: the scanner treats a file with a NUL byte as binary and skips it.
        bad_text = b"\xff\xfe invalid UTF-8 \xc3\x28\n"
        (self.root / "docs/notes.txt").write_bytes(bad_text + fake_token().encode() + b"\n")
        result = run(self.root)
        self.assertEqual(self.statuses(result)["security.secrets"], "failed")
        self.assertNotEqual(exit_code(result), 0)

    def test_malformed_input_gives_error_in_the_cli(self):
        (self.root / "docs/README.md").write_bytes(BAD_BYTES)
        code, out, _ = main_code(["check", "--root", str(self.root), "--format", "json"])
        self.assertEqual(code, EXIT_INTERNAL)
        self.assertIn('"status": "error"', out)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read any file")
    def test_unreadable_file_gives_error_and_nonzero_exit(self):
        path = self.root / "docs/README.md"
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        result = run(self.root)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.statuses(result)["markdown.local-links"], "error")
        self.assertEqual(exit_code(result), EXIT_INTERNAL)

    def test_missing_files_never_crash_and_never_hide_a_missing_link(self):
        for check_id, rel in READS.items():
            if rel is None:
                continue
            with self.subTest(check=check_id):
                root = build_repo(self.base, f"missing-{check_id}")
                (root / rel).unlink()
                result = run(root)
                self.assertNotEqual(self.statuses(result)[check_id], "error")
        root = build_repo(self.base, "missing-link-target")
        (root / "plans/demo/plan.md").unlink()
        result = run(root)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code(result), EXIT_DEFECTS)

    def test_missing_manifest_is_a_configuration_error(self):
        (self.root / "controls.toml").unlink()
        code, _, err = main_code(["check", "--root", str(self.root)])
        self.assertEqual(code, EXIT_CONFIG)
        self.assertIn("manifest not found", err)

    def test_malformed_manifest_is_a_configuration_error(self):
        (self.root / "controls.toml").write_text("schema_version = [", encoding="utf-8")
        code, _, _ = main_code(["check", "--root", str(self.root)])
        self.assertEqual(code, EXIT_CONFIG)

    def test_unknown_check_id_is_a_configuration_error(self):
        (self.root / "controls.toml").write_text(
            'schema_version = 1\nenabled = ["no.such-check"]\n', encoding="utf-8")
        code, _, err = main_code(["check", "--root", str(self.root)])
        self.assertEqual(code, EXIT_CONFIG)
        self.assertIn("unknown check ID", err)

    def test_missing_root_is_a_configuration_error(self):
        code, _, _ = main_code(["check", "--root", str(self.base / "absent")])
        self.assertEqual(code, EXIT_CONFIG)


class SkippedMandatoryTests(FailClosedBase):
    def test_mandatory_check_cannot_be_disabled(self):
        (self.root / "controls.toml").write_text(
            'schema_version = 1\nenabled = ["plans.schema"]\ndisabled = ["security.secrets"]\n',
            encoding="utf-8")
        code, _, err = main_code(["check", "--root", str(self.root)])
        self.assertEqual(code, EXIT_CONFIG)
        self.assertIn("mandatory", err)

    def test_mandatory_check_runs_when_the_manifest_enables_nothing(self):
        (self.root / "controls.toml").write_text("schema_version = 1\n", encoding="utf-8")
        result = run(self.root)
        self.assertEqual(self.statuses(result).get("security.secrets"), "passed")

    def test_mandatory_check_runs_in_profile_quick(self):
        result = run(self.root, profile="quick")
        self.assertEqual(self.statuses(result)["security.secrets"], "passed")

    def test_required_check_skipped_in_profile_ci_fails(self):
        """A check with status `required` that does not run fails the run."""
        catalog = load_catalog()
        entry = catalog["plans.schema"]
        required = type(entry)(**{**entry.__dict__, "status": "required"})
        catalog = {**catalog, "plans.schema": required}
        (self.root / "controls.toml").write_text(
            'schema_version = 1\nenabled = ["security.secrets"]\n', encoding="utf-8")
        from deterministic_controls.core.manifest import read_manifest
        from deterministic_controls.core.runner import run_checks

        manifest, text = read_manifest(self.root)
        result = run_checks(self.root, manifest, text, catalog)
        self.assertEqual(self.statuses(result)["plans.schema"], "skipped")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code(result), EXIT_DEFECTS)

    def test_secret_in_profile_quick_still_fails(self):
        from test_mutation import fake_token

        (self.root / "docs/notes.md").write_text(f"Key: {fake_token()}\n", encoding="utf-8")
        result = run(self.root, profile="quick")
        self.assertEqual(self.statuses(result)["security.secrets"], "failed")
        self.assertEqual(exit_code(result), EXIT_DEFECTS)


if __name__ == "__main__":
    unittest.main()
