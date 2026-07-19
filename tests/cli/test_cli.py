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


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures"


class ProofrailCliTests(unittest.TestCase):
    def _run(self, case_directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "proofrail_verifier",
                "verify",
                str(case_directory),
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    @staticmethod
    def _statuses(output: str) -> dict[str, str]:
        result = json.loads(output)
        return {claim["claim_id"]: claim["status"] for claim in result["claims"]}

    @staticmethod
    def _tree_digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _copy_case(
        temporary_root: Path, fixture_name: str
    ) -> tuple[Path, Path]:
        case_directory = temporary_root / "cases" / fixture_name
        case_directory.parent.mkdir(parents=True)
        shutil.copytree(FIXTURES / fixture_name, case_directory)
        schema = temporary_root / "schemas" / "case.schema.json"
        schema.parent.mkdir(parents=True)
        shutil.copy2(REPOSITORY_ROOT / "schemas" / "case.schema.json", schema)
        return case_directory, schema

    def test_fixture_001_json_statuses(self) -> None:
        completed = self._run(FIXTURES / "001-partial-workflow-fix")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            self._statuses(completed.stdout),
            {
                "obsolete-lockfile-deleted": "verified",
                "workflow-triggers-updated": "contradicted",
                "green-run-proves-new-trigger": "unsupported",
                "change-merged": "human_review_required",
            },
        )
        self.assertEqual(json.loads(completed.stdout)["overall_verdict"], "partially_verified")
        self.assertNotIn(str(REPOSITORY_ROOT), completed.stdout)

    def test_overall_contradicted_verdict_still_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-contradicted-") as temporary:
            case_directory, _ = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            (case_directory / "actual.patch").write_text("", encoding="utf-8")
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["overall_verdict"], "contradicted")

    def test_fixture_002_json_statuses(self) -> None:
        completed = self._run(FIXTURES / "002-incapable-validation-command", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self._statuses(completed.stdout),
            {
                "validation-command-executed": "verified",
                "page-renders-expected-text": "unsupported",
                "static-html-contains-expected-text": "contradicted",
            },
        )

    def test_markdown_contains_verdict_and_every_claim(self) -> None:
        completed = self._run(
            FIXTURES / "001-partial-workflow-fix", "--format", "markdown"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("**Overall verdict:** `partially_verified`", completed.stdout)
        self.assertIn("## What remains unverified", completed.stdout)
        for claim in (
            "obsolete-lockfile-deleted",
            "workflow-triggers-updated",
            "green-run-proves-new-trigger",
            "change-merged",
        ):
            self.assertIn(f"## Claim: {claim}", completed.stdout)
        self.assertIn("`unsupported`", completed.stdout)
        self.assertIn("`human_review_required`", completed.stdout)

    def test_output_file_matches_stdout_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-output-") as temporary:
            output = Path(temporary) / "result.json"
            stdout_run = self._run(FIXTURES / "002-incapable-validation-command")
            file_run = self._run(
                FIXTURES / "002-incapable-validation-command", "--output", str(output)
            )
            self.assertEqual(stdout_run.returncode, 0, stdout_run.stderr)
            self.assertEqual(file_run.returncode, 0, file_run.stderr)
            self.assertEqual(file_run.stdout, "")
            self.assertEqual(output.read_text(encoding="utf-8"), stdout_run.stdout)

    def test_unsupported_format_is_usage_error(self) -> None:
        completed = self._run(
            FIXTURES / "001-partial-workflow-fix", "--format", "xml"
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("invalid choice", completed.stderr)

    def test_missing_case_directory_is_invalid_case(self) -> None:
        completed = self._run(REPOSITORY_ROOT / "tests" / "fixtures" / "missing")
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, "")
        self.assertIn("invalid case", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_malformed_case_json_is_controlled_invalid_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-malformed-") as temporary:
            case_directory, _ = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            (case_directory / "case.json").write_text("{", encoding="utf-8")
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 3)
            self.assertIn("invalid JSON in case.json", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_schema_invalid_case_is_controlled_invalid_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-schema-invalid-") as temporary:
            case_directory, _ = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            case_path = case_directory / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["claims"][0]["status"] = "partially_verified"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 3)
            self.assertIn("does not satisfy schema", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_broken_evidence_relationship_is_verification_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-relationship-") as temporary:
            case_directory, _ = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            case_path = case_directory / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            evidence = next(item for item in case["evidence"] if item["id"] == "actual-commit-diff")
            evidence["claim_ids"].remove("workflow-triggers-updated")
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 4)
            self.assertIn("verification failed", completed.stderr)
            self.assertIn("invalid evidence relationship", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_recorded_command_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-command-") as temporary:
            root = Path(temporary)
            case_directory, _ = self._copy_case(root, "002-incapable-validation-command")
            sentinel = root / "command-was-executed"
            case_path = case_directory / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["evidence"][0]["command"] = f"touch {sentinel}"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            before = self._tree_digest(case_directory)
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual(self._tree_digest(case_directory), before)

    def test_output_is_deterministic_across_runs(self) -> None:
        case_directory = FIXTURES / "002-incapable-validation-command"
        first = self._run(case_directory, "--format", "markdown")
        second = self._run(case_directory, "--format", "markdown")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_case_directories_remain_byte_for_byte_unchanged(self) -> None:
        for fixture_name in (
            "001-partial-workflow-fix",
            "002-incapable-validation-command",
        ):
            with self.subTest(fixture_name=fixture_name):
                case_directory = FIXTURES / fixture_name
                before = self._tree_digest(case_directory)
                completed = self._run(case_directory)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(self._tree_digest(case_directory), before)

    def test_missing_schema_is_invalid_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-schema-") as temporary:
            case_directory, schema = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            schema.unlink()
            completed = self._run(case_directory)
            self.assertEqual(completed.returncode, 3)
            self.assertIn("case.schema.json", completed.stderr)

    def test_output_write_failure_is_distinct_and_case_is_unchanged(self) -> None:
        case_directory = FIXTURES / "001-partial-workflow-fix"
        before = self._tree_digest(case_directory)
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-write-") as temporary:
            missing_parent_output = Path(temporary) / "missing" / "result.json"
            completed = self._run(case_directory, "--output", str(missing_parent_output))
        self.assertEqual(completed.returncode, 5)
        self.assertIn("output write failed", completed.stderr)
        self.assertEqual(self._tree_digest(case_directory), before)

    def test_output_inside_case_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-cli-contained-") as temporary:
            case_directory, _ = self._copy_case(
                Path(temporary), "001-partial-workflow-fix"
            )
            before = self._tree_digest(case_directory)
            completed = self._run(
                case_directory, "--output", str(case_directory / "result.json")
            )
            self.assertEqual(completed.returncode, 5)
            self.assertIn("refusing to write output inside", completed.stderr)
            self.assertEqual(self._tree_digest(case_directory), before)


if __name__ == "__main__":
    unittest.main()
