---
id: b11-verify
status: done
depends_on: [b10-release-prep]
touches:
  - plans/bootstrap/steps/b11-verify.md
lane: none
tier: light
gate: rm -rf "${TMPDIR:-/tmp}/controls-b11" && git clone -q . "${TMPDIR:-/tmp}/controls-b11" && cd "${TMPDIR:-/tmp}/controls-b11" && bash scripts/release_check.sh && python3 scripts/secret_guard.py --tracked
claimed_by: claude cli-default
claimed_at: "2026-11-24T01:34:12Z"
evidence: gate passed 2026-11-24 (driver-verified)
---

# Verify everything from a clean clone

Read `plans/bootstrap/plan.md` first. This step changes only its own file.

## Do

1. Clone this worktree into a temporary directory outside the repository. Run `bash scripts/release_check.sh` there. The gate does the same.
2. Record under "Results" below: the unit test count and result, the summary of `docs/fault-matrix.md`, the measured times for 100, 1,000 and 10,000 files, the SHA-256 of the wheel, and the result of `secret_guard.py --tracked`.
3. Run `python3 scripts/secret_guard.py --history` in this repository. Record the finding count. If it is not zero, list the finding rule IDs and paths (never the secret). Do not add an exception.
4. List each exception in `.secret-guard-allow` and each inline `secret-guard: allow`. The owner reviews them.
5. Do not write local paths in this file.

## Results

Run date: 2026-11-23. Source: a clean clone of this worktree.

- `bash scripts/release_check.sh`: passed.
- Unit tests: 196 tests ran, result OK.
- Self check, profile `full`: passed. All 7 checks passed (`context.index-freshness`, `markdown.local-links`, `plans.graph`, `plans.schema`, `repo.forbidden-artifacts`, `security.personal-data`, `security.secrets`).
- `docs/fault-matrix.md`: it has no numeric summary. Its rule is: a fault never gives a pass. A check that cannot do its work gives `error` or `failed`, and the command exits nonzero. Each fault row names the test that proves it.
- Measured times (Markdown files): 100 files 0.03 s, 1,000 files 0.24 s, 10,000 files 2.35 s.
- Wheel `deterministic_controls-0.1.0-py3-none-any.whl` SHA-256: `b046088d0b50f086381fb0ff5d888803a320eb2532606d76779e698043efb5e9`.
- `python3 scripts/secret_guard.py --tracked`: 0 findings, 0 allowed, 0 unscanned.
- `python3 scripts/secret_guard.py --history`: 0 findings, 0 allowed, 0 unscanned. No rule IDs or paths to list.

### Exceptions for owner review

- `.secret-guard-allow`: the file does not exist. There are no file exceptions.
- Inline `secret-guard: allow` in tracked files that are not documentation of the feature:
  - `tests/test_secrets.py` line 139: a synthetic test value, with a reason.
  - `tests/test_secret_guard.py` lines 161 and 164: a test sentinel with a reason, and a test of a missing reason.
- Other matches only describe the marker: `scripts/secret_guard.py`, `src/deterministic_controls/adopt/templates/secret_guard.py`, `src/deterministic_controls/checks/secrets.py` and the step file `b06-secrets.md`.

## Do not change

- Files outside `touches`. The `gate` command.

## Already done by earlier steps

- b00 to b10.

## Done when

- The gate passes. "Results" holds the numbers above.

## Record

Set `status: done`. Fill `evidence` with the gate command, the result and the date.
If you cannot finish, write "Resume notes" below. Keep the status `in_progress`.

## Resume notes

(none)
