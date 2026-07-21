# Releasing Proofrail internally

Proofrail is currently an **Internal Alpha**. This guide covers a local,
offline distribution artifact only; it does not authorize a public release,
package-index upload, Git tag, GitHub Release, or network access.

## Version source

`proofrail_verifier.__version__` is the package version source. The current
Internal Alpha version is `0.1.0a1`.

## Build locally

Use the repository's existing Python environment and build backend. Do not
install dependencies or allow a build tool to fetch from a package index.
Setuptools 58.0.4 creates the raw PEP 517 wheel and source distribution in a
disposable source copy. The release helper leaves the reproducible wheel bytes
unchanged and deterministically normalizes the raw sdist into the final release
sdist.

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

## Scope and rollback

An Internal Alpha artifact is suitable only for controlled local evaluation.
If an unpublished artifact is unsuitable, discard that local artifact and
rebuild from a corrected committed range. Do not represent removal of a local
file as a public-package withdrawal. Future tags, releases, package-index
publication, compatibility promises, and support commitments require separate
human authorization.
