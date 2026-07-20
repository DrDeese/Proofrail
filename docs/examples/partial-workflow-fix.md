# Partial workflow fix

## Requested change

The agent was asked to make two related changes:

1. Remove the obsolete `bun.lockb` file.
2. Update both workflow trigger blocks to watch the active `bun.lock` file.

## Actual partial commit

The delivered commit deleted `bun.lockb`, but it did not modify the workflow file. The requested workflow update was absent from the final artifact.

## Why the workflow still looked green

The workflow ran successfully because its old trigger still referenced the deleted `bun.lockb` file. The green run therefore observed the old configuration reacting to the deletion. It did not show that a `bun.lock` change would trigger the workflow.

## Claim-by-claim result

| Claim | Status | Why |
| --- | --- | --- |
| Obsolete lockfile deleted | `verified` | The final artifact deletes `bun.lockb`. |
| Workflow triggers updated | `contradicted` | The workflow path filters still reference `bun.lockb`. |
| Green run proves the new trigger | `unsupported` | The supplied run information cannot authenticate the event, run, SHA, workflow version, or triggering path. |
| Change merged | `human_review_required` | The offline fixture has no merge provenance. |

The overall verdict is `partially_verified`.

## What the evidence means

This incident separates five different facts:

- **attempted**: the agent intended to stage the deletion and workflow updates;
- **executed**: a staging command was run, but its error output was suppressed;
- **artifact_changed**: the final commit deleted `bun.lockb`;
- **claim_supported**: the deletion claim is supported by the final artifact;
- **outcome_verified**: no evidence verifies that the new `bun.lock` trigger works.

The fixture is a deterministic reconstruction of the incident. Its structured workflow-run information is scenario-provided and unauthenticated; it is not independently verified execution provenance.
