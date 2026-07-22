# Instructions for AI Agents

## Source of truth

Read these files before beginning work:

1. `PRODUCT.md`
2. `ACCEPTANCE_MODEL.md`
3. Relevant files under `docs/founder-evidence/`

Do not redefine the product without explicit human approval.

## Completion rules

A task is not complete merely because a command passed.

### Proofrail acceptance boundary

For every task that changes repository files, do not report the task as complete until one of these conditions is recorded:

1. All intended delivery changes are contained in an exact committed Git range and `proofrail-acceptance` has been invoked on that range.
2. Acceptance verification is explicitly reported as blocked because the intended delivery is uncommitted.

If the user has not authorized a commit, do not create one and do not run Proofrail against `HEAD`, staged files, or unstaged files. Report exactly:

> Proofrail acceptance: blocked — the intended delivery is uncommitted, so no exact committed Git range exists for verification.

Ask the user whether to authorize a commit. You may report the files changed and commands executed, but do not describe the task or its claims as complete or Proofrail-verified.

Before reporting completion:

1. Restate the claims you are making.
2. Identify the artifact expected to support each claim.
3. Inspect the final Git diff.
4. Inspect the final commit contents.
5. Record the commands used as evidence.
6. Explain whether each command directly exercised the claimed behavior.
7. Mark unsupported or untested claims explicitly.
8. Never suppress errors from a command used as completion evidence.

## Evidence rules

Distinguish between:

- attempted actions;
- executed commands;
- changed artifacts;
- supported claims;
- verified outcomes.

Do not present one category as proof of another without supporting evidence.

## Development rules

- Prefer deterministic verification over model judgment.
- Keep the initial product focused on GitHub pull requests.
- Do not add unrelated agent-platform features.
- Do not build a generic code-review chatbot.
- Do not automatically merge pull requests.
- Preserve real failures as regression fixtures.
