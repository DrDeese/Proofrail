#!/usr/bin/env bash
set -euo pipefail

fixture_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -m json.tool "$fixture_dir/case.json" >/dev/null

if grep -F "Dashboard ready" "$fixture_dir/artifacts/index.html"; then
  printf 'fixture validation failed: static HTML unexpectedly contains rendered text\n' >&2
  exit 1
fi

grep -F "Dashboard ready" "$fixture_dir/artifacts/app.js"
printf 'fixture 002 validation passed without executing the supplied command\n'
