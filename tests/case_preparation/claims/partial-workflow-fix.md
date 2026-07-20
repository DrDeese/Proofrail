# Completion claim

The obsolete lockfile was removed and both workflow triggers now watch bun.lock.

## Atomic claims

- id: obsolete-lockfile-deleted
  statement: bun.lockb was deleted.
  expected-path: bun.lockb
  expected-change: deleted

- id: workflow-triggers-updated
  statement: Both workflow trigger blocks were updated to watch bun.lock.
  expected-path: .github/workflows/ci.yml
  expected-change: modified
