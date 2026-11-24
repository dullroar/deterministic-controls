"""Fail-closed tests of the translation and Markdown pack: a fault never gives a pass.

For each pack check: an exception inside the check, a timeout, a file that is
not valid UTF-8, an unreadable file and a missing parameter file give status
`error` or `failed`, and a nonzero exit. The opt-in tests show that a
repository that does not use the pack is not changed by it.
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fail_closed import BAD_BYTES, main_code  # noqa: E402
from test_mutation import run  # noqa: E402
from test_translation_negative import (  # noqa: E402
    PACK_CHECKS,
    good_files,
    jsonl,
    manifest_text,
    rule_ids,
    sha,
    write_files,
)

from deterministic_controls.core.catalog import load_catalog  # noqa: E402
from deterministic_controls.core.errors import EXIT_CONFIG, EXIT_INTERNAL  # noqa: E402
from deterministic_controls.core.runner import exit_code  # noqa: E402

MARKDOWN_CHECKS = ["markdown.required-headings", "markdown.front-matter", "markdown.document-ids"]
ALL_PACK_CHECKS = PACK_CHECKS + MARKDOWN_CHECKS

PARAMETERS = {
    "translation.fences": {"mapping": "map.toml", "inline_code": True},
    "translation.links": {"mapping": "map.toml"},
    "translation.structure": {"mapping": "map.toml", "fixed_front_matter_keys": ["kind"]},
    "translation.glossary": {"mapping": "map.toml", "glossary": "glossary.toml"},
    "translation.chunks": {"source_manifest": "source.jsonl", "target_manifest": "target.jsonl"},
    "translation.untranslated-heuristic": {"mapping": "map.toml"},
    "markdown.required-headings": {
        "rules": [{"glob": "docs/*.md", "headings": ["Title"], "level": 1}]},
    "markdown.front-matter": {"rules": [{"glob": "docs/*.md", "required_keys": ["id"]}]},
    "markdown.document-ids": {"glob": "docs/*.md", "registry": "registry.toml"},
}
# For each check, a repository file that the check reads.
READS = {
    "translation.fences": "es/doc.md",
    "translation.links": "es/doc.md",
    "translation.structure": "es/doc.md",
    "translation.glossary": "es/doc.md",
    "translation.chunks": "target.jsonl",
    "translation.untranslated-heuristic": "es/prose.md",
    "markdown.required-headings": "docs/a.md",
    "markdown.front-matter": "docs/a.md",
    "markdown.document-ids": "docs/a.md",
}
# For each check, the parameters that name a file, and the files that must exist.
FILE_PARAMETERS = {
    "translation.fences": ["mapping", "exceptions"],
    "translation.links": ["mapping", "exceptions"],
    "translation.structure": ["mapping", "exceptions"],
    "translation.glossary": ["mapping", "glossary", "exceptions"],
    "translation.chunks": ["source_manifest", "target_manifest"],
    "translation.untranslated-heuristic": ["mapping", "exceptions"],
    "markdown.document-ids": ["registry"],
}


def toml_value(value) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(value)


def single_manifest(check: str, parameters: dict | None) -> str:
    lines = ["schema_version = 1", 'profile = "ci"', f'enabled = ["{check}"]']
    if parameters:
        lines.append(f'\n[parameters."{check}"]')
        lines.extend(f"{k} = {toml_value(v)}" for k, v in parameters.items())
    return "\n".join(lines) + "\n"


def repo_files(check: str, parameters: dict | None = ...) -> dict[str, str]:
    """The good control with only `check` enabled, and the files of the Markdown checks."""
    files = good_files()
    files["docs/a.md"] = "---\nid: a1\n---\n\n# Title\n"
    files["registry.toml"] = '[ids]\n"docs/a.md" = "a1"\n'
    files["controls.toml"] = single_manifest(
        check, PARAMETERS[check] if parameters is ... else parameters)
    return files


class PackFaultBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def build(self, check: str, name: str = "repo", parameters=...) -> Path:
        return write_files(self.base / name, repo_files(check, parameters))

    @staticmethod
    def statuses(result) -> dict:
        return {c["check_id"]: c["status"] for c in result["checks"]}


class ControlsAreCleanTests(PackFaultBase):
    def test_each_pack_check_passes_on_its_good_control(self):
        for check in ALL_PACK_CHECKS:
            with self.subTest(check=check):
                result = run(self.build(check, check))
                self.assertEqual(rule_ids(result), set())
                self.assertEqual(self.statuses(result)[check], "passed")
                self.assertEqual(exit_code(result), 0)

    def test_the_pack_checks_are_in_the_catalog(self):
        self.assertTrue(set(ALL_PACK_CHECKS) <= set(load_catalog()))


class InternalErrorTests(PackFaultBase):
    @staticmethod
    def patch_entry(check_id: str, exc: BaseException):
        entry = load_catalog()[check_id]
        module = importlib.import_module(entry.module)
        return mock.patch.object(module, entry.entry, side_effect=exc)

    def test_exception_in_each_pack_check_gives_error_and_nonzero_exit(self):
        for check in ALL_PACK_CHECKS:
            with self.subTest(check=check), self.patch_entry(check, RuntimeError("boom")):
                result = run(self.build(check, check))
                self.assertEqual(self.statuses(result)[check], "error")
                self.assertEqual(result["status"], "error")
                self.assertEqual(exit_code(result), EXIT_INTERNAL)

    def test_timeout_in_each_pack_check_gives_error_and_nonzero_exit(self):
        for check in ALL_PACK_CHECKS:
            exc = subprocess.TimeoutExpired(cmd="check", timeout=1)
            with self.subTest(check=check), self.patch_entry(check, exc):
                result = run(self.build(check, check))
                self.assertEqual(self.statuses(result)[check], "error")
                self.assertNotEqual(exit_code(result), 0)

    def test_builtin_timeout_error_gives_error(self):
        with self.patch_entry("translation.links", TimeoutError("late")):
            result = run(self.build("translation.links"))
        self.assertEqual(result["status"], "error")

    def test_a_pack_check_that_returns_garbage_gives_error(self):
        for check in ALL_PACK_CHECKS:
            entry = load_catalog()[check]
            module = importlib.import_module(entry.module)
            with self.subTest(check=check), mock.patch.object(
                    module, entry.entry, return_value="not a list"):
                result = run(self.build(check, check))
                self.assertEqual(self.statuses(result)[check], "error")
                self.assertEqual(exit_code(result), EXIT_INTERNAL)


class FileFaultTests(PackFaultBase):
    def test_invalid_utf8_never_passes(self):
        for check, rel in READS.items():
            with self.subTest(check=check):
                root = self.build(check, f"bad-{check}")
                (root / rel).write_bytes(BAD_BYTES)
                result = run(root)
                self.assertIn(self.statuses(result)[check], ("error", "failed"))
                self.assertNotEqual(exit_code(result), 0)

    def test_invalid_utf8_in_the_source_file_never_passes(self):
        # `translation.untranslated-heuristic` reads only the target file.
        for check in ["translation.fences", "translation.links", "translation.structure",
                      "translation.glossary"]:
            with self.subTest(check=check):
                root = self.build(check, f"bad-source-{check}")
                (root / "en/doc.md").write_bytes(BAD_BYTES)
                result = run(root)
                self.assertIn(self.statuses(result)[check], ("error", "failed"))
                self.assertNotEqual(exit_code(result), 0)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read any file")
    def test_unreadable_file_never_passes(self):
        for check, rel in READS.items():
            with self.subTest(check=check):
                root = self.build(check, f"locked-{check}")
                path = root / rel
                os.chmod(path, 0)
                self.addCleanup(os.chmod, path, 0o644)
                result = run(root)
                self.assertIn(self.statuses(result)[check], ("error", "failed"))
                self.assertNotEqual(exit_code(result), 0)

    def test_a_missing_parameter_file_never_passes(self):
        for check, names in FILE_PARAMETERS.items():
            for name in names:
                with self.subTest(check=check, parameter=name):
                    parameters = dict(PARAMETERS[check])
                    parameters[name] = "no-such-file.toml"
                    root = self.build(check, f"missing-{check}-{name}", parameters)
                    result = run(root)
                    self.assertEqual(self.statuses(result)[check], "failed")
                    self.assertNotEqual(exit_code(result), 0)
                    self.assertTrue(rule_ids(result))

    def test_a_malformed_mapping_never_passes(self):
        for check in ["translation.fences", "translation.links", "translation.structure",
                      "translation.glossary", "translation.untranslated-heuristic"]:
            with self.subTest(check=check):
                root = self.build(check, f"badmap-{check}")
                (root / "map.toml").write_text("source_root = [", encoding="utf-8")
                result = run(root)
                self.assertEqual(self.statuses(result)[check], "failed")
                self.assertTrue(any(r.endswith(".bad-config") for r in rule_ids(result)))

    def test_a_mapping_that_leaves_the_repository_never_passes(self):
        for check in ["translation.fences", "translation.links", "translation.structure",
                      "translation.glossary", "translation.untranslated-heuristic"]:
            with self.subTest(check=check):
                root = self.build(check, f"escape-{check}")
                (root / "map.toml").write_text(
                    'source_root = "../outside"\ntarget_root = "es"\n', encoding="utf-8")
                result = run(root)
                self.assertEqual(self.statuses(result)[check], "failed")
                self.assertTrue(any(r.endswith(".bad-config") for r in rule_ids(result)))

    def test_a_missing_target_file_never_passes(self):
        for check in ["translation.fences", "translation.links", "translation.structure",
                      "translation.glossary"]:
            with self.subTest(check=check):
                root = self.build(check, f"notarget-{check}")
                (root / "es/prose.md").unlink()
                result = run(root)
                self.assertEqual(self.statuses(result)[check], "failed")
                self.assertTrue(any(r.endswith(".missing-target") for r in rule_ids(result)))

    def test_a_malformed_manifest_row_never_passes(self):
        root = self.build("translation.chunks")
        (root / "target.jsonl").write_text("{not json\n", encoding="utf-8")
        result = run(root)
        self.assertEqual(self.statuses(result)["translation.chunks"], "failed")
        self.assertIn("translation.chunks.bad-manifest", rule_ids(result))

    def test_an_unclosed_fence_is_a_finding_not_a_skip(self):
        root = self.build("translation.fences")
        path = root / "es/doc.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n```text\nnever closed\n",
                        encoding="utf-8")
        result = run(root)
        self.assertEqual(self.statuses(result)["translation.fences"], "failed")
        self.assertTrue(any(r.endswith(".unclosed") for r in rule_ids(result)))

    def test_an_unsupported_diagram_is_a_finding_not_a_skip(self):
        root = self.build("translation.structure")
        for rel in ("en/flow.md", "es/flow.md"):
            path = root / rel
            path.write_text(path.read_text(encoding="utf-8").replace(
                "flowchart TD", "gantt"), encoding="utf-8")
        result = run(root)
        self.assertEqual(self.statuses(result)["translation.structure"], "failed")
        self.assertIn("translation.structure.mermaid-unsupported", rule_ids(result))

    def test_a_bad_parameter_value_never_passes(self):
        root = self.build("translation.fences", parameters={
            "mapping": "map.toml", "inline_code": "yes"})
        result = run(root)
        self.assertEqual(self.statuses(result)["translation.fences"], "failed")
        self.assertIn("translation.fences.bad-config", rule_ids(result))

    def test_a_fault_gives_a_nonzero_exit_in_the_cli(self):
        root = self.build("translation.links")
        (root / "es/doc.md").write_bytes(BAD_BYTES)
        code, out, _ = main_code(["check", "--root", str(root), "--format", "json"])
        self.assertNotEqual(code, 0)
        self.assertIn('"status": "', out)


class OptInTests(PackFaultBase):
    def test_no_pack_configuration_and_no_pack_check_passes(self):
        files = good_files()
        files["controls.toml"] = "schema_version = 1\n"
        root = write_files(self.base / "plain", files)
        result = run(root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(exit_code(result), 0)
        ran = {c["check_id"] for c in result["checks"]}
        self.assertFalse(ran & set(ALL_PACK_CHECKS))

    def test_a_good_pair_with_a_defect_is_ignored_when_no_pack_check_is_enabled(self):
        files = good_files()
        files["controls.toml"] = "schema_version = 1\n"
        files["es/doc.md"] = files["es/doc.md"].replace("output 1", "output 2")
        result = run(write_files(self.base / "off", files))
        self.assertEqual(result["status"], "passed")

    def test_each_pack_check_enabled_without_parameters_passes(self):
        for check in ALL_PACK_CHECKS:
            with self.subTest(check=check):
                root = self.build(check, f"noparams-{check}", parameters=None)
                files = good_files()
                files["es/doc.md"] = files["es/doc.md"].replace("output 1", "output 2")
                (root / "es/doc.md").write_text(files["es/doc.md"], encoding="utf-8")
                result = run(root)
                self.assertEqual(self.statuses(result)[check], "passed")
                self.assertEqual(rule_ids(result), set())
                self.assertEqual(exit_code(result), 0)

    def test_all_pack_checks_enabled_without_parameters_pass_together(self):
        files = good_files()
        files["controls.toml"] = manifest_text(ALL_PACK_CHECKS, parameters={})
        result = run(write_files(self.base / "all", files))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(rule_ids(result), set())

    def test_an_unknown_pack_check_in_enabled_is_exit_2(self):
        for name in ["translation.no-such-check", "markdown.no-such-check"]:
            with self.subTest(check=name):
                root = self.build("translation.fences", f"unknown-{name}")
                (root / "controls.toml").write_text(
                    f'schema_version = 1\nenabled = ["{name}"]\n', encoding="utf-8")
                code, _, err = main_code(["check", "--root", str(root)])
                self.assertEqual(code, EXIT_CONFIG)
                self.assertIn("unknown check ID", err)

    def test_a_pack_check_name_with_a_typo_is_exit_2(self):
        root = self.build("translation.fences")
        (root / "controls.toml").write_text(
            'schema_version = 1\nenabled = ["translation.fence"]\n', encoding="utf-8")
        code, _, _ = main_code(["check", "--root", str(root)])
        self.assertEqual(code, EXIT_CONFIG)

    def test_this_repository_does_not_enable_the_pack(self):
        repo = Path(__file__).resolve().parent.parent
        text = (repo / "controls.toml").read_text(encoding="utf-8")
        for check in ALL_PACK_CHECKS:
            self.assertNotIn(f'"{check}"', text)


class PackSizeTests(PackFaultBase):
    """Measured times for 100 and 1,000 file pairs. The bound is loose on purpose."""

    def build_pairs(self, count: int) -> Path:
        files = {
            "map.toml": 'source_root = "en"\ntarget_root = "es"\n',
            "glossary.toml": '[[terms]]\nid = "w"\nen = "widget"\ntarget = "artilugio"\n'
                             'banned = ["cacharro"]\n',
        }
        rows_s, rows_t = [], []
        for i in range(count):
            nxt = (i + 1) % count
            src = (f"# Page {i}\n\nThe widget is on [next](p{nxt}.md#page-{nxt}).\n\n"
                   f"```text\nvalue {i}\n```\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n")
            tgt = (f"# Pagina {i}\n\nEl artilugio esta en [siguiente](p{nxt}.md#pagina-{nxt}).\n\n"
                   f"```text\nvalue {i}\n```\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n")
            files[f"en/p{i}.md"] = src
            files[f"es/p{i}.md"] = tgt
            rows_s.append({"id": f"s-{i}", "path": f"en/p{i}.md", "digest": sha(src)})
            rows_t.append({"id": f"s-{i}", "path": f"es/p{i}.md", "source_digest": sha(src),
                           "text": tgt})
        files["source.jsonl"] = jsonl(rows_s)
        files["target.jsonl"] = jsonl(rows_t)
        files["map.toml"] += "\n[anchor_renames]\n" + "\n".join(
            f'"page-{i}" = "pagina-{i}"' for i in range(count)) + "\n"
        files["controls.toml"] = manifest_text(PACK_CHECKS, parameters={
            k: v for k, v in PARAMETERS.items() if k in PACK_CHECKS})
        return write_files(self.base / f"pairs-{count}", files)

    def test_pack_scales_to_1000_pairs(self):
        for count, bound in ((100, 60.0), (1000, 300.0)):
            with self.subTest(pairs=count):
                root = self.build_pairs(count)
                started = time.perf_counter()
                result = run(root)
                elapsed = time.perf_counter() - started
                print(f"pack run, {count} file pairs: {elapsed:.2f} s", file=sys.stderr)
                self.assertEqual(rule_ids(result), set(), sorted(rule_ids(result)))
                self.assertEqual(result["status"], "passed")
                self.assertLess(elapsed, bound)


if __name__ == "__main__":
    unittest.main()
