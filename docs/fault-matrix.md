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

## Translation and Markdown pack

The pack is opt-in. See [translation-pack.md](./translation-pack.md). The rule for faults is the same as above: a fault never gives a pass. A pack check that cannot do its work gives a finding or status `error`. The command then exits with a nonzero code.

### Tests of the pack

| Test file | What it proves |
| --- | --- |
| [test_translation_negative.py](../tests/test_translation_negative.py) | A catalog of 26 planted defects. The control is clean. Each mutation fails for the stated rule ID, matched as a whole ID. |
| [test_translation_mutation.py](../tests/test_translation_mutation.py) | One mutation of a good pair gives one expected failure. File order, repeated runs and the root name do not change the findings. |
| [test_translation_fail_closed.py](../tests/test_translation_fail_closed.py) | A fault in a pack check gives `error` or `failed`, never `passed`. A repository that does not use the pack is not changed. |

### Faults for each pack check

In the table, "all pack checks" means these nine checks: `translation.fences`, `translation.links`, `translation.structure`, `translation.glossary`, `translation.chunks`, `translation.untranslated-heuristic`, `markdown.required-headings`, `markdown.front-matter` and `markdown.document-ids`. The test names are in the class `InternalErrorTests`, `FileFaultTests` or `OptInTests` of `test_translation_fail_closed.py`.

| Fault | Check | Expected result | Test |
| --- | --- | --- | --- |
| Internal error | All pack checks | Status `error`, run status `error`, exit `3`. | `InternalErrorTests.test_exception_in_each_pack_check_gives_error_and_nonzero_exit` |
| Timeout | All pack checks | Status `error`, nonzero exit. | `InternalErrorTests.test_timeout_in_each_pack_check_gives_error_and_nonzero_exit`, `InternalErrorTests.test_builtin_timeout_error_gives_error` |
| The check returns a bad value | All pack checks | Status `error`, exit `3`. | `InternalErrorTests.test_a_pack_check_that_returns_garbage_gives_error` |
| A target file is not valid UTF-8 | All pack checks | Status `error` or `failed`, nonzero exit. | `FileFaultTests.test_invalid_utf8_never_passes` |
| A source file is not valid UTF-8 | `translation.fences`, `translation.links`, `translation.structure`, `translation.glossary` | Status `error` or `failed`, nonzero exit. `translation.untranslated-heuristic` does not read the source file. | `FileFaultTests.test_invalid_utf8_in_the_source_file_never_passes` |
| A file is unreadable | All pack checks | Status `error` or `failed`, nonzero exit. The test is skipped when it runs as root. | `FileFaultTests.test_unreadable_file_never_passes` |
| A parameter names a missing file (mapping, exceptions, glossary, manifest, registry) | Each check that has such a parameter | Status `failed` with a `bad-config`, `bad-glossary` or `bad-manifest` rule. Never a pass. `markdown.required-headings` and `markdown.front-matter` have no such parameter. | `FileFaultTests.test_a_missing_parameter_file_never_passes` |
| The mapping file is not valid TOML | `translation.fences`, `translation.links`, `translation.structure`, `translation.glossary`, `translation.untranslated-heuristic` | Rule `<check-id>.bad-config`. | `FileFaultTests.test_a_malformed_mapping_never_passes` |
| The mapping names a path outside the repository | The same five checks | Rule `<check-id>.bad-config`. | `FileFaultTests.test_a_mapping_that_leaves_the_repository_never_passes` |
| A target file is missing | `translation.fences`, `translation.links`, `translation.structure`, `translation.glossary` | Rule `<check-id>.missing-target`. | `FileFaultTests.test_a_missing_target_file_never_passes` |
| A manifest row is not valid JSON | `translation.chunks` | Rule `translation.chunks.bad-manifest`. | `FileFaultTests.test_a_malformed_manifest_row_never_passes` |
| A fence never closes | `translation.fences` | Rule `translation.fences.unclosed`. It is never a skip. | `FileFaultTests.test_an_unclosed_fence_is_a_finding_not_a_skip` |
| A diagram has a type that the check does not understand | `translation.structure` | Rule `translation.structure.mermaid-unsupported`. It is never a skip. | `FileFaultTests.test_an_unsupported_diagram_is_a_finding_not_a_skip` |
| A parameter has a wrong value | `translation.fences` | Rule `translation.fences.bad-config`. | `FileFaultTests.test_a_bad_parameter_value_never_passes` |
| A fault in the command line run | `translation.links` | Nonzero exit. | `FileFaultTests.test_a_fault_gives_a_nonzero_exit_in_the_cli` |

### Opt-in faults

| Case | Expected result | Test |
| --- | --- | --- |
| No pack configuration and no pack check enabled | Status `passed`, exit `0`. No pack check runs. | `OptInTests.test_no_pack_configuration_and_no_pack_check_passes`, `OptInTests.test_a_good_pair_with_a_defect_is_ignored_when_no_pack_check_is_enabled` |
| A pack check is enabled and has no parameters | Status `passed`, no findings, exit `0`. | `OptInTests.test_each_pack_check_enabled_without_parameters_passes`, `OptInTests.test_all_pack_checks_enabled_without_parameters_pass_together` |
| A pack check named in `enabled` is not in the catalog | Exit `2` with the message `unknown check ID`. | `OptInTests.test_an_unknown_pack_check_in_enabled_is_exit_2`, `OptInTests.test_a_pack_check_name_with_a_typo_is_exit_2` |
| This repository enables the pack | It does not. `controls.toml` has no pack check. | `OptInTests.test_this_repository_does_not_enable_the_pack` |

### Mutations of the pack

Each row starts from a good pair that passes. One change must give the named rule ID. The full catalog of 26 planted defects is the table `ROWS` in `test_translation_negative.py`.

| Mutation | Rule ID | Test |
| --- | --- | --- |
| Drop a fence | `translation.fences.count` | `PackMutationTests.test_drop_a_fence` |
| Swap two Mermaid edges | `translation.structure.mermaid-skeleton` | `PackMutationTests.test_swap_two_mermaid_edges` |
| Drop a table cell | `translation.structure.table-cells` | `PackMutationTests.test_drop_a_table_cell` |
| Change a link fragment | `translation.links.missing-anchor` | `PackMutationTests.test_change_a_link_fragment` |
| Rename a file without a path rename | `translation.links.missing-target` | `PackMutationTests.test_rename_a_file_without_a_path_rename` |
| Remove a chunk row | `translation.chunks.missing` | `PackMutationTests.test_remove_a_chunk_row` |
| Change a source digest | `translation.chunks.stale` | `PackMutationTests.test_change_a_source_digest` |
| Weaken the banned list of a glossary term in a copy of the check | The weakened copy misses the banned word. The real check finds it. | `PackMutationTests.test_weaken_the_glossary_banned_list_in_a_copy_of_the_check` |

### Known limits of the pack

The pack does not detect these defects. Two tests in `KnownLimitTests` keep them in view. If a later check finds one of them, the test fails. Then move the case to the negative catalog.

| Defect | Result | Test |
| --- | --- | --- |
| A macro ID changes (`[[entry:m4]]` becomes `[[entry:m5]]`) | Not detected. No pack check compares macro tokens. | `KnownLimitTests.test_a_changed_macro_id_is_not_detected` |
| A number is dropped from a sentence of prose | Not detected by the Markdown checks. A chunk manifest detects a dropped segment, not a changed one. | `KnownLimitTests.test_a_dropped_number_in_prose_is_not_detected` |

### Measured times of the pack

The test `PackSizeTests.test_pack_scales_to_1000_pairs` builds the file pairs in a temporary directory. Each page has a link to the next page, a fenced block, a table and one glossary term. The test runs the six `translation.*` checks in process. Times are from one run on a developer laptop. They show the order of size only.

| File pairs | Time (seconds) |
| --- | --- |
| 100 | 0.13 |
| 1,000 | 1.22 |

The test asserts only a loose bound: 100 pairs in less than 60 seconds and 1,000 pairs in less than 300 seconds.
