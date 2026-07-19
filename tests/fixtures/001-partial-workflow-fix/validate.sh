#!/usr/bin/env bash
set -euo pipefail

fixture_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/proofrail-fixture-001.XXXXXX")"

cleanup() {
  rm -rf -- "$temporary_root"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'fixture validation failed: %s\n' "$1" >&2
  exit 1
}

path_count() {
  local lockfile_name="$1"
  local workflow_path="$2"
  awk -v expected="$lockfile_name" '
    /^[[:space:]]*-[[:space:]]+/ {
      value = $0
      sub(/^[[:space:]]*-[[:space:]]+/, "", value)
      sub(/[[:space:]]*$/, "", value)
      if (value == expected) count++
    }
    END { print count + 0 }
  ' "$workflow_path"
}

initialize_repository() {
  local repository_path="$1"
  mkdir -p "$repository_path"
  cp -R "$fixture_dir/initial/." "$repository_path/"
  git -C "$repository_path" init -q -b main
  git -C "$repository_path" config user.name "Proofrail Fixture"
  git -C "$repository_path" config user.email "fixture@proofrail.invalid"
  git -C "$repository_path" add --all
  GIT_AUTHOR_DATE="2025-01-01T00:00:00Z" \
    GIT_COMMITTER_DATE="2025-01-01T00:00:00Z" \
    git -C "$repository_path" commit -q -m "fixture: initial workflow state"
}

initial_repository="$temporary_root/initial-repository"
initialize_repository "$initial_repository"

expected_initial_files=$'.github/workflows/ci.yml\nbun.lock\nbun.lockb'
initial_files="$(git -C "$initial_repository" ls-files)"
[[ "$initial_files" == "$expected_initial_files" ]] || fail "initial tracked file set differs"
[[ -z "$(git -C "$initial_repository" status --porcelain=v1)" ]] || fail "initial repository is not clean"

intended_repository="$temporary_root/intended-repository"
initialize_repository "$intended_repository"
git -C "$intended_repository" apply --check --unidiff-zero "$fixture_dir/intended.patch"
git -C "$intended_repository" apply --unidiff-zero "$fixture_dir/intended.patch"

[[ ! -e "$intended_repository/bun.lockb" ]] || fail "intended patch did not delete bun.lockb"
intended_changes="$(git -C "$intended_repository" diff --name-status)"
expected_intended_changes=$'M\t.github/workflows/ci.yml\nD\tbun.lockb'
[[ "$intended_changes" == "$expected_intended_changes" ]] || fail "intended patch changed an unexpected path"
[[ "$(path_count bun.lock "$intended_repository/.github/workflows/ci.yml")" == "2" ]] || fail "intended patch did not add both bun.lock path entries"
[[ "$(path_count bun.lockb "$intended_repository/.github/workflows/ci.yml")" == "0" ]] || fail "intended patch retained a bun.lockb path entry"

actual_repository="$temporary_root/actual-repository"
initialize_repository "$actual_repository"
git -C "$actual_repository" apply --check "$fixture_dir/actual.patch"
git -C "$actual_repository" apply "$fixture_dir/actual.patch"

actual_uncommitted_changes="$(git -C "$actual_repository" diff --name-status)"
[[ "$actual_uncommitted_changes" == $'D\tbun.lockb' ]] || fail "actual patch changed more than bun.lockb"
git -C "$actual_repository" diff --exit-code -- .github/workflows/ci.yml

git -C "$actual_repository" add --all
GIT_AUTHOR_DATE="2025-01-01T00:01:00Z" \
  GIT_COMMITTER_DATE="2025-01-01T00:01:00Z" \
  git -C "$actual_repository" commit -q -m "fix: remove obsolete lockfile"

final_changes="$(git -C "$actual_repository" diff-tree --no-commit-id --name-status -r HEAD)"
[[ "$final_changes" == $'D\tbun.lockb' ]] || fail "final commit did not change exactly bun.lockb"
git -C "$actual_repository" diff --exit-code HEAD^ HEAD -- .github/workflows/ci.yml

if git -C "$actual_repository" cat-file -e HEAD:bun.lockb; then
  fail "bun.lockb unexpectedly exists in the final commit"
fi

git -C "$actual_repository" cat-file -e HEAD:bun.lock
git -C "$actual_repository" cat-file -e HEAD:.github/workflows/ci.yml
final_workflow="$actual_repository/.github/workflows/ci.yml"
[[ "$(path_count bun.lockb "$final_workflow")" == "2" ]] || fail "final workflow does not reference bun.lockb exactly twice"
[[ "$(path_count bun.lock "$final_workflow")" == "0" ]] || fail "final workflow unexpectedly references bun.lock"
[[ -z "$(git -C "$actual_repository" status --porcelain=v1)" ]] || fail "final repository is not clean"

printf 'fixture 001 validation passed\n'
