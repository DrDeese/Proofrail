from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_REPOSITORY = (
    REPOSITORY_ROOT / "tests" / "source_repositories" / "partial-workflow-fix"
)
REFERENCE_CLAIM = (
    REPOSITORY_ROOT
    / "tests"
    / "case_preparation"
    / "claims"
    / "partial-workflow-fix.md"
)
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier import evaluate_case, load_case_directory
from proofrail_verifier.preparation import OutputWriteFailure, prepare_case
from proofrail_verifier.schema_validation import validate


class PrepareCaseTests(unittest.TestCase):
    run_number = 0

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return completed.stdout.strip()

    @classmethod
    def _new_repository(
        cls,
        root: Path,
        base_files: dict[str, bytes | str],
        head_files: dict[str, bytes | str],
    ) -> Path:
        cls.run_number += 1
        repository = root / f"repository-{cls.run_number}"
        template = root / f"empty-template-{cls.run_number}"
        template.mkdir()
        subprocess.run(
            [
                "git",
                "init",
                "--initial-branch=main",
                f"--template={template}",
                str(repository),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        cls._write_tree(repository, base_files)
        cls._commit(repository, "base", "2024-01-01T00:00:00+00:00")
        for relative in set(base_files) - set(head_files):
            (repository / relative).unlink()
        cls._write_tree(repository, head_files)
        cls._commit(repository, "head", "2024-01-01T00:01:00+00:00")
        return repository

    @staticmethod
    def _write_tree(root: Path, files: dict[str, bytes | str]) -> None:
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")

    @classmethod
    def _commit(cls, repository: Path, message: str, date: str) -> None:
        cls._git(repository, "add", "--all")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_DATE": date,
            }
        )
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Proofrail Test",
                "-c",
                "user.email=test@proofrail.local",
                "commit",
                "--no-gpg-sign",
                "-m",
                message,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)

    @staticmethod
    def _claim_file(
        root: Path,
        claims: list[tuple[str, str, str, str]],
        overall: str = "The requested local change is complete.",
    ) -> Path:
        lines = ["# Completion claim", "", overall, "", "## Atomic claims", ""]
        for claim_id, statement, path, change in claims:
            lines.extend(
                [
                    f"- id: {claim_id}",
                    f"  statement: {statement}",
                    f"  expected-path: {path}",
                    f"  expected-change: {change}",
                    "",
                ]
            )
        claim_file = root / f"claim-{len(list(root.glob('claim-*')))}.md"
        claim_file.write_text("\n".join(lines), encoding="utf-8")
        return claim_file

    @staticmethod
    def _run_cli(
        repository: Path,
        claim_file: Path,
        output: Path,
        base: str = "HEAD^",
        head: str = "HEAD",
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "proofrail_verifier",
                "prepare-case",
                "--repo",
                str(repository),
                "--base",
                base,
                "--head",
                head,
                "--claim-file",
                str(claim_file),
                "--output-dir",
                str(output),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

    @staticmethod
    def _tree(directory: Path) -> dict[str, bytes]:
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    @classmethod
    def _digest(cls, directory: Path) -> str:
        digest = hashlib.sha256()
        for path, content in cls._tree(directory).items():
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _statuses(case_directory: Path) -> dict[str, str]:
        result = evaluate_case(load_case_directory(case_directory))
        return {item["claim_id"]: item["status"] for item in result["claims"]}

    def test_reference_repository_generates_valid_consumable_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-reference-") as temporary:
            root = Path(temporary)
            output = root / "generated-case"
            source_before = self._digest(REFERENCE_REPOSITORY)
            completed = self._run_cli(REFERENCE_REPOSITORY, REFERENCE_CLAIM, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertIn("atomic claims: 2", completed.stdout)
            self.assertIn("changed paths: 1", completed.stdout)
            expected_tree = {
                "artifacts/base/.github/workflows/ci.yml",
                "artifacts/base/bun.lockb",
                "artifacts/head/.github/workflows/ci.yml",
                "case.json",
                "git/changed-files.json",
                "git/commit-metadata.json",
                "git/diff.patch",
                "schema/case.schema.json",
                "source/completion-claim.md",
            }
            self.assertEqual(set(self._tree(output)), expected_tree)

            case = json.loads((output / "case.json").read_text(encoding="utf-8"))
            schema = json.loads(
                (REPOSITORY_ROOT / "schemas" / "case.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            validate(case, schema, schema)
            bundle = load_case_directory(output)
            result = evaluate_case(bundle)
            self.assertEqual(
                {item["claim_id"]: item["status"] for item in result["claims"]},
                {
                    "obsolete-lockfile-deleted": "verified",
                    "workflow-triggers-updated": "contradicted",
                },
            )
            self.assertEqual(result["overall_verdict"], "partially_verified")
            base_sha = self._git(REFERENCE_REPOSITORY, "rev-parse", "HEAD^")
            head_sha = self._git(REFERENCE_REPOSITORY, "rev-parse", "HEAD")
            changed = json.loads(
                (output / "git" / "changed-files.json").read_text(encoding="utf-8")
            )
            self.assertEqual(changed["base_sha"], base_sha)
            self.assertEqual(changed["head_sha"], head_sha)
            self.assertEqual(changed["paths"], [{"path": "bun.lockb", "status": "deleted"}])
            metadata = json.loads(
                (output / "git" / "commit-metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["base"]["sha"], base_sha)
            self.assertEqual(metadata["head"]["sha"], head_sha)
            self.assertEqual(metadata["base"]["author_name"], "Proofrail Fixture")
            self.assertEqual(metadata["head"]["authored_at"], "2024-01-01T00:01:00Z")
            self.assertEqual(
                (output / "artifacts" / "base" / "bun.lockb").read_text(encoding="utf-8"),
                "obsolete lockfile fixture\n",
            )
            self.assertFalse((output / "artifacts" / "head" / "bun.lockb").exists())
            self.assertEqual(
                (output / "source" / "completion-claim.md").read_bytes(),
                REFERENCE_CLAIM.read_bytes(),
            )
            self.assertEqual(
                (output / "schema" / "case.schema.json").read_bytes(),
                (REPOSITORY_ROOT / "schemas" / "case.schema.json").read_bytes(),
            )
            self.assertEqual(self._digest(REFERENCE_REPOSITORY), source_before)

    def test_output_is_byte_identical_and_contains_no_checkout_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-deterministic-") as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            self.assertEqual(
                self._run_cli(REFERENCE_REPOSITORY, REFERENCE_CLAIM, first).returncode, 0
            )
            self.assertEqual(
                self._run_cli(REFERENCE_REPOSITORY, REFERENCE_CLAIM, second).returncode, 0
            )
            self.assertEqual(self._tree(first), self._tree(second))
            generated = b"".join(
                content
                for path, content in self._tree(first).items()
                if path != "source/completion-claim.md"
            )
            self.assertNotIn(str(REFERENCE_REPOSITORY.resolve()).encode(), generated)
            self.assertNotIn(str(root.resolve()).encode(), generated)

    def test_added_and_modified_head_artifacts_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-head-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root,
                {"modified.txt": "old\n"},
                {"modified.txt": "new\n", "added.txt": "added\n"},
            )
            claim_file = self._claim_file(
                root,
                [
                    ("modified-file", "modified.txt was modified.", "modified.txt", "modified"),
                    ("added-file", "added.txt was added.", "added.txt", "added"),
                ],
            )
            output = root / "case"
            completed = self._run_cli(repository, claim_file, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                self._statuses(output),
                {"modified-file": "verified", "added-file": "verified"},
            )
            self.assertEqual(
                (output / "artifacts" / "head" / "modified.txt").read_text(), "new\n"
            )
            self.assertEqual(
                (output / "artifacts" / "head" / "added.txt").read_text(), "added\n"
            )

    def test_present_and_absent_predicates_use_committed_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-state-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root,
                {"present.txt": "same\n", "changed.txt": "old\n"},
                {"present.txt": "same\n", "changed.txt": "new\n"},
            )
            claim_file = self._claim_file(
                root,
                [
                    ("present-file", "present.txt is present.", "present.txt", "present"),
                    ("absent-file", "missing.txt is absent.", "missing.txt", "absent"),
                ],
            )
            output = root / "case"
            completed = self._run_cli(repository, claim_file, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                self._statuses(output),
                {"present-file": "verified", "absent-file": "verified"},
            )

    def test_working_tree_is_ignored_and_never_mutated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-dirty-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root, {"item.txt": "old\n"}, {"item.txt": "committed\n"}
            )
            claim_file = self._claim_file(
                root, [("item-modified", "item.txt was modified.", "item.txt", "modified")]
            )
            clean_output = root / "clean-case"
            self.assertEqual(self._run_cli(repository, claim_file, clean_output).returncode, 0)
            (repository / "item.txt").write_text("working tree only\n", encoding="utf-8")
            (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            status_before = self._git(repository, "status", "--porcelain=v1", "--untracked-files=all")
            dirty_output = root / "dirty-case"
            completed = self._run_cli(repository, claim_file, dirty_output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(self._tree(clean_output), self._tree(dirty_output))
            self.assertEqual(
                self._git(repository, "status", "--porcelain=v1", "--untracked-files=all"),
                status_before,
            )
            self.assertEqual(
                (dirty_output / "artifacts" / "head" / "item.txt").read_text(),
                "committed\n",
            )

    def test_spaces_and_shell_text_are_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-spaces-") as temporary:
            root = Path(temporary)
            sentinel = root / "claim-executed"
            repository = self._new_repository(
                root, {"other.txt": "old\n"}, {"other.txt": "new\n", "dir/file name.txt": "safe\n"}
            )
            statement = f"$(touch {sentinel})"
            claim_file = self._claim_file(
                root,
                [("space-path", statement, "dir/file name.txt", "added")],
                overall=f"Do not run: touch {sentinel}",
            )
            output = root / "case"
            completed = self._run_cli(repository, claim_file, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual(
                (output / "artifacts" / "head" / "dir" / "file name.txt").read_text(),
                "safe\n",
            )
            self.assertEqual(self._statuses(output)["space-path"], "unsupported")

    def test_untouched_and_external_wording_are_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-boundary-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root,
                {"untouched.txt": "same\n", "deploy.txt": "old\n"},
                {"untouched.txt": "same\n", "deploy.txt": "new\n"},
            )
            claim_file = self._claim_file(
                root,
                [
                    ("untouched-modified", "untouched.txt was modified.", "untouched.txt", "modified"),
                    ("deployment-succeeded", "The production deployment succeeded.", "deploy.txt", "modified"),
                ],
            )
            output = root / "case"
            completed = self._run_cli(repository, claim_file, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                self._statuses(output),
                {"untouched-modified": "contradicted", "deployment-succeeded": "unsupported"},
            )

    def test_declared_statuses_are_not_preparation_evaluation_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-status-input-") as temporary:
            output = Path(temporary) / "case"
            completed = self._run_cli(REFERENCE_REPOSITORY, REFERENCE_CLAIM, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            case_path = output / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            for claim in case["claims"]:
                claim["status"] = "human_review_required"
            case["verdict"]["status"] = "unsupported"
            case_path.write_text(
                json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                self._statuses(output),
                {
                    "obsolete-lockfile-deleted": "verified",
                    "workflow-triggers-updated": "contradicted",
                },
            )

    def test_missing_prepare_arguments_are_usage_error_two(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-m", "proofrail_verifier", "prepare-case"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("required", completed.stderr)

    def test_invalid_repositories_refs_and_ranges_fail_with_three(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-input-") as temporary:
            root = Path(temporary)
            missing = root / "missing"
            nongit = root / "nongit"
            nongit.mkdir()
            output = root / "output"
            for label, repository, base, head in (
                ("missing repository", missing, "HEAD^", "HEAD"),
                ("non-Git directory", nongit, "HEAD^", "HEAD"),
                ("missing base", REFERENCE_REPOSITORY, "missing-base", "HEAD"),
                ("missing head", REFERENCE_REPOSITORY, "HEAD^", "missing-head"),
                ("identical refs", REFERENCE_REPOSITORY, "HEAD", "HEAD"),
                ("reversed range", REFERENCE_REPOSITORY, "HEAD", "HEAD^"),
            ):
                with self.subTest(label=label):
                    completed = self._run_cli(repository, REFERENCE_CLAIM, output, base, head)
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn("invalid preparation input", completed.stderr)
                    self.assertFalse(output.exists())

    def test_malformed_claim_variants_fail_with_three(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-claim-") as temporary:
            root = Path(temporary)
            variants = {
                "malformed": "# Wrong heading\n",
                "duplicate ids": """# Completion claim

Done.

## Atomic claims

- id: same
  statement: a.txt was added.
  expected-path: a.txt
  expected-change: added
- id: same
  statement: b.txt was added.
  expected-path: b.txt
  expected-change: added
""",
                "unsupported change": """# Completion claim

Done.

## Atomic claims

- id: bad-change
  statement: a.txt was renamed.
  expected-path: a.txt
  expected-change: renamed
""",
                "absolute path": """# Completion claim

Done.

## Atomic claims

- id: absolute
  statement: /tmp/a was added.
  expected-path: /tmp/a
  expected-change: added
""",
                "traversal": """# Completion claim

Done.

## Atomic claims

- id: traversal
  statement: ../outside was added.
  expected-path: ../outside
  expected-change: added
""",
            }
            for label, content in variants.items():
                with self.subTest(label=label):
                    claim_file = root / f"{label.replace(' ', '-')}.md"
                    claim_file.write_text(content, encoding="utf-8")
                    output = root / "output"
                    completed = self._run_cli(REFERENCE_REPOSITORY, claim_file, output)
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertIn("invalid preparation input", completed.stderr)
                    self.assertFalse(output.exists())

    def test_output_guards_fail_with_five(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-output-") as temporary:
            root = Path(temporary)
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "keep.txt").write_text("keep\n", encoding="utf-8")
            inside_source = REFERENCE_REPOSITORY / "generated-case"
            real = root / "real"
            real.mkdir()
            symlink = root / "symlink-output"
            symlink.symlink_to(real, target_is_directory=True)
            for label, output in (
                ("nonempty", nonempty),
                ("inside source", inside_source),
                ("symlink", symlink),
            ):
                with self.subTest(label=label):
                    completed = self._run_cli(REFERENCE_REPOSITORY, REFERENCE_CLAIM, output)
                    self.assertEqual(completed.returncode, 5, completed.stderr)
                    self.assertIn("output write failed", completed.stderr)
            self.assertEqual((nonempty / "keep.txt").read_text(), "keep\n")
            self.assertFalse(inside_source.exists())

    def test_repository_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-repo-link-") as temporary:
            root = Path(temporary)
            link = root / "repository-link"
            link.symlink_to(REFERENCE_REPOSITORY, target_is_directory=True)
            completed = self._run_cli(link, REFERENCE_CLAIM, root / "case")
            self.assertEqual(completed.returncode, 3, completed.stderr)
            self.assertIn("symbolic link", completed.stderr)

    def test_failed_git_command_is_controlled_preparation_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-git-failure-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root, {"item.txt": "old\n"}, {"item.txt": "new\n"}
            )
            claim_file = self._claim_file(
                root, [("item-modified", "item.txt was modified.", "item.txt", "modified")]
            )
            object_id = self._git(repository, "rev-parse", "HEAD:item.txt")
            object_path = repository / ".git" / "objects" / object_id[:2] / object_id[2:]
            object_path.unlink()
            output = root / "case"
            completed = self._run_cli(repository, claim_file, output)
            self.assertEqual(completed.returncode, 4, completed.stderr)
            self.assertIn("preparation failed", completed.stderr)
            self.assertIn("Git diff failed", completed.stderr)
            self.assertFalse(output.exists())

    def test_partial_staging_directory_is_removed_after_write_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-prepare-cleanup-") as temporary:
            root = Path(temporary)
            output = root / "case"
            original_write = Path.write_bytes
            calls = 0

            def fail_second_write(path: Path, content: bytes) -> int:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("deliberate write failure")
                return original_write(path, content)

            with mock.patch.object(Path, "write_bytes", fail_second_write):
                with self.assertRaises(OutputWriteFailure):
                    prepare_case(
                        REFERENCE_REPOSITORY,
                        "HEAD^",
                        "HEAD",
                        REFERENCE_CLAIM,
                        output,
                    )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".case.*")), [])


if __name__ == "__main__":
    unittest.main()
