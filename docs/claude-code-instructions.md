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

### Status handling

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
observe that claim. Path-level verification does not automatically prove
runtime behavior.

### Final response

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
