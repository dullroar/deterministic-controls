---
id: p02-fences
status: done
depends_on: [p01-pack-contract]
touches:
  - src/deterministic_controls/checks/translation_fences.py
  - src/deterministic_controls/catalog/translation.fences.toml
  - tests/test_translation_fences.py
  - tests/fixtures/translation_fences/**
  - plans/translation-pack/steps/p02-fences.md
lane: none
gate: python3 -m unittest discover -s tests -p 'test_translation_fences.py' -v && python3 -m unittest discover -s tests -v && python3 scripts/check_context.py && python3 scripts/secret_guard.py --tracked && git diff --check
claimed_by: ""
claimed_at: ""
evidence: "Gate command of this step passed on 2026-11-23: 7 new tests, 234 tests in the full suite, check_context.py ok, secret_guard --tracked 0 findings, git diff --check clean."
---

# Add the check `translation.fences`

Read `plans/translation-pack/plan.md` first (pack contract, "Fences" and "Mask and protect"). Use `checks/translation_common.py` of `p01` without change. Look at `checks/markdown_links.py` and its catalog file for the pattern.

## Change

- `checks/translation_fences.py` with `entry(context)`: for each source and target pair of the mapping, compare the fenced blocks in order. Stable rule IDs: `translation.fences.count` (different number of fences), `.kind` (fence character or language tag differs), `.code-differs` (body not byte-identical), `.unclosed` (a fence never closes), `.missing-target` (from the shared helper). Blocks whose kind is in the parameter `translatable_kinds` (default `["mermaid"]`) are skipped here. Parameter `inline_code` (default `false`): when `true`, the multiset of inline code spans of each file must also equal (`.inline-code`).
- `catalog/translation.fences.toml`: id `translation.fences`, status `advisory`, severity `error`, module and entry as in the pattern. The `summary` says why the check is generic (any translation keeps code blocks byte for byte).
- Not configured (no `mapping` parameter): no findings.

## Fixtures and tests

Follow the fixture rule in `plan.md`. `tests/fixtures/translation_fences/` has one good pair and one bad pair for each rule above. Edge cases, each its own fixture: `~~~` fences; a longer outer fence that holds a shorter one; an indented fence (up to 3 spaces); an info string with attributes; an empty block; fence-like text inside inline code (not a fence); a Windows line ending difference (it is a difference: bytes must equal). Bad fixtures include a changed code span (`total > 40` becomes `total >= 40`) and a block that changes kind (`text` to `console`). The test asserts for each bad fixture the rule ID, the path and exit code `1`. The good fixtures give exit `0`. A test with no `mapping` parameter gives exit `0`.

## Do not change

- Files outside `touches`. The `gate` command. `translation_common.py`.

## Already done by earlier steps

- p01-pack-contract: the mapping loader, the Markdown scanner, the finding and exception helpers, and `docs/translation-pack.md`.

## Done when

- The gate passes. Each bad fixture fails for its own rule. Each good fixture passes.

## Record

Set `status: done`. Fill `evidence` with the gate command, the result and the date.
If you cannot finish, write "Resume notes" below. Keep the status `in_progress`.

## Resume notes

Notes for the review:

- The runner rejects a manifest parameter that the catalog file does not declare. So `translation.fences.toml` declares `mapping = ""` and `exceptions = ""`. The check treats an empty string as "not configured". `translation_common.py` is unchanged. Other pack steps may need the same rule.
- `translation_common.scan_markdown` removes `\r`. The check reads bytes and compares raw lines itself, so a line ending difference is found.
- The CRLF case is built at run time in the test, not stored as a fixture.
