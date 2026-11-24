"""Tests for the adoption tools. Every repository is built at run time in a temporary directory."""

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

from deterministic_controls import adopt  # noqa: E402
from deterministic_controls.cli import main as cli_main  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
OLD_WORKFLOW = """name: context
on:
  pull_request:
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/check_context.py
"""


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(list(argv))
    return code, out.getvalue(), err.getvalue()


class RepoCase(unittest.TestCase):
    def make_repo(self, files=None, commit=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "target-repo"
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main")
        for rel, content in (files or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        if commit:
            self.commit(root)
        return root

    def git(self, root, *args):
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                             env=GIT_ENV, check=True)
        return out.stdout

    def commit(self, root, message="c"):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "--allow-empty", "-m", message)

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}

    def template_repo(self):
        return self.make_repo({
            "README.md": "# Example\n",
            "plans/AGENTS.md": "# Plans\n",
            "scripts/check_context.py": "print('old template script')\n",
            "scripts/build_indexes.py": "print('old')\n",
            "scripts/deploy.sh": "#!/bin/sh\necho project script\n",
            "tests/test_x.py": "import unittest\n",
            ".github/workflows/context.yml": OLD_WORKFLOW,
        })

    def adopted_repo(self):
        root = self.template_repo()
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)[0], 0)
        self.commit(root, "adopt")
        return root


class ClassificationTest(RepoCase):
    def classify(self, root):
        code, out, _ = run_cli("adopt", "audit", "--root", str(root), "--format", "json")
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_needs_shims(self):
        r = self.classify(self.template_repo())
        self.assertEqual(r["classification"], "needs-shims")
        self.assertTrue(r["template_derived"])
        self.assertIn("python", r["languages"])
        self.assertIn(".github/workflows/context.yml", r["ci_files"])
        self.assertIn("python3 -m unittest discover -s tests", r["test_commands"])
        self.assertEqual(r["current_checks"], ["build_indexes.py"])

    def test_compliant(self):
        self.assertEqual(self.classify(self.adopted_repo())["classification"], "compliant")

    def test_partial(self):
        root = self.template_repo()
        (root / "controls.toml").write_text('schema_version = 1\nprofile = "ci"\n', encoding="utf-8")
        self.assertEqual(self.classify(root)["classification"], "partial")

    def test_not_suitable(self):
        root = self.make_repo({"main.go": "package main\n"})
        r = self.classify(root)
        self.assertEqual(r["classification"], "not-suitable")
        self.assertEqual(r["languages"], ["go"])

    def test_blocked_not_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run_cli("adopt", "audit", "--root", tmp, "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["classification"], "blocked")

    def test_blocked_case_collision(self):
        root = self.template_repo()
        # Two blobs whose paths differ only by case. Add them with the index, so any file system works.
        for name in ("Notes.md", "notes.md"):
            blob = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"],
                                  input="x\n", capture_output=True, text=True, env=GIT_ENV, check=True)
            self.git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob.stdout.strip()},{name}")
        r = self.classify(root)
        self.assertEqual(r["classification"], "blocked")
        self.assertEqual(r["case_collisions"], [["Notes.md", "notes.md"]])

    def test_blocked_bad_manifest(self):
        root = self.template_repo()
        (root / "controls.toml").write_text("not valid = = toml\n", encoding="utf-8")
        self.assertEqual(self.classify(root)["classification"], "blocked")

    def test_text_output_and_read_only(self):
        root = self.template_repo()
        before = self.snapshot(root)
        code, out, _ = run_cli("adopt", "audit", "--root", str(root))
        self.assertEqual(code, 0)
        self.assertIn("classification: needs-shims", out)
        self.assertEqual(self.snapshot(root), before)


class PlanApplyTest(RepoCase):
    def test_plan_prints_diff_and_changes_nothing(self):
        root = self.template_repo()
        before = self.snapshot(root)
        code, out, _ = run_cli("adopt", "plan", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 0)
        self.assertIn("+++ b/scripts/check_context.py", out)
        self.assertIn("+++ b/controls.toml", out)
        self.assertIn(f"@{COMMIT}", out)
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_apply_writes_expected_files(self):
        root = self.template_repo()
        code, _, _ = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 0)
        for rel in ("scripts/check_context.py", "scripts/controls-requirements.txt", "controls.toml",
                    "scripts/secret_guard.py", "scripts/install_hooks.sh"):
            self.assertTrue((root / rel).is_file(), rel)
        req = (root / "scripts/controls-requirements.txt").read_text(encoding="utf-8")
        self.assertIn(f'"deterministic-controls @ git+https://github.com/dullroar/deterministic-controls@{COMMIT}"', req)
        self.assertNotIn("<commit>", req)
        self.assertIn("schema_version = 1", (root / "controls.toml").read_text(encoding="utf-8"))
        self.assertTrue(os.access(root / "scripts/install_hooks.sh", os.X_OK))
        workflow = (root / ".github/workflows/context.yml").read_text(encoding="utf-8")
        self.assertIn("  check:\n", workflow)
        self.assertIn("  controls:\n", workflow)
        self.assertIn("permissions:\n      contents: read", workflow)
        self.assertIn("secret_guard.py --tracked", workflow)
        self.assertIn("secret_guard.py --range", workflow)
        for line in workflow.splitlines():
            if "uses:" in line:
                self.assertRegex(line, r"@[0-9a-f]{40}")
        # Nothing is committed and the branch is the same.
        self.assertEqual(self.git(root, "rev-list", "--count", "HEAD").strip(), "1")
        self.assertEqual(self.git(root, "branch", "--show-current").strip(), "main")

    def test_apply_scripts_have_run_me_when(self):
        # Regression (0.1.1): every file that apply writes under scripts/ needs a
        # "Run me when:" line in its first 25 lines, or build_indexes.py fails.
        root = self.template_repo()
        code, _, _ = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 0)
        for rel in ("scripts/check_context.py", "scripts/controls-requirements.txt",
                    "scripts/secret_guard.py", "scripts/install_hooks.sh"):
            head = (root / rel).read_text(encoding="utf-8").splitlines()[:25]
            self.assertTrue(any("Run me when:" in line for line in head), rel)

    def test_apply_creates_workflow_when_absent(self):
        root = self.make_repo({"README.md": "# x\n"})
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)[0], 0)
        workflow = (root / ".github/workflows/context.yml").read_text(encoding="utf-8")
        self.assertIn("jobs:\n  controls:\n", workflow)

    def test_apply_twice_is_idempotent_and_keeps_project_files(self):
        root = self.template_repo()
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)[0], 0)
        self.commit(root, "adopt")
        before = self.snapshot(root)
        code, out, _ = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 0)
        self.assertIn("nothing to change", out)
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(self.git(root, "status", "--porcelain"), "")
        self.assertIn("project script", (root / "scripts/deploy.sh").read_text(encoding="utf-8"))
        self.assertIn("  check:\n", (root / ".github/workflows/context.yml").read_text(encoding="utf-8"))
        self.assertEqual(run_cli("adopt", "plan", "--root", str(root), "--commit", COMMIT)[1], "")

    def test_apply_new_pin_changes_only_the_pin(self):
        root = self.adopted_repo()
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", OTHER_COMMIT)[0], 0)
        self.assertEqual(self.git(root, "status", "--porcelain").split(), ["M", "scripts/controls-requirements.txt"])

    def test_apply_keeps_an_existing_manifest(self):
        root = self.make_repo({"controls.toml": 'schema_version = 1\nprofile = "quick"\nenabled = []\n'})
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)[0], 0)
        self.assertIn('profile = "quick"', (root / "controls.toml").read_text(encoding="utf-8"))

    def test_dirty_tree_fails_and_changes_nothing(self):
        root = self.template_repo()
        (root / "README.md").write_text("# changed\n", encoding="utf-8")
        before = self.snapshot(root)
        code, _, err = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 2)
        self.assertIn("not clean", err)
        self.assertEqual(self.snapshot(root), before)

    def test_untracked_file_counts_as_dirty(self):
        root = self.template_repo()
        (root / "new.txt").write_text("x\n", encoding="utf-8")
        code, _, err = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual((code, "not clean" in err), (2, True))

    def test_detached_head_fails_and_changes_nothing(self):
        root = self.template_repo()
        self.git(root, "checkout", "-q", "--detach")
        before = self.snapshot(root)
        code, _, err = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 2)
        self.assertIn("detached", err)
        self.assertEqual(self.snapshot(root), before)

    def test_bad_commit_fails_and_changes_nothing(self):
        root = self.template_repo()
        before = self.snapshot(root)
        for bad in ("", "abc123", "<commit>", COMMIT.upper(), COMMIT + "0", "main"):
            for cmd in ("apply", "plan", "receipt"):
                code, _, err = run_cli("adopt", cmd, "--root", str(root), "--commit", bad)
                self.assertEqual(code, 2, (cmd, bad))
                self.assertIn("commit must be", err)
        self.assertEqual(self.snapshot(root), before)

    def test_not_a_repository_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli("adopt", "apply", "--root", tmp, "--commit", COMMIT)
            self.assertEqual(code, 2)
            self.assertIn("Git repository", err)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_workflow_without_jobs_fails_and_changes_nothing(self):
        root = self.make_repo({".github/workflows/context.yml": "name: context\non: push\n"})
        before = self.snapshot(root)
        code, _, err = run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 2)
        self.assertIn("jobs", err)
        self.assertEqual(self.snapshot(root), before)

    def test_no_remote_or_push(self):
        root = self.template_repo()
        run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(self.git(root, "remote").strip(), "")
        self.assertEqual(self.git(root, "config", "--local", "--list").count("remote."), 0)


class ShimTest(RepoCase):
    def cache_with_fake_environment(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = Path(tmp.name)
        target = cache / "deterministic-controls" / COMMIT
        (target / "venv" / "bin").mkdir(parents=True)
        python = target / "venv" / "bin" / "python"
        python.write_text(f'#!/bin/sh\nPYTHONPATH="{REPO / "src"}" exec "{sys.executable}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        (target / "ready").write_text(COMMIT + "\n", encoding="utf-8")
        return cache

    def run_shim(self, root, cache, extra_env=None):
        env = {**os.environ, "XDG_CACHE_HOME": str(cache), **(extra_env or {})}
        return subprocess.run([sys.executable, str(root / "scripts/check_context.py")], cwd=root,
                              capture_output=True, text=True, env=env, timeout=120)

    def test_old_output_lines_and_exit_zero(self):
        root = self.template_repo()
        # The fixture has no generated indexes and no link targets. Enable only the checks it can pass.
        (root / "controls.toml").write_text(
            'schema_version = 1\nprofile = "ci"\n'
            'enabled = ["plans.schema", "plans.graph", "security.secrets", "security.personal-data"]\n',
            encoding="utf-8")
        self.commit(root, "manifest")
        self.assertEqual(run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)[0], 0)
        self.commit(root, "adopt")
        proc = self.run_shim(root, self.cache_with_fake_environment())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["ok   check_plan.py", "ok   scan_secrets.py"])

    def test_failure_gives_old_fail_line_and_exit_one(self):
        root = self.adopted_repo()
        key = "".join(["-----BEGIN ", "RSA ", "PRIVATE KEY-----"])
        (root / "leak.txt").write_text(key + "\n", encoding="utf-8")
        self.commit(root, "leak")
        proc = self.run_shim(root, self.cache_with_fake_environment())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL scan_secrets.py", proc.stdout.splitlines())
        self.assertIn("ok   check_plan.py", proc.stdout.splitlines())

    def test_no_network_and_no_cache_exits_two_and_never_passes(self):
        root = self.adopted_repo()
        with tempfile.TemporaryDirectory() as empty:
            proxy = "http://127.0.0.1:9"
            proc = self.run_shim(root, empty, {"HTTPS_PROXY": proxy, "https_proxy": proxy,
                                               "HTTP_PROXY": proxy, "http_proxy": proxy,
                                               "ALL_PROXY": proxy, "GIT_TERMINAL_PROMPT": "0"})
            leftovers = [p.name for p in (Path(empty) / "deterministic-controls").glob("*")] \
                if (Path(empty) / "deterministic-controls").exists() else []
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("ok", proc.stdout)
        self.assertIn("cannot create the environment", proc.stderr)
        self.assertEqual(leftovers, [])

    def test_missing_requirements_exits_two(self):
        root = self.adopted_repo()
        (root / "scripts/controls-requirements.txt").unlink()
        proc = self.run_shim(root, self.cache_with_fake_environment())
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")

    def test_library_config_error_exits_two(self):
        root = self.adopted_repo()
        (root / "controls.toml").write_text("schema_version = 9\n", encoding="utf-8")
        proc = self.run_shim(root, self.cache_with_fake_environment())
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("ok", proc.stdout)


class ReceiptTest(RepoCase):
    FIELDS = {"schema_version", "repository", "base_revision", "control_pin", "date", "profile",
              "enabled_checks", "files_added", "files_changed", "commands_kept", "checks_run",
              "enforcement_state", "rollback"}

    def test_receipt_fields_and_content(self):
        root = self.template_repo()
        base = self.git(root, "rev-parse", "HEAD").strip()
        run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        code, out, _ = run_cli("adopt", "receipt", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual(set(r), self.FIELDS)
        self.assertEqual(r["schema_version"], 1)
        self.assertEqual(r["repository"], "target-repo")
        self.assertEqual(r["base_revision"], base)
        self.assertEqual(r["control_pin"], COMMIT)
        self.assertEqual(r["enforcement_state"], "advisory")
        self.assertIn("controls.toml", r["files_added"])
        self.assertIn("scripts/check_context.py", r["files_changed"])
        self.assertIn(".github/workflows/context.yml", r["files_changed"])
        self.assertIn("scripts/deploy.sh", r["commands_kept"])
        self.assertIn("ci-job: check", r["commands_kept"])
        self.assertTrue(r["checks_run"])
        self.assertTrue(all(set(c) == {"check_id", "status"} for c in r["checks_run"]))
        self.assertTrue(r["rollback"])
        self.assertTrue(all(isinstance(s, str) and s for s in r["rollback"]))
        self.assertRegex(r["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_receipt_holds_no_local_path(self):
        root = self.template_repo()
        run_cli("adopt", "apply", "--root", str(root), "--commit", COMMIT)
        out = run_cli("adopt", "receipt", "--root", str(root), "--commit", COMMIT)[1]
        self.assertNotIn(str(root.parent), out)
        self.assertNotIn(str(root), out)
        self.assertNotIn(str(Path.home()), out)

    def test_receipt_to_file(self):
        root = self.adopted_repo()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "receipt.json"
            code, out, _ = run_cli("adopt", "receipt", "--root", str(root), "--commit", COMMIT,
                                   "--output", str(target))
            self.assertEqual((code, out), (0, ""))
            self.assertEqual(set(json.loads(target.read_text(encoding="utf-8"))), self.FIELDS)

    def test_receipt_needs_the_matching_pin(self):
        root = self.template_repo()
        code, _, err = run_cli("adopt", "receipt", "--root", str(root), "--commit", COMMIT)
        self.assertEqual(code, 2)
        self.assertIn("apply first", err)


class TemplateTest(unittest.TestCase):
    def test_templates_match_repository_scripts(self):
        t = Path(adopt.__file__).parent / "templates"
        for name in ("secret_guard.py", "install_hooks.sh"):
            self.assertEqual((t / name).read_bytes(), (REPO / "scripts" / name).read_bytes(), name)

    def test_example_list_has_placeholders_only(self):
        text = (REPO / "adoption" / "repos.example.toml").read_text(encoding="utf-8")
        self.assertIn("example-repo-one", text)
        self.assertNotIn("/home/", text)


if __name__ == "__main__":
    unittest.main()
