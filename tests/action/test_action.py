from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier import (
    evaluate_policy,
    evaluate_case,
    load_case_directory,
    load_policy,
    render_policy_json,
    render_policy_markdown,
    render_json,
    render_markdown,
    verify_change,
)
from proofrail_verifier.claim_checking import (
    check_claims,
    render_claim_check_json,
    render_claim_check_markdown,
)


class ProofrailActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_number = 0

    def _workspace(self, root: Path, *fixture_names: str) -> Path:
        workspace = root / "workspace"
        workspace.mkdir()
        shutil.copytree(
            REPOSITORY_ROOT / "src",
            workspace / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(REPOSITORY_ROOT / "schemas", workspace / "schemas")
        shutil.copytree(
            REPOSITORY_ROOT / ".github" / "actions" / "proofrail-verify",
            workspace / ".github" / "actions" / "proofrail-verify",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for fixture_name in fixture_names:
            target = workspace / "tests" / "fixtures" / fixture_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(REPOSITORY_ROOT / "tests" / "fixtures" / fixture_name, target)
        return workspace

    def _run(
        self,
        workspace: Path,
        case_directory: str | None = "tests/fixtures/001-partial-workflow-fix",
        result_format: str | None = "json",
        overrides: dict[str, str | None] | None = None,
        git_inputs: dict[str, str] | None = None,
        policy_file: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        self.run_number += 1
        output = workspace.parent / f"github-output-{self.run_number}"
        summary = workspace.parent / f"github-summary-{self.run_number}"
        output.write_text("", encoding="utf-8")
        summary.write_text("", encoding="utf-8")
        environment = os.environ.copy()
        for name in (
            "GITHUB_WORKSPACE",
            "GITHUB_OUTPUT",
            "GITHUB_STEP_SUMMARY",
            "INPUT_CASE_DIRECTORY",
            "INPUT_REPO",
            "INPUT_BASE",
            "INPUT_HEAD",
            "INPUT_CLAIM_FILE",
            "INPUT_POLICY_FILE",
            "INPUT_CHECK_CLAIMS",
            "INPUT_FORMAT",
            "PYTHONPATH",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "GITHUB_WORKSPACE": str(workspace),
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
        )
        if case_directory is not None:
            environment["INPUT_CASE_DIRECTORY"] = case_directory
        environment.update(git_inputs or {})
        if policy_file is not None:
            environment["INPUT_POLICY_FILE"] = policy_file
        if result_format is not None:
            environment["INPUT_FORMAT"] = result_format
        for name, value in (overrides or {}).items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = value
        completed = subprocess.run(
            [
                sys.executable,
                str(workspace / ".github" / "actions" / "proofrail-verify" / "run.py"),
            ],
            cwd=workspace,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return completed, output, summary

    @staticmethod
    def _outputs(path: Path) -> dict[str, str]:
        return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())

    @staticmethod
    def _policy_text(
        statuses: tuple[str, ...] = ("verified",),
        verdicts: tuple[str, ...] = ("partially_verified",),
        exceptions: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> str:
        lines = ["version: 1", "", "claims:", "  allowed-statuses:"]
        lines.extend(f"    - {status}" for status in statuses)
        lines.extend(["", "overall:", "  allowed-verdicts:"])
        lines.extend(f"    - {verdict}" for verdict in verdicts)
        if exceptions:
            lines.extend(["", "exceptions:"])
            for claim_id, allowed in exceptions:
                lines.extend(
                    [f"  - claim-id: {claim_id}", "    allowed-statuses:"]
                )
                lines.extend(f"      - {status}" for status in allowed)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
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
    def _commit(cls, repository: Path, message: str, date: str) -> str:
        cls._git(repository, "add", "--all")
        environment = os.environ.copy()
        environment.update(
            {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        )
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Proofrail Action Test",
                "-c",
                "user.email=action-test@proofrail.local",
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
        return cls._git(repository, "rev-parse", "HEAD")

    @classmethod
    def _git_change_source(
        cls, root: Path, workspace: Path
    ) -> tuple[Path, Path, str, str, Path]:
        repository = workspace / "repository with spaces"
        template = root / "empty-git-template"
        template.mkdir()
        subprocess.run(
            [
                "git",
                "init",
                "--initial-branch=main",
                f"--template={template}",
                str(repository),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        changed_path = repository / "path with spaces.txt"
        changed_path.write_text("base\n", encoding="utf-8")
        claim_file = repository / ".proofrail" / "change claim.md"
        claim_file.parent.mkdir()
        sentinel = root / "claim-content-executed"
        claim_file.write_text(
            f"""# Completion claim

Do not run claim text.

## Atomic claims

- id: path-modified
  statement: path with spaces.txt was modified.
  expected-path: path with spaces.txt
  expected-change: modified

- id: missing-added
  statement: missing.txt was added.
  expected-path: missing.txt
  expected-change: added

- id: shell-text-inert
  statement: $(touch {sentinel})
  expected-path: path with spaces.txt
  expected-change: modified
""",
            encoding="utf-8",
        )
        base = cls._commit(repository, "base", "2024-01-01T00:00:00+00:00")
        changed_path.write_text("head\n", encoding="utf-8")
        head = cls._commit(repository, "head", "2024-01-01T00:01:00+00:00")
        return repository, claim_file, base, head, sentinel

    @staticmethod
    def _git_inputs(
        workspace: Path, repository: Path, claim_file: Path, base: str, head: str
    ) -> dict[str, str]:
        return {
            "INPUT_REPO": repository.relative_to(workspace).as_posix(),
            "INPUT_BASE": base,
            "INPUT_HEAD": head,
            "INPUT_CLAIM_FILE": claim_file.relative_to(workspace).as_posix(),
        }

    @staticmethod
    def _retain_claims(case_path: Path, claim_ids: set[str]) -> None:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["claims"] = [claim for claim in case["claims"] if claim["id"] in claim_ids]
        finding_ids = {
            finding_id for claim in case["claims"] for finding_id in claim["finding_ids"]
        }
        evidence_ids = {
            evidence_id for claim in case["claims"] for evidence_id in claim["evidence_ids"]
        }
        case["findings"] = [
            finding for finding in case["findings"] if finding["id"] in finding_ids
        ]
        case["evidence"] = [
            evidence for evidence in case["evidence"] if evidence["id"] in evidence_ids
        ]
        for evidence in case["evidence"]:
            evidence["claim_ids"] = [
                claim_id for claim_id in evidence["claim_ids"] if claim_id in claim_ids
            ]
        for finding in case["findings"]:
            finding["evidence_ids"] = [
                evidence_id
                for evidence_id in finding["evidence_ids"]
                if evidence_id in evidence_ids
            ]
        case["verdict"]["finding_ids"] = [
            finding["id"] for finding in case["findings"]
        ]
        case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")

    def _assert_fixture_success(self, fixture_name: str, result_format: str | None) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-positive-") as temporary:
            workspace = self._workspace(Path(temporary), fixture_name)
            case_directory = workspace / "tests" / "fixtures" / fixture_name
            before = self._digest(case_directory)
            completed, output, summary = self._run(
                workspace,
                f"tests/fixtures/{fixture_name}",
                result_format,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")

            expected = evaluate_case(load_case_directory(case_directory))
            expected_json = render_json(expected)
            expected_markdown = render_markdown(expected)
            outputs = self._outputs(output)
            self.assertEqual(outputs["overall-verdict"], "partially_verified")
            result_path = outputs["result-json-path"]
            self.assertFalse(Path(result_path).is_absolute())
            self.assertNotIn("..", Path(result_path).parts)
            self.assertEqual(
                result_path,
                f".proofrail/results/{fixture_name}.json",
            )
            self.assertEqual((workspace / result_path).read_text(encoding="utf-8"), expected_json)
            self.assertEqual(summary.read_text(encoding="utf-8"), expected_markdown)
            self.assertEqual(
                completed.stdout,
                expected_markdown if result_format == "markdown" else expected_json,
            )
            for rendered in (
                expected_json,
                expected_markdown,
                completed.stdout,
                output.read_text(encoding="utf-8"),
            ):
                self.assertNotIn(str(workspace), rendered)
            self.assertEqual(self._digest(case_directory), before)

    def test_fixture_001_writes_json_markdown_and_outputs(self) -> None:
        self._assert_fixture_success("001-partial-workflow-fix", None)

    def test_fixture_002_writes_json_markdown_and_outputs(self) -> None:
        self._assert_fixture_success("002-incapable-validation-command", "markdown")

    def test_git_change_mode_matches_direct_verification_in_both_formats(self) -> None:
        for result_format in ("json", "markdown"):
            with self.subTest(result_format=result_format), tempfile.TemporaryDirectory(
                prefix="proofrail-action-git-positive-"
            ) as temporary:
                root = Path(temporary)
                workspace = self._workspace(root)
                repository, claim_file, base, head, sentinel = self._git_change_source(
                    root, workspace
                )
                direct = verify_change(repository, base, head, claim_file)
                repository_before = self._digest(repository)
                status_before = self._git(
                    repository, "status", "--porcelain=v1", "--untracked-files=all"
                )
                completed, output, summary = self._run(
                    workspace,
                    None,
                    result_format,
                    git_inputs=self._git_inputs(
                        workspace, repository, claim_file, base, head
                    ),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stderr, "")
                outputs = self._outputs(output)
                self.assertEqual(outputs["overall-verdict"], "partially_verified")
                result_path = workspace / outputs["result-json-path"]
                self.assertEqual(result_path.read_text(), render_json(direct.result))
                self.assertEqual(summary.read_text(), render_markdown(direct.result))
                self.assertEqual(
                    completed.stdout,
                    render_json(direct.result)
                    if result_format == "json"
                    else render_markdown(direct.result),
                )
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    {claim["claim_id"]: claim["status"] for claim in result["claims"]},
                    {
                        "path-modified": "verified",
                        "missing-added": "contradicted",
                        "shell-text-inert": "unsupported",
                    },
                )
                self.assertEqual(
                    result["case_id"], f"git-range-{base[:12]}-{head[:12]}"
                )
                for rendered in (
                    completed.stdout,
                    result_path.read_text(),
                    summary.read_text(),
                    output.read_text(),
                ):
                    self.assertNotIn(str(workspace), rendered)
                    self.assertNotIn(str(repository), rendered)
                self.assertFalse(sentinel.exists())
                self.assertEqual(self._digest(repository), repository_before)
                self.assertEqual(
                    self._git(
                        repository,
                        "status",
                        "--porcelain=v1",
                        "--untracked-files=all",
                    ),
                    status_before,
                )

    def test_mode_selection_rejects_none_mixed_and_partial_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-modes-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            git_inputs = self._git_inputs(workspace, repository, claim_file, base, head)

            no_mode, _, _ = self._run(workspace, None)
            self.assertEqual(no_mode.returncode, 2)
            self.assertIn("select prepared-case mode", no_mode.stderr)

            mixed, _, _ = self._run(workspace, git_inputs=git_inputs)
            self.assertEqual(mixed.returncode, 2)
            self.assertIn("cannot be combined", mixed.stderr)

            for omitted in git_inputs:
                with self.subTest(omitted=omitted):
                    partial = dict(git_inputs)
                    del partial[omitted]
                    completed, _, _ = self._run(
                        workspace, None, git_inputs=partial
                    )
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn("requires repo, base, head, and claim-file", completed.stderr)

    def test_git_change_invalid_sources_and_refs_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-git-invalid-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            valid = self._git_inputs(workspace, repository, claim_file, base, head)
            malformed = repository / ".proofrail" / "malformed.md"
            malformed.write_text("# Wrong heading\n", encoding="utf-8")
            scenarios = {
                "missing repository": {**valid, "INPUT_REPO": "missing-repository"},
                "invalid base": {**valid, "INPUT_BASE": "missing-base"},
                "invalid head": {**valid, "INPUT_HEAD": "missing-head"},
                "missing claim": {**valid, "INPUT_CLAIM_FILE": "missing-claim.md"},
                "malformed claim": {
                    **valid,
                    "INPUT_CLAIM_FILE": malformed.relative_to(workspace).as_posix(),
                },
            }
            for label, inputs in scenarios.items():
                with self.subTest(label=label):
                    completed, output, summary = self._run(
                        workspace, None, git_inputs=inputs
                    )
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(output.read_text(), "")
                    self.assertEqual(summary.read_text(), "")
                    self.assertNotIn("Traceback", completed.stderr)

    def test_git_change_paths_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-git-paths-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            valid = self._git_inputs(workspace, repository, claim_file, base, head)
            outside_repository = root / "outside-repository"
            shutil.copytree(repository, outside_repository)
            repository_link = workspace / "repository-link"
            repository_link.symlink_to(outside_repository, target_is_directory=True)
            inside_repository_link = workspace / "inside-repository-link"
            inside_repository_link.symlink_to(repository, target_is_directory=True)
            outside_claim = root / "outside-claim.md"
            outside_claim.write_text(claim_file.read_text(), encoding="utf-8")
            claim_link = workspace / "claim-link.md"
            claim_link.symlink_to(outside_claim)
            inside_claim_link = workspace / "inside-claim-link.md"
            inside_claim_link.symlink_to(claim_file)
            scenarios = {
                "claim traversal": {**valid, "INPUT_CLAIM_FILE": "../outside-claim.md"},
                "repository traversal": {**valid, "INPUT_REPO": "../outside-repository"},
                "absolute repository": {**valid, "INPUT_REPO": str(outside_repository)},
                "repository symlink": {**valid, "INPUT_REPO": "repository-link"},
                "internal repository symlink": {
                    **valid,
                    "INPUT_REPO": "inside-repository-link",
                },
                "claim symlink": {**valid, "INPUT_CLAIM_FILE": "claim-link.md"},
                "internal claim symlink": {
                    **valid,
                    "INPUT_CLAIM_FILE": "inside-claim-link.md",
                },
            }
            for label, inputs in scenarios.items():
                with self.subTest(label=label):
                    completed, _, _ = self._run(workspace, None, git_inputs=inputs)
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertIn("usage error", completed.stderr)

    def test_git_change_failure_and_result_collision_do_not_report_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-git-failure-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            inputs = self._git_inputs(workspace, repository, claim_file, base, head)
            case_id = f"git-range-{base[:12]}-{head[:12]}"
            collision = workspace / ".proofrail" / "results" / f"{case_id}.json"
            collision.parent.mkdir(parents=True)
            collision.write_text("source-owned\n", encoding="utf-8")
            collided, output, summary = self._run(
                workspace, None, git_inputs=inputs
            )
            self.assertEqual(collided.returncode, 5)
            self.assertIn("refusing to overwrite source", collided.stderr)
            self.assertEqual(collision.read_text(), "source-owned\n")
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")

            collision.unlink()
            object_id = self._git(repository, "rev-parse", "HEAD:path with spaces.txt")
            (repository / ".git" / "objects" / object_id[:2] / object_id[2:]).unlink()
            failed, output, summary = self._run(
                workspace, None, git_inputs=inputs
            )
            self.assertEqual(failed.returncode, 4)
            self.assertIn("verification failed", failed.stderr)
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")

    def test_completed_negative_claim_statuses_do_not_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-verdicts-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, output, _ = self._run(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result_path = workspace / self._outputs(output)["result-json-path"]
            result = json.loads(result_path.read_text(encoding="utf-8"))
            statuses = {claim["status"] for claim in result["claims"]}
            self.assertTrue(
                {"contradicted", "unsupported", "human_review_required"}.issubset(statuses)
            )

    def test_every_completed_overall_verdict_exits_zero(self) -> None:
        scenarios = (
            ("verified", "002-incapable-validation-command", {"validation-command-executed"}),
            ("unsupported", "002-incapable-validation-command", {"page-renders-expected-text"}),
            ("human_review_required", "001-partial-workflow-fix", {"change-merged"}),
        )
        for expected_verdict, fixture_name, claim_ids in scenarios:
            with self.subTest(expected_verdict=expected_verdict), tempfile.TemporaryDirectory(
                prefix="proofrail-action-overall-"
            ) as temporary:
                workspace = self._workspace(Path(temporary), fixture_name)
                case_path = workspace / "tests" / "fixtures" / fixture_name / "case.json"
                if expected_verdict == "human_review_required":
                    case = json.loads(case_path.read_text(encoding="utf-8"))
                    claim = next(item for item in case["claims"] if item["id"] == "change-merged")
                    finding = next(
                        item for item in case["findings"] if item["id"] == "merge-unverified"
                    )
                    claim["evidence_ids"] = ["untrusted-merge-record"]
                    finding["evidence_ids"] = ["untrusted-merge-record"]
                    case["evidence"].append(
                        {
                            "id": "untrusted-merge-record",
                            "kind": "unauthenticated_external",
                            "summary": "Unauthenticated merge record supplied for testing.",
                            "acceptance_stage": "executed",
                            "observation_method": "external_record",
                            "observes": ["merge_record"],
                            "claim_ids": ["change-merged"],
                            "provenance": {
                                "source_type": "scenario_document",
                                "authentication": "unauthenticated",
                                "independently_verified": False,
                                "limitations": ["The merge record is unauthenticated."],
                            },
                        }
                    )
                    case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
                self._retain_claims(case_path, claim_ids)
                completed, output, _ = self._run(
                    workspace, f"tests/fixtures/{fixture_name}"
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(
                    (workspace / self._outputs(output)["result-json-path"]).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(result["overall_verdict"], expected_verdict)

        with tempfile.TemporaryDirectory(prefix="proofrail-action-overall-contradicted-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            (
                workspace
                / "tests"
                / "fixtures"
                / "001-partial-workflow-fix"
                / "actual.patch"
            ).write_text("", encoding="utf-8")
            completed, output, _ = self._run(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(
                (workspace / self._outputs(output)["result-json-path"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["overall_verdict"], "contradicted")

    def test_markdown_contains_every_claim_status_and_limitations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-markdown-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, summary = self._run(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = evaluate_case(
                load_case_directory(workspace / "tests" / "fixtures" / "001-partial-workflow-fix")
            )
            markdown = summary.read_text(encoding="utf-8")
            self.assertIn("# Proofrail case: 001-partial-workflow-fix", markdown)
            self.assertIn("**Overall verdict:** `partially_verified`", markdown)
            self.assertIn("## What remains unverified", markdown)
            for claim in result["claims"]:
                self.assertIn(f"## Claim: {claim['claim_id']}", markdown)
                self.assertIn(f"- Status: `{claim['status']}`", markdown)
                for limitation in claim["provenance_limitations"]:
                    self.assertIn(limitation, markdown)

    def test_two_runs_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-deterministic-") as temporary:
            workspace = self._workspace(Path(temporary), "002-incapable-validation-command")
            first, first_output, first_summary = self._run(
                workspace, "tests/fixtures/002-incapable-validation-command"
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_json = (
                workspace / self._outputs(first_output)["result-json-path"]
            ).read_bytes()
            first_markdown = first_summary.read_bytes()
            second, second_output, second_summary = self._run(
                workspace, "tests/fixtures/002-incapable-validation-command"
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            second_json = (
                workspace / self._outputs(second_output)["result-json-path"]
            ).read_bytes()
            self.assertEqual(second_json, first_json)
            self.assertEqual(second_summary.read_bytes(), first_markdown)

    def test_recorded_command_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-command-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "002-incapable-validation-command")
            case_directory = workspace / "tests" / "fixtures" / "002-incapable-validation-command"
            case_path = case_directory / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            sentinel = root / "recorded-command-ran"
            case["evidence"][0]["command"] = f"touch {sentinel}"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            before = self._digest(case_directory)
            completed, _, _ = self._run(
                workspace, "tests/fixtures/002-incapable-validation-command"
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual(self._digest(case_directory), before)

    def test_missing_case_directory_input_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-missing-input-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(
                workspace, overrides={"INPUT_CASE_DIRECTORY": None}
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("usage error", completed.stderr)

    def test_missing_github_workspace_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-missing-workspace-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(workspace, overrides={"GITHUB_WORKSPACE": None})
            self.assertEqual(completed.returncode, 2)
            self.assertIn("GITHUB_WORKSPACE", completed.stderr)

    def test_missing_github_output_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-missing-output-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(workspace, overrides={"GITHUB_OUTPUT": None})
            self.assertEqual(completed.returncode, 2)
            self.assertIn("GITHUB_OUTPUT", completed.stderr)

    def test_missing_github_step_summary_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-missing-summary-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(
                workspace, overrides={"GITHUB_STEP_SUMMARY": None}
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("GITHUB_STEP_SUMMARY", completed.stderr)

    def test_unsupported_format_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-format-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(workspace, result_format="xml")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unsupported format", completed.stderr)

    def test_missing_case_path_is_invalid_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-missing-case-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(workspace, "tests/fixtures/missing")
            self.assertEqual(completed.returncode, 3)
            self.assertIn("invalid case", completed.stderr)

    def test_malformed_json_is_invalid_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-malformed-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            case_path = workspace / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"
            case_path.write_text("{", encoding="utf-8")
            completed, _, _ = self._run(workspace)
            self.assertEqual(completed.returncode, 3)
            self.assertNotIn("Traceback", completed.stderr)

    def test_schema_invalid_case_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-schema-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            case_path = workspace / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["claims"][0]["status"] = "partially_verified"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            completed, _, _ = self._run(workspace)
            self.assertEqual(completed.returncode, 3)
            self.assertIn("does not satisfy schema", completed.stderr)

    def test_broken_evidence_relationship_is_verification_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-relationship-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            case_path = workspace / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            evidence = next(item for item in case["evidence"] if item["id"] == "actual-commit-diff")
            evidence["claim_ids"].remove("workflow-triggers-updated")
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            completed, _, _ = self._run(workspace)
            self.assertEqual(completed.returncode, 4)
            self.assertIn("verification failed", completed.stderr)

    def test_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-traversal-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, _, _ = self._run(workspace, "../outside")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("traversal", completed.stderr)

    def test_absolute_path_outside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-absolute-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            outside = root / "outside"
            outside.mkdir()
            completed, _, _ = self._run(workspace, str(outside))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("workspace-relative", completed.stderr)

    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-symlink-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            outside = root / "outside"
            shutil.copytree(
                workspace / "tests" / "fixtures" / "001-partial-workflow-fix",
                outside,
            )
            (workspace / "escape").symlink_to(outside, target_is_directory=True)
            completed, _, _ = self._run(workspace, "escape")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("symbolic link", completed.stderr)

    def test_output_write_failure_returns_five(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-output-failure-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            output_directory = root / "not-an-output-file"
            output_directory.mkdir()
            completed, output, summary = self._run(
                workspace, overrides={"GITHUB_OUTPUT": str(output_directory)}
            )
            self.assertEqual(completed.returncode, 5)
            self.assertIn("output error", completed.stderr)
            self.assertFalse((workspace / ".proofrail" / "results").exists())
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")

    def test_result_path_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-result-symlink-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            outside = root / "outside-results"
            outside.mkdir()
            (workspace / ".proofrail").symlink_to(outside, target_is_directory=True)
            completed, output, summary = self._run(workspace)
            self.assertEqual(completed.returncode, 5)
            self.assertIn("result path resolves outside", completed.stderr)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(output.read_text(encoding="utf-8"), "")
            self.assertEqual(summary.read_text(encoding="utf-8"), "")

    def test_action_metadata_cannot_collide_with_json_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-result-collision-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            result_path = (
                workspace
                / ".proofrail"
                / "results"
                / "001-partial-workflow-fix.json"
            )
            completed, _, summary = self._run(
                workspace, overrides={"GITHUB_OUTPUT": str(result_path)}
            )
            self.assertEqual(completed.returncode, 5)
            self.assertIn("collides with the JSON result", completed.stderr)
            self.assertFalse(result_path.exists())
            self.assertEqual(summary.read_text(encoding="utf-8"), "")

    def test_newline_case_id_cannot_inject_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-injection-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            malicious_id = "evil\ninjected-key=value"
            source = workspace / "tests" / "fixtures" / "001-partial-workflow-fix"
            target = workspace / "tests" / "fixtures" / malicious_id
            shutil.copytree(source, target)
            case_path = target / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["id"] = malicious_id
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            completed, output, _ = self._run(
                workspace, f"tests/fixtures/{malicious_id}"
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "")
            self.assertNotIn("injected-key", output.read_text(encoding="utf-8"))

    def test_verifier_failure_is_not_reported_as_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-verifier-failure-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            (
                workspace
                / "tests"
                / "fixtures"
                / "001-partial-workflow-fix"
                / "actual.patch"
            ).unlink()
            completed, output, summary = self._run(workspace)
            self.assertEqual(completed.returncode, 4)
            self.assertIn("verification failed", completed.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "")
            self.assertEqual(summary.read_text(encoding="utf-8"), "")

    def test_policy_acceptance_exposes_four_outputs_and_both_reports(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-policy-accept-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            policy_path = workspace / "policy with spaces.yml"
            policy_path.write_text(
                self._policy_text(
                    statuses=(
                        "verified",
                        "unsupported",
                        "contradicted",
                        "human_review_required",
                    )
                ),
                encoding="utf-8",
            )
            case_directory = (
                workspace / "tests" / "fixtures" / "001-partial-workflow-fix"
            )
            result = evaluate_case(load_case_directory(case_directory))
            decision = evaluate_policy(result, load_policy(policy_path))
            completed, output, summary = self._run(
                workspace,
                policy_file="policy with spaces.yml",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs = self._outputs(output)
            self.assertEqual(
                set(outputs),
                {
                    "overall-verdict",
                    "result-json-path",
                    "policy-accepted",
                    "policy-result-json-path",
                },
            )
            self.assertEqual(outputs["policy-accepted"], "true")
            self.assertEqual(
                (workspace / outputs["result-json-path"]).read_text(),
                render_json(result),
            )
            self.assertEqual(
                (workspace / outputs["policy-result-json-path"]).read_text(),
                render_policy_json(decision),
            )
            self.assertEqual(
                summary.read_text(),
                render_markdown(result) + "\n" + render_policy_markdown(decision),
            )
            self.assertEqual(
                completed.stdout, render_json(result) + render_policy_json(decision)
            )

    def test_policy_rejection_is_one_and_not_a_verifier_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-policy-reject-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            policy = workspace / "policy.yml"
            policy.write_text(self._policy_text(), encoding="utf-8")
            completed, output, summary = self._run(
                workspace, policy_file="policy.yml"
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(completed.stderr, "")
            outputs = self._outputs(output)
            self.assertEqual(outputs["policy-accepted"], "false")
            self.assertTrue((workspace / outputs["result-json-path"]).is_file())
            policy_result = json.loads(
                (workspace / outputs["policy-result-json-path"]).read_text()
            )
            self.assertFalse(policy_result["accepted"])
            self.assertIn("# Proofrail acceptance policy", summary.read_text())

    def test_without_policy_preserves_existing_outputs_and_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-no-policy-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            completed, output, summary = self._run(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs = self._outputs(output)
            self.assertEqual(set(outputs), {"overall-verdict", "result-json-path"})
            self.assertNotIn("acceptance policy", summary.read_text())

    def test_claim_check_success_precedes_verification_and_exposes_six_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-claim-check-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            claim_file.write_text(
                """# Completion claim

The committed path change is covered.

## Atomic claims

- id: human-chosen-id
  statement: path with spaces.txt was modified.
  expected-path: path with spaces.txt
  expected-change: modified
""",
                encoding="utf-8",
            )
            policy = workspace / "policy.yml"
            policy.write_text(
                self._policy_text(statuses=("verified",), verdicts=("verified",)),
                encoding="utf-8",
            )
            inputs = self._git_inputs(workspace, repository, claim_file, base, head)
            direct_check = check_claims(repository, base, head, claim_file)
            direct_cli = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofrail_verifier",
                    "check-claims",
                    "--repo",
                    str(repository),
                    "--base",
                    base,
                    "--head",
                    head,
                    "--claim-file",
                    str(claim_file),
                ],
                cwd=workspace,
                env={**os.environ, "PYTHONPATH": str(workspace / "src")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(direct_cli.returncode, 0, direct_cli.stderr)
            direct_verification = verify_change(repository, base, head, claim_file)
            direct_policy = evaluate_policy(direct_verification.result, load_policy(policy))
            completed, output, summary = self._run(
                workspace,
                None,
                git_inputs=inputs,
                policy_file="policy.yml",
                overrides={"INPUT_CHECK_CLAIMS": "true"},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs = self._outputs(output)
            self.assertEqual(
                set(outputs),
                {
                    "claims-synchronized",
                    "claim-check-json-path",
                    "overall-verdict",
                    "result-json-path",
                    "policy-accepted",
                    "policy-result-json-path",
                },
            )
            self.assertEqual(outputs["claims-synchronized"], "true")
            self.assertEqual(outputs["overall-verdict"], "verified")
            self.assertEqual(outputs["policy-accepted"], "true")
            self.assertEqual(
                (workspace / outputs["claim-check-json-path"]).read_text(encoding="utf-8"),
                direct_cli.stdout,
            )
            self.assertEqual(direct_cli.stdout, render_claim_check_json(direct_check))
            expected_stdout = (
                render_claim_check_json(direct_check)
                + render_json(direct_verification.result)
                + render_policy_json(direct_policy)
            )
            self.assertEqual(completed.stdout, expected_stdout)
            expected_summary = (
                render_claim_check_markdown(direct_check)
                + render_markdown(direct_verification.result)
                + "\n"
                + render_policy_markdown(direct_policy)
            )
            self.assertEqual(summary.read_text(encoding="utf-8"), expected_summary)
            self.assertLess(
                completed.stdout.index('"synchronized":true'),
                completed.stdout.index('"overall_verdict":"verified"'),
            )

    def test_claim_drift_stops_before_verification_and_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-claim-drift-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            repository, claim_file, base, head, _ = self._git_change_source(root, workspace)
            malformed_policy = workspace / "policy.yml"
            malformed_policy.write_text("not a policy\n", encoding="utf-8")
            shutil.rmtree(workspace / "schemas")
            completed, output, summary = self._run(
                workspace,
                None,
                git_inputs=self._git_inputs(workspace, repository, claim_file, base, head),
                policy_file="policy.yml",
                overrides={"INPUT_CHECK_CLAIMS": "true"},
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(completed.stderr, "")
            outputs = self._outputs(output)
            self.assertEqual(
                set(outputs), {"claims-synchronized", "claim-check-json-path"}
            )
            self.assertEqual(outputs["claims-synchronized"], "false")
            report = json.loads(
                (workspace / outputs["claim-check-json-path"]).read_text(encoding="utf-8")
            )
            self.assertFalse(report["synchronized"])
            self.assertTrue(report["stale"])
            self.assertTrue(report["duplicates"])
            self.assertNotIn("overall-verdict", outputs)
            self.assertNotIn("policy-accepted", outputs)
            self.assertIn("# Proofrail claim freshness", summary.read_text())
            self.assertNotIn("# Proofrail verification", summary.read_text())
            self.assertNotIn("# Proofrail acceptance policy", summary.read_text())

    def test_prepared_case_rejects_claim_check_and_false_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-claim-mode-") as temporary:
            workspace = self._workspace(Path(temporary), "001-partial-workflow-fix")
            rejected, output, summary = self._run(
                workspace, overrides={"INPUT_CHECK_CLAIMS": "true"}
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("requires Git-change mode", rejected.stderr)
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")
            unchanged, output, summary = self._run(
                workspace, overrides={"INPUT_CHECK_CLAIMS": "false"}
            )
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertEqual(
                set(self._outputs(output)), {"overall-verdict", "result-json-path"}
            )
            self.assertNotIn("claim freshness", summary.read_text())

    def test_invalid_policy_and_policy_path_escapes_are_controlled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-policy-path-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            malformed = workspace / "malformed.yml"
            malformed.write_text("version 1\n", encoding="utf-8")
            invalid, output, summary = self._run(
                workspace, policy_file="malformed.yml"
            )
            self.assertEqual(invalid.returncode, 3, invalid.stderr)
            self.assertIn("invalid policy input", invalid.stderr)
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")

            outside = root / "outside policy.yml"
            outside.write_text(self._policy_text(), encoding="utf-8")
            direct_link = workspace / "direct-policy.yml"
            direct_link.symlink_to(outside)
            linked_directory = workspace / "linked-directory"
            linked_directory.symlink_to(root, target_is_directory=True)
            scenarios = (
                "../outside policy.yml",
                str(outside),
                "direct-policy.yml",
                "linked-directory/outside policy.yml",
            )
            for policy_file in scenarios:
                with self.subTest(policy_file=policy_file):
                    completed, output, summary = self._run(
                        workspace, policy_file=policy_file
                    )
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertIn("usage error", completed.stderr)
                    self.assertEqual(output.read_text(), "")
                    self.assertEqual(summary.read_text(), "")

    def test_verifier_failure_precedes_policy_and_policy_text_is_inert(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-policy-order-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            sentinel = root / "policy-executed"
            policy = workspace / "policy.yml"
            policy.write_text(
                f"# $(touch {sentinel})\n" + self._policy_text(),
                encoding="utf-8",
            )
            before = policy.read_bytes()
            (
                workspace
                / "tests"
                / "fixtures"
                / "001-partial-workflow-fix"
                / "actual.patch"
            ).unlink()
            completed, output, summary = self._run(
                workspace, policy_file="policy.yml"
            )
            self.assertEqual(completed.returncode, 4, completed.stderr)
            self.assertIn("verification failed", completed.stderr)
            self.assertNotIn("policy accepted", completed.stderr)
            self.assertEqual(output.read_text(), "")
            self.assertEqual(summary.read_text(), "")
            self.assertFalse(sentinel.exists())
            self.assertEqual(policy.read_bytes(), before)

    def test_action_and_workflow_are_bounded(self) -> None:
        action = (
            REPOSITORY_ROOT / ".github" / "actions" / "proofrail-verify" / "action.yml"
        ).read_text(encoding="utf-8")
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "proofrail-fixtures.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("using: composite", action)
        self.assertIn("case-directory:", action)
        for action_input in (
            "repo:", "base:", "head:", "claim-file:", "policy-file:", "check-claims:"
        ):
            self.assertIn(action_input, action)
        self.assertIn("default: json", action)
        self.assertIn("overall-verdict:", action)
        self.assertIn("result-json-path:", action)
        self.assertIn("policy-accepted:", action)
        self.assertIn("policy-result-json-path:", action)
        self.assertIn("claims-synchronized:", action)
        self.assertIn("claim-check-json-path:", action)
        self.assertIn("pull_request:", workflow)
        self.assertRegex(workflow, r"push:\n\s+branches:\n\s+- main")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("dogfood-pull-request:", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", workflow)
        self.assertIn("base: ${{ github.event.pull_request.base.sha }}", workflow)
        self.assertIn("head: ${{ github.event.pull_request.head.sha }}", workflow)
        self.assertIn("claim-file: .proofrail/claim.md", workflow)
        self.assertIn("policy-file: .proofrail/policy.yml", workflow)
        self.assertIn("check-claims: true", workflow)
        self.assertNotIn("api.github.com", workflow)
        self.assertNotIn("gh api", workflow)
        uses = re.findall(r"^\s*- uses: (\S+)", workflow, flags=re.MULTILINE)
        self.assertEqual(
            uses,
            [
                "actions/checkout@v4",
                "actions/setup-python@v5",
                "./.github/actions/proofrail-verify",
                "actions/checkout@v4",
                "actions/setup-python@v5",
                "./.github/actions/proofrail-verify",
            ],
        )
        self.assertIn("tests/fixtures/001-partial-workflow-fix", workflow)
        self.assertIn("tests/fixtures/002-incapable-validation-command", workflow)
        contract_path = REPOSITORY_ROOT / "contracts" / "step-15.yml"
        self.assertIn("contracts/step-15.yml", workflow)
        preflight = runpy.run_path(
            str(REPOSITORY_ROOT / "scripts" / "proofrail_step_preflight.py")
        )
        raw_contract = preflight["parse_bounded_yaml"](
            contract_path.read_text(encoding="utf-8"), contract=True
        )
        schema = json.loads(
            (REPOSITORY_ROOT / "contracts" / "step-contract.schema.json").read_text(
                encoding="utf-8"
            )
        )
        contract = preflight["validate_contract"](raw_contract, schema)
        reason, offending = preflight["validate_contract_source"](
            contract,
            "contracts/step-15.yml",
            preflight["parse_bounded_yaml"](workflow, contract=False),
            workflow,
            (REPOSITORY_ROOT / "scripts" / "proofrail_step_preflight.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIsNone(reason, (reason, offending))
        for claim_id in contract["expectations"]["claim-statuses"]:
            self.assertNotIn(json.dumps(claim_id), workflow)
        for key in (
            "claim-statuses",
            "overall-verdict",
            "policy-accepted",
            "allowed-statuses-source",
            "exceptions-applied",
            "fixture-verdicts",
        ):
            self.assertIn(f'["{key}"]', workflow)
        self.assertNotIn("expected = {", workflow)


if __name__ == "__main__":
    unittest.main()
