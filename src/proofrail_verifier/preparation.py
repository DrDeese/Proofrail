"""Prepare self-contained Proofrail cases from local committed Git trees."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactInspectionError
from .claim_file import AtomicClaim, ParsedClaim, parse_claim_file
from .evaluation import VerificationError, evaluate_case
from .git_source import (
    blob_at,
    changed_paths,
    commit_metadata,
    diff_patch,
    resolve_commit,
    resolve_repository,
    validate_range,
)
from .loading import FixtureLoadError, load_case_directory, resolve_case_schema
from .preparation_errors import (
    InvalidPreparationInput,
    OutputWriteFailure,
    PreparationFailure,
)
from .schema_validation import SchemaValidationError, validate


@dataclass(frozen=True)
class PreparationResult:
    case_id: str
    base_sha: str
    head_sha: str
    output_dir: Path
    claim_count: int
    changed_path_count: int


def _portable_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _write_bytes(root: Path, relative: str, content: bytes) -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _claim_evaluation(claim: AtomicClaim) -> dict[str, Any]:
    if claim.expected_change in {"deleted", "absent"}:
        return {"predicate": "path_absent", "path": claim.expected_path}
    return {
        "predicate": "text_present",
        "path": claim.expected_path,
        "expected_text": f"Committed path predicate: {claim.expected_change}",
    }


def _initial_case(
    parsed: ParsedClaim, base_sha: str, head_sha: str
) -> dict[str, Any]:
    case_id = f"git-range-{base_sha[:12]}-{head_sha[:12]}"
    claims: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    required_changes: list[dict[str, str]] = []
    for claim in parsed.atomic_claims:
        evidence_id = f"git-path-{claim.claim_id}"
        finding_id = f"finding-{claim.claim_id}"
        required_changes.append(
            {
                "path": claim.expected_path,
                "location": f"claim:{claim.claim_id}",
                "change": claim.expected_change,
            }
        )
        claims.append(
            {
                "id": claim.claim_id,
                "statement": claim.statement,
                "acceptance_stage": "claim_supported",
                "status": "unsupported",
                "required_observation": "file_contents",
                "evaluation": _claim_evaluation(claim),
                "evidence_ids": [evidence_id],
                "finding_ids": [finding_id],
                "provenance": {
                    "source_type": "scenario_document",
                    "authentication": "unauthenticated",
                    "independently_verified": False,
                    "limitations": [
                        "The human-supplied completion statement is unauthenticated.",
                        "Only the explicit expected-path and expected-change fields are evaluated; broader wording remains unverified.",
                    ],
                },
            }
        )
        evidence.append(
            {
                "id": evidence_id,
                "kind": "artifact_derived",
                "summary": f"Committed-tree and range evidence for {claim.expected_path}.",
                "acceptance_stage": "artifact_changed",
                "observation_method": (
                    "file_inspection"
                    if claim.expected_change in {"present", "absent"}
                    else "git_diff"
                ),
                "observes": ["file_contents"],
                "artifact_path": claim.expected_path,
                "claim_ids": [claim.claim_id],
                "provenance": {
                    "source_type": "git_artifact",
                    "authentication": "not_applicable",
                    "independently_verified": True,
                    "limitations": [
                        "Git establishes committed-tree path facts, not behavioral outcomes.",
                        "Commit authorship and timestamps are recorded but not externally authenticated.",
                    ],
                },
            }
        )
        findings.append(
            {
                "id": finding_id,
                "claim_id": claim.claim_id,
                "evidence_ids": [evidence_id],
                "acceptance_stage": "claim_supported",
                "result": "insufficient",
                "summary": "Prepared path evidence has not yet been evaluated.",
                "provenance": {
                    "source_type": "deterministic_validation",
                    "authentication": "not_applicable",
                    "independently_verified": True,
                    "limitations": [],
                },
            }
        )
    return {
        "id": case_id,
        "title": f"Prepared Git range {base_sha[:12]}..{head_sha[:12]}",
        "source": f"local-git-commit-range:{base_sha}..{head_sha}",
        "requested_change": {
            "summary": parsed.overall_statement,
            "required_artifact_changes": required_changes,
        },
        "agent_completion_claim": parsed.text,
        "acceptance_stages": [
            "attempted",
            "executed",
            "artifact_changed",
            "claim_supported",
            "outcome_verified",
        ],
        "claims": claims,
        "evidence": evidence,
        "findings": findings,
        "verdict": {
            "status": "unsupported",
            "explanation": "Prepared path evidence has not yet been evaluated.",
            "finding_ids": [item["id"] for item in findings],
        },
    }


def _synchronize_case_results(case: dict[str, Any], result: dict[str, Any]) -> None:
    result_by_id = {item["claim_id"]: item for item in result["claims"]}
    findings = {item["claim_id"]: item for item in case["findings"]}
    counts: dict[str, int] = {}
    for claim in case["claims"]:
        evaluated = result_by_id[claim["id"]]
        status = evaluated["status"]
        claim["status"] = status
        finding = findings[claim["id"]]
        finding["result"] = {
            "verified": "supports",
            "contradicted": "contradicts",
            "unsupported": "insufficient",
            "human_review_required": "insufficient",
        }[status]
        finding["summary"] = evaluated["finding"]
        counts[status] = counts.get(status, 0) + 1
    case["verdict"]["status"] = result["overall_verdict"]
    count_summary = ", ".join(
        f"{status}={counts[status]}" for status in sorted(counts)
    )
    case["verdict"]["explanation"] = (
        "Deterministic committed-tree path evaluation produced " + count_summary + "."
    )


def _materialize_case(
    staging: Path,
    repository: Path,
    parsed: ParsedClaim,
    base_sha: str,
    head_sha: str,
    changes: list[dict[str, str]],
    schema_path: Path,
) -> str:
    case = _initial_case(parsed, base_sha, head_sha)
    _write_bytes(staging, "schema/case.schema.json", schema_path.read_bytes())
    _write_bytes(staging, "source/completion-claim.md", parsed.text.encode("utf-8"))
    _write_bytes(
        staging,
        "git/changed-files.json",
        _portable_json({"base_sha": base_sha, "head_sha": head_sha, "paths": changes}),
    )
    _write_bytes(
        staging,
        "git/commit-metadata.json",
        _portable_json(
            {
                "base": commit_metadata(repository, base_sha),
                "head": commit_metadata(repository, head_sha),
            }
        ),
    )
    _write_bytes(staging, "git/diff.patch", diff_patch(repository, base_sha, head_sha))

    for path in sorted({claim.expected_path for claim in parsed.atomic_claims}):
        base_blob = blob_at(repository, base_sha, path)
        head_blob = blob_at(repository, head_sha, path)
        if base_blob is not None:
            _write_bytes(staging, f"artifacts/base/{path}", base_blob.content)
        if head_blob is not None:
            _write_bytes(staging, f"artifacts/head/{path}", head_blob.content)
    (staging / "artifacts" / "base").mkdir(parents=True, exist_ok=True)
    (staging / "artifacts" / "head").mkdir(parents=True, exist_ok=True)

    _write_bytes(staging, "case.json", _portable_json(case))
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validate(case, schema, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationError) as error:
        raise PreparationFailure(f"generated case does not satisfy the repository schema: {error}") from error
    try:
        result = evaluate_case(load_case_directory(staging))
    except (
        ArtifactInspectionError,
        FixtureLoadError,
        VerificationError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise PreparationFailure(f"generated case cannot be verified: {error}") from error
    _synchronize_case_results(case, result)
    _write_bytes(staging, "case.json", _portable_json(case))
    try:
        final_result = evaluate_case(load_case_directory(staging))
    except (
        ArtifactInspectionError,
        FixtureLoadError,
        VerificationError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise PreparationFailure(f"final generated case cannot be verified: {error}") from error
    if [item["status"] for item in final_result["claims"]] != [
        item["status"] for item in case["claims"]
    ] or final_result["overall_verdict"] != case["verdict"]["status"]:
        raise PreparationFailure("generated case result changed after final rendering")
    return case["id"]


def prepare_case(
    repository_path: Path,
    base_ref: str,
    head_ref: str,
    claim_file: Path,
    output_dir: Path,
) -> PreparationResult:
    repository = resolve_repository(repository_path)
    parsed = parse_claim_file(claim_file)
    base_sha = resolve_commit(repository, base_ref, "base")
    head_sha = resolve_commit(repository, head_ref, "head")
    validate_range(repository, base_sha, head_sha)
    changes = changed_paths(repository, base_sha, head_sha)

    try:
        schema_path = resolve_case_schema()
    except FixtureLoadError as error:
        raise PreparationFailure("repository case schema is unavailable") from error

    if output_dir.is_symlink():
        raise OutputWriteFailure("output directory must not be a symbolic link")
    if output_dir.exists():
        raise OutputWriteFailure("output directory already exists; refusing to overwrite it")
    try:
        output_parent = output_dir.parent.resolve(strict=True)
    except OSError as error:
        raise OutputWriteFailure(f"output parent is unavailable: {error}") from error
    resolved_output = output_parent / output_dir.name
    if not output_dir.name or _inside(resolved_output, repository):
        raise OutputWriteFailure("output directory must be outside the source repository")

    staging: Path | None = None
    try:
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_parent)
        )
        case_id = _materialize_case(
            staging,
            repository,
            parsed,
            base_sha,
            head_sha,
            changes,
            schema_path,
        )
        os.replace(staging, resolved_output)
        staging = None
    except (InvalidPreparationInput, PreparationFailure):
        raise
    except OSError as error:
        raise OutputWriteFailure(f"cannot write prepared case: {error}") from error
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)

    return PreparationResult(
        case_id=case_id,
        base_sha=base_sha,
        head_sha=head_sha,
        output_dir=resolved_output,
        claim_count=len(parsed.atomic_claims),
        changed_path_count=len(changes),
    )
