# Release policy

## Versions

The project uses [SemVer](https://semver.org): `MAJOR.MINOR.PATCH`.

- `MAJOR`: a change that breaks a consumer. Examples: a renamed or retired check, a new manifest schema, a new exit code meaning.
- `MINOR`: a new check, a new option or a new tool that does not break a consumer.
- `PATCH`: a fix that does not add a rule.

A new check that can fail an existing repository starts with the status `experimental` or `advisory`. See [catalog.md](./catalog.md).

## Tags are immutable

- A release tag points to one commit. It never moves and it is never deleted.
- A defect in a release is fixed in a new release.
- Consumers pin a full commit hash. See [install.md](./install.md).

## Release notes

Each release has an entry in [CHANGELOG.md](../CHANGELOG.md). The entry lists:

- the added checks
- the changed checks
- the renamed checks
- the retired checks

If there is none in a group, the entry says so.

A retired check first gets the status `deprecated` for at least one release.

## Release steps

1. Set the version in `pyproject.toml` and in `src/deterministic_controls/__init__.py`.
2. Write the changelog entry.
3. Run `bash scripts/release_check.sh`. Keep the printed wheel digest.
4. Get a review and merge.
5. The operator tags the commit and publishes. Agents do not tag and do not publish.
