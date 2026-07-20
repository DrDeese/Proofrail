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

The same action can prepare and verify an exact committed Git range without an intermediate case directory:

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    repo: .
    base: ${{ github.event.pull_request.base.sha }}
    head: ${{ github.event.pull_request.head.sha }}
    claim-file: .proofrail/claim.md
    check-claims: true
    format: json
```

The two modes are mutually exclusive. Prepared-case mode requires only `case-directory`; Git-change mode requires all four of `repo`, `base`, `head`, and `claim-file`. Every supplied path must stay inside `GITHUB_WORKSPACE`, and the action rejects missing, partial, or mixed mode inputs before verification.

When `check-claims` is `true`, Git-change mode first checks that the claim file covers the exact range once per changed path. It exposes `claims-synchronized` and `claim-check-json-path`; synchronized claims proceed to verification, while completed drift writes its JSON and Markdown reports, exits `1`, and does not run verification or policy enforcement. The default is `false`, and prepared-case mode rejects `true` because it has no Git range.

Verification outputs remain available as `steps.proofrail.outputs.overall-verdict` and `steps.proofrail.outputs.result-json-path`. A completed `verified`, `partially_verified`, `unsupported`, `contradicted`, or `human_review_required` result succeeds; usage, case/schema, verification, and output failures return nonzero status.

## Enforce an acceptance policy

Evidence verification and team acceptance are separate operations. `enforce` evaluates a completed Proofrail JSON result against a bounded, non-executable YAML policy:

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier enforce \
  --result proofrail-result.json \
  --policy .proofrail/policy.yml
```

The policy must use version `1`, list default allowed claim statuses and overall verdicts, and may override an exact claim ID. Unknown keys, empty lists, aliases, tags, interpolation, includes, scripts, expressions, globs, and regexes are unsupported. A policy rejection exits `1`; usage, invalid input, evaluation, and output failures exit `2`, `3`, `4`, and `5` respectively.

Policy enforcement can follow `verify-change` directly through the same evaluator:

```sh
python3 -m proofrail_verifier verify-change \
  --repo . \
  --base "$BASE_SHA" \
  --head "$HEAD_SHA" \
  --claim-file .proofrail/claim.md \
  --policy .proofrail/policy.yml
```

With `--policy`, the selected format and optional new `--output` path apply to the policy decision. Without `--policy`, all existing `verify-change` behavior is unchanged.

The GitHub Action accepts the same optional policy and exposes both verification and policy outputs:

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    repo: .
    base: ${{ github.event.pull_request.base.sha }}
    head: ${{ github.event.pull_request.head.sha }}
    claim-file: .proofrail/claim.md
    policy-file: .proofrail/policy.yml
```

The outputs are `overall-verdict`, `result-json-path`, `policy-accepted`, and `policy-result-json-path`. Without `policy-file`, completed verifier verdicts still succeed. With a policy, both JSON reports are written and both Markdown reports are appended to the job summary; acceptance exits `0`, rejection exits `1`, and verifier or policy process failures retain their distinct error codes.

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

## Draft path claims from local Git

`draft-claims` creates the strict completion-claim file for every path changed in an exact committed range. It emits only canonical `added`, `modified`, and `deleted` path statements; a rename is deliberately represented as one deletion and one addition. It does not infer intent, behavior, correctness, test results, deployment state, workflow execution, or merge status.

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier draft-claims \
  --repo . \
  --base main \
  --head HEAD \
  --output /tmp/completion-claim.md \
  --case-title "Step 12 artifact changes"
```

The output must be a new file outside the source repository. Claims are ordered by the UTF-8 bytes of their repository-relative paths. IDs use a readable lowercase path-and-change slug; normalization collisions and long slugs receive a bounded deterministic SHA-256 suffix. The command reads committed trees only, disables Git lazy fetching and replacement objects, ignores dirty working-tree content, disables rename detection, refuses unsafe path or title data, and publishes the complete file atomically without overwriting an existing path.

The generated file works directly as `--claim-file` input to `prepare-case`, `verify-change`, and the Git-change mode of the local GitHub Action. Successful drafting exits `0`; command-line usage exits `2`; invalid repositories, refs, ranges, source structures, paths, or titles exit `3`; claim-generation failures exit `4`; and output publication failures exit `5`.

## Check claim freshness and path coverage

`check-claims` compares only each claim's structured `(expected-path, expected-change)` predicate with the exact committed paths in a Git range. IDs and statement wording do not affect matching, and this command does not verify evidence or evaluate acceptance policy.

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier check-claims \
  --repo . \
  --base main \
  --head HEAD \
  --claim-file .proofrail/claim.md
```

Every added, modified, or deleted path must have exactly one matching predicate. Renames are deliberately checked as deletion of the old path plus addition of the new path. A changed path without coverage is `missing`; a predicate for an unchanged path is `stale`; a wrong change type is a `conflict`; and repeated path/change predicates are `duplicates`. `present` and `absent` predicates are never inferred from a diff.

JSON is the default and deterministic Markdown is available with `--format markdown`. `--output` atomically writes a new report outside the source repository without overwriting. Synchronized coverage exits `0`; completed drift exits `1`; usage, invalid input, comparison, and output-write failures exit `2`, `3`, `4`, and `5` respectively. The command resolves exact commits, reads committed trees only, ignores working-tree changes, disables rename detection, lazy fetching, and replacement objects, and never executes claim text or repository code.

## Verify a local Git change end to end

`verify-change` composes the same case preparation and verifier in one offline command. The generated case lives in a secure temporary directory and is removed after verification unless `--keep-case` names a new destination outside the source repository.

```sh
export PYTHONPATH=src
python3 -m proofrail_verifier verify-change \
  --repo tests/source_repositories/partial-workflow-fix \
  --base HEAD^ \
  --head HEAD \
  --claim-file tests/case_preparation/claims/partial-workflow-fix.md
```

JSON is the default; `--format markdown` renders the same result as Markdown. `--output result.json` atomically writes the rendered result instead of stdout, and `--keep-case generated-case` atomically preserves a self-contained case that can later be passed to `proofrail_verifier verify`. Both destinations must be new paths outside the source repository.

The command exits `0` whenever preparation and verification complete, including contradicted, unsupported, or partially verified verdicts. Invalid repository, ref, claim, or generated-schema input exits `3`; preparation or verification failure exits `4`; destination publication failure exits `5`; command-line usage errors exit `2`.

## Start here

1. Read `PRODUCT.md`.
2. Read `ACCEPTANCE_MODEL.md`.
3. Read `AGENTS.md`.
4. Review the founder evidence under `docs/founder-evidence/`.
