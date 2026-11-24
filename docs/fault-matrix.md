# Fault matrix

This document lists the faults that the checks must survive. For each fault it gives the expected result and the test that proves it.

The rule for all faults: a fault never gives a pass. A check that cannot do its work gives status `error` or `failed`. The command then exits with a nonzero code.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All checks passed. |
| `1` | A check found a defect, or a required check was skipped. |
| `2` | Bad configuration or invocation. |
| `3` | Internal failure: a check raised an error. |

## Tests

| Test file | What it proves |
| --- | --- |
| [test_mutation.py](../tests/test_mutation.py) | Each mutation of a good repository gives the expected rule ID. |
| [test_metamorphic.py](../tests/test_metamorphic.py) | File order, repeated runs and the root name do not change the findings. |
| [test_fail_closed.py](../tests/test_fail_closed.py) | A fault gives `error` or `failed`, never `passed`. |
| [test_performance.py](../tests/test_performance.py) | A run on 10,000 files takes less than 120 seconds. |

## Faults for each check

The tests in `test_fail_closed.py` use the class names `InternalErrorTests`, `FileFaultTests` and `SkippedMandatoryTests`.

| Fault | Expected result | Test |
| --- | --- | --- |
| A file that the check reads is missing (all checks) | The check does not crash. A missing link target gives `markdown.local-links.missing-file`. A missing plan file gives a `plans.schema` finding. | `FileFaultTests.test_missing_files_never_crash_and_never_hide_a_missing_link` |
| A file is unreadable (all checks that read files) | Status `error`, run status `error`, exit `3`. The test is skipped when it runs as root, because root can read any file. | `FileFaultTests.test_unreadable_file_gives_error_and_nonzero_exit` |
| A file is not valid UTF-8 (`context.index-freshness`, `markdown.local-links`, `plans.schema`, `plans.graph`, `security.personal-data`) | Status `error`, exit `3`. | `FileFaultTests.test_malformed_input_never_passes`, `FileFaultTests.test_malformed_input_gives_error_in_the_cli` |
| A file is not valid UTF-8 (`security.secrets`) | The scanner decodes with replacement. It still finds a secret in the file. A file with a NUL byte is binary and is reported as not scanned. | `FileFaultTests.test_secret_scanner_still_finds_a_secret_in_a_malformed_file` |
| Malformed front matter (`plans.schema`) | Status `failed` with a `plans.schema.missing-*` rule. | `MutationTests.test_remove_gate` |
| Index markers are missing (`context.index-freshness`) | Status `failed`, rule `context.index-freshness.missing-markers`. | `MutationTests.test_remove_index_markers` |
| An internal error in a check (all checks) | Status `error`, run status `error`, exit `3`. The other checks still run. | `InternalErrorTests.test_exception_in_each_check_gives_error_and_nonzero_exit`, `InternalErrorTests.test_error_in_one_check_does_not_hide_a_defect_in_another` |
| A timeout in a check (all checks) | A timeout error is an exception. Status `error`, exit `3`. | `InternalErrorTests.test_timeout_in_each_check_gives_error_and_nonzero_exit`, `InternalErrorTests.test_builtin_timeout_error_gives_error` |
| A check returns a bad value (all checks) | Status `error`, exit `3`. | `InternalErrorTests.test_a_check_that_returns_garbage_gives_error` |
| The command crashes outside a check | Exit `3`. A crash never gives `0`. | `InternalErrorTests.test_cli_crash_never_gives_zero` |

## Faults of the configuration

| Fault | Expected result | Test |
| --- | --- | --- |
| The manifest is missing | Exit `2` with the message `manifest not found`. | `FileFaultTests.test_missing_manifest_is_a_configuration_error` |
| The manifest is not valid TOML | Exit `2`. | `FileFaultTests.test_malformed_manifest_is_a_configuration_error` |
| The manifest names an unknown check ID | Exit `2`. | `FileFaultTests.test_unknown_check_id_is_a_configuration_error` |
| The root directory does not exist | Exit `2`. | `FileFaultTests.test_missing_root_is_a_configuration_error` |
| The manifest disables a mandatory check | Exit `2`. | `SkippedMandatoryTests.test_mandatory_check_cannot_be_disabled` |
| The manifest enables no check | The mandatory check `security.secrets` still runs. | `SkippedMandatoryTests.test_mandatory_check_runs_when_the_manifest_enables_nothing` |
| The profile is `quick` | The mandatory check `security.secrets` still runs and still fails on a secret. | `SkippedMandatoryTests.test_mandatory_check_runs_in_profile_quick`, `SkippedMandatoryTests.test_secret_in_profile_quick_still_fails` |
| A required check does not run | Status `skipped`, run status `failed`, exit `1`. | `SkippedMandatoryTests.test_required_check_skipped_in_profile_ci_fails` |

## Mutations

Each row starts from a good repository. One change must give the named rule ID.

| Mutation | Rule ID | Test |
| --- | --- | --- |
| Remove the `gate` of a step | `plans.schema.missing-gate` | `MutationTests.test_remove_gate` |
| Empty the `gate` of a step | `plans.schema.empty-gate` | `MutationTests.test_empty_gate` |
| Rename a dependency | `plans.graph.unknown-dependency` | `MutationTests.test_rename_dependency` |
| Change a heading target | `markdown.local-links.missing-anchor` | `MutationTests.test_change_heading_target` |
| Change a link target file | `markdown.local-links.missing-file` | `MutationTests.test_change_link_file` |
| Drop an index line | `context.index-freshness.stale` | `MutationTests.test_drop_index_line` |
| Remove an index marker | `context.index-freshness.missing-markers` | `MutationTests.test_remove_index_markers` |
| Add a secret | `security.secrets.github-token` | `MutationTests.test_secret_is_found` |
| Weaken a token pattern | The weakened copy misses the secret. The real pattern finds it. | `MutationTests.test_weakened_token_pattern_is_detected_by_the_oracle` |
| Add a personal path | A rule `security.personal-data.*` | `MutationTests.test_personal_path_is_found` |
| Add a forbidden file | `repo.forbidden-artifacts.tracked` or `security.secrets.forbidden-file` | `MutationTests.test_forbidden_artifact_is_found` |

## Measured times

The test `test_performance.py` builds synthetic Markdown files in a temporary directory. Each file has one link to the next file. The test runs all seven checks in process. Times are from one run on a developer laptop. They show the order of size only.

| Markdown files | Time (seconds) |
| --- | --- |
| 100 | 0.03 |
| 1,000 | 0.23 |
| 10,000 | 2.28 |

The test asserts only a loose bound: 10,000 files in less than 120 seconds.
