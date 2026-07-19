"""Validate the small JSON Schema subset used by Proofrail case files."""

from __future__ import annotations

import json
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a case does not satisfy the loaded repository schema."""


def _fail(path: str, message: str) -> None:
    raise SchemaValidationError(f"{path}: {message}")


def _resolve(root: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        _fail("$ref", f"unsupported non-local reference {reference!r}")
    value: Any = root
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            _fail("$ref", f"unresolved reference {reference!r}")
        value = value[token]
    return value


def validate(instance: Any, schema: Any, root: dict[str, Any], path: str = "$") -> None:
    if isinstance(schema, bool):
        if not schema:
            _fail(path, "value is forbidden by the schema")
        return
    if not isinstance(schema, dict):
        _fail(path, "schema node must be an object or boolean")
    if "$ref" in schema:
        validate(instance, _resolve(root, schema["$ref"]), root, path)
        return

    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "boolean": isinstance(instance, bool),
    }
    if expected_type is not None and not type_matches.get(expected_type, False):
        _fail(path, f"expected {expected_type}, got {type(instance).__name__}")
    if "const" in schema and instance != schema["const"]:
        _fail(path, f"expected constant {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        _fail(path, f"{instance!r} is not one of {schema['enum']!r}")
    if isinstance(instance, str) and len(instance) < schema.get("minLength", 0):
        _fail(path, "string is shorter than minLength")

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                _fail(path, f"missing required property {name!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(instance) - set(properties)
            if extras:
                _fail(path, f"unexpected properties {sorted(extras)!r}")
        for name, value in instance.items():
            if name in properties:
                validate(value, properties[name], root, f"{path}.{name}")

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            _fail(path, "array is shorter than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            _fail(path, "array is longer than maxItems")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            if len(encoded) != len(set(encoded)):
                _fail(path, "array items are not unique")
        prefix_items = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix_items[: len(instance)]):
            validate(instance[index], item_schema, root, f"{path}[{index}]")
        if "items" in schema:
            start = len(prefix_items) if prefix_items else 0
            for index in range(start, len(instance)):
                validate(instance[index], schema["items"], root, f"{path}[{index}]")
