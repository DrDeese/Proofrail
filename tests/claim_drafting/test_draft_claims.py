from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from proofrail_verifier.claim_drafting import (
    MAX_CLAIM_ID,
    ClaimGenerationFailure,
    draft_claims,
    render_claims,
)
from proofrail_verifier.claim_file import parse_claim_file
from proofrail_verifier.cli import main
from proofrail_verifier.preparation import prepare_case
from proofrail_verifier.preparation_errors import InvalidPreparationInput


class DraftClaimsTests(unittest.TestCase):
    sequence = 0

    @staticmethod
    def _git(repository: Path, *arguments: str, check: bool = True) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if check and completed.returncode:
            raise AssertionError(completed.stderr)
        return completed.stdout.strip()

    @classmethod
    def _repository(
        cls,
        root: Path,
        base: dict[str, str],
        head: dict[str, str],
        *,
        rename: tuple[str, str] | None = None,
    ) -> Path:
        cls.sequence += 1
        repository = root / f"repository {cls.sequence}"
        template = root / f"template-{cls.sequence}"
        template.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main", f"--template={template}", str(repository)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        cls._write_tree(repository, base)
        cls._commit(repository, "base", "2024-01-01T00:00:00+00:00")
        if rename is None:
            cls._write_tree(repository, head)
        else:
            old, new = rename
            (repository / new).parent.mkdir(parents=True, exist_ok=True)
            os.rename(repository / old, repository / new)
        cls._commit(repository, "head", "2024-01-01T00:01:00+00:00")
        return repository

    @staticmethod
    def _write_tree(repository: Path, files: dict[str, str]) -> None:
        for path in list(repository.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                path.unlink()
        for relative, content in files.items():
            destination = repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

    @classmethod
    def _commit(cls, repository: Path, message: str, date: str) -> None:
        cls._git(repository, "add", "--all")
        environment = os.environ.copy()
        environment.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        subprocess.run(
            [
                "git", "-C", str(repository), "-c", "user.name=Proofrail Test",
                "-c", "user.email=test@proofrail.local", "commit", "--no-gpg-sign",
                "-m", message,
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    @staticmethod
    def _run(*arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["draft-claims", *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_added_modified_deleted_order_and_real_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(
                root,
                {"z-delete.txt": "old", "b-modify.txt": "old"},
                {"a add.txt": "new", "b-modify.txt": "new"},
            )
            output = root / "claims.md"
            result = draft_claims(repository, "HEAD^", "HEAD", output)
            parsed = parse_claim_file(output)
            self.assertEqual(result.claim_count, 3)
            self.assertEqual(
                [(c.expected_path, c.expected_change) for c in parsed.atomic_claims],
                [
                    ("a add.txt", "added"),
                    ("b-modify.txt", "modified"),
                    ("z-delete.txt", "deleted"),
                ],
            )
            self.assertTrue(all(c.statement == f"{c.expected_path} was {c.expected_change}." for c in parsed.atomic_claims))

    def test_rename_is_deleted_plus_added_without_configuration_dependence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(
                root, {"old.txt": "same"}, {"new.txt": "same"}, rename=("old.txt", "new.txt")
            )
            self._git(repository, "config", "diff.renames", "true")
            output = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", output)
            parsed = parse_claim_file(output)
            self.assertEqual(
                {(c.expected_path, c.expected_change) for c in parsed.atomic_claims},
                {("old.txt", "deleted"), ("new.txt", "added")},
            )

    def test_ids_are_deterministic_unique_collision_safe_and_bounded(self) -> None:
        changes = [
            {"path": "A!.txt", "status": "added"},
            {"path": "a?.txt", "status": "added"},
            {"path": "deep/" + "very-long-name-" * 20 + ".txt", "status": "modified"},
        ]
        first = render_claims(changes, "Title")
        second = render_claims(list(reversed(changes)), "Title")
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claims.md"
            path.write_text(first, encoding="utf-8")
            ids = [claim.claim_id for claim in parse_claim_file(path).atomic_claims]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(identifier == identifier.lower() for identifier in ids))
        self.assertTrue(all(len(identifier) <= MAX_CLAIM_ID for identifier in ids))

    def test_collision_handling_fails_closed_if_hashes_collide(self) -> None:
        changes = [
            {"path": "A!.txt", "status": "added"},
            {"path": "a?.txt", "status": "added"},
        ]
        with mock.patch("proofrail_verifier.claim_drafting._digest", return_value="0" * 12):
            with self.assertRaisesRegex(ClaimGenerationFailure, "not unique"):
                render_claims(changes, "Title")

    def test_spaces_unicode_leading_dash_and_shell_metacharacters_are_inert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "must-not-exist"
            paths = {
                "space name.txt": "x",
                "unicodé-猫.txt": "x",
                "-leading.txt": "x",
                f"$(touch {marker.name});`echo nope`:#.txt": "x",
            }
            repository = self._repository(root, {"base.txt": "x"}, paths)
            output = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", output)
            parsed = parse_claim_file(output)
            self.assertEqual({c.expected_path for c in parsed.atomic_claims}, set(paths) | {"base.txt"})
            self.assertFalse(marker.exists())

    def test_byte_identical_across_runs_locations_and_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a.txt": "old"}, {"a.txt": "new", "猫.txt": "x"})
            copy = root / "equivalent checkout"
            shutil.copytree(repository, copy)
            first, second, third = root / "one.md", root / "two.md", root / "three.md"
            draft_claims(repository, "HEAD^", "HEAD", first)
            (repository / "a.txt").write_text("dirty content", encoding="utf-8")
            (repository / "untracked.txt").write_text("dirty", encoding="utf-8")
            draft_claims(repository, "HEAD^", "HEAD", second)
            draft_claims(copy, "HEAD^", "HEAD", third)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), third.read_bytes())

    def test_source_repository_is_unchanged_and_output_inside_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            before = (self._git(repository, "rev-parse", "HEAD"), self._git(repository, "status", "--porcelain"))
            code, _, error = self._run(
                "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                "--output", str(repository / "claims.md"),
            )
            after = (self._git(repository, "rev-parse", "HEAD"), self._git(repository, "status", "--porcelain"))
            self.assertEqual(code, 5)
            self.assertIn("outside the source repository", error)
            self.assertEqual(before, after)

    def test_generated_claims_prepare_and_verify_all_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1", "gone": "x"}, {"a": "2", "new": "y"})
            claims = root / "claims.md"
            case = root / "case"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            prepare_case(repository, "HEAD^", "HEAD", claims, case)
            completed = subprocess.run(
                [sys.executable, "-m", "proofrail_verifier", "verify-change", "--repo", str(repository),
                 "--base", "HEAD^", "--head", "HEAD", "--claim-file", str(claims)],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["overall_verdict"], "verified")
            self.assertTrue(all(claim["status"] == "verified" for claim in result["claims"]))
            preserved = subprocess.run(
                [sys.executable, "-m", "proofrail_verifier", "verify", str(case)],
                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
            )
            self.assertEqual(preserved.returncode, 0, preserved.stderr)
            self.assertEqual(json.loads(preserved.stdout)["overall_verdict"], "verified")

    def test_custom_title_is_preserved_and_shell_text_is_inert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            output = root / "claims.md"
            title = "Release: #1 uses `echo` and $(false)"
            draft_claims(repository, "HEAD^", "HEAD", output, case_title=title)
            self.assertEqual(parse_claim_file(output).overall_statement, title)

    def test_invalid_repository_refs_ranges_and_empty_change_fail_as_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            cases = [
                (root / "missing", "HEAD^", "HEAD"),
                (root, "HEAD^", "HEAD"),
                (repository, "missing", "HEAD"),
                (repository, "HEAD^", "missing"),
                (repository, "HEAD", "HEAD"),
                (repository, "HEAD", "HEAD^"),
            ]
            for index, (repo, base, head) in enumerate(cases):
                code, _, error = self._run(
                    "--repo", str(repo), "--base", base, "--head", head,
                    "--output", str(root / f"failure-{index}.md"),
                )
                self.assertEqual(code, 3, error)

    def test_missing_git_tree_and_unrepresentable_git_path_fail_as_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            damaged = self._repository(root, {"a": "1"}, {"a": "2"})
            tree = self._git(damaged, "rev-parse", "HEAD^{tree}")
            (damaged / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
            code, _, error = self._run(
                "--repo", str(damaged), "--base", "HEAD^", "--head", "HEAD",
                "--output", str(root / "damaged.md"),
            )
            self.assertEqual(code, 3, error)

            unsafe = self._repository(root, {"base": "1"}, {"bad\nclaim": "2"})
            code, _, error = self._run(
                "--repo", str(unsafe), "--base", "HEAD^", "--head", "HEAD",
                "--output", str(root / "unsafe.md"),
            )
            self.assertEqual(code, 3, error)
            self.assertIn("cannot be represented safely", error)

    def test_existing_file_directory_symlink_and_parent_symlink_fail_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            existing = root / "existing"
            existing.write_text("keep", encoding="utf-8")
            directory = root / "directory"
            directory.mkdir()
            symlink = root / "symlink"
            symlink.symlink_to(existing)
            outside = root / "outside"
            outside.mkdir()
            parent_link = root / "parent-link"
            parent_link.symlink_to(outside, target_is_directory=True)
            for output in (existing, directory, symlink, parent_link / "claims.md"):
                code, _, error = self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--output", str(output),
                )
                self.assertEqual(code, 5, error)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_git_failure_is_generation_failure_and_temporary_is_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            output = root / "claims.md"
            with mock.patch("proofrail_verifier.claim_drafting.changed_paths", side_effect=ClaimGenerationFailure("boom")):
                with self.assertRaisesRegex(ClaimGenerationFailure, "boom"):
                    draft_claims(repository, "HEAD^", "HEAD", output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".claims.md.*")), [])

    def test_publication_failure_and_interruption_clean_temporary_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            for failure in (OSError("fail"), KeyboardInterrupt()):
                output = root / "claims.md"
                with mock.patch("proofrail_verifier.claim_drafting.os.link", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        draft_claims(repository, "HEAD^", "HEAD", output)
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob(".claims.md.*")), [])

    def test_invalid_path_and_title_injection_are_rejected(self) -> None:
        with self.assertRaises(InvalidPreparationInput):
            render_claims([{"path": "bad\n- id: injected", "status": "added"}], "Title")
        with self.assertRaises(InvalidPreparationInput):
            render_claims([{"path": "safe", "status": "added"}], "Title\n\n## Atomic claims")
        with self.assertRaises(InvalidPreparationInput):
            render_claims([{"path": "safe", "status": "added"}], "")
        with self.assertRaises(InvalidPreparationInput):
            render_claims([{"path": "safe", "status": "added"}], "## Atomic claims")

    def test_success_cli_reports_portable_output_and_usage_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "1"}, {"a": "2"})
            output = root / "claims.md"
            code, stdout, stderr = self._run(
                "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                "--output", str(output),
            )
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("base sha: ", stdout)
            self.assertIn("head sha: ", stdout)
            self.assertIn("atomic claims: 1", stdout)
            self.assertIn("output: claims.md", stdout)
            self.assertNotIn(str(root), stdout)
            with self.assertRaises(SystemExit) as caught:
                main(["draft-claims"])
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
