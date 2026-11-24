# Changelog

This project uses [SemVer](https://semver.org). See [docs/release-policy.md](./docs/release-policy.md).

## 0.1.0

First release.

### Added checks

- `plans.schema`: each plan step has valid front matter. Each plan has `goal.md` and `plan.md`.
- `plans.graph`: a plan has no unknown dependency, no cycle, no overlap of `touches` and no shared serial lane.
- `context.index-freshness`: the generated index files are up to date.
- `markdown.local-links`: each relative Markdown link and each anchor is valid.
- `security.secrets`: no secret, private key or forbidden file in the tracked files. This check is mandatory.
- `security.personal-data`: no personal path or e-mail address in the Markdown of the context folders.
- `repo.forbidden-artifacts`: no runtime output, lock file or settings file is tracked.

### Added tools

- The command line: `list`, `check`, `explain`, `version` and `adopt`.
- The manifest `controls.toml` and the JSON result contract.
- The adoption tools: `adopt audit`, `adopt plan`, `adopt apply` and the receipt, with a shim and workflow templates.
- The secret guard, with the pre-commit hook, the pre-push hook and a CI job.
- `scripts/release_check.sh`.

### Changed, renamed and retired checks

None. No check is changed, renamed or retired in this release.
