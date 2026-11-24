# Security limits

Read this page before you rely on the checks. The checks reduce risk. They do not remove it.

## The secret scan is best effort

- The scan uses known patterns for keys and tokens, and a generic rule. It can miss a secret that has an unknown form.
- It can report a value that is not a secret. An exception needs a reason and a fingerprint, and the owner reviews it.
- It does not scan a binary file. It does not scan a file over 5 MiB. It lists these files as not scanned.
- A secret that was committed once stays in the Git history. Revoke it. A later fix does not help.
- Local hooks help, but a developer can skip them. CI is the control that cannot be skipped by one person.

## Personal data

The check `security.personal-data` finds personal paths and e-mail addresses in the Markdown of the context folders. It does not find a name, an address or other personal data.

## What CI can enforce

- CI runs the checks on every pull request and gives a result that a reviewer can see.
- A failed run can block a merge only when the repository requires the check before a merge.
- CI cannot stop a person with the right to bypass the rules.
- CI cannot check a file that the workflow does not cover. A change to the workflow itself needs a review.

## What CI cannot enforce

- CI cannot prove that the code is correct. It runs the listed checks only.
- CI cannot undo a push. It reports after the push on a branch that has no protection.
- A check has the rights of the job that runs it. Keep the job rights small.

## Branch protection limits

- **Public repository:** branch protection and required status checks are free on GitHub.
- **Private repository:** these features need a paid plan. On a free plan, a private repository cannot require the check before a merge. CI still runs, but it cannot block.
- On any plan, an administrator can bypass the rules unless the setting for administrators is on.
- This library never changes a repository setting. The owner sets branch protection.

## Report a problem

Report a defect in a check as an issue. Do not put a real secret in an issue.
