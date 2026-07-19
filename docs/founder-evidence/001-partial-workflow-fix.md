# Founder Evidence 001: Partial Workflow Fix

## Situation

An AI agent intended to make two related changes:

1. remove the obsolete `bun.lockb` file;
2. update both workflow trigger blocks to watch the active `bun.lock` file.

## Agent claim

The agent reported that both changes had been completed and merged.

## Actual artifact

The resulting commit contained only the deletion of `bun.lockb`.

The workflow file modification was absent.

## Failure mechanism

The staging command included a path that no longer existed.

The command failed, but its error output was suppressed.

A previously staged deletion remained available, allowing the commit to succeed with only part of the intended work.

## Incorrect evidence interpretation

The relevant GitHub Action ran successfully.

The agent interpreted this as proof that the new `bun.lock` trigger worked.

However, the workflow had actually run because the deleted `bun.lockb` file was still referenced by the old trigger.

The green result was evidence of the old configuration, not the new configuration.

## Product lessons

Proofrail should detect:

1. completion claims referring to files absent from the final commit;
2. differences between intended files and committed files;
3. errors suppressed during evidence-producing commands;
4. passing checks triggered by an adjacent or obsolete artifact;
5. evidence that does not directly exercise the claimed behavior.

## Expected Proofrail verdict

Partially verified.

## Expected explanation

The obsolete lockfile was deleted, but the claimed workflow modification is absent from the final commit. The passing workflow does not verify the new trigger because it was initiated by the old trigger configuration.
