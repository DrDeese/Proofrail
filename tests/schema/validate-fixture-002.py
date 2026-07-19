#!/usr/bin/env python3
"""Validate fixture 002 using the repository's existing schema test support."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    schema_path = repository_root / "schemas" / "case.schema.json"
    case_path = repository_root / "tests" / "fixtures" / "002-incapable-validation-command" / "case.json"
    support = runpy.run_path(str(Path(__file__).with_name("validate-fixture-001.py")), run_name="schema_support")
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    support["validate"](case, schema, schema)
    support["validate_relationships"](case)
    print(f"loaded schema: {schema_path.relative_to(repository_root)}")
    print(f"schema sha256: {hashlib.sha256(schema_bytes).hexdigest()}")
    print(f"validated fixture: {case_path.relative_to(repository_root)}")
    print("fixture 002 schema validation passed")


if __name__ == "__main__":
    main()
