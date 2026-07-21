# Proofrail

## Acceptance verification for AI-generated code changes.

**Internal Alpha**

Proofrail checks whether an AI coding agent actually completed what it claims.

## What Proofrail is

Proofrail is an offline, deterministic acceptance-verification layer for AI-generated Git changes. It compares a structured completion claim with an exact committed range and the evidence available in a supported case. Its result is machine-readable JSON or Markdown, with the paths and evidence references that led to it.

## Why it exists

An agent can run commands, pass tests, and report “done” while only partially completing the requested change. A successful command proves that the command executed; it does not automatically prove that the delivered commit contains the intended change or that the claimed outcome occurred.

Proofrail keeps these statuses distinct:

- `verified` — the available capable evidence supports the atomic claim.
- `unsupported` — the supplied evidence cannot observe the claimed outcome.
- `contradicted` — the delivered artifact conflicts with the claim.
- `human_review_required` — capable authenticated evidence is unavailable.

## The partial-workflow-fix example

The founder incident asked an AI agent to delete an obsolete `bun.lockb` and update both workflow path triggers to watch `bun.lock`. The actual commit deleted the obsolete lockfile but left the workflow unchanged. The old workflow still ran on the deletion, so a green run was incorrectly treated as evidence that the new trigger worked.

| Claim | Proofrail status |
| --- | --- |
| Obsolete lockfile deletion | `verified` |
| Workflow trigger update | `contradicted` |
| Green run proves the new trigger | `unsupported` |
| Overall verdict | `partially_verified` |

Read the complete, factual walkthrough in [the partial-workflow-fix example](docs/examples/partial-workflow-fix.md).

## How it fits into an AI coding workflow

1. An agent makes a bounded Git change and supplies path-level completion claims.
2. Proofrail checks that every changed path has exactly one current claim.
3. Proofrail inspects the exact committed range and evaluates each supported artifact-level claim.
4. A team may apply a separate acceptance policy to the completed result.

Proofrail does not replace code review or tests. It makes clear what those artifacts actually establish.

## Five-minute quick start

Install a locally built wheel into a clean virtual environment, then invoke the
`proofrail` command without `PYTHONPATH`. Proofrail is not published to a
package index.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --no-index --no-deps dist/proofrail_verifier-0.1.0a1-py3-none-any.whl

# Run both deterministic fixtures.
proofrail verify tests/fixtures/001-partial-workflow-fix
proofrail verify tests/fixtures/002-incapable-validation-command
```

For source-checkout development, set `PYTHONPATH=src` and use
`python3 -m proofrail_verifier` with the same commands.

For an exact local Git range, use the included source repository. These commands create a real temporary output directory and can be run from the repository root:

```sh
export PROOFRAIL_SOURCE_REPO=tests/source_repositories/partial-workflow-fix
export PROOFRAIL_OUTPUT_DIR="$(mktemp -d)"

proofrail draft-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" --case-title "Partial workflow fix"

proofrail check-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md"

proofrail verify-change \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-verification.json"

proofrail enforce \
  --result "$PROOFRAIL_OUTPUT_DIR/proofrail-verification.json" --policy .proofrail/policy.yml
```

For a template against your own repository, replace the explicitly marked placeholders `<repo>`, `<base-sha>`, `<head-sha>`, and `<claim-file>`:

```sh
proofrail verify-change \
  --repo <repo> --base <base-sha> --head <head-sha> --claim-file <claim-file>
```

The [quick-start guide](docs/QUICKSTART.md) explains the commands, outputs, and safe boundaries in more detail.

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

Proofrail is **Internal Alpha**. Local build artifacts can be installed for
controlled internal repositories, technically capable design partners, and
read-only CI evaluation. It is not published to a package index, a turnkey
hosted platform, a universal behavioral verifier, or a supported
general-availability product. See [project status](docs/PROJECT_STATUS.md).

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
