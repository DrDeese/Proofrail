# Use Proofrail with Claude Code

Proofrail can act as a post-implementation acceptance boundary for Claude Code.
Run it after implementation, before Claude reports "done," and before a change is
merged or otherwise accepted.

A diff shows what changed. Proofrail checks whether the agent's stated claims are
supported by what changed. Asking another model for its opinion is not
deterministic evidence.

## Add the acceptance boundary to `CLAUDE.md`

Use the standalone [Claude Code instructions](claude-code-instructions.md), or
append them directly to an existing `CLAUDE.md`:

```sh
cat docs/claude-code-instructions.md >> CLAUDE.md
```

## Run the workflow

Proofrail is available on PyPI and is not hosted. Choose one local invocation:

```sh
# After installation with: pip install proofrail
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

Proofrail is a public alpha distributed on PyPI, not a hosted service. Its
current deterministic Git-range workflow verifies bounded artifact facts such
as path-level changes. Path-level verification does not automatically prove
runtime behavior, deployment state, external-system behavior, authorship, or
human intent. Proofrail complements tests and code review; it does not replace
them.
