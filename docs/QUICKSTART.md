# Proofrail quick start

This guide runs Proofrail’s offline interfaces from either a local wheel or a
source checkout. Proofrail is not published to a package index.

## Install a local wheel

Build with the deterministic release helper, which invokes the repository's
existing local PEP 517 backend in a disposable copy and normalizes the final
source distribution. Then install only the local wheel into a clean virtual
environment. This does not fetch or install dependencies.

```sh
python3 scripts/build_release_artifacts.py --repository . --output-dir dist
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --no-index --no-deps dist/proofrail_verifier-0.1.0a1-py3-none-any.whl
```

The remaining commands use `proofrail` and require no `PYTHONPATH` setting.

## Source-checkout development

For development directly from the checkout, use the module entry point:

```sh
export PYTHONPATH=src
```

## Run the preserved fixtures

```sh
proofrail verify tests/fixtures/001-partial-workflow-fix
proofrail verify tests/fixtures/002-incapable-validation-command
```

Each command emits deterministic JSON. A completed `partially_verified`, `unsupported`, `contradicted`, or `human_review_required` verdict is a result, not a verifier failure.

## Draft, check, and verify a real included range

The repository includes a small committed source repository for the partial-workflow-fix example:

```sh
export PROOFRAIL_SOURCE_REPO=tests/source_repositories/partial-workflow-fix
export PROOFRAIL_OUTPUT_DIR="$(mktemp -d)"

proofrail draft-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" --case-title "Partial workflow fix"

proofrail check-claims \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md"

proofrail prepare-case \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" \
  --output-dir "$PROOFRAIL_OUTPUT_DIR/proofrail-case"

proofrail verify-change \
  --repo "$PROOFRAIL_SOURCE_REPO" --base HEAD^ --head HEAD \
  --claim-file "$PROOFRAIL_OUTPUT_DIR/proofrail-claims.md" \
  --output "$PROOFRAIL_OUTPUT_DIR/proofrail-verification.json"

proofrail enforce \
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
proofrail verify-change \
  --repo <repo> --base <base-sha> --head <head-sha> --claim-file <claim-file>
```

Proofrail does not authenticate external provenance or prove runtime behavior from a path diff. Review [PROJECT_STATUS.md](PROJECT_STATUS.md) before evaluating it outside a controlled pilot. For source-run development, replace `proofrail` with `python3 -m proofrail_verifier` after setting `PYTHONPATH=src`.
