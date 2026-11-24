# Run

## Commands

```bash
python3 -m deterministic_controls list
python3 -m deterministic_controls explain <check-id>
python3 -m deterministic_controls check --root . --profile full
python3 -m deterministic_controls version
```

| Command | What it does |
| --- | --- |
| `list` | Lists the checks of the catalog. It does not import a check module. |
| `explain` | Shows the details of one check. |
| `check` | Runs the checks of the manifest. |
| `version` | Prints the version. |
| `adopt` | Adoption tools. See [install.md](./install.md). |

## Options of `check`

| Option | Meaning |
| --- | --- |
| `--root DIR` | The repository to check. Default: the current folder. |
| `--profile quick\|ci\|full` | The profile. It overrides the manifest. |
| `--format text\|json` | The output format. Default: `text`. |
| `--report FILE` | Write the JSON result to a file. The file must be outside the checked repository. |

A check never changes a file in the repository.

## Profiles

- `quick`: runs only the mandatory checks. Use it in a hook.
- `ci`: runs every enabled check.
- `full`: runs every enabled check. Use it before a release.

## The manifest

The file `controls.toml` in the root of the repository has these keys:

| Key | Meaning |
| --- | --- |
| `schema_version` | Must be `1`. |
| `profile` | The default profile. |
| `enabled` | A list of check IDs. |
| `disabled` | A list of check IDs to turn off. |
| `parameters` | Parameters for each check. See [catalog.md](./catalog.md). |

The manifest has no command. An unknown key or an unknown check ID is an error. A mandatory check cannot be disabled.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All checks passed. |
| `1` | A check found a defect. |
| `2` | Bad configuration or bad invocation. For example, the manifest is missing. |
| `3` | Internal failure. A check crashed. |

Every code other than `0` must fail CI. A crash never gives `0`.

## The JSON result

The JSON result has these fields: `schema_version`, `tool_version`, `repository_revision`, `control_revision`, `config_digest`, `profile`, `status` and `checks`. Each check has `check_id`, `status`, `duration_ms` and `findings`. The status of a check is `passed`, `failed`, `skipped` (with a reason) or `error`. A finding has `rule_id`, `severity`, `path`, `line`, `message` and `evidence`.
