from __future__ import annotations

import contextlib
import hashlib
import importlib
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

from proofrail_verifier import evaluate_case, load_case_directory, verify_change
from proofrail_verifier.cli import main
from proofrail_verifier.preparation import prepare_case
from proofrail_verifier.preparation_errors import OutputWriteFailure
from proofrail_verifier.rendering import render_json


change_module = importlib.import_module("proofrail_verifier.change_verification")


class VerifyChangeTests(unittest.TestCase):
    run_number = 0

    @staticmethod
    def _environment(**updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        environment.update(updates)
        return environment

    @classmethod
    def _run(
        cls,
        repository: Path = REFERENCE_REPOSITORY,
        claim_file: Path = REFERENCE_CLAIM,
        *,
        base: str = "HEAD^",
        head: str = "HEAD",
        result_format: str = "json",
        output: Path | None = None,
        keep_case: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "proofrail_verifier",
            "verify-change",
            "--repo",
            str(repository),
            "--base",
            base,
            "--head",
            head,
            "--claim-file",
            str(claim_file),
            "--format",
            result_format,
        ]
        if output is not None:
            command.extend(("--output", str(output)))
        if keep_case is not None:
            command.extend(("--keep-case", str(keep_case)))
        return subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment or cls._environment(),
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
        base_files: dict[str, str],
        head_files: dict[str, str],
    ) -> Path:
        cls.run_number += 1
        repository = root / f"repository with spaces {cls.run_number}"
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
        for files, message, date in (
            (base_files, "base", "2024-01-01T00:00:00+00:00"),
            (head_files, "head", "2024-01-01T00:01:00+00:00"),
        ):
            for existing in [path for path in repository.rglob("*") if path.is_file()]:
                if ".git" not in existing.parts:
                    existing.unlink()
            for relative, content in files.items():
                path = repository / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            cls._git(repository, "add", "--all")
            environment = cls._environment(
                GIT_AUTHOR_DATE=date,
                GIT_COMMITTER_DATE=date,
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
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        return repository

    @staticmethod
    def _claim_file(root: Path, body: str) -> Path:
        path = root / "claim file.md"
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def _arguments() -> list[str]:
        return [
            "verify-change",
            "--repo",
            str(REFERENCE_REPOSITORY),
            "--base",
            "HEAD^",
            "--head",
            "HEAD",
            "--claim-file",
            str(REFERENCE_CLAIM),
        ]

    def test_reference_result_matches_manual_two_command_flow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-manual-") as temporary:
            case_directory = Path(temporary) / "manual-case"
            prepare_case(
                REFERENCE_REPOSITORY,
                "HEAD^",
                "HEAD",
                REFERENCE_CLAIM,
                case_directory,
            )
            manual = render_json(evaluate_case(load_case_directory(case_directory)))
            completed = self._run()
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(completed.stdout, manual)
            result = json.loads(completed.stdout)
            self.assertEqual(
                {claim["claim_id"]: claim["status"] for claim in result["claims"]},
                {
                    "obsolete-lockfile-deleted": "verified",
                    "workflow-triggers-updated": "contradicted",
                },
            )
            self.assertEqual(result["overall_verdict"], "partially_verified")
            self.assertNotIn(str(REFERENCE_REPOSITORY.resolve()), completed.stdout)

    def test_json_markdown_output_preservation_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-render-") as temporary:
            root = Path(temporary)
            json_first = self._run()
            json_second = self._run()
            markdown_first = self._run(result_format="markdown")
            markdown_second = self._run(result_format="markdown")
            self.assertEqual(json_first.returncode, 0, json_first.stderr)
            self.assertEqual(markdown_first.returncode, 0, markdown_first.stderr)
            self.assertEqual(json_first.stdout, json_second.stdout)
            self.assertEqual(markdown_first.stdout, markdown_second.stdout)
            self.assertIn("**Overall verdict:** `partially_verified`", markdown_first.stdout)
            self.assertIn("## Claim: workflow-triggers-updated", markdown_first.stdout)

            markdown_output = root / "result.md"
            markdown_file = self._run(
                result_format="markdown", output=markdown_output
            )
            self.assertEqual(markdown_file.returncode, 0, markdown_file.stderr)
            self.assertEqual(markdown_file.stdout, "")
            self.assertEqual(markdown_output.read_text(), markdown_first.stdout)

            output = root / "result.json"
            kept = root / "preserved case"
            source_before = self._digest(REFERENCE_REPOSITORY)
            published = self._run(output=output, keep_case=kept)
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertEqual(published.stdout, "")
            self.assertEqual(output.read_text(encoding="utf-8"), json_first.stdout)
            self.assertEqual(
                render_json(evaluate_case(load_case_directory(kept))),
                json_first.stdout,
            )
            self.assertEqual(self._digest(REFERENCE_REPOSITORY), source_before)

    def test_temporary_case_is_removed_without_keep_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-temp-") as temporary:
            temporary_parent = Path(temporary) / "private temp"
            temporary_parent.mkdir()
            with mock.patch.object(tempfile, "tempdir", str(temporary_parent)):
                completed = verify_change(
                    REFERENCE_REPOSITORY,
                    "HEAD^",
                    "HEAD",
                    REFERENCE_CLAIM,
                )
            self.assertEqual(completed.result["overall_verdict"], "partially_verified")
            self.assertEqual(list(temporary_parent.iterdir()), [])

    def test_dirty_tree_spaces_hooks_scripts_and_shell_claim_are_inert(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-inert-") as temporary:
            root = Path(temporary)
            sentinel = root / "executed"
            repository = self._new_repository(
                root,
                {"path with spaces.txt": "old\n"},
                {"path with spaces.txt": "committed\n"},
            )
            hook = repository / ".git" / "hooks" / "post-checkout"
            hook.parent.mkdir()
            hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n", encoding="utf-8")
            hook.chmod(0o755)
            (repository / "repository-script.sh").write_text(
                f"#!/bin/sh\ntouch '{sentinel}'\n", encoding="utf-8"
            )
            (repository / "path with spaces.txt").write_text("dirty\n", encoding="utf-8")
            (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            claim = self._claim_file(
                root,
                f"""# Completion claim

Do not run $(touch {sentinel}).

## Atomic claims

- id: spaced-path
  statement: $(touch {sentinel})
  expected-path: path with spaces.txt
  expected-change: modified
""",
            )
            before = self._digest(repository)
            status_before = self._git(repository, "status", "--porcelain=v1", "--untracked-files=all")
            completed = self._run(repository, claim)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["claims"][0]["status"], "unsupported")
            self.assertFalse(sentinel.exists())
            self.assertEqual(self._digest(repository), before)
            self.assertEqual(
                self._git(repository, "status", "--porcelain=v1", "--untracked-files=all"),
                status_before,
            )

    def test_invalid_repositories_refs_and_ranges_exit_three(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-input-") as temporary:
            missing = Path(temporary) / "missing"
            scenarios = (
                (missing, "HEAD^", "HEAD"),
                (REFERENCE_REPOSITORY, "missing", "HEAD"),
                (REFERENCE_REPOSITORY, "HEAD^", "missing"),
                (REFERENCE_REPOSITORY, "HEAD", "HEAD"),
                (REFERENCE_REPOSITORY, "HEAD", "HEAD^"),
            )
            for repository, base, head in scenarios:
                with self.subTest(repository=repository, base=base, head=head):
                    completed = self._run(repository, base=base, head=head)
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn("invalid change input", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_malformed_duplicate_and_unsafe_claims_exit_three(self) -> None:
        variants = {
            "malformed": "# Wrong heading\n",
            "duplicate": """# Completion claim

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
            "unsafe": """# Completion claim

Done.

## Atomic claims

- id: unsafe
  statement: outside was added.
  expected-path: ../outside
  expected-change: added
""",
        }
        for label, content in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="proofrail-end-to-end-claim-"
            ) as temporary:
                claim = self._claim_file(Path(temporary), content)
                completed = self._run(claim_file=claim)
                self.assertEqual(completed.returncode, 3, completed.stderr)
                self.assertEqual(completed.stdout, "")
                self.assertNotIn("Traceback", completed.stderr)

    def test_existing_and_symlink_destinations_exit_five_without_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-destination-") as temporary:
            root = Path(temporary)
            existing_output = root / "existing.json"
            existing_output.write_text("keep\n", encoding="utf-8")
            existing_case = root / "existing-case"
            existing_case.mkdir()
            (existing_case / "keep.txt").write_text("keep\n", encoding="utf-8")
            outside_file = root / "outside.json"
            outside_file.write_text("outside\n", encoding="utf-8")
            output_link = root / "output-link"
            output_link.symlink_to(outside_file)
            outside_directory = root / "outside-case"
            outside_directory.mkdir()
            case_link = root / "case-link"
            case_link.symlink_to(outside_directory, target_is_directory=True)
            for output, keep_case in (
                (existing_output, None),
                (None, existing_case),
                (output_link, None),
                (None, case_link),
                (REFERENCE_REPOSITORY / "result.json", None),
                (None, REFERENCE_REPOSITORY / "generated-case"),
            ):
                with self.subTest(output=output, keep_case=keep_case):
                    completed = self._run(output=output, keep_case=keep_case)
                    self.assertEqual(completed.returncode, 5, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn("output write failed", completed.stderr)
            self.assertEqual(existing_output.read_text(), "keep\n")
            self.assertEqual((existing_case / "keep.txt").read_text(), "keep\n")
            self.assertEqual(outside_file.read_text(), "outside\n")
            self.assertEqual(list(outside_directory.iterdir()), [])

    def test_git_failure_exits_four_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-git-failure-") as temporary:
            root = Path(temporary)
            repository = self._new_repository(
                root,
                {"item.txt": "old\n"},
                {"item.txt": "new\n"},
            )
            claim = self._claim_file(
                root,
                """# Completion claim

Done.

## Atomic claims

- id: item-modified
  statement: item.txt was modified.
  expected-path: item.txt
  expected-change: modified
""",
            )
            object_id = self._git(repository, "rev-parse", "HEAD:item.txt")
            (repository / ".git" / "objects" / object_id[:2] / object_id[2:]).unlink()
            output = root / "result.json"
            kept = root / "case"
            completed = self._run(repository, claim, output=output, keep_case=kept)
            self.assertEqual(completed.returncode, 4, completed.stderr)
            self.assertIn("change verification failed", completed.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(kept.exists())

    def test_schema_and_relationship_failures_are_controlled(self) -> None:
        real_prepare = change_module.prepare_case

        def corrupt_schema_case(*arguments: object, **keywords: object) -> object:
            result = real_prepare(*arguments, **keywords)
            case_path = Path(arguments[4]) / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["claims"][0]["status"] = "partially_verified"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            return result

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            change_module, "prepare_case", side_effect=corrupt_schema_case
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            schema_code = main(self._arguments())
        self.assertEqual(schema_code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("generated case is invalid", stderr.getvalue())

        def corrupt_relationship(*arguments: object, **keywords: object) -> object:
            result = real_prepare(*arguments, **keywords)
            case_path = Path(arguments[4]) / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["evidence"][0]["claim_ids"] = [case["claims"][1]["id"]]
            case_path.write_text(
                json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return result

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            change_module, "prepare_case", side_effect=corrupt_relationship
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            relationship_code = main(self._arguments())
        self.assertEqual(relationship_code, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid evidence relationship", stderr.getvalue())

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            change_module, "render_json", side_effect=TypeError("broken result shape")
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rendering_code = main(self._arguments())
        self.assertEqual(rendering_code, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("result rendering failed", stderr.getvalue())

    def test_actual_schema_and_verifier_are_loaded_and_declarations_are_not_results(self) -> None:
        real_prepare = change_module.prepare_case
        real_load = change_module.load_case_directory
        real_evaluate = change_module.evaluate_case
        observations = {"schema": False, "evaluations": 0}

        def alter_declarations(*arguments: object, **keywords: object) -> object:
            result = real_prepare(*arguments, **keywords)
            case_path = Path(arguments[4]) / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            for claim in case["claims"]:
                claim["status"] = "human_review_required"
            case["verdict"]["status"] = "unsupported"
            case_path.write_text(
                json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return result

        def tracked_load(path: Path) -> object:
            bundle = real_load(path)
            observations["schema"] = (
                bundle.schema_path.read_bytes()
                == (REPOSITORY_ROOT / "schemas" / "case.schema.json").read_bytes()
            )
            return bundle

        def tracked_evaluate(bundle: object) -> dict[str, object]:
            observations["evaluations"] += 1
            return real_evaluate(bundle)

        with mock.patch.object(
            change_module, "prepare_case", side_effect=alter_declarations
        ), mock.patch.object(
            change_module, "load_case_directory", side_effect=tracked_load
        ), mock.patch.object(
            change_module, "evaluate_case", side_effect=tracked_evaluate
        ):
            completed = verify_change(
                REFERENCE_REPOSITORY,
                "HEAD^",
                "HEAD",
                REFERENCE_CLAIM,
            )
        self.assertTrue(observations["schema"])
        self.assertEqual(observations["evaluations"], 1)
        self.assertEqual(
            {claim["claim_id"]: claim["status"] for claim in completed.result["claims"]},
            {
                "obsolete-lockfile-deleted": "verified",
                "workflow-triggers-updated": "contradicted",
            },
        )

    def test_publication_failure_rolls_back_all_destinations_and_staging(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-publish-") as temporary:
            root = Path(temporary)
            output = root / "result.json"
            kept = root / "case"
            resolved_kept = kept.parent.resolve() / kept.name
            real_replace = os.replace

            def fail_case_publish(source: object, destination: object) -> None:
                if Path(destination) == resolved_kept:
                    raise OSError("deliberate preserved-case publish failure")
                real_replace(source, destination)

            with mock.patch.object(change_module.os, "replace", side_effect=fail_case_publish):
                with self.assertRaises(OutputWriteFailure):
                    verify_change(
                        REFERENCE_REPOSITORY,
                        "HEAD^",
                        "HEAD",
                        REFERENCE_CLAIM,
                        output=output,
                        keep_case=kept,
                    )
            self.assertFalse(output.exists())
            self.assertFalse(kept.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_interrupted_preparation_cleans_temporary_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-end-to-end-interrupt-") as temporary:
            root = Path(temporary)

            def interrupt(*arguments: object, **keywords: object) -> None:
                output = Path(arguments[4])
                output.mkdir()
                (output / "partial").write_text("partial\n", encoding="utf-8")
                raise KeyboardInterrupt

            with mock.patch.object(tempfile, "tempdir", str(root)), mock.patch.object(
                change_module, "prepare_case", side_effect=interrupt
            ), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(
                io.StringIO()
            ) as stderr:
                return_code = main(self._arguments())
            self.assertEqual(return_code, 4)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("interrupted", stderr.getvalue())
            self.assertEqual(list(root.iterdir()), [])

    def test_usage_errors_exit_two(self) -> None:
        unsupported = self._run(result_format="xml")
        self.assertEqual(unsupported.returncode, 2)
        self.assertEqual(unsupported.stdout, "")
        self.assertIn("invalid choice", unsupported.stderr)
        missing = subprocess.run(
            [sys.executable, "-m", "proofrail_verifier", "verify-change"],
            cwd=REPOSITORY_ROOT,
            env=self._environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(missing.stdout, "")
        self.assertIn("required", missing.stderr)


if __name__ == "__main__":
    unittest.main()
