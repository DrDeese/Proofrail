"""Evaluate fixture 001 claims and aggregate its deterministic verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import ArtifactState, inspect_actual_state, workflow_trigger_paths
from .loading import FixtureBundle


class VerificationError(ValueError):
    """Raised when fixture relationships or required claims are invalid."""


CLAIM_IDS = (
    "obsolete-lockfile-deleted",
    "workflow-triggers-updated",
    "green-run-proves-new-trigger",
    "change-merged",
)


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
    if tuple(claims) != CLAIM_IDS:
        raise VerificationError("fixture 001 claim set or order is materially altered")
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
        provenance = item.get("provenance", {})
        for limitation in provenance.get("limitations", []):
            if limitation not in result:
                result.append(limitation)
    return result


def _finding(
    claim_id: str,
    status: str,
    summary: str,
    evidence_ids: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "status": status,
        "finding": summary,
        "evidence_ids": evidence_ids,
        "provenance_limitations": limitations,
    }


def _evaluate_deletion(claim: dict[str, Any], state: ArtifactState) -> dict[str, Any]:
    deleted = (
        "bun.lockb" in state.initial_files
        and "bun.lockb" not in state.final_files
        and "bun.lockb" in state.changed_paths
    )
    status = "verified" if deleted else "contradicted"
    summary = (
        "The reconstructed final artifact deletes bun.lockb."
        if deleted
        else "The reconstructed final artifact does not contain the claimed bun.lockb deletion."
    )
    return _finding(claim["id"], status, summary, ["actual-commit-diff"], _limitations(claim))


def _evaluate_workflow(claim: dict[str, Any], state: ArtifactState) -> dict[str, Any]:
    paths = workflow_trigger_paths(state)
    updated = paths == {"push": ("bun.lock",), "pull_request": ("bun.lock",)}
    old_configuration = paths == {"push": ("bun.lockb",), "pull_request": ("bun.lockb",)}
    if updated:
        status = "verified"
        summary = "Both reconstructed workflow path filters reference bun.lock."
    elif old_configuration:
        status = "contradicted"
        summary = "The reconstructed workflow still references bun.lockb twice."
    else:
        status = "unsupported"
        summary = "The reconstructed workflow does not deterministically support either expected trigger state."
    return _finding(claim["id"], status, summary, ["actual-commit-diff"], _limitations(claim))


def _authenticated_evidence(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    for evidence_id in claim["evidence_ids"]:
        item = evidence[evidence_id]
        provenance = item.get("provenance", {})
        if (
            item.get("kind") == "authenticated_external"
            and provenance.get("authentication") == "authenticated"
            and provenance.get("independently_verified") is True
        ):
            return item
    return None


def _evaluate_run(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    authenticated = _authenticated_evidence(claim, evidence)
    referenced = [evidence[evidence_id] for evidence_id in claim["evidence_ids"]]
    status = "verified" if authenticated is not None else "unsupported"
    summary = (
        "Authenticated execution evidence verifies the claimed trigger outcome."
        if authenticated is not None
        else "Scenario-provided workflow information does not authenticate the claimed trigger outcome."
    )
    return _finding(
        claim["id"],
        status,
        summary,
        list(claim["evidence_ids"]),
        _limitations(claim, *referenced),
    )


def _evaluate_merge(
    claim: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    authenticated = _authenticated_evidence(claim, evidence)
    referenced = [evidence[evidence_id] for evidence_id in claim["evidence_ids"]]
    status = "verified" if authenticated is not None else "human_review_required"
    summary = (
        "Authenticated external evidence verifies the merge claim."
        if authenticated is not None
        else "No authenticated merge provenance is available in the offline fixture."
    )
    return _finding(
        claim["id"],
        status,
        summary,
        list(claim["evidence_ids"]),
        _limitations(claim, *referenced),
    )


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


def evaluate_fixture_001(bundle: FixtureBundle) -> dict[str, Any]:
    claims = _index(bundle.case["claims"], "claim")
    evidence = _index(bundle.case["evidence"], "evidence")
    _validate_relationships(claims, evidence)
    state = inspect_actual_state(bundle.fixture_dir)

    results = [
        _evaluate_deletion(claims["obsolete-lockfile-deleted"], state),
        _evaluate_workflow(claims["workflow-triggers-updated"], state),
        _evaluate_run(claims["green-run-proves-new-trigger"], evidence),
        _evaluate_merge(claims["change-merged"], evidence),
    ]
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
                "path": bundle.schema_path.relative_to(bundle.repository_root).as_posix(),
                "sha256": bundle.schema_sha256,
            },
        },
    }
