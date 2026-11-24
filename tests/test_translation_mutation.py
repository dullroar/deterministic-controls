"""Mutation and metamorphic tests of the translation pack.

Each test starts from a good pair that passes, applies one mutation and
expects one failure with one rule ID. The good pair comes from
`test_translation_negative.py`.
"""

import dataclasses
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_mutation import run  # noqa: E402
from test_translation_negative import (  # noqa: E402
    PACK_CHECKS,
    build_good,
    edit,
    good_files,
    mutate_chunks,
    rule_ids,
    sha,
    write_files,
)

from deterministic_controls.checks import translation_glossary as glossary_check  # noqa: E402
from deterministic_controls.core.runner import exit_code  # noqa: E402


def stable(result: dict) -> list:
    return [(c["check_id"], c["status"], c.get("reason"), c["findings"]) for c in result["checks"]]


class PackMutationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = build_good(self.base)

    def assert_good(self):
        result = run(self.root)
        self.assertEqual(rule_ids(result), set())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(exit_code(result), 0)

    def assert_mutant_fails(self, rule: str):
        result = run(self.root)
        self.assertIn(rule, rule_ids(result))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code(result), 1)

    def test_baseline_runs_all_pack_checks(self):
        result = run(self.root)
        self.assertTrue(set(PACK_CHECKS) <= {c["check_id"] for c in result["checks"]})
        self.assert_good()

    def test_drop_a_fence(self):
        self.assert_good()
        edit(self.root, "es/doc.md", "```text\noutput 1\n```\n\n", "")
        self.assert_mutant_fails("translation.fences.count")

    def test_swap_two_mermaid_edges(self):
        self.assert_good()
        edit(self.root, "es/flow.md", '    B -->|si| C["Enviar"]\n    B -->|no| D["Rechazar"]\n',
             '    B -->|no| D["Rechazar"]\n    B -->|si| C["Enviar"]\n')
        self.assert_mutant_fails("translation.structure.mermaid-skeleton")

    def test_drop_a_table_cell(self):
        self.assert_good()
        edit(self.root, "es/doc.md", "| a | b |", "| a |")
        self.assert_mutant_fails("translation.structure.table-cells")

    def test_change_a_link_fragment(self):
        self.assert_good()
        edit(self.root, "es/doc.md", "otro.md#parte", "otro.md#part")
        self.assert_mutant_fails("translation.links.missing-anchor")

    def test_rename_a_file_without_a_path_rename(self):
        self.assert_good()
        (self.root / "es" / "otro.md").rename(self.root / "es" / "renamed.md")
        self.assert_mutant_fails("translation.links.missing-target")

    def test_remove_a_chunk_row(self):
        self.assert_good()
        mutate_chunks(self.root, lambda src, tgt: tgt.pop())
        self.assert_mutant_fails("translation.chunks.missing")

    def test_change_a_source_digest(self):
        self.assert_good()
        mutate_chunks(self.root, lambda src, tgt: src[0].update(digest=sha("edited")))
        self.assert_mutant_fails("translation.chunks.stale")

    def test_weaken_the_glossary_banned_list_in_a_copy_of_the_check(self):
        """A copy of the check with an empty banned list misses the defect. The real check finds it."""
        edit(self.root, "es/doc.md", "El artilugio usa", "El cacharro usa")
        self.assertIn("translation.glossary.banned-term", rule_ids(run(self.root)))
        real = glossary_check._load_terms

        def weak(context):
            loaded = real(context)
            if loaded is None:
                return loaded
            terms, *rest = loaded
            return ([dataclasses.replace(t, banned=()) for t in terms], *rest)

        with mock.patch.object(glossary_check, "_load_terms", weak):
            mutant = run(self.root)
        self.assertNotIn("translation.glossary.banned-term", rule_ids(mutant))
        # Only the missing approved rendering is left: the banned word is not seen.
        glossary_rules = {r for r in rule_ids(mutant) if r.startswith("translation.glossary.")}
        self.assertEqual(glossary_rules, {"translation.glossary.missing-rendering"})

    def test_each_mutation_is_caught_by_its_own_check_only(self):
        """A fence mutation does not make the chunk check fail."""
        edit(self.root, "es/doc.md", "output 1", "output 2")
        result = run(self.root)
        status = {c["check_id"]: c["status"] for c in result["checks"]}
        self.assertEqual(status["translation.fences"], "failed")
        self.assertEqual(status["translation.chunks"], "passed")
        self.assertEqual(status["translation.glossary"], "passed")


class PackMetamorphicTests(unittest.TestCase):
    """Changes that must not change the findings."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def defects(self) -> dict[str, str]:
        files = good_files()
        files["es/doc.md"] = files["es/doc.md"].replace("output 1", "output 2").replace(
            "(#preparacion)", "(#setup)")
        files["es/flow.md"] = files["es/flow.md"].replace('B -->|no| D["Rechazar"]',
                                                         'B -->|no| E["Rechazar"]')
        files["es/prose.md"] = files["es/prose.md"].replace("Primer", "El cacharro")
        return files

    def test_the_defect_repository_has_findings_of_many_checks(self):
        result = run(write_files(self.base / "r", self.defects()))
        self.assertEqual(result["status"], "failed")
        failed = {c["check_id"] for c in result["checks"] if c["status"] == "failed"}
        self.assertTrue({"translation.fences", "translation.links", "translation.structure"} <= failed)

    def test_repeated_runs_give_the_same_findings(self):
        root = write_files(self.base / "r", self.defects())
        first = run(root)
        for _ in range(3):
            again = run(root)
            self.assertEqual(stable(first), stable(again))
            self.assertEqual(first["config_digest"], again["config_digest"])

    def test_file_creation_order_does_not_change_the_findings(self):
        files = self.defects()
        forward = write_files(self.base / "forward", files)
        backward = write_files(self.base / "backward", dict(reversed(list(files.items()))))
        self.assertEqual(stable(run(forward)), stable(run(backward)))

    def test_root_directory_name_changes_only_the_path_root(self):
        root = write_files(self.base / "first-name", self.defects())
        expected = stable(run(root))
        renamed = self.base / "a-very-different-root-name"
        shutil.copytree(root, renamed)
        moved = self.base / "deeper" / "level" / "x"
        moved.parent.mkdir(parents=True)
        shutil.copytree(root, moved)
        for other in (renamed, moved):
            result = run(other)
            self.assertEqual(expected, stable(result))
            text = repr(result["checks"])
            self.assertNotIn(str(other), text)
            self.assertNotIn(str(self.base), text)

    def test_an_unrelated_file_does_not_change_the_findings(self):
        root = write_files(self.base / "r", self.defects())
        expected = stable(run(root))
        (root / "src").mkdir()
        (root / "src" / "tool.py").write_text("print('hello')\n", encoding="utf-8")
        self.assertEqual(expected, stable(run(root)))


if __name__ == "__main__":
    unittest.main()
