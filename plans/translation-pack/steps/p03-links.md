---
id: p03-links
status: done
depends_on: [p01-pack-contract]
touches:
  - src/deterministic_controls/checks/translation_links.py
  - src/deterministic_controls/catalog/translation.links.toml
  - tests/test_translation_links.py
  - tests/fixtures/translation_links/**
  - plans/translation-pack/steps/p03-links.md
lane: none
gate: python3 -m unittest discover -s tests -p 'test_translation_links.py' -v && python3 -m unittest discover -s tests -v && python3 scripts/check_context.py && python3 scripts/secret_guard.py --tracked && git diff --check
claimed_by: ""
claimed_at: ""
evidence: "Gate command run in the worktree on 2026-11-23: test_translation_links.py 12 tests OK; full suite 239 tests OK; check_context.py ok; secret_guard.py --tracked 0 findings; git diff --check clean."
---

# Add the check `translation.links`

Read `plans/translation-pack/plan.md` first (pack contract, "Links"). Use `checks/translation_common.py` of `p01` without change. This check compares a target with its source. It is not `markdown.local-links` (that check has no source). Do not import it or change it.

## Change

- `checks/translation_links.py` with `entry(context)`. For each pair of the mapping, extract the links, images and HTML `href` and `src` of the source and of the target (not inside code; skip `{{...}}` and `[[...]]`). Stable rule IDs:
  - `.destination-differs`: the link list of the target is not the link list of the source after the path renames and anchor renames of the mapping (compare in order; report the first difference of each link).
  - `.external-differs`: an external URL (has a scheme) is not equal. External URLs are never fetched.
  - `.missing-file`: a relative path of the target does not exist.
  - `.missing-anchor`: a `#fragment` matches no heading ID of the target file (GitHub style, see `plan.md`) and no `id=` or `name=` attribute. Duplicate headings get `-1`, `-2`.
  - `.line-anchor`: a `#L12` or `#L12-L20` range is invalid or past the end of the target file.
  - `.foreign-repository`: a link or image of the target points into the URL named by the parameter `source_repository_url` (optional).
- `catalog/translation.links.toml`: id `translation.links`, status `advisory`, severity `error`. The `summary` says why the check is generic.
- No `mapping` parameter: no findings.

## Fixtures and tests

Follow the fixture rule in `plan.md`. One good pair and one bad pair for each rule. Edge cases, each its own fixture: accents and Unicode in headings; percent-encoded paths; reference-style links; a link inside a fence (not a link); heading renamed with an anchor rename in the mapping (good) and without (bad); a renamed target file with the path rename in the mapping (good) and without (bad); a link into the source repository; an image from the source repository; a line anchor past the end. The test asserts for each bad fixture the rule ID, the path and exit code `1`. Good fixtures give exit `0`.

## Do not change

- Files outside `touches`. The `gate` command. `translation_common.py`, `markdown_links.py`.

## Already done by earlier steps

- p01-pack-contract: the mapping loader (with path and anchor renames), the scanner, the finding and exception helpers, and `docs/translation-pack.md`.

## Done when

- The gate passes. Each bad fixture fails for its own rule. Each good fixture passes.

## Record

Set `status: done`. Fill `evidence` with the gate command, the result and the date.
If you cannot finish, write "Resume notes" below. Keep the status `in_progress`.

## Resume notes

For the review (no work remains in this step):

- The runner rejects a parameter that the catalog file does not list. So `translation.links.toml` has a `[parameters]` table with `mapping`, `exceptions` and `source_repository_url`, each set to `""`. TOML has no null value. The check treats `""` as "not configured". Other pack checks (p02 and p04 to p08) need the same catalog table and the same rule. The shared loader `translation_common._read_parameter_file` rejects `""`. A later step can move the filter of `""` into that helper.
- A link past the pairing (a missing target file) gives `missing-target` from the shared helper. The links of that file are not compared.
- A source file with an unclosed fence also gives a finding (on the source path).
