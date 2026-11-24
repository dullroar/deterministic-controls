# Catalog of checks

This page lists each check of release `0.2.0`. The source is `python3 -m deterministic_controls list`. The rules of the pack checks are in the module of each check.

Statuses: `experimental`, `advisory`, `required`, `deprecated`. A mandatory check runs in every profile. The manifest cannot disable it.

| ID | Status | Severity | Parameters |
| --- | --- | --- | --- |
| `context.index-freshness` | advisory | error | none |
| `markdown.document-ids` | advisory | error | `glob`, `key`, `registry` |
| `markdown.front-matter` | advisory | error | `rules` |
| `markdown.local-links` | advisory | error | `all` (boolean, default `false`) |
| `markdown.required-headings` | advisory | error | `rules` |
| `plans.graph` | advisory | error | none |
| `plans.schema` | advisory | error | none |
| `repo.forbidden-artifacts` | advisory | error | `extra_patterns` (list of glob strings, default empty) |
| `security.personal-data` | advisory | error | none |
| `security.secrets` | required, mandatory | error | none |
| `translation.chunks` | advisory | error | `source_manifest`, `target_manifest`, `custom_id_digits` |
| `translation.fences` | advisory | error | `mapping`, `exceptions`, `translatable_kinds`, `inline_code` |
| `translation.glossary` | advisory | error | `glossary`, `mapping`, `dnt`, `exceptions` |
| `translation.links` | advisory | error | `mapping`, `exceptions`, `source_repository_url` |
| `translation.structure` | advisory | error | `mapping`, `exceptions`, `disabled_rules`, `fixed_front_matter_keys` |
| `translation.untranslated-heuristic` | advisory only | info | `mapping`, `exceptions`, `dnt`, `threshold`, `min_words`, `source_stopwords`, `target_stopwords` |

The checks `markdown.document-ids`, `markdown.front-matter`, `markdown.required-headings` and all `translation.*` checks belong to the translation and Markdown pack. They are opt-in and run only if you enable them. An enabled pack check without parameters passes. See [translation-pack.md](./translation-pack.md).

## context.index-freshness

The generated index files `memory/AGENTS.md`, `plans/AGENTS.md` and `scripts/AGENTS.md` are up to date. The check never writes. Run `python3 scripts/build_indexes.py` to fix.

| Rule | Meaning |
| --- | --- |
| `context.index-freshness.stale` | The index differs from the generated text. |
| `context.index-freshness.missing-markers` | The index has no generated-index markers. |
| `context.index-freshness.missing-gist` | A file has no `gist` or no `Run me when` line. |

## markdown.document-ids

Markdown files that match `glob` have a non-empty, unique ID without spaces in their front matter. The optional `registry` keeps the IDs stable. Generic: it reads only front matter and a registry file, so it fits any Markdown repository. No `glob`: no findings.

| Rule | Meaning |
| --- | --- |
| `markdown.document-ids.missing` | A file has no ID. |
| `markdown.document-ids.empty` | The ID is empty. |
| `markdown.document-ids.bad-id` | The ID has a space, or it is a list. |
| `markdown.document-ids.duplicate` | Two files have one ID. |
| `markdown.document-ids.changed` | The ID differs from its registry entry. |
| `markdown.document-ids.orphan` | A registry path has no file. |
| `markdown.document-ids.bad-config` | A parameter is wrong. |

## markdown.front-matter

Markdown files that match a glob have front matter with the required keys and allowed values. Generic: it reads only the simple forms `key: value` and `key: [a, b]`. A line that it does not understand is a finding. No `rules`: no findings.

| Rule | Meaning |
| --- | --- |
| `markdown.front-matter.missing-file-block` | The file has no front matter. |
| `markdown.front-matter.missing-key` | A required key is absent. |
| `markdown.front-matter.bad-value` | A value is not in the allowed list. |
| `markdown.front-matter.unterminated` | The block never closes. |
| `markdown.front-matter.unreadable` | A line is not understood. |
| `markdown.front-matter.bad-config` | A parameter is wrong. |

## markdown.local-links

Each relative Markdown link points to a file that exists. Each `#anchor` matches a heading.

| Rule | Meaning |
| --- | --- |
| `markdown.local-links.missing-file` | The target file does not exist. |
| `markdown.local-links.missing-anchor` | The heading for the anchor does not exist. |

## markdown.required-headings

Markdown files that match a glob have the required headings, at the given level and in the given order. Generic: it reads only Markdown headings and a list of rules. No `rules`: no findings.

| Rule | Meaning |
| --- | --- |
| `markdown.required-headings.missing` | A required heading does not exist. |
| `markdown.required-headings.order` | The headings are in the wrong order. |
| `markdown.required-headings.unclosed-fence` | A fence never closes. |
| `markdown.required-headings.bad-config` | A parameter is wrong. |

## plans.graph

A plan has a valid dependency graph.

| Rule | Meaning |
| --- | --- |
| `plans.graph.unknown-dependency` | A step depends on a step that does not exist. |
| `plans.graph.cycle` | The dependencies form a cycle. |
| `plans.graph.touch-overlap` | Two steps that can run together touch the same file. |
| `plans.graph.shared-lane` | Two steps share a serial lane. |
| `plans.graph.too-deep` | The graph is too deep. |

## plans.schema

Each plan step file has valid front matter. Each plan has `goal.md` and `plan.md`.

| Rule | Meaning |
| --- | --- |
| `plans.schema.id-mismatch` | The `id` does not match the file name. |
| `plans.schema.bad-status` | The `status` is not a valid value. |
| `plans.schema.done-without-evidence` | A done step has no `evidence`. |
| `plans.schema.empty-gate` | The `gate` is empty. |

The check can also report a missing file or key. Run `explain` for the full list.

## repo.forbidden-artifacts

No forbidden file is tracked by Git. The default patterns are `driver.out`, `ledger.jsonl`, `plans/**/*.lock`, `.claude/settings.json`, `.claude/settings.local.json` and `.env`. The parameter `extra_patterns` adds patterns.

| Rule | Meaning |
| --- | --- |
| `repo.forbidden-artifacts.tracked` | A tracked file matches a forbidden pattern. |

## security.personal-data

No personal path or e-mail address in the Markdown of the context folders. Each rule is `security.personal-data.<label>`.

| Label | Meaning |
| --- | --- |
| `private-key` | A private key header. |
| `token` | A token with a known prefix. |
| `credential-in-url` | A user name and password in a URL. |
| `connection-string` | A password or key in a connection string. |
| `personal-path` | A path in a user home folder. |
| `email` | An e-mail address that is not an example address. |

## security.secrets

No secret, private key or forbidden file in the tracked files. This check is mandatory and has the status `required`. See [security-limits.md](./security-limits.md). Each rule is `security.secrets.<rule>`.

| Rule | Meaning |
| --- | --- |
| `private-key` | A private key. |
| `anthropic-key`, `openai-key`, `huggingface-token` | A key for an AI service. |
| `github-token`, `github-pat` | A GitHub token. |
| `aws-access-key-id`, `aws-secret-key` | An AWS credential. |
| `google-api-key`, `azure-key` | A cloud key. |
| `slack-token`, `slack-webhook` | A Slack credential. |
| `stripe-key`, `sendgrid-key` | A payment or mail key. |
| `npm-auth-token`, `pypi-token` | A package registry token. |
| `jwt` | A JSON Web Token. |
| `url-credential` | A credential in a URL. |
| `generic-secret` | A value that looks like a secret by its name and form. |
| `forbidden-file` | A file that must not be tracked, for example a local settings file. |

## Rules that all `translation.*` checks share

Each rule is `<check-id>.<rule>`. The finding path is the target path.

| Rule | Meaning |
| --- | --- |
| `bad-config` | A parameter is present but wrong: a missing file, bad TOML, an unknown key or a path outside the repository. |
| `missing-target` | The target file of a pair does not exist. |
| `duplicate-target` | Two source files map to one target. |
| `missing-source-root` | The source root has no Markdown file. |
| `stale-exception` | An exception row matches no finding. |

Without its main parameter (`mapping`, `glossary` or `source_manifest`) a check passes with no findings.

## translation.chunks

The chunks of the target match the chunks of a source manifest. Generic: it compares two JSONL files, so it needs no Markdown parser, language or project name. `custom_id_digits` (default `12`) sets the digest prefix in `custom_id`.

| Rule | Meaning |
| --- | --- |
| `translation.chunks.missing` | A source ID has no target row. |
| `translation.chunks.orphan` | A target ID is not in the source manifest. |
| `translation.chunks.duplicate` | An ID appears twice in one manifest. |
| `translation.chunks.stale` | The source digest of the target differs from the source. |
| `translation.chunks.empty` | A target row has no text. |
| `translation.chunks.fuzzy` | A target row has status `fuzzy` or `needs-review`. |
| `translation.chunks.custom-id` | `custom_id` is not the ID plus the digest prefix. |
| `translation.chunks.bad-manifest` | A row or a file of a manifest is not valid. |

## translation.fences

Fenced code blocks equal the source byte for byte, in the same count, order and kind. Generic: any translation keeps code blocks unchanged. Kinds in `translatable_kinds` (default `["mermaid"]`) are not compared. With `inline_code = true` the inline code spans are compared too.

| Rule | Meaning |
| --- | --- |
| `translation.fences.count` | The number of fences differs. |
| `translation.fences.kind` | The fence character or language tag differs. |
| `translation.fences.code-differs` | A body is not byte-identical. |
| `translation.fences.unclosed` | A fence never closes. |
| `translation.fences.inline-code` | The inline code spans differ. |

## translation.glossary

Each source term has its approved rendering in the target and no banned word. Generic: the terms, the banned words and the do-not-translate phrases come from files. Matching uses Unicode NFC, ignores case, matches whole words and skips code, URLs and link destinations.

| Rule | Meaning |
| --- | --- |
| `translation.glossary.bad-glossary` | The glossary or the do-not-translate file is missing or not valid. |
| `translation.glossary.missing-rendering` | The target has no approved rendering of a source term. |
| `translation.glossary.banned-term` | The target has a banned word of a term. |
| `translation.glossary.dnt-missing` | A do-not-translate phrase of the source is not in the target. |

## translation.links

Each link, image and anchor of the target matches its source after the path and anchor renames of the mapping. Generic: it needs no language, book or project name. It never fetches a URL. `source_repository_url` is optional.

| Rule | Meaning |
| --- | --- |
| `translation.links.destination-differs` | The links differ from the source after the maps. |
| `translation.links.external-differs` | An external URL is not equal to the source. |
| `translation.links.missing-file` | A relative path does not exist. |
| `translation.links.missing-anchor` | A fragment matches no heading ID. |
| `translation.links.line-anchor` | A `#L12` or `#L12-L20` range is not valid. |
| `translation.links.foreign-repository` | A link points into the source repository. |

## translation.structure

The target keeps the structure of its source. Generic: it reads only Markdown structure and the mapping file. `disabled_rules` turns off named rules. `fixed_front_matter_keys` names keys whose values must not change.

| Rule | Meaning |
| --- | --- |
| `translation.structure.headings` | The count or levels of headings differ. |
| `translation.structure.table-rows` | The table row count differs. |
| `translation.structure.table-cells` | The cell count of a row differs. |
| `translation.structure.footnotes` | Footnote references or definitions differ. |
| `translation.structure.bold-count` | The count of bold spans differs. |
| `translation.structure.front-matter` | The front matter keys or fixed values differ. |
| `translation.structure.mermaid-skeleton` | The skeleton of a Mermaid diagram differs. |
| `translation.structure.mermaid-label` | A Mermaid label has a syntax problem. |
| `translation.structure.mermaid-unsupported` | The diagram is not understood. This is never a skip. |

## translation.untranslated-heuristic

Advisory only. It hints that a prose segment may still be in the source language, by the share of source-language stopwords. Every finding has severity `info`, so it never fails a run. Generic: the stopword list is a parameter. `threshold` (default `0.30`) and `min_words` (default `6`) tune it.

| Rule | Meaning |
| --- | --- |
| `translation.untranslated-heuristic.segment` | A segment has a high share of source-language stopwords. |
