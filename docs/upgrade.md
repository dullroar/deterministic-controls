# Upgrade and roll back

A consumer repository pins one commit of this library. A change of the pin is a change of the rules. So you change it in a pull request.

## Upgrade

1. Read the release notes in [CHANGELOG.md](../CHANGELOG.md). Look for added, changed, renamed and retired checks.
2. Make a branch.
3. Change the pinned commit in the workflow and in the requirements file that the adoption tools wrote. Use the full commit hash of the new release.
4. Run the checks on the branch:

   ```bash
   python3 -m deterministic_controls check --root . --profile full
   ```

5. Fix each new finding in the same pull request. Or record why you cannot fix it.
6. Open the pull request. Let CI run. Get a review.
7. Merge when CI passes.

Do not change the pin and other code in one pull request.

## Upgrade to 0.2.0

Release `0.2.0` adds the translation and Markdown pack. See [translation-pack.md](./translation-pack.md).

- Use `<commit>` for the install line of this release: the commit that the tag `v0.2.0` points to.
- No check is renamed or retired. The core and the first seven checks are unchanged.
- The new checks are opt-in. They run only if you list them in `enabled`. An upgrade alone adds no finding to your repository.

## Roll back

1. Make a branch.
2. Change the pin back to the previous commit. The Git history of the workflow shows it.
3. Run the checks.
4. Open a pull request. Merge it when CI passes.

A tag of a release never moves. So the previous pin always gives the same result.

## What can go wrong

- A new check finds old defects. Fix them, or roll back and plan the fix.
- A renamed check changes the IDs in your `controls.toml`. The release notes list each rename.
- An unknown check ID in the manifest gives exit code `2`.
