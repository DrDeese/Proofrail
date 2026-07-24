# Changelog

## 0.1.0a2 — Public alpha

- Made human-readable verification output adapt to terminal width without
  truncating claim findings.
- Corrected the PyPI package summary to describe Proofrail's acceptance
  boundary directly.

## 0.1.0a1 — Public alpha

- Added the `proofrail` distribution for installation from PyPI.
- Added the `proofrail` command for the existing deterministic interfaces.
- Added `proofrail verify --demo` as the packaged first-run example.
- Changed `proofrail verify` to emit human-readable text by default; machine
  consumers must pass `--format json` explicitly.
- Packaged the canonical case schema and public operating documentation.

This public alpha does not establish a stable compatibility commitment or
proof of external runtime outcomes.
