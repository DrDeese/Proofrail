# Proofrail

Proofrail is an acceptance and evidence layer for AI-generated software changes.

The current prototype runs locally against supported deterministic case directories. It loads the real case data, repository schema, and offline artifacts; evaluates atomic claims with the existing evidence-capability model; and emits stable JSON or Markdown without executing recorded commands or contacting external services.

## Run the verifier

Use the source package directly from the repository:

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier verify tests/fixtures/001-partial-workflow-fix
python3 -m proofrail_verifier verify tests/fixtures/002-incapable-validation-command
```

JSON is the default. Select a format or write the complete result atomically to a file:

```sh
python3 -m proofrail_verifier verify tests/fixtures/001-partial-workflow-fix --format json
python3 -m proofrail_verifier verify tests/fixtures/002-incapable-validation-command --format markdown
python3 -m proofrail_verifier verify tests/fixtures/001-partial-workflow-fix --format json --output result.json
```

JSON output is deterministic and machine-readable:

```json
{"case_id":"001-partial-workflow-fix","claims":[{"claim_id":"obsolete-lockfile-deleted","status":"verified"}],"overall_verdict":"partially_verified"}
```

The complete result includes findings, evidence references, provenance limitations, and source hashes. Markdown presents the same result as a report:

```markdown
# Proofrail case: 002-incapable-validation-command

**Overall verdict:** `partially_verified`

## Claim: page-renders-expected-text

- Status: `unsupported`
```

## GitHub Actions

The local composite action runs the same offline verifier, writes deterministic JSON under `.proofrail/results/`, appends the Markdown report to the job summary, and exposes the overall verdict and JSON path:

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    case-directory: tests/fixtures/001-partial-workflow-fix
    format: json
```

Outputs are available as `steps.proofrail.outputs.overall-verdict` and `steps.proofrail.outputs.result-json-path`. A completed `verified`, `partially_verified`, `unsupported`, `contradicted`, or `human_review_required` result succeeds; usage, case/schema, verification, and output failures return nonzero status.

## Proof boundary

This is an offline deterministic prototype. It proves only what the supported case artifacts and structured evidence can establish; a recorded successful command is not treated as proof of the outcome it claimed to test.

The CLI does not run recorded commands, contact a deployment or GitHub, render a browser DOM, authenticate external provenance, accept arbitrary case schemas, provide a web interface, or merge changes.

## Prepare a case from local Git

`prepare-case` converts an explicit completion-claim file and two local commit refs into a self-contained case directory. It reads committed trees with Git plumbing, never reads working-tree files as evidence, and does not execute repository hooks, scripts, or claim text.

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier prepare-case \
  --repo tests/source_repositories/partial-workflow-fix \
  --base HEAD^ \
  --head HEAD \
  --claim-file tests/case_preparation/claims/partial-workflow-fix.md \
  --output-dir /tmp/generated-case
```

The claim file is deliberately strict:

```markdown
# Completion claim

The requested local change is complete.

## Atomic claims

- id: example-file-deleted
  statement: example.txt was deleted.
  expected-path: example.txt
  expected-change: deleted
```

Supported structured changes are `added`, `modified`, `deleted`, `present`, and `absent`. A statement can be marked `verified` only when it exactly states its structured path fact, such as `example.txt was deleted.`; broader human wording is preserved but remains `unsupported` when Git proves only the path predicate. Git may still contradict broader wording when a necessary expected path change is absent.

The generated directory contains `case.json`, committed base/head artifacts for claim-relevant paths, changed-file and commit metadata, the exact binary-capable Git patch, the verbatim claim source, and an exact schema snapshot. Preparation refuses existing output directories and output paths inside the source repository, builds in a sibling temporary directory, and publishes only a complete case. Commit identities are recorded but not externally authenticated, and the command does not infer test, deployment, workflow-run, browser, merge, or other external outcomes.

## Start here

1. Read `PRODUCT.md`.
2. Read `ACCEPTANCE_MODEL.md`.
3. Read `AGENTS.md`.
4. Review the founder evidence under `docs/founder-evidence/`.
