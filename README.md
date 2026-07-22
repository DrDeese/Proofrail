# Proofrail

**Check whether an AI coding agent's delivered commit supports what it claims it completed.**

> Public alpha: local and read-only. Proofrail is not on PyPI and is not yet a hosted service.

## What Proofrail is

In short: Acceptance verification for AI-generated code changes.

AI agents can pass tests and report "done" even when part of the requested change never reached the final commit. Proofrail compares the agent's claims with an exact Git commit range and the available evidence, then reports each claim as verified, contradicted, unsupported, or requiring human review (`human_review_required`).

## Why not just read the diff or ask another AI?

A diff shows what changed, but it does not tell you whether every completion claim is present or whether a passing check actually tested the claimed behavior.

A second AI can offer another interpretation. Proofrail instead applies deterministic checks to fixed artifacts: the claims, committed range, and submitted evidence. Its report shows which artifact supports each result and what remains unproven.

Proofrail complements code review and tests; it does not replace them.

## The failure that motivated Proofrail

An agent was asked to delete an obsolete `bun.lockb` file and update two workflow triggers to watch `bun.lock`.

The delivered commit deleted the obsolete file but omitted both workflow changes. CI still turned green because the old workflow was triggered by the deleted `bun.lockb`. The green check appeared to confirm the fix while actually exercising the configuration that should have been replaced.

| Claim | Proofrail result |
| --- | --- |
| Obsolete lockfile deletion | `verified` |
| Workflow trigger update | `contradicted` |
| Green run proves the new trigger | `unsupported` |
| Overall result | `partially_verified` |

This fixture is a deterministic reconstruction of the real incident. It does not represent a failure caught from a live external user. Read the [complete reconstructed example](docs/examples/partial-workflow-fix.md).

## Five-minute quick start: try it from a fresh clone

Requires Python 3.9 or newer. No installation or network access is needed:

```sh
PYTHONPATH=src python3 -m proofrail_verifier verify tests/fixtures/001-partial-workflow-fix
```

The expected overall verdict is `partially_verified`. That means Proofrail ran successfully and found that the available artifacts and evidence support only part of the agent's claims.

For local wheel installation and a real Git-range walkthrough, continue to the [quick-start guide](docs/QUICKSTART.md).

## Example output

```json
{
  "case_id": "001-partial-workflow-fix",
  "overall_verdict": "partially_verified"
}
```

The complete JSON includes per-claim findings, evidence references, source hashes, and provenance limitations.

## GitHub Actions usage

This repository provides a local composite action. Reference it from a workflow in the same checkout:

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    case-directory: tests/fixtures/001-partial-workflow-fix
    format: json
```

The action writes JSON under `.proofrail/results/`, appends a Markdown report to the job summary, and exposes the verdict and JSON path as outputs. The included workflow uses read-only `contents: read` permissions.

## Core concepts

Proofrail separates five statements that are often conflated:

1. **Attempted** — an agent tried an action.
2. **Executed** — a command completed.
3. **Artifact changed** — a final artifact has a measurable change.
4. **Claim supported** — the artifact directly supports a completion claim.
5. **Outcome verified** — relevant evidence demonstrates the requested behavior.

See [ACCEPTANCE_MODEL.md](ACCEPTANCE_MODEL.md) for the full model.

## What Proofrail proves

For supported inputs, Proofrail can deterministically inspect an exact local Git range, draft path-level claims, check claim freshness, prepare a case, evaluate artifact-level evidence, and apply a bounded acceptance policy. It can show that a final committed artifact matches or conflicts with a path-level claim.

## What Proofrail does not prove

Proofrail does not authenticate authorship or timestamps, prove deployment state, browser rendering, external-system behavior, human intent, or that an execution command tested the claimed outcome. It does not run recorded commands, contact external services, or turn a green check into evidence by itself.

## Project status

Proofrail is a **Public alpha** for local, read-only evaluation. The linked
release materials still use the earlier **Internal Alpha** packaging label. It
is not on PyPI, a hosted platform, a universal behavioral verifier, or a
supported general-availability product. See [project status](docs/PROJECT_STATUS.md)
for the current capabilities and limitations.

## Pilot guidance

Use a controlled pilot to test whether Proofrail improves review quality in your environment. The [pilot guide](docs/PILOT_GUIDE.md) defines a three-repository evaluation and measurable future targets.

## Development and contributing

Read the product doctrine first: [PRODUCT.md](PRODUCT.md), [ACCEPTANCE_MODEL.md](ACCEPTANCE_MODEL.md), and [AGENTS.md](AGENTS.md). The autonomous engineering process is documented in [docs/WORKFLOW.md](docs/WORKFLOW.md). The repository uses explicit step contracts and deterministic preflight before a bounded change is committed.

## Repository orientation

- `src/proofrail_verifier/` — deterministic verifier, claim, policy, and Git-range code.
- `tests/fixtures/` — preserved regression fixtures.
- `tests/` — deterministic regression and integration coverage.
- `.github/actions/proofrail-verify/` — local GitHub Actions integration.
- `contracts/` — exact step contracts for deterministic preflight.
