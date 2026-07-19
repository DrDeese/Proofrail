"""Load a deterministic fixture and its declared schema from repository files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    content = path.read_bytes()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise FixtureLoadError(f"expected JSON object in {path}")
    return value, hashlib.sha256(content).hexdigest()


def load_case(repository_root: Path, fixture_name: str) -> FixtureBundle:
    root = repository_root.resolve()
    fixture_dir = root / "tests" / "fixtures" / fixture_name
    case_path = fixture_dir / "case.json"
    schema_path = root / "schemas" / "case.schema.json"
    case, case_sha256 = _load_json(case_path)
    schema, schema_sha256 = _load_json(schema_path)

    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise FixtureLoadError("fixture schema must declare JSON Schema Draft 2020-12")
    if case.get("id") != fixture_name:
        raise FixtureLoadError("fixture directory and case id differ")
    for field in ("claims", "evidence", "findings", "verdict"):
        if field not in case:
            raise FixtureLoadError(f"fixture case is missing {field!r}")

    return FixtureBundle(
        case=case,
        repository_root=root,
        fixture_dir=fixture_dir,
        case_path=case_path,
        schema_path=schema_path,
        case_sha256=case_sha256,
        schema_sha256=schema_sha256,
    )


def load_fixture_001(repository_root: Path) -> FixtureBundle:
    return load_case(repository_root, "001-partial-workflow-fix")
