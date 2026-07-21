"""Load a deterministic case directory and its declared repository schema."""

from __future__ import annotations

import hashlib
import json
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate


class FixtureLoadError(ValueError):
    """Raised when fixture inputs are missing or structurally unusable."""


def _source_case_schema() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "case.schema.json"


def resolve_case_schema() -> Path:
    """Locate the canonical schema from a checkout or installed package data."""
    source_schema = _source_case_schema()
    if source_schema.is_file():
        return source_schema
    data_path = sysconfig.get_path("data")
    if data_path is not None:
        packaged_schema = Path(data_path) / "proofrail_verifier" / "case.schema.json"
        if packaged_schema.is_file():
            return packaged_schema
    raise FixtureLoadError(
        "cannot locate canonical case schema in the source checkout or installed package data"
    )


@dataclass(frozen=True)
class FixtureBundle:
    case: dict[str, Any]
    repository_root: Path
    fixture_dir: Path
    case_path: Path
    schema_path: Path
    schema_reference: str
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


def _load_bundle(
    root: Path,
    fixture_dir: Path,
    schema_path: Path | None = None,
    schema_reference: str | None = None,
) -> FixtureBundle:
    case_path = fixture_dir / "case.json"
    schema_path = schema_path or root / "schemas" / "case.schema.json"
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
    if schema_path.parent.name == "schemas" and case["id"] != fixture_dir.name:
        raise FixtureLoadError("fixture directory and case id differ")

    if schema_reference is None:
        schema_reference = schema_path.relative_to(root).as_posix()
    return FixtureBundle(
        case=case,
        repository_root=root,
        fixture_dir=fixture_dir,
        case_path=case_path,
        schema_path=schema_path,
        schema_reference=schema_reference,
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
    self_contained_schema = fixture_dir / "schema" / "case.schema.json"
    if self_contained_schema.is_file():
        return _load_bundle(fixture_dir, fixture_dir, self_contained_schema)
    root = next(
        (
            candidate
            for candidate in fixture_dir.parents
            if (candidate / "schemas" / "case.schema.json").is_file()
        ),
        None,
    )
    if root is not None:
        return _load_bundle(root, fixture_dir)
    if _source_case_schema().is_file():
        raise FixtureLoadError("cannot locate schemas/case.schema.json above case directory")
    return _load_bundle(
        fixture_dir,
        fixture_dir,
        resolve_case_schema(),
        "proofrail_verifier/case.schema.json",
    )


def load_fixture_001(repository_root: Path) -> FixtureBundle:
    return load_case(repository_root, "001-partial-workflow-fix")
