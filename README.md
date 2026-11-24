# deterministic-controls

A small, versioned library of deterministic checks for repositories that follow the `repo-template` layout.

The library runs the same checks in a developer shell, in a pre-commit hook and in CI. A check never changes a file. An agent never certifies its own work: the checks run on their own and without condition.

It uses only the Python standard library. It needs Python 3.11 or later.

## Install

```bash
python3 -m pip install "deterministic-controls @ git+https://github.com/dullroar/deterministic-controls@<commit>"
```

Replace `<commit>` with the commit of the release that you pin. See [docs/upgrade.md](./docs/upgrade.md).

## Example

Put a file `controls.toml` in the root of your repository:

```toml
schema_version = 1
profile = "ci"
enabled = ["plans.schema", "plans.graph", "security.secrets"]
```

Run the checks:

```bash
python3 -m deterministic_controls check --root . --profile full
```

The exit code is `0` when all checks pass. See [docs/run.md](./docs/run.md) for all commands and exit codes.

## Translation pack

The library has an opt-in pack of checks for a Markdown-to-Markdown translation that has a source manifest: code blocks, links, structure, glossary, chunks and more. A check runs only if you enable it. See [docs/translation-pack.md](./docs/translation-pack.md).

## Documents

See [docs/README.md](./docs/README.md) for the full list: install, run, read a failure, upgrade, roll back, security limits, release policy and the catalog of checks.

## Develop

```bash
python3 -m unittest discover -s tests -v
bash scripts/release_check.sh
```

## License

MIT. See [LICENSE](./LICENSE).
