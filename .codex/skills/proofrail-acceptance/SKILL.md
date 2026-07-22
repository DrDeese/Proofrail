---
name: proofrail-acceptance
description: Apply Proofrail after implementing any bounded repository change and before reporting completion, whether the intended delivery is committed or uncommitted. Verify against an exact committed Git range when available; otherwise report acceptance blocked and request commit authorization. Never commit automatically or treat staged or unstaged work as Proofrail-verified.
---

# Proofrail acceptance

## Trigger

Invoke this skill after implementing any bounded repository change and before reporting the task as complete. If all intended changes are in an exact committed Git range, run the acceptance workflow. If the intended delivery is uncommitted, do not create a commit or run Proofrail against HEAD, staged files, or unstaged files. Report acceptance as blocked and ask the user whether to authorize a commit.

Do not use this skill in place of implementation, code review, tests, `proofrail-autonomous-step`, `proofrail-step-preflight`, or `proofrail-scope-escalation`.

## Preconditions

1. Read the repository's agent instructions and completion report.
2. Select the repository, base commit, and head commit. Resolve both to full SHAs and confirm the base is an ancestor of the head:

   ```sh
   git -C <repo> rev-parse --verify <base>^{commit}
   git -C <repo> rev-parse --verify <head>^{commit}
   git -C <repo> merge-base --is-ancestor <base-sha> <head-sha>
   git -C <repo> status --short
   ```

3. Stop if tracked or untracked implementation work is outside `<head-sha>`. Proofrail inspects committed artifacts, not an unstaged or staged delivery.
4. Define one supported local Proofrail invocation before running the workflow:

   ```sh
   # After installing a locally built wheel:
   PROOFRAIL_CMD="proofrail"

   # Or, from a Proofrail source checkout:
   export PYTHONPATH="/absolute/path/to/Proofrail/src"
   PROOFRAIL_CMD="python3 -m proofrail_verifier"
   ```

   Select one definition, not both. `PYTHONPATH` identifies the `src` directory in the Proofrail source checkout. The later `--repo` argument identifies the separate software repository whose committed range Proofrail will inspect.

Proofrail is a public alpha. It is not on PyPI and is not hosted. Its locally built release materials still use the earlier Internal Alpha packaging label.

## Run the acceptance workflow

Create outputs outside the inspected repository. Substitute the exact repository path and full SHAs; do not use an inferred branch range.

```sh
PROOFRAIL_OUTPUT_DIR="$(mktemp -d)"

$PROOFRAIL_CMD draft-claims \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --output "$PROOFRAIL_OUTPUT_DIR/claims.md" --case-title "Acceptance claims"
```

Open `claims.md`. Compare the completion report with every changed path. Keep one atomic claim for each delivered path and keep each statement no broader than the `expected-path` and `expected-change` that Proofrail can observe. Do not convert behavioral, deployment, provenance, or intent assertions into artifact claims merely by rewording them. Record those assertions as unsupported or requiring human review unless capable evidence is available in a supported case.

Then run:

```sh
$PROOFRAIL_CMD check-claims \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/claims.md" \
  --format json --output "$PROOFRAIL_OUTPUT_DIR/claim-check.json"

$PROOFRAIL_CMD verify-change \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/claims.md" \
  --format json --output "$PROOFRAIL_OUTPUT_DIR/verification.json"
```

Inspect the claim-check and verification JSON. Retain each claim ID, status, evidence reference, finding, provenance limitation, and the exact base and head SHAs. A completed `partially_verified`, `unsupported`, `contradicted`, or `human_review_required` result is not a command failure.

## Required status actions

- `verified`: Report only the specific claim as supported and retain its evidence reference. Do not expand an artifact-level result into a runtime or external-outcome claim.
- `unsupported`: Do not report the claim as completed. Gather capable evidence, narrow the claim, or explicitly disclose that it remains unsupported.
- `contradicted`: Return to implementation. Correct the delivered artifact or withdraw the claim, then rerun the entire workflow before reporting completion.
- `human_review_required`: Stop automated acceptance for that claim. Identify the exact unresolved judgment or unavailable evidence for the human.

Never treat the agent's completion summary, another model's opinion, command success alone, or a general green CI result as proof of a specific claim unless the evidence can observe that claim.

## Failure handling

- If the intended delivery is uncommitted, report: `Proofrail acceptance: blocked — the intended delivery is uncommitted, so no exact committed Git range exists for verification.` Ask for commit authorization and stop. Do not describe the implementation as complete or Proofrail-verified.
- If Proofrail is unavailable, the range is invalid, the worktree contains undelivered implementation work, claim drafting fails, or any command exits nonzero, stop and report the exact command and error. Do not substitute model judgment.
- If `check-claims` reports missing, stale, or duplicate coverage, repair the claim file or the implementation as appropriate and rerun checking before verification.
- If the implementation or completion claims change after verification, select the new full head SHA, create new outputs, and rerun drafting, checking, and verification. Never reuse a result for an older range.
- Preserve stderr. Do not weaken a claim, omit a changed path, or relabel a result merely to obtain acceptance.
- Do not automatically commit, stage, push, merge, publish, deploy, install from a package index, or change repository state. Create only the explicit Proofrail output files required above.

## Final-report template

```text
Exact Git range inspected
- base: <full-base-sha>
- head: <full-head-sha>

What changed
- <path>: <objective committed change>

What Proofrail verified
- <claim-id>: <supported claim>; evidence: <evidence-id-or-reference>

What remains unsupported or contradicted
- <claim-id>: <status>; <finding and required next action>

What requires human review
- <claim-id>: <exact unresolved judgment or unavailable evidence>

Acceptance result
- overall verdict: <verdict>
- result artifact: <verification-output-path>
```

Use `none` under an empty section. Do not place unsupported or contradicted claims under “What Proofrail verified,” and do not describe them as completed.
