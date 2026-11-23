"""Tests for the check `security.personal-data`.

Every personal path and e-mail address is built at run time, in a temporary directory.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.checks.personal_data import entry  # noqa: E402
from deterministic_controls.cli import main  # noqa: E402
from deterministic_controls.core.api import Context  # noqa: E402

MANIFEST = 'schema_version = 1\nprofile = "ci"\nenabled = ["security.personal-data"]\n'


def make_repo(test, files):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / "repo"
    root.mkdir()
    (root / "controls.toml").write_text(MANIFEST, encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def run_cli(root):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    return code, json.loads(out.getvalue()), out.getvalue()


def template_script_passes(root):
    if not (root / ".git").exists():
        (root / ".git").mkdir()
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "scan_secrets.py"), str(root)],
                          capture_output=True, text=True, check=False)
    return proc.returncode == 0


PERSONAL_PATH = "/ho" + "me/" + "jsmith" + "/work"
EMAIL = "jsmith" + "@" + "corp.test"


class PersonalDataTests(unittest.TestCase):
    def test_personal_path_fails(self):
        root = make_repo(self, {"docs/a.md": f"intro\nsee {PERSONAL_PATH}\n"})
        code, result, raw = run_cli(root)
        self.assertEqual(code, 1)
        check = {c["check_id"]: c for c in result["checks"]}["security.personal-data"]
        finding = check["findings"][0]
        self.assertEqual(finding["rule_id"], "security.personal-data.personal-path")
        self.assertEqual((finding["path"], finding["line"]), ("docs/a.md", 2))
        self.assertNotIn(PERSONAL_PATH, raw)

    def test_email_fails(self):
        root = make_repo(self, {"memory/m.md": f"mail {EMAIL}\n"})
        code, result, raw = run_cli(root)
        self.assertEqual(code, 1)
        findings = entry(Context(root))
        self.assertEqual([(f.rule_id, f.path, f.line) for f in findings],
                         [("security.personal-data.email", "memory/m.md", 1)])
        self.assertNotIn(EMAIL, raw)

    def test_windows_path_fails(self):
        text = "C:" + "\\Us" + "ers\\" + "jsmith"
        root = make_repo(self, {"plans/p.md": text + "\n"})
        self.assertEqual([f.rule_id for f in entry(Context(root))],
                         ["security.personal-data.personal-path"])

    def test_placeholders_pass(self):
        text = "path /home/<user>/work\nmail user@example.com\nnoreply 1+a@users.noreply.github.com\n"
        root = make_repo(self, {"docs/a.md": text})
        code, result, _ = run_cli(root)
        self.assertEqual(code, 0)
        self.assertEqual(entry(Context(root)), [])

    def test_ignore_marker_and_scope(self):
        root = make_repo(self, {
            "docs/a.md": f"{PERSONAL_PATH} <!-- scan:ignore -->\n",
            "other/b.md": f"{PERSONAL_PATH}\n",
        })
        self.assertEqual(entry(Context(root)), [])

    def test_agrees_with_template_script(self):
        cases = {
            "bad-path": {"docs/a.md": PERSONAL_PATH + "\n"},
            "bad-email": {"docs/a.md": EMAIL + "\n"},
            "good": {"docs/a.md": "path /home/<user>/x\n"},
            "ignored": {"docs/a.md": PERSONAL_PATH + " <!-- scan:ignore -->\n"},
            "out-of-scope": {"other/a.md": PERSONAL_PATH + "\n"},
        }
        for name, files in cases.items():
            with self.subTest(case=name):
                root = make_repo(self, files)
                self.assertEqual(not entry(Context(root)), template_script_passes(root))

    def test_this_repository_agrees_with_template_script(self):
        self.assertEqual(not entry(Context(REPO)), template_script_passes(REPO))


if __name__ == "__main__":
    unittest.main()
