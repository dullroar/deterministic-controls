"""Tests for the check `security.secrets`.

Every synthetic secret is built at run time from parts, in a temporary directory.
This file holds no literal secret, so the guard finds nothing here.
"""

import contextlib
import hashlib
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

from deterministic_controls.checks import secrets as lib  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402

GUARD = REPO / "scripts" / "secret_guard.py"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
       "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
MANIFEST = 'schema_version = 1\nprofile = "ci"\nenabled = []\n'


def mix(n, alphabet="aZ3kQ9mX7pL2wR5t"):
    """A high-entropy string of length n with no placeholder words."""
    return (alphabet * (n // len(alphabet) + 1))[:n]


def J(*parts):
    return "".join(parts)


# One synthetic sample for each content rule. The key is the expected rule ID.
SAMPLES = {
    "private-key": J("-----BEGIN ", "RSA ", "PRIVATE KEY-----"),
    "anthropic-key": J("sk-", "ant-", mix(40)),
    "openai-key": J("sk-", "proj-", mix(40)),
    "github-token": J("gh", "p_", mix(36)),
    "github-pat": J("github", "_pat_", mix(40)),
    "aws-access-key-id": J("AK", "IA", "QZ7K3M9X2W5R8T4N"),
    "aws-secret-key": J("aws_secret", "_access_key = ", mix(40, "aZ3k/Q9m+X7pL2wR")),
    "google-api-key": J("AI", "za", mix(35)),
    "slack-token": J("xo", "xb-", mix(30)),
    "slack-webhook": J("https://hooks.", "slack.com/services/", "T0ABC/", "B0DEF/", mix(24)),
    "stripe-key": J("sk", "_live_", mix(24)),
    "huggingface-token": J("h", "f_", mix(34)),
    "sendgrid-key": J("S", "G.", mix(22), ".", mix(43)),
    "npm-auth-token": J("//registry.npmjs.org/:_auth", "Token=", mix(36)),
    "pypi-token": J("py", "pi-", mix(60)),
    "azure-key": J("DefaultEndpointsProtocol=https;Account", "Key=", mix(44), ";"),
    "jwt": J("ey", "J", mix(20), ".ey", "J", mix(30), ".", mix(43)),
    "url-credential": J("postgres://", "app:", mix(18), "@db.internal:5432/x"),
    "generic-secret": J("client_", "secret = \"", mix(24), "\""),
}
# The secret value that the rule matches, for the redaction test.
VALUES = {
    "aws-secret-key": mix(40, "aZ3k/Q9m+X7pL2wR"),
    "npm-auth-token": mix(36),
    "azure-key": mix(44),
    "url-credential": mix(18),
    "generic-secret": mix(24),
}

PLACEHOLDER_LINES = [
    J("pass", "word = \"<your-password-here>\""),
    J("pass", "word = \"${DB_PASSWORD}\""),
    J("api", "_key = \"", mix(10), "example", mix(10), "\""),
    J("tok", "en: ", "xxxx", mix(20)),
    J("sec", "ret = \"****", mix(20), "\""),
    J("pass", "word = changeme", mix(16)),
    J("postgres://", "user:<password>@host/db"),
]


class RepoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("controls.toml", MANIFEST)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], env=ENV, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["check", "--root", str(self.root), *extra])
        return code, out.getvalue(), err.getvalue()

    def cli_json(self, *extra):
        code, out, _ = self.cli("--format", "json", *extra)
        return code, json.loads(out), out

    def guard(self, *args):
        proc = subprocess.run(
            [sys.executable, str(GUARD), "--root", str(self.root), "--format", "json", *args],
            env=ENV, capture_output=True, text=True)
        return proc.returncode, json.loads(proc.stdout)

    @staticmethod
    def secret_findings(result):
        checks = {c["check_id"]: c for c in result["checks"]}
        return checks["security.secrets"]["findings"]


def guard_set(data):
    return {(f["rule"], f["path"], f["line"]) for f in data["findings"]}


def lib_set(report):
    return {(f.rule, f.path, f.line) for f in report.findings}


class GoodRepoTests(RepoCase):
    def test_placeholders_and_allowed_line_pass(self):
        self.write("notes.txt", "\n".join(PLACEHOLDER_LINES) + "\n")
        allowed = SAMPLES["anthropic-key"] + " <!-- secret-guard: allow synthetic test value -->"
        self.write("allowed.md", allowed + "\n")
        self.commit()
        code, result, _ = self.cli_json()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(self.secret_findings(result), [])

    def test_fingerprint_exception_passes(self):
        sample = SAMPLES["anthropic-key"]
        self.write("tests/data.txt", f"key {sample}\n")
        self.commit()
        self.assertEqual(self.cli_json()[0], 1)
        fp = hashlib.sha256(("tests/data.txt\0" + sample).encode()).hexdigest()
        self.write(lib.ALLOW_FILE, f"{fp}  tests/data.txt  synthetic test value\n")
        self.commit()
        self.assertEqual(self.cli_json()[0], 0)

    def test_bad_allow_file_does_not_pass(self):
        self.write(lib.ALLOW_FILE, "not a valid line\n")
        self.commit()
        code, result, _ = self.cli_json()
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "error")


class BadRepoTests(RepoCase):
    def test_each_rule_fails_with_rule_path_line(self):
        for rule, sample in SAMPLES.items():
            with self.subTest(rule=rule):
                self.write("src/config.txt", f"# settings\nx {sample}\n")
                self.commit(rule)
                code, result, _ = self.cli_json()
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "failed")
                found = [f for f in self.secret_findings(result)
                         if f["rule_id"] == "security.secrets." + rule]
                self.assertTrue(found, f"{rule} not found")
                self.assertEqual((found[0]["path"], found[0]["line"]), ("src/config.txt", 2))
                self.assertEqual(found[0]["severity"], "error")

    def test_forbidden_file_name(self):
        self.write(".env", "A=1\n")
        self.commit()
        code, result, _ = self.cli_json()
        self.assertEqual(code, 1)
        found = self.secret_findings(result)
        self.assertEqual([(f["rule_id"], f["path"]) for f in found],
                         [("security.secrets.forbidden-file", ".env")])

    def test_secret_in_earlier_commit_of_a_range(self):
        base = self.commit("base")
        self.write("a.txt", f"x {SAMPLES['github-token']}\n")
        self.commit("add")
        self.write("a.txt", "clean\n")
        head = self.commit("remove")
        self.assertEqual(self.cli_json()[0], 0)  # the tracked files are clean
        report = lib.scan_range(self.root, f"{base}..{head}")
        self.assertEqual(lib_set(report), {("github-token", "a.txt", 1)})
        self.assertTrue(report.findings[0].commit)

    def test_secret_in_history_only(self):
        self.write("a.txt", f"x {SAMPLES['pypi-token']}\n")
        self.commit("add")
        self.write("a.txt", "clean\n")
        self.commit("remove")
        self.assertEqual(self.cli_json()[0], 0)
        self.assertEqual(lib_set(lib.scan_history(self.root)), {("pypi-token", "a.txt", 1)})

    def test_staged_and_paths_modes(self):
        self.commit("base")
        path = self.write("s.txt", f"x {SAMPLES['jwt']}\n")
        self.git("add", "s.txt")
        self.assertEqual(lib_set(lib.scan_staged(self.root)), {("jwt", "s.txt", 1)})
        self.assertEqual(lib_set(lib.scan_paths(self.root, [str(path)])), {("jwt", "s.txt", 1)})

    def test_bad_range_and_not_a_repository_are_errors(self):
        self.commit()
        with self.assertRaises(lib.GuardError):
            lib.scan_range(self.root, "nope")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(lib.GuardError):
                lib.scan_tracked(Path(tmp))

    def test_without_git_work_tree_scans_files_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "controls.toml").write_text(MANIFEST, encoding="utf-8")
            (root / "a.txt").write_text(f"x {SAMPLES['stripe-key']}\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["check", "--root", str(root), "--format", "json"])
            self.assertEqual(code, 1)


class RedactionTests(RepoCase):
    def test_report_never_holds_the_secret(self):
        values = {}
        for rule, sample in SAMPLES.items():
            values[rule] = VALUES.get(rule, sample)
        lines = [f"line {i} {sample}" for i, sample in enumerate(SAMPLES.values())]
        self.write("all.txt", "\n".join(lines) + "\n")
        self.commit()
        for fmt in ("text", "json"):
            code, out, err = self.cli("--format", fmt)
            self.assertEqual(code, 1)
            for rule, value in values.items():
                self.assertNotIn(value, out + err, f"{rule} leaked in {fmt}")
        report_file = self.root.parent / "report.json"
        self.cli("--format", "json", "--report", str(report_file))
        text = report_file.read_text(encoding="utf-8")
        for rule, value in values.items():
            self.assertNotIn(value, text, rule)
        for item in lib.to_findings(lib.scan_tracked(self.root)):
            self.assertRegex(item.evidence, r"^.{0,4}…\d+$")


class CompatibilityTests(RepoCase):
    def test_library_finds_all_that_the_guard_finds(self):
        self.write("controls.toml", MANIFEST)
        base = self.commit("base")
        for i, sample in enumerate(SAMPLES.values()):
            self.write(f"d/f{i}.txt", f"# header\nvalue {sample}\n")
        self.write(".env", "A=1\n")
        self.write("p.txt", "\n".join(PLACEHOLDER_LINES) + "\n")
        mid = self.commit("secrets")
        for i in range(0, len(SAMPLES), 2):
            self.write(f"d/f{i}.txt", "clean\n")
        head = self.commit("partial removal")
        modes = {
            "tracked": (["--tracked"], lib.scan_tracked(self.root)),
            "history": (["--history"], lib.scan_history(self.root)),
            "range": (["--range", f"{base}..{head}"], lib.scan_range(self.root, f"{base}..{head}")),
            "range-mid": (["--range", f"{base}..{mid}"], lib.scan_range(self.root, f"{base}..{mid}")),
        }
        for name, (args, report) in modes.items():
            with self.subTest(mode=name):
                code, data = self.guard(*args)
                self.assertEqual(code, 1)
                expected = guard_set(data)
                self.assertTrue(expected)
                self.assertEqual(lib_set(report), expected)

    def test_library_agrees_on_a_clean_repository(self):
        self.write("notes.txt", "\n".join(PLACEHOLDER_LINES) + "\n")
        self.commit()
        code, data = self.guard("--tracked")
        self.assertEqual(code, 0)
        self.assertEqual(lib_set(lib.scan_tracked(self.root)), set())


class MandatoryTests(RepoCase):
    def test_cannot_be_disabled(self):
        self.write("controls.toml", MANIFEST + 'disabled = ["security.secrets"]\n')
        self.commit()
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("mandatory", err)

    def test_runs_in_quick_profile(self):
        self.write("controls.toml", 'schema_version = 1\nprofile = "quick"\nenabled = []\n')
        self.write("a.txt", f"x {SAMPLES['openai-key']}\n")
        self.commit()
        code, result, _ = self.cli_json()
        self.assertEqual(code, 1)
        check = {c["check_id"]: c for c in result["checks"]}["security.secrets"]
        self.assertEqual(check["status"], "failed")

    def test_runs_when_not_enabled(self):
        self.commit()
        _, result, _ = self.cli_json()
        check = {c["check_id"]: c for c in result["checks"]}["security.secrets"]
        self.assertEqual(check["status"], "passed")


class SelfScanTests(unittest.TestCase):
    def test_guard_finds_nothing_in_tests_and_src(self):
        for folder in ("tests", "src"):
            files = [str(p) for p in sorted((REPO / folder).rglob("*"))
                     if p.is_file() and "__pycache__" not in p.parts]
            report = lib.scan_paths(REPO, files)
            self.assertEqual(report.findings, [], folder)


if __name__ == "__main__":
    unittest.main()
