# Catalog of checks

This page lists each check of release `0.1.0`. The source is `python3 -m deterministic_controls list`.

Statuses: `experimental`, `advisory`, `required`, `deprecated`. A mandatory check runs in every profile. The manifest cannot disable it.

| ID | Status | Severity | Parameters |
| --- | --- | --- | --- |
| `context.index-freshness` | advisory | error | none |
| `markdown.local-links` | advisory | error | `all` (boolean, default `false`) |
| `plans.graph` | advisory | error | none |
| `plans.schema` | advisory | error | none |
| `repo.forbidden-artifacts` | advisory | error | `extra_patterns` (list of glob strings, default empty) |
| `security.personal-data` | advisory | error | none |
| `security.secrets` | required, mandatory | error | none |

## context.index-freshness

The generated index files `memory/AGENTS.md`, `plans/AGENTS.md` and `scripts/AGENTS.md` are up to date. The check never writes. Run `python3 scripts/build_indexes.py` to fix.

| Rule | Meaning |
| --- | --- |
| `context.index-freshness.stale` | The index differs from the generated text. |
| `context.index-freshness.missing-markers` | The index has no generated-index markers. |
| `context.index-freshness.missing-gist` | A file has no `gist` or no `Run me when` line. |

## markdown.local-links

Each relative Markdown link points to a file that exists. Each `#anchor` matches a heading.

| Rule | Meaning |
| --- | --- |
| `markdown.local-links.missing-file` | The target file does not exist. |
| `markdown.local-links.missing-anchor` | The heading for the anchor does not exist. |

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
