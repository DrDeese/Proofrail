#!/usr/bin/env python3
"""Validate fixture 001 against the repository's Draft 2020-12 case schema."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


class ValidationFailure(Exception):
    """Raised when an instance does not satisfy the schema subset used here."""


def fail(path: str, message: str) -> None:
    raise ValidationFailure(f"{path}: {message}")


def resolve_reference(root_schema: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        fail("$ref", f"only local references are supported, got {reference!r}")
    value: Any = root_schema
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            fail("$ref", f"unresolved reference {reference!r}")
        value = value[token]
    return value


def validate(instance: Any, schema: Any, root_schema: dict[str, Any], path: str = "$") -> None:
    if isinstance(schema, bool):
        if not schema:
            fail(path, "value is forbidden by the schema")
        return
    if not isinstance(schema, dict):
        fail(path, "schema node must be an object or boolean")

    if "$ref" in schema:
        validate(instance, resolve_reference(root_schema, schema["$ref"]), root_schema, path)
        return

    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "boolean": isinstance(instance, bool),
    }
    if expected_type is not None and not type_matches.get(expected_type, False):
        fail(path, f"expected {expected_type}, got {type(instance).__name__}")

    if "const" in schema and instance != schema["const"]:
        fail(path, f"expected constant {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        fail(path, f"{instance!r} is not one of {schema['enum']!r}")

    if isinstance(instance, str) and len(instance) < schema.get("minLength", 0):
        fail(path, "string is shorter than minLength")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                fail(path, f"missing required property {name!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(instance) - set(properties)
            if extras:
                fail(path, f"unexpected properties {sorted(extras)!r}")
        for name, value in instance.items():
            if name in properties:
                validate(value, properties[name], root_schema, f"{path}.{name}")

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            fail(path, "array is shorter than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            fail(path, "array is longer than maxItems")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            if len(encoded) != len(set(encoded)):
                fail(path, "array items are not unique")
        prefix_items = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix_items[: len(instance)]):
            validate(instance[index], item_schema, root_schema, f"{path}[{index}]")
        items_schema = schema.get("items")
        if items_schema is not None:
            start = len(prefix_items) if prefix_items else 0
            for index in range(start, len(instance)):
                validate(instance[index], items_schema, root_schema, f"{path}[{index}]")


def indexed(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item["id"]
        if item_id in result:
            fail(label, f"duplicate id {item_id!r}")
        result[item_id] = item
    return result


def validate_relationships(case: dict[str, Any]) -> None:
    claims = indexed(case["claims"], "$.claims")
    evidence = indexed(case["evidence"], "$.evidence")
    findings = indexed(case["findings"], "$.findings")

    for claim in claims.values():
        for evidence_id in claim["evidence_ids"]:
            if evidence_id not in evidence or claim["id"] not in evidence[evidence_id]["claim_ids"]:
                fail(f"$.claims[{claim['id']!r}]", f"invalid evidence relationship {evidence_id!r}")
        for finding_id in claim["finding_ids"]:
            if finding_id not in findings or findings[finding_id]["claim_id"] != claim["id"]:
                fail(f"$.claims[{claim['id']!r}]", f"invalid finding relationship {finding_id!r}")

    for item in evidence.values():
        for claim_id in item["claim_ids"]:
            if claim_id not in claims or item["id"] not in claims[claim_id]["evidence_ids"]:
                fail(f"$.evidence[{item['id']!r}]", f"non-reciprocal claim relationship {claim_id!r}")

    for finding in findings.values():
        if (
            finding["claim_id"] not in claims
            or finding["id"] not in claims[finding["claim_id"]]["finding_ids"]
        ):
            fail(f"$.findings[{finding['id']!r}]", "invalid claim relationship")
        for evidence_id in finding["evidence_ids"]:
            if evidence_id not in evidence:
                fail(f"$.findings[{finding['id']!r}]", f"unknown evidence id {evidence_id!r}")

    if set(case["verdict"]["finding_ids"]) != set(findings):
        fail("$.verdict.finding_ids", "verdict must reference every case finding exactly once")
    for finding_id in case["verdict"]["finding_ids"]:
        if finding_id not in findings:
            fail("$.verdict.finding_ids", f"unknown finding id {finding_id!r}")


def expect_rejected(label: str, case: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        validate(case, schema, schema)
        validate_relationships(case)
    except ValidationFailure as error:
        print(f"rejected invalid case ({label}): {error}")
        return
    raise AssertionError(f"invalid case was accepted: {label}")


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    schema_path = repository_root / "schemas" / "case.schema.json"
    case_path = repository_root / "tests" / "fixtures" / "001-partial-workflow-fix" / "case.json"

    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise AssertionError("case schema must declare JSON Schema Draft 2020-12")

    validate(case, schema, schema)
    validate_relationships(case)
    print(f"loaded schema: {schema_path.relative_to(repository_root)}")
    print(f"schema sha256: {hashlib.sha256(schema_bytes).hexdigest()}")
    print(f"validated fixture: {case_path.relative_to(repository_root)}")

    invalid_atomic_status = copy.deepcopy(case)
    invalid_atomic_status["claims"][0]["status"] = "partially_verified"
    expect_rejected("overall-only status used for atomic claim", invalid_atomic_status, schema)

    missing_relationship = copy.deepcopy(case)
    del missing_relationship["claims"][0]["evidence_ids"]
    expect_rejected("claim omitted evidence_ids", missing_relationship, schema)

    empty_finding_relationship = copy.deepcopy(case)
    empty_finding_relationship["claims"][0]["finding_ids"] = []
    expect_rejected("claim omitted required finding relationship", empty_finding_relationship, schema)

    broken_relationship = copy.deepcopy(case)
    broken_relationship["claims"][0]["evidence_ids"] = ["missing-evidence"]
    expect_rejected("claim referenced unknown evidence", broken_relationship, schema)

    nonreciprocal_relationship = copy.deepcopy(case)
    nonreciprocal_relationship["claims"][0]["evidence_ids"] = ["reported-workflow-run"]
    expect_rejected("claim and evidence relationship was not reciprocal", nonreciprocal_relationship, schema)

    invalid_evidence_kind = copy.deepcopy(case)
    invalid_evidence_kind["evidence"][0]["kind"] = "provider_result"
    expect_rejected("unknown evidence kind", invalid_evidence_kind, schema)

    invalid_stage_order = copy.deepcopy(case)
    invalid_stage_order["acceptance_stages"][3:5] = ["outcome_verified", "claim_supported"]
    expect_rejected("acceptance stages conflated or reordered", invalid_stage_order, schema)

    missing_provenance = copy.deepcopy(case)
    del missing_provenance["evidence"][0]["provenance"]
    expect_rejected("evidence omitted provenance", missing_provenance, schema)

    missing_claim_provenance = copy.deepcopy(case)
    del missing_claim_provenance["claims"][0]["provenance"]
    expect_rejected("claim omitted provenance", missing_claim_provenance, schema)

    invalid_overall_verdict = copy.deepcopy(case)
    invalid_overall_verdict["verdict"]["status"] = "partially-supported"
    expect_rejected("unknown overall verdict", invalid_overall_verdict, schema)

    print("schema validation passed")


if __name__ == "__main__":
    main()
