# Plans index

<!-- IMMUTABLE HEADER: do not edit the text above the BEGIN marker. -->

This folder holds the plans for agents. Humans read `docs/` instead.

- One plan is one folder: `plans/<plan-name>/`. Copy `for-each-plan/` to start a plan.
- `goal.md` holds the goal and the Ralph loop prompt. `plan.md` holds the high-level plan. `steps/` holds one file for each step.
- A step is small. A small model or agent can implement, test and verify it alone.
- Run a plan in its own Git worktree, on its own branch. Never work on `main`.
- Steps that run at the same time must not touch the same files (see `touches` in the step front matter).
- A plan must survive a stop at any time. Another agent must be able to continue from the files in the repository. Record status and evidence in the step files.
- Runtime output goes outside the repository, in `~/repo-work/<repo>/<plan>/`. Never track it.
- Never put PII, secrets or personal paths in a plan.
- Write in Simplified Technical English (ASD-STE100).
- This file is generated. Run `python3 scripts/build_indexes.py` after any change. Do not edit the list below by hand.

Read the list. Open only the plans whose "Read me when" line matches your task.

<!-- BEGIN GENERATED INDEX -->

* [bootstrap/plan.md](./bootstrap/plan.md)
  Read me when: you build or change the deterministic-controls library before release v0.1.0: the CLI, the manifest, the result contract, the checks or the adoption tools.
* [for-each-plan/plan.md](./for-each-plan/plan.md)
  Read me when: you want to see the format of a plan. (Template only. Copy this folder to start a plan.)
* [translation-pack/plan.md](./translation-pack/plan.md)
  Read me when: you add or change the opt-in translation and Markdown checks of the deterministic-controls library for release v0.2.0.

<!-- END GENERATED INDEX -->
