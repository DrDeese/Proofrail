# Contributing to Proofrail

Proofrail is a public alpha. Contributions are welcome, but behavior and interfaces may change while the project is being validated. Keep proposals focused on the initial GitHub pull-request use case, and read `PRODUCT.md` and `ACCEPTANCE_MODEL.md` before changing product behavior.

## Report an issue

Open a GitHub issue with:

- a concise description of the problem;
- steps or a minimal fixture that reproduces it;
- the expected and actual result;
- the Proofrail version or commit SHA; and
- relevant output, with secrets and private repository details removed.

Preserve real failures when possible: a small deterministic regression fixture is more useful than a generalized description. Do not report a passing command as proof unless it directly exercises the behavior in question.

## Propose a change

For substantial behavior, schema, workflow, or product-scope changes, open an issue before implementation so the intended boundary can be agreed upon. Small documentation fixes and narrowly scoped bug fixes may go directly to a pull request.

Keep changes focused. Do not add unrelated agent-platform features, automatic merging, or claims that exceed the available evidence.

## Run the tests

Proofrail requires Python 3.9 or newer. From the repository root, run every existing test module with:

```sh
for test_file in $(find tests -type f -name 'test*.py' | sort); do
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 "$test_file" || exit 1
done
```

Also run `git diff --check` and inspect the complete diff. Add focused positive and negative tests for changed behavior.

## Submit a pull request

Create a branch from the current `main`, make the smallest coherent change, and submit a pull request that explains:

- what changed and why;
- the exact tests and checks run;
- which claims those checks directly support; and
- any unsupported outcomes, provenance limits, or human-review requirements.

Keep unrelated changes out of the pull request. A green test run is necessary evidence, but it is not by itself proof that every completion claim is supported.
