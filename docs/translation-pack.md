# Translation and Markdown pack

This pack holds checks for a Markdown-to-Markdown translation that has a source manifest. The pack is opt-in. This page is the contract that all checks of the pack follow.

## Opt-in rule

- A check of the pack runs only if you list it in `enabled` in `controls.toml`. Do not enable a check you do not use.
- A check that is enabled and has no parameters passes with no findings. "Not configured" is not a failure.
- A check that has parameters that are wrong gives a finding. It never passes. Wrong means: a file is missing, the TOML is not valid, a key is unknown, or a path leaves the repository. The rule is `<check-id>.bad-config`.

## The "generic" test

A check is in the pack only if it works on any Markdown-to-Markdown translation that has a source manifest. Its code has no language name, book name or project name. Language lists, glossaries and word lists are parameters or files. They are not code. Each check below states why it passes this test.

## Rule IDs and findings

- A rule ID has the form `<check-id>.<rule>`, for example `translation.fences.code-differs`.
- A finding gives the **target** path and the line in the target.
- The message names the source path.
- A check of the pack that is advisory gives severity `info`. Severity `info` never fails the run. `translation.untranslated-heuristic` is always advisory.

## Fail closed

- A pair whose target file is missing is a finding (`missing-target`).
- Two source files that map to one target are a finding (`duplicate-target`).
- A fence, front matter block or HTML comment that never closes is a finding (`unclosed-fence`, `unclosed-front-matter`, `unclosed-comment`). The scanner never ignores it.
- A table that cannot be read, or a diagram that the check does not understand, is a finding. It is never a skip.

## Mapping file

The parameter `mapping` names a TOML file inside the repository. It pairs the source files with the target files.

```toml
source_root = "en"
target_root = "es"

[path_renames]
"guide/intro.md" = "guia/introduccion.md"

[anchor_renames]
"first-title" = "primer-titulo"
```

- `source_root` and `target_root` are required. They are repository-relative and must differ.
- A source file `<source_root>/<path>` pairs with `<target_root>/<path>`. If `path_renames` has the path, the renamed path is used.
- `anchor_renames` maps a heading anchor of the source to the anchor of the target.
- A path that is absolute, has `..`, or leaves the repository is refused with `bad-config`.
- **Limit.** The source tree must be inside the checked root. A check cannot read a file outside the root. If the source is in another repository, copy or vendor it into the checked root first.

## Exception file

The parameter `exceptions` names a TOML file or a JSONL file (a name that ends in `.jsonl`). A row waives one finding. Nothing else turns a finding off.

```toml
[[exception]]
rule = "translation.links.missing-target"
path = "es/guide/intro.md"
reason = "The page is not translated yet."
```

The same row in JSONL:

```json
{"rule": "translation.links.missing-target", "path": "es/guide/intro.md", "reason": "The page is not translated yet."}
```

- A row has `rule` (the full rule ID), `path` (the target path of the finding) and a non-empty `reason`. A row without a reason gives `bad-config`.
- A row that matches no finding is itself a finding: `<check-id>.stale-exception`.
- A row for the rule of another check is ignored by this check.
- A `bad-config` or `stale-exception` finding cannot be waived.

## Shared module

The checks use `src/deterministic_controls/checks/translation_common.py`. It has no catalog file and no check of its own. It gives:

- loaders for `mapping` and `exceptions`, and the error type `ConfigError`;
- pairing of source and target files (`pair_documents`);
- a Markdown scanner with the line classes front matter, fenced block, HTML comment, table row, prose and blank;
- `make_finding`, `apply_exceptions` and `split_table_row`.

## Checks of the pack

| Check ID | Status | What it does |
| --- | --- | --- |
| `translation.fences` | advisory | Code and output blocks equal the source byte for byte. |
| `translation.links` | advisory | Links, images and anchors of the target match the source after the maps. |
| `translation.structure` | advisory | Headings, tables, footnotes, bold spans, front matter keys and Mermaid skeletons equal the source. |
| `translation.glossary` | advisory | Approved terms are used. Banned words are not. Do-not-translate phrases stay. |
| `translation.chunks` | advisory | Chunk IDs and source digests are complete and not stale. |
| `markdown.required-headings` | advisory | Listed headings exist in each Markdown file. |
| `markdown.front-matter` | advisory | Front matter has the required keys and values. |
| `markdown.document-ids` | advisory | Document IDs are present and unique. |
| `translation.untranslated-heuristic` | advisory, severity `info` | Hint: a prose segment that may be in the source language. It never fails a run. |

The catalog status `advisory` means that the check is not required in every profile. A finding of severity `error` still fails the run. See [catalog.md](./catalog.md) for parameters and rules.

## Adopt the pack

1. Add the checks that you need to `enabled` in `controls.toml`. Do not enable the others.

   ```toml
   enabled = ["translation.fences", "translation.links"]

   [parameters."translation.fences"]
   mapping = "translation/mapping.toml"
   exceptions = "translation/exceptions.toml"
   ```

2. Write the mapping file. See "Mapping file" above. Put the source tree inside the repository.
3. Write the exception file. It can be empty. Add a row only for a finding that you accept, and give a reason.
4. Run one check. The command has no option to pick a check. A check runs only if it is in `enabled`. So list only that check in `enabled`, and run:

   ```bash
   python3 -m deterministic_controls check --root . --profile full
   ```

   Run `python3 -m deterministic_controls explain translation.fences` to see the parameters and their defaults.
5. Fix each finding, or add an exception row with a reason.

### Limits

- The source tree must be inside the checked root.
- `translation.untranslated-heuristic` is advisory. It can be wrong in both directions.
- Rules that depend on one language, for example Spanish-specific rules, stay in the translation repository.
- A check does not fetch a URL. An external link is compared as text.

## What stays out

These parts are project-specific. They are not in the pack:

- word lists and glossaries of one language pair;
- the generator of the do-not-translate list;
- the tools that make or send translation batches;
- rules for one language, one book or one project;
- the source manifest writer.
