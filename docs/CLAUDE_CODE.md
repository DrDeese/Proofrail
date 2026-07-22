# Use Proofrail with Claude Code

Proofrail can act as a post-implementation acceptance boundary for Claude Code.
Run it after implementation, before Claude reports "done," and before a change is
merged or otherwise accepted.

A diff shows what changed. Proofrail checks whether the agent's stated claims are
supported by what changed. Asking another model for its opinion is not
deterministic evidence.

## Add the acceptance boundary to `CLAUDE.md`

Copy this block into the repository's `CLAUDE.md` or equivalent repository
instructions:

```markdown
## Proofrail acceptance boundary

After implementing any change, and before reporting the task as done or asking
for merge or acceptance, run Proofrail against the exact committed Git range
that contains all intended delivery changes.

If the intended delivery is uncommitted, do not silently create a commit and do
not run Proofrail against `HEAD`, staged files, or unstaged files as though they
were delivered. Report exactly:

Proofrail acceptance: blocked — the intended delivery is uncommitted, so no exact committed Git range exists for verification.

Ask the user whether to authorize a commit. Never commit automatically.

Convert the completion report into atomic path-level claims, then run
`draft-claims`, inspect and refine the claim file, run `check-claims`, and run
`verify-change` for the same full base and head SHAs. Keep outputs outside the
repository being inspected.

Handle every claim status as follows:

- `verified`: report only that specific claim as supported and retain its
  evidence reference.
- `unsupported`: do not report the claim as completed; gather capable evidence,
  narrow the claim, or disclose that it remains unsupported.
- `contradicted`: return to implementation or withdraw the claim, then rerun
  Proofrail before reporting completion.
- `human_review_required`: stop automated acceptance for that claim and identify
  the exact unresolved judgment or unavailable evidence.

Do not treat a completion summary, another model's opinion, command success
alone, or general green CI as proof of a specific claim unless the evidence can
observe that claim. In the final response, separate the exact Git range, what
changed, what Proofrail verified, unsupported or contradicted claims, human
review, and the result artifact. Path-level verification does not automatically
prove runtime behavior.
```

## Run the workflow

Proofrail is not on PyPI and is not hosted. Choose one local invocation:

```sh
# After installing a locally built wheel:
PROOFRAIL_CMD="proofrail"

# Or from a Proofrail source checkout (choose this instead of the line above):
export PYTHONPATH="/absolute/path/to/Proofrail/src"
PROOFRAIL_CMD="python3 -m proofrail_verifier"
```

`PYTHONPATH` points to the Proofrail source checkout. `--repo` points to the
software repository whose committed range is being inspected.

Resolve and record the full base and head SHAs. Confirm the base is an ancestor
of the head and that no intended delivery work remains outside the committed
range:

```sh
git -C <repo> rev-parse --verify <base>^{commit}
git -C <repo> rev-parse --verify <head>^{commit}
git -C <repo> merge-base --is-ancestor <base-sha> <head-sha>
git -C <repo> status --short
```

Create outputs outside the inspected repository and use the same full SHAs for
every command:

```sh
PROOFRAIL_OUTPUT_DIR="$(mktemp -d)"

$PROOFRAIL_CMD draft-claims \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --output "$PROOFRAIL_OUTPUT_DIR/claims.md" \
  --case-title "Acceptance claims"

$PROOFRAIL_CMD check-claims \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/claims.md" \
  --format json --output "$PROOFRAIL_OUTPUT_DIR/claim-check.json"

$PROOFRAIL_CMD verify-change \
  --repo <repo> --base <base-sha> --head <head-sha> \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/claims.md" \
  --format json --output "$PROOFRAIL_OUTPUT_DIR/verification.json"
```

After `draft-claims`, inspect `claims.md` before continuing. Keep one atomic
claim for each delivered path and do not broaden a path fact into a behavioral,
deployment, provenance, or intent claim. If `check-claims` reports missing,
stale, duplicate, or conflicting coverage, correct the claims or implementation
and rerun it. If the implementation changes after verification, resolve a new
head SHA and rerun the whole workflow.

## Handle the result

- `verified`: the specific claim may be reported as supported with its evidence
  reference.
- `unsupported`: the claim must not be reported as completed. Gather capable
  evidence, narrow it, or disclose the limitation.
- `contradicted`: correct the delivered artifact or withdraw the claim, then
  rerun Proofrail.
- `human_review_required`: stop automated acceptance for that claim and state
  the unresolved judgment or unavailable evidence.

Never silently commit, merge, publish, deploy, or verify staged or unstaged work
as delivered. A non-verified result is an acceptance result, not permission to
omit the claim from the final report.

## Final-response template

```text
Exact Git range inspected
- base: <full-base-sha>
- head: <full-head-sha>

What changed
- <path>: <objective committed change>

What Proofrail verified
- <claim-id>: <supported claim>; evidence: <evidence-reference>

What remains unsupported or contradicted
- <claim-id>: <status>; <finding and required next action>

What requires human review
- <claim-id>: <unresolved judgment or unavailable evidence>

Acceptance result
- overall verdict: <verdict>
- result artifact: <verification-output-path>
```

Use `none` for an empty section. Never list an `unsupported` or `contradicted`
claim under “What Proofrail verified.”

## Current limitations

Proofrail is a public alpha. It is not on PyPI and is not a hosted service. Its
current deterministic Git-range workflow verifies bounded artifact facts such
as path-level changes. Path-level verification does not automatically prove
runtime behavior, deployment state, external-system behavior, authorship, or
human intent. Proofrail complements tests and code review; it does not replace
them.
