"""Tests for the check `translation.chunks`.

Each fixture directory holds one `case.json`. The test builds the two JSONL
manifests from it and computes all digests with `hashlib`. So nobody needs to
check an opaque digest by hand.

Keys of `case.json`:

- `source`: rows with `id`, `path`, `text`. The digest is SHA-256 of `text`.
- `target`: rows with `id`, `path`, `source_text` (gives `source_digest`) and
  other fields. `text_digest_of` gives `text_digest`. `custom_id: "auto"` gives
  the right `custom_id`.
- `raw_source`, `raw_target`: lines written as they are, instead of rows.
- `blank_lines`: put blank lines between the rows.
- `no_target_file`: do not write the target manifest.
"""

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

from deterministic_controls.checks import translation_chunks as tcn  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "translation_chunks"
CHECK = "translation.chunks"

# fixtures that pass
GOOD = ["good", "good-custom-id", "good-blank-unicode", "good-both-empty"]

# fixture name -> set of (rule ID, path) that must be among the findings
BAD = {
    "missing": {(f"{CHECK}.missing", "target.jsonl")},
    "orphan": {(f"{CHECK}.orphan", "es/a.md")},
    "duplicate-source": {(f"{CHECK}.duplicate", "source.jsonl")},
    "duplicate-target": {(f"{CHECK}.duplicate", "es/a.md")},
    "stale": {(f"{CHECK}.stale", "es/a.md")},
    "empty-text": {(f"{CHECK}.empty", "es/a.md")},
    "empty-text-digest": {(f"{CHECK}.empty", "es/a.md")},
    "fuzzy": {(f"{CHECK}.fuzzy", "es/a.md")},
    "needs-review": {(f"{CHECK}.fuzzy", "es/a.md")},
    "custom-id": {(f"{CHECK}.custom-id", "es/a.md")},
    "case-differs": {
        (f"{CHECK}.missing", "target.jsonl"),
        (f"{CHECK}.orphan", "es/a.md"),
    },
    "empty-source-full-target": {(f"{CHECK}.orphan", "es/a.md")},
    "full-source-empty-target": {(f"{CHECK}.missing", "target.jsonl")},
    "bad-json": {(f"{CHECK}.bad-manifest", "target.jsonl")},
    "bad-no-id": {(f"{CHECK}.bad-manifest", "target.jsonl")},
    "bad-no-digest": {(f"{CHECK}.bad-manifest", "source.jsonl")},
    "bad-missing-file": {(f"{CHECK}.bad-manifest", "target.jsonl")},
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False)


def source_lines(case: dict) -> list[str]:
    if "raw_source" in case:
        return list(case["raw_source"])
    return [dump({"id": r["id"], "path": r["path"], "digest": sha(r["text"])})
            for r in case.get("source", [])]


def target_lines(case: dict) -> list[str]:
    if "raw_target" in case:
        return list(case["raw_target"])
    lines = []
    for spec in case.get("target", []):
        row = {k: v for k, v in spec.items()
               if k not in ("source_text", "text_digest_of", "custom_id")}
        row["source_digest"] = sha(spec["source_text"])
        if "text_digest_of" in spec:
            row["text_digest"] = sha(spec["text_digest_of"])
        if spec.get("custom_id") == "auto":
            row["custom_id"] = spec["id"] + sha(spec["source_text"])[:12]
        elif "custom_id" in spec:
            row["custom_id"] = spec["custom_id"]
        lines.append(dump(row))
    return lines


def join(lines: list[str], blank: bool) -> str:
    if not lines:
        return ""
    sep = "\n\n" if blank else "\n"
    return "\n" + sep.join(lines) + "\n" if blank else sep.join(lines) + "\n"


def materialize(test: unittest.TestCase, name: str, extra_params: str = "") -> Path:
    case = json.loads((FIXTURES / name / "case.json").read_text(encoding="utf-8"))
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    shutil.copytree(FIXTURES / name, root, ignore=shutil.ignore_patterns("case.json"))
    root.mkdir(exist_ok=True)
    blank = bool(case.get("blank_lines"))
    (root / "source.jsonl").write_text(join(source_lines(case), blank), encoding="utf-8")
    if not case.get("no_target_file"):
        (root / "target.jsonl").write_text(join(target_lines(case), blank), encoding="utf-8")
    write_manifest(root, extra_params)
    (root / ".git").mkdir()
    return root


def write_manifest(root: Path, extra: str = "") -> None:
    lines = [
        "schema_version = 1", 'profile = "ci"', f'enabled = ["{CHECK}"]', "",
        f'[parameters."{CHECK}"]', 'source_manifest = "source.jsonl"',
        'target_manifest = "target.jsonl"',
    ]
    if extra:
        lines.append(extra)
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
                self.assertEqual(findings_of(result), [])


class BadFixtureTests(unittest.TestCase):
    def test_each_bad_fixture_fails_for_its_rule(self):
        for name, expected in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                code, result = run_cli(root)
                self.assertEqual(code, 1, result)
                found = {(f["rule_id"], f["path"]) for f in findings_of(result)}
                self.assertTrue(expected <= found, f"{expected} not in {found}")

    def test_bad_fixture_fails_only_for_its_rules(self):
        # The control must be clean: no other rule fires.
        for name, expected in BAD.items():
            with self.subTest(fixture=name):
                root = materialize(self, name)
                _, result = run_cli(root)
                rules = {f["rule_id"] for f in findings_of(result)}
                self.assertEqual(rules, {rule for rule, _ in expected})

    def test_every_rule_has_a_bad_fixture(self):
        covered = {rule for expected in BAD.values() for rule, _ in expected}
        for rule in ("missing", "orphan", "duplicate", "stale", "empty",
                     "fuzzy", "custom-id", "bad-manifest"):
            self.assertIn(f"{CHECK}.{rule}", covered)


class ParameterTests(unittest.TestCase):
    def test_no_parameters_passes(self):
        root = materialize(self, "missing")
        (root / "controls.toml").write_text(
            f'schema_version = 1\nprofile = "ci"\nenabled = ["{CHECK}"]\n', encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 0, result)
        self.assertEqual(findings_of(result), [])

    def test_no_target_manifest_parameter_fails(self):
        root = materialize(self, "good")
        text = (root / "controls.toml").read_text(encoding="utf-8")
        (root / "controls.toml").write_text(
            text.replace('target_manifest = "target.jsonl"\n', ""), encoding="utf-8")
        code, result = run_cli(root)
        self.assertEqual(code, 1, result)
        self.assertEqual({f["rule_id"] for f in findings_of(result)}, {f"{CHECK}.bad-manifest"})

    def test_custom_id_digits_parameter(self):
        root = materialize(self, "good-custom-id", "custom_id_digits = 8")
        code, result = run_cli(root)
        self.assertEqual(code, 1, result)
        self.assertEqual({f["rule_id"] for f in findings_of(result)}, {f"{CHECK}.custom-id"})

    def test_bad_custom_id_digits_is_bad_config(self):
        for value in ("0", '"12"', "true"):
            with self.subTest(value=value):
                root = materialize(self, "good-custom-id", f"custom_id_digits = {value}")
                code, result = run_cli(root)
                self.assertEqual(code, 1, result)
                self.assertEqual(
                    {f["rule_id"] for f in findings_of(result)}, {f"{CHECK}.bad-config"})

    def test_entry_without_parameters_returns_nothing(self):
        self.assertEqual(tcn.entry(Context(REPO, {})), [])
        self.assertEqual(tcn.entry(Context(REPO, {"source_manifest": ""})), [])

    def test_manifest_outside_root_is_bad_manifest(self):
        root = materialize(self, "good")
        findings = tcn.entry(Context(root, {"source_manifest": "../x.jsonl",
                                            "target_manifest": "target.jsonl"}))
        self.assertEqual([f.rule_id for f in findings], [f"{CHECK}.bad-manifest"])


if __name__ == "__main__":
    unittest.main()
