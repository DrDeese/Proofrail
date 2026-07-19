"""Load a deterministic case directory and its declared repository schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate


class FixtureLoadError(ValueError):
    """Raised when fixture inputs are missing or structurally unusable."""


@dataclass(frozen=True)
class FixtureBundle:
    case: dict[str, Any]
    repository_root: Path
    fixture_dir: Path
    case_path: Path
    schema_path: Path
    case_sha256: str
    schema_sha256: str


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise FixtureLoadError(f"cannot read {path.name}: {error.strerror or error}") from error
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixtureLoadError(f"invalid JSON in {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise FixtureLoadError(f"expected JSON object in {path}")
    return value, hashlib.sha256(content).hexdigest()


def _validate_case_structure(case: dict[str, Any]) -> None:
    for field in ("id", "claims", "evidence", "findings", "verdict"):
        if field not in case:
            raise FixtureLoadError(f"case is missing {field!r}")
    if not isinstance(case["id"], str) or not case["id"]:
        raise FixtureLoadError("case id must be a non-empty string")
    for field in ("claims", "evidence", "findings"):
        if not isinstance(case[field], list):
            raise FixtureLoadError(f"case field {field!r} must be an array")
    if not isinstance(case["verdict"], dict):
        raise FixtureLoadError("case verdict must be an object")
    for index, claim in enumerate(case["claims"]):
        required = ("id", "required_observation", "evaluation", "evidence_ids", "provenance")
        if not isinstance(claim, dict) or any(field not in claim for field in required):
            raise FixtureLoadError(f"claim at index {index} has invalid structure")
        if not isinstance(claim["evaluation"], dict):
            raise FixtureLoadError(f"claim at index {index} has invalid evaluation")
    for index, evidence in enumerate(case["evidence"]):
        required = ("id", "observation_method", "observes", "claim_ids", "provenance")
        if not isinstance(evidence, dict) or any(field not in evidence for field in required):
            raise FixtureLoadError(f"evidence at index {index} has invalid structure")


def _load_bundle(root: Path, fixture_dir: Path) -> FixtureBundle:
    case_path = fixture_dir / "case.json"
    schema_path = root / "schemas" / "case.schema.json"
    case, case_sha256 = _load_json(case_path)
    schema, schema_sha256 = _load_json(schema_path)

    if (
        schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("type") != "object"
        or not isinstance(schema.get("$defs"), dict)
    ):
        raise FixtureLoadError("fixture schema must declare JSON Schema Draft 2020-12")
    try:
        validate(case, schema, schema)
    except SchemaValidationError as error:
        raise FixtureLoadError(f"case does not satisfy schema: {error}") from error
    _validate_case_structure(case)
    if case["id"] != fixture_dir.name:
        raise FixtureLoadError("fixture directory and case id differ")

    return FixtureBundle(
        case=case,
        repository_root=root,
        fixture_dir=fixture_dir,
        case_path=case_path,
        schema_path=schema_path,
        case_sha256=case_sha256,
        schema_sha256=schema_sha256,
    )


def load_case(repository_root: Path, fixture_name: str) -> FixtureBundle:
    root = repository_root.resolve()
    return _load_bundle(root, root / "tests" / "fixtures" / fixture_name)


def load_case_directory(case_directory: Path) -> FixtureBundle:
    fixture_dir = case_directory.resolve()
    if not fixture_dir.is_dir():
        raise FixtureLoadError(f"case directory does not exist: {case_directory}")
    root = next(
        (
            candidate
            for candidate in fixture_dir.parents
            if (candidate / "schemas" / "case.schema.json").is_file()
        ),
        None,
    )
    if root is None:
        raise FixtureLoadError("cannot locate schemas/case.schema.json above case directory")
    return _load_bundle(root, fixture_dir)


def load_fixture_001(repository_root: Path) -> FixtureBundle:
    return load_case(repository_root, "001-partial-workflow-fix")
