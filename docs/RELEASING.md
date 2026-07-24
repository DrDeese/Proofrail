# Releasing Proofrail

Proofrail is a **Public alpha** distributed through PyPI. Publication uses the
repository's trusted-publishing workflow and the protected GitHub environment
named `pypi`.

## Version source

`proofrail_verifier.__version__` is the package version source. The current
public-alpha version is `0.1.0a2`. A release tag must use the same version with
a leading `v`, for example `v0.1.0a2`.

## Build locally

Use the pinned build backend: setuptools 58.0.4 and wheel 0.37.0. The release
helper invokes that backend from the current Python environment in a disposable
source copy. It leaves the wheel bytes unchanged and deterministically
normalizes the raw sdist into the final release sdist.

```sh
python3 scripts/build_release_artifacts.py --repository . --output-dir dist
```

The helper normalizes archive order, timestamps, ownership, names, modes, and
gzip metadata. Do not describe the unprocessed setuptools 58.0.4 sdist as
reproducible; only the helper's final sdist is the release artifact.

## Verify the artifact

Create a clean virtual environment, install only the local wheel with
`--no-index --no-deps`, and invoke `proofrail` without `PYTHONPATH`. Run the
fixture and Git-range commands documented in [QUICKSTART.md](QUICKSTART.md).
Record SHA-256 hashes for the wheel and source distribution, and rebuild with
the same `SOURCE_DATE_EPOCH` to compare byte-for-byte output.

## Publish through trusted publishing

The `publish-pypi.yml` workflow runs on `v*` tags and supports manual reruns
from a tag ref. Its build job tests and validates the artifacts, checks that
both artifact versions match the tag, and passes them to a separate
OIDC-authorized publish job. The publish job uses the `pypi` environment and
does not use an API token.

Creating or pushing a release tag remains an explicit human-authorized action.
Because PyPI release files are immutable, correct a failed pre-publication
build before tagging rather than relying on replacement uploads.
