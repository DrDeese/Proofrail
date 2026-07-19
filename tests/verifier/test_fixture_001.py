from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier import evaluate_fixture_001, load_fixture_001, render_json
from proofrail_verifier.evaluation import VerificationError


EXPECTED_STATUSES = {
    "obsolete-lockfile-deleted": "verified",
    "workflow-triggers-updated": "contradicted",
    "green-run-proves-new-trigger": "unsupported",
    "change-merged": "human_review_required",
}


class Fixture001VerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = load_fixture_001(REPOSITORY_ROOT)

    def _status_map(self, result: dict[str, object]) -> dict[str, str]:
        return {
            claim["claim_id"]: claim["status"]
            for claim in result["claims"]  # type: ignore[index,union-attr]
        }

    def _mutated_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(prefix="proofrail-verifier-")
        root = Path(temporary.name)
        fixture_target = root / "tests" / "fixtures" / "001-partial-workflow-fix"
        fixture_target.parent.mkdir(parents=True)
        shutil.copytree(self.bundle.fixture_dir, fixture_target)
        schema_target = root / "schemas" / "case.schema.json"
        schema_target.parent.mkdir(parents=True)
        shutil.copy2(self.bundle.schema_path, schema_target)
        return temporary, root

    def test_fixture_001_expected_result_and_deterministic_json(self) -> None:
        result = evaluate_fixture_001(self.bundle)
        self.assertEqual(self._status_map(result), EXPECTED_STATUSES)
        self.assertEqual(result["overall_verdict"], "partially_verified")
        independently_loaded = evaluate_fixture_001(load_fixture_001(REPOSITORY_ROOT))
        self.assertEqual(render_json(result), render_json(independently_loaded))
        self.assertEqual(json.loads(render_json(result)), result)
        self.assertEqual(
            result["sources"]["case"]["path"],
            "tests/fixtures/001-partial-workflow-fix/case.json",
        )
        self.assertEqual(result["sources"]["schema"]["path"], "schemas/case.schema.json")
        for claim in result["claims"]:
            self.assertIn("finding", claim)
            self.assertIn("evidence_ids", claim)
            self.assertIn("provenance_limitations", claim)

    def test_actual_schema_and_fixture_files_are_loaded(self) -> None:
        expected_case = REPOSITORY_ROOT / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"
        expected_schema = REPOSITORY_ROOT / "schemas" / "case.schema.json"
        self.assertEqual(self.bundle.case_path, expected_case)
        self.assertEqual(self.bundle.schema_path, expected_schema)
        self.assertEqual(self.bundle.case_sha256, hashlib.sha256(expected_case.read_bytes()).hexdigest())
        self.assertEqual(
            self.bundle.schema_sha256,
            hashlib.sha256(expected_schema.read_bytes()).hexdigest(),
        )

    def test_updated_workflow_is_not_contradicted(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            fixture = root / "tests" / "fixtures" / "001-partial-workflow-fix"
            (fixture / "actual.patch").write_text(
                (fixture / "intended.patch").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            result = evaluate_fixture_001(load_fixture_001(root))
            self.assertEqual(self._status_map(result)["workflow-triggers-updated"], "verified")

    def test_existing_bun_lockb_is_not_verified_as_deleted(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            fixture = root / "tests" / "fixtures" / "001-partial-workflow-fix"
            (fixture / "actual.patch").write_text("", encoding="utf-8")
            result = evaluate_fixture_001(load_fixture_001(root))
            self.assertEqual(self._status_map(result)["obsolete-lockfile-deleted"], "contradicted")

    def test_authenticated_merge_provenance_requires_new_status(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            merge_claim = next(claim for claim in case["claims"] if claim["id"] == "change-merged")
            merge_claim["evidence_ids"] = ["authenticated-merge"]
            case["evidence"].append(
                {
                    "id": "authenticated-merge",
                    "kind": "authenticated_external",
                    "summary": "Authenticated merge record.",
                    "acceptance_stage": "executed",
                    "claim_ids": ["change-merged"],
                    "provenance": {
                        "source_type": "scenario_document",
                        "authentication": "authenticated",
                        "independently_verified": True,
                        "limitations": [],
                    },
                }
            )
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            result = evaluate_fixture_001(load_fixture_001(root))
            self.assertEqual(self._status_map(result)["change-merged"], "verified")

    def test_materially_broken_evidence_relationship_fails(self) -> None:
        altered = copy.deepcopy(self.bundle.case)
        actual_diff = next(item for item in altered["evidence"] if item["id"] == "actual-commit-diff")
        actual_diff["claim_ids"].remove("workflow-triggers-updated")
        broken_bundle = replace(self.bundle, case=altered)
        with self.assertRaisesRegex(VerificationError, "invalid evidence relationship"):
            evaluate_fixture_001(broken_bundle)


if __name__ == "__main__":
    unittest.main()
