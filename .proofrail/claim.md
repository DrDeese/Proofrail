# Completion claim

Step 13 artifact changes

## Atomic claims

- id: github-actions-proofrail-verify-action-yml-modified
  statement: .github/actions/proofrail-verify/action.yml was modified.
  expected-path: .github/actions/proofrail-verify/action.yml
  expected-change: modified

- id: github-actions-proofrail-verify-run-py-modified
  statement: .github/actions/proofrail-verify/run.py was modified.
  expected-path: .github/actions/proofrail-verify/run.py
  expected-change: modified

- id: github-workflows-proofrail-fixtures-yml-modified
  statement: .github/workflows/proofrail-fixtures.yml was modified.
  expected-path: .github/workflows/proofrail-fixtures.yml
  expected-change: modified

- id: proofrail-claim-md-modified
  statement: .proofrail/claim.md was modified.
  expected-path: .proofrail/claim.md
  expected-change: modified

- id: readme-md-modified
  statement: README.md was modified.
  expected-path: README.md
  expected-change: modified

- id: src-proofrail-verifier-init-py-modified
  statement: src/proofrail_verifier/__init__.py was modified.
  expected-path: src/proofrail_verifier/__init__.py
  expected-change: modified

- id: src-proofrail-verifier-claim-checking-py-added
  statement: src/proofrail_verifier/claim_checking.py was added.
  expected-path: src/proofrail_verifier/claim_checking.py
  expected-change: added

- id: src-proofrail-verifier-cli-py-modified
  statement: src/proofrail_verifier/cli.py was modified.
  expected-path: src/proofrail_verifier/cli.py
  expected-change: modified

- id: tests-action-test-action-py-modified
  statement: tests/action/test_action.py was modified.
  expected-path: tests/action/test_action.py
  expected-change: modified

- id: tests-claim-checking-test-check-claims-py-added
  statement: tests/claim_checking/test_check_claims.py was added.
  expected-path: tests/claim_checking/test_check_claims.py
  expected-change: added

- id: tests-end-to-end-test-draft-claims-action-py-modified
  statement: tests/end_to_end/test_draft_claims_action.py was modified.
  expected-path: tests/end_to_end/test_draft_claims_action.py
  expected-change: modified
