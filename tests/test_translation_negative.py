"""Negative catalog of the translation pack: planted defects in a good control.

Each row has a good control, one mutation of it and the expected rule ID.
The control must be clean (exit 0). The mutation must fail (exit 1) for the
stated rule. The rule is matched as a whole ID, so `I6` never matches `I16`.
A row that does not fail, or fails for another rule, fails the test.

The pairs are built at run time in a temporary directory. The test files of the
other pack steps hold their own fixtures. This file holds one shared good
control that all pack checks accept.
"""

import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from deterministic_controls.cli import main  # noqa: E402

SOURCE_URL = "https://example.org/source-repo"
PACK_CHECKS = [
    "translation.fences",
    "translation.links",
    "translation.structure",
    "translation.glossary",
    "translation.chunks",
    "translation.untranslated-heuristic",
]

SOURCE_DOC = """\
---
title: Guide
kind: tutorial
---

# Title

## Setup

The widget uses `total > 40` and shows 3 items.[^1] See [setup](#setup) and [part](other.md#part).

A macro [[entry:m4]] stays as it is. **Bold** words stay too.

| name | value |
| --- | --- |
| a | b |
| c | d |

```text
output 1
```

```console
$ run --now
```

[^1]: Note text.
"""

TARGET_DOC = """\
---
title: Guia
kind: tutorial
---

# Titulo

## Preparacion

El artilugio usa `total > 40` y muestra 3 elementos.[^1] Mira [preparacion](#preparacion) y [parte](otro.md#parte).

Una macro [[entry:m4]] queda como esta. Las palabras **negrita** quedan.

| nombre | valor |
| --- | --- |
| a | b |
| c | d |

```text
output 1
```

```console
$ run --now
```

[^1]: Texto de la nota.
"""

SOURCE_OTHER = "# Other\n\n## Part\n\nPart text.\n"
TARGET_OTHER = "# Otro\n\n## Parte\n\nTexto de la parte.\n"

SOURCE_FLOW = """\
# Flow

```mermaid
flowchart TD
    accTitle: Order flow
    accDescr: Shows the order flow
    A["Start"] --> B{"Valid?"}
    B -->|yes| C["Ship"]
    B -->|no| D["Reject"]
```
"""

TARGET_FLOW = """\
# Flujo

```mermaid
flowchart TD
    accTitle: Flujo del pedido
    accDescr: Muestra el flujo del pedido
    A["Inicio"] --> B{"Valido?"}
    B -->|si| C["Enviar"]
    B -->|no| D["Rechazar"]
```
"""

SOURCE_PROSE = "# Notes\n\nFirst paragraph of the page.\n\nThe second paragraph has 3 items.\n"
TARGET_PROSE = "# Notas\n\nPrimer parrafo de la pagina.\n\nEl segundo parrafo tiene 3 elementos.\n"

GLOSSARY = """\
[[terms]]
id = "widget"
en = "widget"
target = "artilugio"
banned = ["cacharro"]
"""

MAPPING = """\
source_root = "en"
target_root = "es"

[path_renames]
"other.md" = "otro.md"

[anchor_renames]
"setup" = "preparacion"
"part" = "parte"
"""

SOURCE_FILES = {
    "en/doc.md": SOURCE_DOC,
    "en/other.md": SOURCE_OTHER,
    "en/flow.md": SOURCE_FLOW,
    "en/prose.md": SOURCE_PROSE,
}
TARGET_FILES = {
    "es/doc.md": TARGET_DOC,
    "es/otro.md": TARGET_OTHER,
    "es/flow.md": TARGET_FLOW,
    "es/prose.md": TARGET_PROSE,
}
CHUNKS = [
    # (id, source path, target path, source text, target text)
    ("s-001", "en/prose.md", "es/prose.md", "First paragraph of the page.",
     "Primer parrafo de la pagina."),
    ("s-002", "en/prose.md", "es/prose.md", "The second paragraph has 3 items.",
     "El segundo parrafo tiene 3 elementos."),
]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def source_manifest(chunks=CHUNKS) -> str:
    return jsonl([{"id": i, "path": sp, "digest": sha(st)} for i, sp, _tp, st, _tt in chunks])


def target_manifest(chunks=CHUNKS) -> str:
    return jsonl([
        {"id": i, "path": tp, "source_digest": sha(st), "text": tt}
        for i, _sp, tp, st, tt in chunks
    ])


def manifest_text(checks=None, parameters=None) -> str:
    """Return `controls.toml` with the given pack checks enabled and configured."""
    checks = PACK_CHECKS if checks is None else checks
    params = {
        "translation.fences": {"mapping": "map.toml", "inline_code": True},
        "translation.links": {"mapping": "map.toml", "source_repository_url": SOURCE_URL},
        "translation.structure": {"mapping": "map.toml", "fixed_front_matter_keys": ["kind"]},
        "translation.glossary": {"mapping": "map.toml", "glossary": "glossary.toml"},
        "translation.chunks": {"source_manifest": "source.jsonl",
                               "target_manifest": "target.jsonl"},
        "translation.untranslated-heuristic": {"mapping": "map.toml"},
    }
    if parameters is not None:
        params = parameters
    lines = ["schema_version = 1", 'profile = "ci"',
             "enabled = [" + ", ".join(json.dumps(c) for c in checks) + "]"]
    for check in checks:
        if params.get(check):
            lines.append(f'\n[parameters."{check}"]')
            lines.extend(f"{k} = {json.dumps(v)}" for k, v in params[check].items())
    return "\n".join(lines) + "\n"


def good_files() -> dict[str, str]:
    files = {**SOURCE_FILES, **TARGET_FILES}
    files["map.toml"] = MAPPING
    files["glossary.toml"] = GLOSSARY
    files["source.jsonl"] = source_manifest()
    files["target.jsonl"] = target_manifest()
    files["controls.toml"] = manifest_text()
    return files


def write_files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / ".git").mkdir(exist_ok=True)
    return root


def build_good(base: Path, name: str = "repo", **overrides) -> Path:
    """Build the good control in `base/name`. `overrides` map a path to new text."""
    files = good_files()
    files.update({k.replace("__", "/"): v for k, v in overrides.items()})
    return write_files(base / name, files)


def run_cli(root: Path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["check", "--root", str(root), "--format", "json"])
    try:
        return code, json.loads(out.getvalue())
    except json.JSONDecodeError as error:
        raise AssertionError(f"no JSON (exit {code}): {err.getvalue()}") from error


def rule_ids(result) -> set[str]:
    return {f["rule_id"] for c in result["checks"] for f in c["findings"]}


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation target not found in {rel}: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def whole_word(rule: str, found: set[str]) -> bool:
    """True if `rule` is one of the found IDs as a whole ID (not a prefix or suffix)."""
    return any(re.fullmatch(re.escape(rule), item) for item in found)


def mutate_chunks(root: Path, fn) -> None:
    """Apply `fn(source_rows, target_rows)` to the two manifests."""
    src = [json.loads(x) for x in (root / "source.jsonl").read_text(encoding="utf-8").splitlines()]
    tgt = [json.loads(x) for x in (root / "target.jsonl").read_text(encoding="utf-8").splitlines()]
    fn(src, tgt)
    (root / "source.jsonl").write_text(jsonl(src), encoding="utf-8")
    (root / "target.jsonl").write_text(jsonl(tgt), encoding="utf-8")


def set_target_rows(root: Path, rows: list[dict]) -> None:
    (root / "target.jsonl").write_text(jsonl(rows), encoding="utf-8")


# One row for each planted defect of the plan table.
# name -> (mutation, expected rule ID, exit code)
# A mutation is `("edit", path, old, new)` or `("call", function(root))`.


def _drop_last(src, tgt):
    del tgt[-1]


def _drop_first(src, tgt):
    del tgt[0]


def _stale_digest(src, tgt):
    src[0]["digest"] = sha("First paragraph, edited.")


def _duplicate_chunk(src, tgt):
    tgt[1]["id"] = tgt[0]["id"]


def _unknown_chunk(src, tgt):
    tgt[1]["id"] = "s-999"


def _rename_without_map(root: Path):
    (root / "es" / "otro.md").rename(root / "es" / "nuevo.md")


def _two_files_one_name(root: Path):
    (root / "map.toml").write_text(MAPPING.replace(
        '"other.md" = "otro.md"', '"other.md" = "doc.md"'), encoding="utf-8")


def _flow_swap_edges(root: Path):
    edit(root, "es/flow.md", '    B -->|si| C["Enviar"]\n    B -->|no| D["Rechazar"]\n',
         '    B -->|no| D["Rechazar"]\n    B -->|si| C["Enviar"]\n')


def _chunk(fn):
    return ("call", lambda root: mutate_chunks(root, fn))


ROWS = {
    "code-span-changes": (
        ("edit", "es/doc.md", "`total > 40`", "`total >= 40`"),
        "translation.fences.inline-code"),
    "code-span-dropped": (
        ("edit", "es/doc.md", "El artilugio usa `total > 40` y muestra",
         "El artilugio usa y muestra"),
        "translation.fences.inline-code"),
    "fence-code-changes": (
        ("edit", "es/doc.md", "output 1", "output 2"),
        "translation.fences.code-differs"),
    # The pack does not compare the digits of prose. The chunk manifest does
    # track each segment, so a dropped segment with a number is a missing chunk.
    "sentence-with-number-dropped": (
        _chunk(_drop_last),
        "translation.chunks.missing"),
    "front-matter-key-translated": (
        ("edit", "es/doc.md", "kind: tutorial", "tipo: tutorial"),
        "translation.structure.front-matter"),
    "front-matter-enum-translated": (
        ("edit", "es/doc.md", "kind: tutorial", "kind: tutoria"),
        "translation.structure.front-matter"),
    "mermaid-accdescr-removed": (
        ("edit", "es/flow.md", "    accDescr: Muestra el flujo del pedido\n", ""),
        "translation.structure.mermaid-skeleton"),
    "mermaid-edges-swapped": (
        ("call", _flow_swap_edges),
        "translation.structure.mermaid-skeleton"),
    "mermaid-node-renamed-in-one-edge": (
        ("edit", "es/flow.md", 'B -->|no| D["Rechazar"]', 'B -->|no| E["Rechazar"]'),
        "translation.structure.mermaid-skeleton"),
    "paragraph-deleted": (
        ("edit", "es/doc.md", "Una macro [[entry:m4]] queda como esta. Las palabras **negrita** quedan.\n\n", ""),
        "translation.structure.bold-count"),
    "table-cell-deleted": (
        ("edit", "es/doc.md", "| c | d |", "| c |"),
        "translation.structure.table-cells"),
    "table-row-deleted": (
        ("edit", "es/doc.md", "| c | d |\n", ""),
        "translation.structure.table-rows"),
    "fence-kind-changes": (
        ("edit", "es/doc.md", "```console", "```text"),
        "translation.fences.kind"),
    "fence-dropped": (
        ("edit", "es/doc.md", "```console\n$ run --now\n```\n\n", ""),
        "translation.fences.count"),
    "link-keeps-source-fragment": (
        ("edit", "es/doc.md", "(#preparacion)", "(#setup)"),
        "translation.links.missing-anchor"),
    "link-goes-to-source-repository": (
        ("edit", "es/doc.md", "Mira [preparacion]",
         f"Mira [fuente]({SOURCE_URL}/blob/main/a.md) y [preparacion]"),
        "translation.links.foreign-repository"),
    "image-from-source-repository": (
        ("edit", "es/doc.md", "Mira [preparacion]",
         f"Mira ![img]({SOURCE_URL}/raw/main/p.png) y [preparacion]"),
        "translation.links.foreign-repository"),
    "path-renamed-link-keeps-old-name": (
        ("edit", "es/doc.md", "(otro.md#parte)", "(other.md#parte)"),
        "translation.links.missing-file"),
    "renamed-file-without-path-rename": (
        ("call", _rename_without_map),
        "translation.links.missing-target"),
    "two-files-map-to-one-name": (
        ("call", _two_files_one_name),
        "translation.links.duplicate-target"),
    "two-chunks-one-id": (
        _chunk(_duplicate_chunk),
        "translation.chunks.duplicate"),
    "chunk-missing-from-target": (
        _chunk(_drop_first),
        "translation.chunks.missing"),
    "source-digest-stale": (
        _chunk(_stale_digest),
        "translation.chunks.stale"),
    "chunk-id-unknown": (
        _chunk(_unknown_chunk),
        "translation.chunks.orphan"),
    "glossary-banned-rendering": (
        ("edit", "es/doc.md", "El artilugio usa", "El cacharro usa"),
        "translation.glossary.banned-term"),
    "glossary-approved-rendering-missing": (
        ("edit", "es/doc.md", "El artilugio usa", "El aparato usa"),
        "translation.glossary.missing-rendering"),
}


def apply(root: Path, mutation) -> None:
    if mutation[0] == "edit":
        edit(root, *mutation[1:])
    else:
        mutation[1](root)


class NegativeCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_the_control_is_clean(self):
        root = build_good(self.base)
        code, result = run_cli(root)
        self.assertEqual(code, 0, [f for c in result["checks"] for f in c["findings"]])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(rule_ids(result), set())
        ran = {c["check_id"] for c in result["checks"]}
        self.assertTrue(set(PACK_CHECKS) <= ran)

    def test_each_mutation_fails_for_its_rule(self):
        for name, (mutation, rule) in ROWS.items():
            with self.subTest(defect=name):
                root = build_good(self.base, name)
                self.assertEqual(run_cli(root)[0], 0, "the control must be clean")
                apply(root, mutation)
                code, result = run_cli(root)
                found = rule_ids(result)
                self.assertEqual(code, 1, (name, found))
                self.assertEqual(result["status"], "failed")
                self.assertTrue(whole_word(rule, found), (name, rule, found))

    def test_each_failing_finding_names_a_target_path(self):
        for name, (mutation, rule) in ROWS.items():
            with self.subTest(defect=name):
                root = build_good(self.base, f"p-{name}")
                apply(root, mutation)
                _, result = run_cli(root)
                hits = [f for c in result["checks"] for f in c["findings"] if f["rule_id"] == rule]
                self.assertTrue(hits)
                for finding in hits:
                    self.assertIsInstance(finding["path"], str)
                    self.assertFalse(finding["path"].startswith("en/") and rule.endswith(".missing-target"))

    def test_advisory_untranslated_segment_is_info_and_does_not_fail(self):
        root = build_good(self.base)
        edit(root, "es/prose.md", "El segundo parrafo tiene 3 elementos.",
             "This is the second one that you can read when it is here.")
        code, result = run_cli(root)
        findings = [f for c in result["checks"] for f in c["findings"]]
        rules = {f["rule_id"] for f in findings
                 if f["rule_id"].startswith("translation.untranslated-heuristic.")}
        self.assertEqual(rules, {"translation.untranslated-heuristic.segment"})
        for finding in findings:
            if finding["rule_id"].startswith("translation.untranslated-heuristic."):
                self.assertEqual(finding["severity"], "info")
                self.assertEqual(finding["path"], "es/prose.md")
        # The chunk digests do not change, so no other check fails.
        self.assertEqual(code, 0)

    def test_every_defect_row_of_the_plan_table_is_covered(self):
        """Each rule family of the plan table has at least one case."""
        families = {
            "fences": "translation.fences.", "code spans": "translation.fences.inline-code",
            "front matter": "translation.structure.front-matter",
            "mermaid": "translation.structure.mermaid-", "chunks": "translation.chunks.",
            "structure": "translation.structure.", "links": "translation.links.",
            "mapping": "translation.links.duplicate-target", "glossary": "translation.glossary.",
        }
        rules = {rule for _m, rule in ROWS.values()}
        for family, prefix in families.items():
            with self.subTest(family=family):
                self.assertTrue(any(r.startswith(prefix) for r in rules))


class KnownLimitTests(unittest.TestCase):
    """Defects that the pack does not detect. They are limits, written down on purpose.

    If a later check detects one of them, the test fails. Then move the row
    to `ROWS` and update `docs/fault-matrix.md`.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_a_changed_macro_id_is_not_detected(self):
        root = build_good(self.base)
        edit(root, "es/doc.md", "[[entry:m4]]", "[[entry:m5]]")
        code, result = run_cli(root)
        self.assertEqual((code, rule_ids(result)), (0, set()))

    def test_a_dropped_number_in_prose_is_not_detected(self):
        root = build_good(self.base)
        edit(root, "es/prose.md", "tiene 3 elementos", "tiene elementos")
        code, result = run_cli(root)
        self.assertEqual((code, rule_ids(result)), (0, set()))


class WholeWordTests(unittest.TestCase):
    def test_a_prefix_is_not_a_match(self):
        self.assertFalse(whole_word("I6", {"I16"}))
        self.assertFalse(whole_word("translation.links", {"translation.links.missing-file"}))
        self.assertTrue(whole_word("a.b", {"a.b"}))


if __name__ == "__main__":
    unittest.main()
