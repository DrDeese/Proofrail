# Completion claim

The Step 10 pull request adds bounded Git-change verification to the local Proofrail action and dogfoods that mode against its own commit range.

## Atomic claims

- id: action-metadata-modified
  statement: .github/actions/proofrail-verify/action.yml was modified.
  expected-path: .github/actions/proofrail-verify/action.yml
  expected-change: modified

- id: action-wrapper-modified
  statement: .github/actions/proofrail-verify/run.py was modified.
  expected-path: .github/actions/proofrail-verify/run.py
  expected-change: modified

- id: claim-file-added
  statement: .proofrail/claim.md was added.
  expected-path: .proofrail/claim.md
  expected-change: added

- id: readme-modified
  statement: README.md was modified.
  expected-path: README.md
  expected-change: modified

- id: workflow-uses-exact-pr-shas
  statement: The pull request workflow invokes Proofrail using exact base and head commit SHAs.
  expected-path: .github/workflows/proofrail-fixtures.yml
  expected-change: modified
