"""Evaluate supported structured predicates and aggregate deterministic verdicts."""

from __future__ import annotations

from typing import Any

from .artifacts import ArtifactState, inspect_actual_state, workflow_trigger_paths
from .loading import FixtureBundle


class VerificationError(ValueError):
    """Raised when fixture relationships or capability labels are invalid."""


METHOD_CAPABILITIES = {
    "git_diff": {"file_contents"},
    "file_inspection": {"file_contents"},
    "static_http_fetch": {"static_response_body", "command_exit_status"},
    "browser_dom_capture": {"client_rendered_dom"},
    "command_execution": {"command_exit_status"},
    "external_record": {"command_exit_status", "workflow_trigger_event", "merge_record"},
}


def _index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in indexed:
            raise VerificationError(f"invalid or duplicate {label} id: {item_id!r}")
        indexed[item_id] = item
    return indexed


def _validate_relationships(
    claims: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]]
) -> None:
    for evidence_id, item in evidence.items():
        method = item.get("observation_method")
        observes = item.get("observes")
        allowed = METHOD_CAPABILITIES.get(method)
        if allowed is None or not isinstance(observes, list) or not set(observes).issubset(allowed):
            raise VerificationError(
                f"evidence {evidence_id!r} has capabilities inconsistent with method {method!r}"
            )
    for claim_id, claim in claims.items():
        evidence_ids = claim.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            raise VerificationError(f"claim {claim_id!r} has no evidence relationship list")
        for evidence_id in evidence_ids:
            item = evidence.get(evidence_id)
            if item is None or claim_id not in item.get("claim_ids", []):
                raise VerificationError(
                    f"claim {claim_id!r} has invalid evidence relationship {evidence_id!r}"
                )
    for evidence_id, item in evidence.items():
        for claim_id in item.get("claim_ids", []):
            if claim_id not in claims or evidence_id not in claims[claim_id]["evidence_ids"]:
                raise VerificationError(
                    f"evidence {evidence_id!r} has non-reciprocal claim relationship {claim_id!r}"
                )


def _limitations(*items: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        for limitation in item.get("provenance", {}).get("limitations", []):
            if limitation not in result:
                result.append(limitation)
    return result


def _related_evidence(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return [evidence[evidence_id] for evidence_id in claim["evidence_ids"]]


def _capable_evidence(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    required = claim["required_observation"]
    return [item for item in _related_evidence(claim, evidence) if required in item["observes"]]


def _finding(
    claim: dict[str, Any], status: str, summary: str, evidence: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    related = _related_evidence(claim, evidence)
    return {
        "claim_id": claim["id"],
        "status": status,
        "finding": summary,
        "evidence_ids": list(claim["evidence_ids"]),
        "provenance_limitations": _limitations(claim, *related),
    }


PATH_CHANGES = {"added", "modified", "deleted", "present", "absent"}


def _canonical_path_statement(path: str, expected_change: str) -> str:
    if expected_change in {"added", "modified", "deleted"}:
        return f"{path} was {expected_change}."
    return f"{path} is {expected_change}."


def _prepared_change_for_claim(case: dict[str, Any], claim: dict[str, Any]) -> str | None:
    marker = f"claim:{claim['id']}"
    matches = [
        item
        for item in case.get("requested_change", {}).get("required_artifact_changes", [])
        if item.get("location") == marker
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise VerificationError(f"prepared claim {claim['id']!r} has ambiguous path expectation")
    item = matches[0]
    path = claim.get("evaluation", {}).get("path")
    expected_change = item.get("change")
    if item.get("path") != path or expected_change not in PATH_CHANGES:
        raise VerificationError(f"prepared claim {claim['id']!r} has invalid path expectation")
    return expected_change


def _evaluate_prepared_path_claim(
    claim: dict[str, Any],
    expected_change: str,
    evidence: dict[str, dict[str, Any]],
    state: ArtifactState,
) -> dict[str, Any]:
    path = claim["evaluation"]["path"]
    base_present = path in state.initial_files
    head_present = path in state.final_files
    change_type = state.change_types.get(path)
    facts = {
        "added": not base_present and head_present and change_type == "added",
        "modified": (
            base_present
            and head_present
            and change_type == "modified"
            and state.initial_contents.get(path) != state.final_files.get(path)
        ),
        "deleted": base_present and not head_present and change_type == "deleted",
        "present": head_present,
        "absent": not head_present,
    }
    if not facts[expected_change]:
        return _finding(
            claim,
            "contradicted",
            f"The committed trees contradict the expected {expected_change} state for {path}.",
            evidence,
        )
    if not _capable_evidence(claim, evidence):
        return _finding(
            claim,
            "unsupported",
            f"No capable Git artifact evidence observes {path}.",
            evidence,
        )
    if claim.get("statement", "").strip() != _canonical_path_statement(path, expected_change):
        return _finding(
            claim,
            "unsupported",
            f"Git proves only that {path} is {expected_change}; the broader human wording was not interpreted.",
            evidence,
        )
    return _finding(
        claim,
        "verified",
        f"The committed trees verify that {path} is {expected_change}.",
        evidence,
    )


def _evaluate_claim(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]], state: ArtifactState
) -> dict[str, Any]:
    evaluation = claim.get("evaluation", {})
    predicate = evaluation.get("predicate")
    capable = _capable_evidence(claim, evidence)

    if predicate == "path_absent":
        path = evaluation.get("path")
        absent = path in state.initial_files and path not in state.final_files and path in state.changed_paths
        if absent and capable:
            return _finding(claim, "verified", f"The final artifact deletes {path}.", evidence)
        return _finding(claim, "contradicted", f"The final artifact does not delete {path}.", evidence)

    if predicate == "workflow_paths_equal":
        expected = tuple(evaluation.get("expected_values", []))
        actual = workflow_trigger_paths(state)
        target = {"push": expected, "pull_request": expected}
        if actual == target and capable:
            return _finding(claim, "verified", "Both workflow path filters match the claim.", evidence)
        if actual != target:
            return _finding(claim, "contradicted", "The workflow path filters contradict the claim.", evidence)
        return _finding(claim, "unsupported", "No capable evidence observes the workflow file.", evidence)

    if predicate == "execution_success":
        if any(item.get("execution_succeeded") is True for item in capable):
            return _finding(claim, "verified", "Structured execution evidence records success.", evidence)
        return _finding(claim, "unsupported", "No capable evidence records successful execution.", evidence)

    if predicate == "text_present":
        path = evaluation.get("path")
        expected_text = evaluation.get("expected_text")
        content = state.final_files.get(path, "")
        capable = [item for item in capable if item.get("artifact_path") == path]
        if expected_text not in content:
            return _finding(claim, "contradicted", "The inspected artifact does not contain the expected text.", evidence)
        if capable:
            return _finding(claim, "verified", "The inspected artifact contains the expected text.", evidence)
        return _finding(claim, "unsupported", "The text exists but no capable evidence observes it.", evidence)

    if predicate == "evidence_capability":
        expected_text = evaluation.get("expected_text")
        matching = capable
        if expected_text is not None:
            matching = [item for item in capable if item.get("observed_text") == expected_text]
        if evaluation.get("requires_authentication") is True:
            matching = [
                item
                for item in matching
                if item.get("kind") == "authenticated_external"
                and item.get("provenance", {}).get("authentication") == "authenticated"
                and item.get("provenance", {}).get("independently_verified") is True
            ]
        if matching:
            return _finding(claim, "verified", "Capable evidence observes the claimed outcome.", evidence)
        return _finding(claim, "unsupported", "Supplied evidence cannot observe the claimed outcome.", evidence)

    if predicate == "authenticated_evidence":
        authenticated = [
            item
            for item in capable
            if item.get("kind") == "authenticated_external"
            and item.get("provenance", {}).get("authentication") == "authenticated"
            and item.get("provenance", {}).get("independently_verified") is True
        ]
        if authenticated:
            return _finding(claim, "verified", "Authenticated capable evidence supports the claim.", evidence)
        return _finding(claim, "human_review_required", "Authenticated capable evidence is unavailable.", evidence)

    raise VerificationError(f"unsupported evaluation predicate {predicate!r}")


def aggregate_verdict(claim_results: list[dict[str, Any]]) -> str:
    statuses = [result["status"] for result in claim_results]
    if all(status == "verified" for status in statuses):
        return "verified"
    if "verified" in statuses:
        return "partially_verified"
    if "contradicted" in statuses:
        return "contradicted"
    if "unsupported" in statuses:
        return "unsupported"
    return "human_review_required"


def evaluate_case(bundle: FixtureBundle) -> dict[str, Any]:
    claims = _index(bundle.case["claims"], "claim")
    evidence = _index(bundle.case["evidence"], "evidence")
    _validate_relationships(claims, evidence)
    state = inspect_actual_state(bundle.fixture_dir)
    results: list[dict[str, Any]] = []
    for claim in claims.values():
        prepared_change = (
            _prepared_change_for_claim(bundle.case, claim)
            if state.source_kind == "prepared_git_range"
            else None
        )
        if prepared_change is None:
            results.append(_evaluate_claim(claim, evidence, state))
        else:
            results.append(
                _evaluate_prepared_path_claim(claim, prepared_change, evidence, state)
            )
    limitations: list[str] = []
    for result in results:
        for limitation in result["provenance_limitations"]:
            if limitation not in limitations:
                limitations.append(limitation)
    return {
        "case_id": bundle.case["id"],
        "claims": results,
        "overall_verdict": aggregate_verdict(results),
        "provenance_limitations": limitations,
        "sources": {
            "case": {
                "path": bundle.case_path.relative_to(bundle.repository_root).as_posix(),
                "sha256": bundle.case_sha256,
            },
            "schema": {
                "path": bundle.schema_reference,
                "sha256": bundle.schema_sha256,
            },
        },
    }


def evaluate_fixture_001(bundle: FixtureBundle) -> dict[str, Any]:
    return evaluate_case(bundle)
