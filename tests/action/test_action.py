from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier import evaluate_case, load_case_directory, render_json, render_markdown


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
        case_directory: str = "tests/fixtures/001-partial-workflow-fix",
        result_format: str | None = "json",
        overrides: dict[str, str | None] | None = None,
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
            "INPUT_FORMAT",
            "PYTHONPATH",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "GITHUB_WORKSPACE": str(workspace),
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
                "INPUT_CASE_DIRECTORY": case_directory,
            }
        )
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
    def _digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

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
            self.assertIn("outside GITHUB_WORKSPACE", completed.stderr)

    def test_output_write_failure_returns_five(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-action-output-failure-") as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, "001-partial-workflow-fix")
            output_directory = root / "not-an-output-file"
            output_directory.mkdir()
            completed, _, _ = self._run(
                workspace, overrides={"GITHUB_OUTPUT": str(output_directory)}
            )
            self.assertEqual(completed.returncode, 5)
            self.assertIn("output error", completed.stderr)

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

    def test_action_and_workflow_are_bounded(self) -> None:
        action = (
            REPOSITORY_ROOT / ".github" / "actions" / "proofrail-verify" / "action.yml"
        ).read_text(encoding="utf-8")
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "proofrail-fixtures.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("using: composite", action)
        self.assertIn("case-directory:", action)
        self.assertIn("default: json", action)
        self.assertIn("overall-verdict:", action)
        self.assertIn("result-json-path:", action)
        self.assertIn("pull_request:", workflow)
        self.assertRegex(workflow, r"push:\n\s+branches:\n\s+- main")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("secrets.", workflow)
        uses = re.findall(r"^\s*- uses: (\S+)", workflow, flags=re.MULTILINE)
        self.assertEqual(
            uses,
            [
                "actions/checkout@v4",
                "actions/setup-python@v5",
                "./.github/actions/proofrail-verify",
            ],
        )
        self.assertIn("tests/fixtures/001-partial-workflow-fix", workflow)
        self.assertIn("tests/fixtures/002-incapable-validation-command", workflow)
        self.assertIn('test "$PROOFRAIL_VERDICT" = "partially_verified"', workflow)
        self.assertIn('test -f "$PROOFRAIL_RESULT_PATH"', workflow)


if __name__ == "__main__":
    unittest.main()
