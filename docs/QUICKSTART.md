# Proofrail quick start

This guide runs the repository’s current offline interfaces from a clean checkout. Proofrail is source-run in this repository; there is no package-installation step.

## Set up the module path

The repository workflow uses Python 3.11. From the repository root:

```sh
export PYTHONPATH=src
```

## Run the preserved fixtures

```sh
python3 -m proofrail_verifier verify tests/fixtures/001-partial-workflow-fix
python3 -m proofrail_verifier verify tests/fixtures/002-incapable-validation-command
```

Each command emits deterministic JSON. A completed `partially_verified`, `unsupported`, `contradicted`, or `human_review_required` verdict is a result, not a verifier failure.

## Draft, check, and verify a real included range

The repository includes a small committed source repository for the partial-workflow-fix example:

```sh
export PROOFRAIL_SOURCE_REPO=tests/source_repositories/partial-workflow-fix
export PROOFRAIL_OUTPUT_DIR="$(mktemp -d)"

python3 -m proofrail_verifier draft-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" --case-title "Partial workflow fix"

python3 -m proofrail_verifier check-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md"

python3 -m proofrail_verifier prepare-case \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" \
  --output-dir "$PROOFRAIL_OUTPUT_DIR/proofrail-case"

python3 -m proofrail_verifier verify-change \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-verification.json"

python3 -m proofrail_verifier enforce \
  --result "$PROOFRAIL_OUTPUT_DIR/proofrail-verification.json" --policy .proofrail/policy.yml
```

`draft-claims` and `check-claims` establish path coverage. `verify-change` prepares and evaluates a self-contained case from the exact committed range. `enforce` evaluates the result against a separate acceptance policy.

## Use the local GitHub Action

Add this step to a workflow in a checkout that includes this repository-local action:

```yaml
- uses: ./.github/actions/proofrail-verify
  id: proofrail
  with:
    case-directory: tests/fixtures/001-partial-workflow-fix
    format: json
```

The action writes a JSON result, appends Markdown to the job summary, and exposes `overall-verdict` and `result-json-path`.

## Template for another repository

The following is a template. Replace every `<placeholder>` with an exact local value and provide a strict claim file:

```sh
python3 -m proofrail_verifier verify-change \
  --repo <repo> --base <base-sha> --head <head-sha> --claim-file <claim-file>
```

Proofrail does not authenticate external provenance or prove runtime behavior from a path diff. Review [PROJECT_STATUS.md](PROJECT_STATUS.md) before evaluating it outside a controlled pilot.
