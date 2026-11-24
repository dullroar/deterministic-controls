# Install

## Needs

- Python 3.11 or later.
- Git.
- Network access to the Git host, to install from a commit.

The library has no run-time dependency.

## Install a pinned release

Pin a full commit hash. Do not pin a branch name.

```bash
python3 -m pip install "deterministic-controls @ git+https://github.com/dullroar/deterministic-controls@<commit>"
```

Replace `<commit>` with the commit that the release notes name. For release `0.2.0`, the commit is the one that the tag `v0.2.0` points to. The operator writes it in the release notes after the tag exists.

## Check the install

```bash
python3 -m deterministic_controls version
```

The command prints the version, for example `0.2.0`.

## Add the manifest

Put a file `controls.toml` in the root of your repository. See [run.md](./run.md).

## Adopt in an existing repository

The adoption tools classify a repository, make a plan and apply it. The tools never push. Use the same pinned commit.

```bash
python3 -m deterministic_controls adopt audit --root <repo>
python3 -m deterministic_controls adopt plan --root <repo> --commit <commit>
python3 -m deterministic_controls adopt apply --root <repo> --commit <commit>
```

`adopt audit` reads only. `adopt plan` shows what `adopt apply` will write. `adopt apply` writes the shim, the workflow, the manifest and a receipt. Read the plan before you apply it. Then make a pull request.
