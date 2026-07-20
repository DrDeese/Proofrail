from __future__ import annotations

import contextlib
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

from proofrail_verifier.claim_checking import (
    ClaimComparisonFailure,
    check_claims,
    render_claim_check_json,
    render_claim_check_markdown,
    write_claim_check_output,
)
from proofrail_verifier.claim_drafting import draft_claims
from proofrail_verifier.cli import main
from proofrail_verifier.preparation_errors import OutputWriteFailure


class ClaimCheckingTests(unittest.TestCase):
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
    def _commit(cls, repository: Path, message: str) -> None:
        cls._git(repository, "add", "--all")
        cls._git(
            repository,
            "-c", "user.name=Proofrail Test",
            "-c", "user.email=test@proofrail.local",
            "commit", "--no-gpg-sign", "-m", message,
        )

    @classmethod
    def _repository(
        cls, root: Path, base: dict[str, str], head: dict[str, str]
    ) -> Path:
        cls.sequence += 1
        repository = root / f"repository-{cls.sequence}"
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
        cls._commit(repository, "base")
        cls._write_tree(repository, head)
        cls._commit(repository, "head")
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

    @staticmethod
    def _claim_text(
        predicates: list[tuple[str, str, str]], *, wording: str = "Completion"
    ) -> str:
        lines = ["# Completion claim", "", wording, "", "## Atomic claims", ""]
        for claim_id, path, change in predicates:
            lines.extend(
                [
                    f"- id: {claim_id}",
                    f"  statement: Human wording for {claim_id}.",
                    f"  expected-path: {path}",
                    f"  expected-change: {change}",
                    "",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _run(*arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["check-claims", *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_generated_claims_ids_and_wording_synchronize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(
                root,
                {"modified.txt": "old", "deleted.txt": "gone"},
                {"modified.txt": "new", "added.txt": "new"},
            )
            generated = root / "generated.md"
            draft_claims(repository, "HEAD^", "HEAD", generated)
            first = check_claims(repository, "HEAD^", "HEAD", generated)
            self.assertTrue(first["synchronized"])
            self.assertEqual(first["changed_path_count"], 3)
            edited = root / "edited.md"
            edited.write_text(
                self._claim_text(
                    [
                        ("new-id", "added.txt", "added"),
                        ("another-id", "deleted.txt", "deleted"),
                        ("last-id", "modified.txt", "modified"),
                    ],
                    wording="Broader human wording does not control matching.",
                ),
                encoding="utf-8",
            )
            second = check_claims(repository, "HEAD^", "HEAD", edited)
            self.assertTrue(second["synchronized"])
            self.assertEqual(
                [item["claim_id"] for item in second["matched"]],
                ["new-id", "another-id", "last-id"],
            )

    def test_rename_is_delete_plus_add_even_when_git_rename_detection_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"old.txt": "same"}, {"new.txt": "same"})
            self._git(repository, "config", "diff.renames", "true")
            claims = root / "claims.md"
            claims.write_text(
                self._claim_text(
                    [("new", "new.txt", "added"), ("old", "old.txt", "deleted")]
                ),
                encoding="utf-8",
            )
            result = check_claims(repository, "HEAD^", "HEAD", claims)
            self.assertTrue(result["synchronized"])
            self.assertEqual(result["changed_path_count"], 2)

    def test_portable_paths_are_ordered_and_shell_text_is_inert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "must-not-exist"
            paths = {
                "space name.txt": "x",
                "unicodé-猫.txt": "x",
                "-leading.txt": "x",
                "$(touch must-not-exist);`false`.txt": "x",
            }
            repository = self._repository(root, {"base": "x"}, paths)
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            claim_lines = claims.read_text(encoding="utf-8").splitlines()
            claim_lines[2] = f"$(touch {marker})"
            claims.write_text("\n".join(claim_lines) + "\n", encoding="utf-8")
            result = check_claims(repository, "HEAD^", "HEAD", claims)
            self.assertTrue(result["synchronized"])
            expected = sorted(
                set(paths) | {"base"}, key=lambda value: value.encode("utf-8")
            )
            self.assertEqual([item["path"] for item in result["matched"]], expected)
            self.assertFalse(marker.exists())
            self.assertNotIn(str(root), render_claim_check_json(result))

    def test_json_markdown_stdout_output_and_locations_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new", "b": "x"})
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            arguments = (
                "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                "--claim-file", str(claims),
            )
            code, stdout, error = self._run(*arguments)
            self.assertEqual((code, error), (0, ""))
            output = root / "result.json"
            code, written_stdout, error = self._run(*arguments, "--output", str(output))
            self.assertEqual((code, written_stdout, error), (0, "", ""))
            self.assertEqual(output.read_text(encoding="utf-8"), stdout)
            result = json.loads(stdout)
            self.assertEqual(render_claim_check_json(result), stdout)
            self.assertEqual(
                render_claim_check_markdown(result), render_claim_check_markdown(result)
            )
            copy = root / "copied-checkout"
            shutil.copytree(repository, copy)
            copied = check_claims(copy, "HEAD^", "HEAD", claims)
            self.assertEqual(render_claim_check_json(result), render_claim_check_json(copied))

    def test_dirty_worktree_and_untracked_files_do_not_affect_or_mutate_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new"})
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            claim_bytes = claims.read_bytes()
            clean = render_claim_check_json(check_claims(repository, "HEAD^", "HEAD", claims))
            (repository / "a").write_text("dirty", encoding="utf-8")
            (repository / "untracked").write_text("dirty", encoding="utf-8")
            status_before = self._git(repository, "status", "--porcelain")
            dirty = render_claim_check_json(check_claims(repository, "HEAD^", "HEAD", claims))
            self.assertEqual(clean, dirty)
            self.assertEqual(self._git(repository, "status", "--porcelain"), status_before)
            self.assertEqual(claims.read_bytes(), claim_bytes)

    def test_drift_categories_and_duplicate_coverage_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(
                root,
                {"mod": "old", "deleted": "old"},
                {"mod": "new", "added": "new"},
            )
            cases = {
                "missing": [("mod", "mod", "modified"), ("deleted", "deleted", "deleted")],
                "stale": [
                    ("added", "added", "added"), ("mod", "mod", "modified"),
                    ("deleted", "deleted", "deleted"), ("old", "old-path", "modified"),
                ],
                "conflict-added": [
                    ("added", "added", "modified"), ("mod", "mod", "modified"),
                    ("deleted", "deleted", "deleted"),
                ],
                "conflict-modified": [
                    ("added", "added", "added"), ("mod", "mod", "added"),
                    ("deleted", "deleted", "deleted"),
                ],
                "conflict-deleted": [
                    ("added", "added", "added"), ("mod", "mod", "modified"),
                    ("deleted", "deleted", "modified"),
                ],
                "duplicate": [
                    ("added-one", "added", "added"), ("added-two", "added", "added"),
                    ("mod", "mod", "modified"), ("deleted", "deleted", "deleted"),
                ],
                "simultaneous": [
                    ("mod-wrong", "mod", "added"),
                    ("stale", "previous", "modified"),
                ],
            }
            for name, predicates in cases.items():
                with self.subTest(name=name):
                    claims = root / f"{name}.md"
                    claims.write_text(self._claim_text(predicates), encoding="utf-8")
                    code, stdout, error = self._run(
                        "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                        "--claim-file", str(claims),
                    )
                    self.assertEqual(code, 1, error)
                    result = json.loads(stdout)
                    self.assertFalse(result["synchronized"])
            simultaneous = json.loads(
                self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(root / "simultaneous.md"),
                )[1]
            )
            self.assertTrue(simultaneous["missing"])
            self.assertTrue(simultaneous["stale"])
            self.assertTrue(simultaneous["conflicts"])
            duplicate = json.loads(
                self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(root / "duplicate.md"),
                )[1]
            )
            self.assertEqual(duplicate["duplicates"][0]["claim_ids"], ["added-one", "added-two"])

    def test_incomplete_rename_and_previous_range_claim_are_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"old": "x"}, {"new": "x"})
            incomplete = root / "incomplete.md"
            incomplete.write_text(self._claim_text([("new", "new", "added")]), encoding="utf-8")
            self.assertEqual(
                self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(incomplete),
                )[0],
                1,
            )
            self._write_tree(repository, {"new": "changed"})
            self._commit(repository, "third")
            old_range = root / "old-range.md"
            old_range.write_text(
                self._claim_text([("new-added", "new", "added"), ("old-deleted", "old", "deleted")]),
                encoding="utf-8",
            )
            result = check_claims(repository, "HEAD^", "HEAD", old_range)
            self.assertFalse(result["synchronized"])
            self.assertTrue(result["stale"])
            self.assertTrue(result["conflicts"])

    def test_invalid_inputs_are_exit_three_and_usage_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new"})
            valid = root / "valid.md"
            draft_claims(repository, "HEAD^", "HEAD", valid)
            malformed = root / "malformed.md"
            malformed.write_text("not a claim\n", encoding="utf-8")
            duplicate_ids = root / "duplicate-ids.md"
            duplicate_ids.write_text(
                self._claim_text([("same", "a", "modified"), ("same", "b", "added")]),
                encoding="utf-8",
            )
            unsafe = root / "unsafe.md"
            unsafe.write_text(self._claim_text([("bad", "../escape", "modified")]), encoding="utf-8")
            cases = [
                (root / "missing-repo", "HEAD^", "HEAD", valid),
                (root, "HEAD^", "HEAD", valid),
                (repository, "missing", "HEAD", valid),
                (repository, "HEAD^", "missing", valid),
                (repository, "HEAD", "HEAD", valid),
                (repository, "HEAD", "HEAD^", valid),
                (repository, "HEAD^", "HEAD", root / "missing-claim"),
                (repository, "HEAD^", "HEAD", malformed),
                (repository, "HEAD^", "HEAD", duplicate_ids),
                (repository, "HEAD^", "HEAD", unsafe),
            ]
            for repo, base, head, claim in cases:
                with self.subTest(repo=repo, base=base, head=head, claim=claim):
                    code, _, error = self._run(
                        "--repo", str(repo), "--base", base, "--head", head,
                        "--claim-file", str(claim),
                    )
                    self.assertEqual(code, 3, error)
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "check-claims", "--repo", str(repository), "--base", "HEAD^",
                        "--head", "HEAD", "--claim-file", str(valid),
                        "--format", "xml",
                    ]
                )
            self.assertEqual(raised.exception.code, 2)

    def test_repository_and_claim_symlink_escapes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new"})
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            repo_link = root / "repo-link"
            repo_link.symlink_to(repository, target_is_directory=True)
            claim_link = root / "claim-link"
            claim_link.symlink_to(claims)
            for repo, claim in ((repo_link, claims), (repository, claim_link)):
                code, _, error = self._run(
                    "--repo", str(repo), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(claim),
                )
                self.assertEqual(code, 3, error)

    def test_output_collisions_fail_five_and_interruption_cleans_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new"})
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            existing = root / "existing.json"
            existing.write_text("preserve", encoding="utf-8")
            symlink = root / "output-link"
            symlink.symlink_to(existing)
            for output in (existing, symlink, repository / "inside.json"):
                code, _, error = self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(claims), "--output", str(output),
                )
                self.assertEqual(code, 5, error)
            destination = root / "interrupted.json"
            with mock.patch("proofrail_verifier.claim_checking.os.link", side_effect=KeyboardInterrupt):
                code, _, error = self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(claims), "--output", str(destination),
                )
            self.assertEqual(code, 4)
            self.assertIn("interrupted", error)
            self.assertFalse(destination.exists())
            self.assertFalse(list(root.glob(".interrupted.json.*")))
            with mock.patch("proofrail_verifier.claim_checking.tempfile.mkstemp", side_effect=OSError("full")):
                with self.assertRaises(OutputWriteFailure):
                    write_claim_check_output(destination, "{}\n", repository)

    def test_git_comparison_failure_is_exit_four(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, {"a": "old"}, {"a": "new"})
            claims = root / "claims.md"
            draft_claims(repository, "HEAD^", "HEAD", claims)
            with mock.patch(
                "proofrail_verifier.claim_checking.changed_paths",
                side_effect=ClaimComparisonFailure("controlled Git failure"),
            ):
                code, _, error = self._run(
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--claim-file", str(claims),
                )
            self.assertEqual(code, 4)
            self.assertIn("controlled Git failure", error)


if __name__ == "__main__":
    unittest.main()
