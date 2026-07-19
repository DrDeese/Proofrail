from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier import evaluate_case, load_case, render_json
from proofrail_verifier.evaluation import VerificationError


EXPECTED_STATUSES = {
    "validation-command-executed": "verified",
    "page-renders-expected-text": "unsupported",
    "static-html-contains-expected-text": "contradicted",
}


class Fixture002VerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = load_case(REPOSITORY_ROOT, "002-incapable-validation-command")

    @staticmethod
    def _statuses(result: dict[str, object]) -> dict[str, str]:
        return {
            claim["claim_id"]: claim["status"]
            for claim in result["claims"]  # type: ignore[index,union-attr]
        }

    def _mutated_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(prefix="proofrail-verifier-002-")
        root = Path(temporary.name)
        fixture_target = root / "tests" / "fixtures" / self.bundle.case["id"]
        fixture_target.parent.mkdir(parents=True)
        shutil.copytree(self.bundle.fixture_dir, fixture_target)
        schema_target = root / "schemas" / "case.schema.json"
        schema_target.parent.mkdir(parents=True)
        shutil.copy2(self.bundle.schema_path, schema_target)
        return temporary, root

    def test_original_fixture_and_deterministic_rendering(self) -> None:
        result = evaluate_case(self.bundle)
        self.assertEqual(self._statuses(result), EXPECTED_STATUSES)
        self.assertEqual(result["overall_verdict"], "partially_verified")
        second = evaluate_case(load_case(REPOSITORY_ROOT, self.bundle.case["id"]))
        self.assertEqual(render_json(result), render_json(second))

    def test_browser_dom_evidence_verifies_rendered_claim(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            claim = next(item for item in case["claims"] if item["id"] == "page-renders-expected-text")
            claim["evidence_ids"].append("browser-dom-capture")
            case["evidence"].append({
                "id": "browser-dom-capture",
                "kind": "authenticated_external",
                "summary": "Authenticated browser DOM capture contains Dashboard ready.",
                "acceptance_stage": "outcome_verified",
                "observation_method": "browser_dom_capture",
                "observes": ["client_rendered_dom"],
                "observed_text": "Dashboard ready",
                "claim_ids": ["page-renders-expected-text"],
                "provenance": {"source_type": "deterministic_validation", "authentication": "authenticated", "independently_verified": True, "limitations": []}
            })
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            result = evaluate_case(load_case(root, self.bundle.case["id"]))
            self.assertEqual(self._statuses(result)["page-renders-expected-text"], "verified")

    def test_unauthenticated_dom_evidence_remains_unsupported(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            claim = next(item for item in case["claims"] if item["id"] == "page-renders-expected-text")
            claim["evidence_ids"].append("unauthenticated-dom")
            case["evidence"].append({
                "id": "unauthenticated-dom",
                "kind": "unauthenticated_external",
                "summary": "Untrusted DOM text report.",
                "acceptance_stage": "outcome_verified",
                "observation_method": "browser_dom_capture",
                "observes": ["client_rendered_dom"],
                "observed_text": "Dashboard ready",
                "claim_ids": ["page-renders-expected-text"],
                "provenance": {"source_type": "scenario_document", "authentication": "unauthenticated", "independently_verified": False, "limitations": ["DOM report is unauthenticated."]}
            })
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            result = evaluate_case(load_case(root, self.bundle.case["id"]))
            self.assertEqual(self._statuses(result)["page-renders-expected-text"], "unsupported")

    def test_static_text_does_not_verify_browser_dom_claim(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            html_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "artifacts" / "index.html"
            html_path.write_text(html_path.read_text(encoding="utf-8").replace("<div id=\"root\"></div>", "<div id=\"root\">Dashboard ready</div>"), encoding="utf-8")
            result = evaluate_case(load_case(root, self.bundle.case["id"]))
            statuses = self._statuses(result)
            self.assertEqual(statuses["static-html-contains-expected-text"], "verified")
            self.assertEqual(statuses["page-renders-expected-text"], "unsupported")

    def test_removed_execution_evidence_is_not_verified(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            claim = next(item for item in case["claims"] if item["id"] == "validation-command-executed")
            claim["evidence_ids"] = []
            evidence = next(item for item in case["evidence"] if item["id"] == "static-shell-command")
            evidence["claim_ids"].remove("validation-command-executed")
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            result = evaluate_case(load_case(root, self.bundle.case["id"]))
            self.assertEqual(self._statuses(result)["validation-command-executed"], "unsupported")

    def test_false_capability_label_fails_closed(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["evidence"][0]["observes"].append("client_rendered_dom")
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(VerificationError, "inconsistent with method"):
                evaluate_case(load_case(root, self.bundle.case["id"]))

    def test_declared_expected_statuses_are_not_evaluation_inputs(self) -> None:
        temporary, root = self._mutated_root()
        with temporary:
            case_path = root / "tests" / "fixtures" / self.bundle.case["id"] / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            for claim in case["claims"]:
                claim["status"] = "human_review_required"
            case["verdict"]["status"] = "unsupported"
            case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            result = evaluate_case(load_case(root, self.bundle.case["id"]))
            self.assertEqual(self._statuses(result), EXPECTED_STATUSES)
            self.assertEqual(result["overall_verdict"], "partially_verified")


if __name__ == "__main__":
    unittest.main()
