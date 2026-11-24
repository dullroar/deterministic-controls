# Read a failure

## Text output

Each line of a finding has this form:

```text
<rule_id> <path>:<line> <message>
```

Example:

```text
markdown.local-links.missing-file docs/a.md:3 link target not found
```

## Steps

1. Read the exit code. See [run.md](./run.md).
   - `1`: a check found a defect. Go to step 2.
   - `2`: the configuration is wrong. Read the message on standard error. Fix `controls.toml` or the command.
   - `3`: a check crashed. Report it with the full output. Do not ignore it.
2. Find the `rule_id`. The first part is the check ID. Find it in [catalog.md](./catalog.md).
3. Run `python3 -m deterministic_controls explain <check-id>` for the summary.
4. Open the file at `path` and the `line`. Fix the cause.
5. Run the check again.

## Do not hide a failure

- Do not disable a check to make CI pass.
- Do not add an exception for a secret to pass a step. A new exception needs a reason and a fingerprint. The owner must review it.
- A secret finding means the secret may be in the Git history. Revoke the secret first. Then remove it.

## Skipped checks

A skipped check has a reason. In profile `quick`, only mandatory checks run. A required check that does not run in profile `ci` or `full` fails the run.

## JSON output

Use `--format json` or `--report FILE` for tools. The fields are in [run.md](./run.md).
