# Changelog

This project uses [SemVer](https://semver.org). See [docs/release-policy.md](./docs/release-policy.md).

## 0.1.2

### Fixed

- `context.index-freshness` no longer treats `README.md` in `memory/` or `scripts/` as an index entry. The ten repositories of the 2026-11-22 rollout keep a `README.md` in both folders, and their own `build_indexes.py` skips it. Before, the check failed in each of them. Found by the controls-rollout pilot.
- The hook installer (`scripts/install_hooks.sh`, also installed by `adopt apply`) now falls back to `git config secretguard.path` when `SECRET_GUARD` is unset. Non-interactive shells do not read `~/.bashrc`, so the hooks refused every commit in a repository without its own guard copy.

### Changed, renamed and retired checks

- `context.index-freshness`: `README.md` in `memory/` and `scripts/` is skipped, like `AGENTS.md`. This is a compatibility fix, not a weaker check: a folder README is never an index entry.

## 0.1.1

### Fixed

- `adopt apply` now writes `scripts/controls-requirements.txt` with a `Run me when:` line. Before, `build_indexes.py --check` failed in every repository that uses the template layout after an adoption.

### Changed, renamed and retired checks

None.

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
