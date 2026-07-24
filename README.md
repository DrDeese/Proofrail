# Proofrail

**Check whether an AI coding agent's delivered commit supports what it claims it completed.**

> Public alpha: available on PyPI, local and read-only, and not a hosted service.

## Install and try the reconstructed incident

Requires Python 3.9 or newer:

```sh
pip install proofrail
proofrail verify --demo
```

The demo should finish with `partially_verified`: the deletion is supported,
the workflow update is contradicted, the green-CI claim is unsupported, and
merge status requires human review.

## The reconstructed failure

An agent was asked to delete an obsolete `bun.lockb` file and update two workflow triggers to watch `bun.lock`.

The delivered commit deleted the obsolete file but omitted both workflow changes. CI still turned green because the old workflow was triggered by the deleted `bun.lockb`. The green check appeared to confirm the fix while actually exercising the configuration that should have been replaced.

| Claim | Proofrail result |
| --- | --- |
| Obsolete lockfile deletion | `verified` |
| Workflow trigger update | `contradicted` |
| Green run proves the new trigger | `unsupported` |
| Merge status | `human_review_required` |
| Overall result | `partially_verified` |

This fixture is a deterministic reconstruction of the real incident. It does not represent a failure caught from a live external user. Read the [complete reconstructed example](https://github.com/DrDeese/Proofrail/blob/main/docs/examples/partial-workflow-fix.md).

For a no-install source-checkout run and a real committed-range walkthrough,
continue to the [quick-start guide](https://github.com/DrDeese/Proofrail/blob/main/docs/QUICKSTART.md).

## What Proofrail is

In short: Acceptance verification for AI-generated code changes.

AI agents can pass tests and report "done" even when part of the requested change never reached the final commit. Proofrail compares the agent's claims with an exact Git commit range and the available evidence, then reports each claim as verified, contradicted, unsupported, or requiring human review (`human_review_required`).

## Why not just read the diff or ask another AI?

A diff shows what changed, but it does not tell you whether every completion claim is present or whether a passing check actually tested the claimed behavior.

A second AI can offer another interpretation. Proofrail instead applies deterministic checks to fixed artifacts: the claims, committed range, and submitted evidence. Its report shows which artifact supports each result and what remains unproven.

Proofrail complements code review and tests; it does not replace them.

## For AI coding agents

Run Proofrail after implementation and before the agent reports "done." A diff shows what changed. Proofrail checks whether the agent's stated claims are supported by what changed.

Use the [Proofrail acceptance skill](https://github.com/DrDeese/Proofrail/blob/main/.codex/skills/proofrail-acceptance/SKILL.md) to inspect an exact committed range, handle each claim status, and produce an evidence-bounded final report.

Claude Code users can copy the repository instructions in the [Claude Code integration guide](https://github.com/DrDeese/Proofrail/blob/main/docs/CLAUDE_CODE.md).

## Example output

```text
Overall verdict: partially_verified - some claims are supported, while others
are not or still need human review.
```

Use `--format json` for per-claim findings, evidence references, source hashes,
and provenance limitations.

## GitHub Actions usage

The composite action under `.github/actions/proofrail-verify` is currently
repository-local dogfood infrastructure. It works within this repository's
checkout; it is not installed by `pip install proofrail` and is not yet a
reusable action for external repositories.

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    case-directory: tests/fixtures/001-partial-workflow-fix
    format: json
```

Within this repository, the action writes JSON under `.proofrail/results/`,
appends a Markdown report to the job summary, and exposes the verdict and JSON
path as outputs. The included workflow uses read-only `contents: read`
permissions. External CI should install `proofrail` from PyPI and invoke its
CLI directly.

## Core concepts

Proofrail separates five statements that are often conflated:

1. **Attempted** — an agent tried an action.
2. **Executed** — a command completed.
3. **Artifact changed** — a final artifact has a measurable change.
4. **Claim supported** — the artifact directly supports a completion claim.
5. **Outcome verified** — relevant evidence demonstrates the requested behavior.

See the [acceptance model](https://github.com/DrDeese/Proofrail/blob/main/ACCEPTANCE_MODEL.md) for the full model.

## What Proofrail proves

For supported inputs, Proofrail can deterministically inspect an exact local Git range, draft path-level claims, check claim freshness, prepare a case, evaluate artifact-level evidence, and apply a bounded acceptance policy. It can show that a final committed artifact matches or conflicts with a path-level claim.

## What Proofrail does not prove

Proofrail does not authenticate authorship or timestamps, prove deployment state, browser rendering, external-system behavior, human intent, or that an execution command tested the claimed outcome. It does not run recorded commands, contact external services, or turn a green check into evidence by itself.

## Project status

Proofrail is a **Public alpha** distributed on PyPI for local, read-only
evaluation. It is not a hosted platform, a universal behavioral verifier, or a
supported general-availability product. See [project status](https://github.com/DrDeese/Proofrail/blob/main/docs/PROJECT_STATUS.md)
for the current capabilities and limitations.

## Pilot guidance

Use a controlled pilot to test whether Proofrail improves review quality in your environment. The [pilot guide](https://github.com/DrDeese/Proofrail/blob/main/docs/PILOT_GUIDE.md) defines a three-repository evaluation and measurable future targets.

## Development and contributing

Read the [product doctrine](https://github.com/DrDeese/Proofrail/blob/main/PRODUCT.md),
[acceptance model](https://github.com/DrDeese/Proofrail/blob/main/ACCEPTANCE_MODEL.md),
and [agent instructions](https://github.com/DrDeese/Proofrail/blob/main/AGENTS.md).
The [autonomous engineering process](https://github.com/DrDeese/Proofrail/blob/main/docs/WORKFLOW.md)
uses explicit step contracts and deterministic preflight before a bounded
change is committed.

## Repository orientation

- `src/proofrail_verifier/` — deterministic verifier, claim, policy, and Git-range code.
- `tests/fixtures/` — preserved regression fixtures.
- `tests/` — deterministic regression and integration coverage.
- `.github/actions/proofrail-verify/` — local GitHub Actions integration.
- `contracts/` — exact step contracts for deterministic preflight.
