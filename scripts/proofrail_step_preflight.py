#!/usr/bin/env python3
"""Deterministic, fail-closed preflight for an explicit Proofrail step contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
from typing import Any


CHECK_IDS = (
    "contract",
    "workflow-yaml",
    "action-tests",
    "end-to-end-tests",
    "policy-tests",
    "diff-check",
    "authorized-files",
    "stale-identifiers",
    "contract-source",
)
VALID_STATUSES = {
    "verified",
    "unsupported",
    "contradicted",
    "human_review_required",
}
VALID_VERDICTS = VALID_STATUSES | {"partially_verified"}
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class InputFailure(Exception):
    """Invalid contract, repository, base commit, or source input."""


class ExecutionFailure(Exception):
    """A parser, comparison, launch, or preflight operation could not complete."""


class PublicationFailure(Exception):
    """The deterministic report could not be published."""


class YamlFailure(Exception):
    """The bounded YAML subset was violated."""


class _Lines:
    def __init__(self, text: str, *, contract: bool) -> None:
        if "\t" in text:
            raise YamlFailure("tabs are not allowed")
        if contract and re.search(r"(^|[\s:\[,])(?:&|\*)[^\s]+", text):
            raise YamlFailure("YAML aliases and anchors are not allowed")
        if contract and re.search(r"(^|[\s:\[,])![^\s]+", text):
            raise YamlFailure("YAML tags and constructors are not allowed")
        if contract and ("${" in text or "$(" in text or "<<:" in text or "%YAML" in text):
            raise YamlFailure("YAML expressions, merge keys, and directives are not allowed")
        self.items: list[tuple[int, str, int]] = []
        for number, raw in enumerate(text.splitlines(), 1):
            if raw.rstrip() != raw:
                raise YamlFailure(f"trailing whitespace at line {number}")
            stripped = raw.lstrip(" ")
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw) - len(stripped)
            if indent % 2:
                raise YamlFailure(f"indentation must use two spaces at line {number}")
            self.items.append((indent, stripped, number))


def _scalar(value: str, line: int, *, contract: bool) -> Any:
    if value == "[]":
        return []
    if value in {"{}", "null", "~"}:
        if value == "{}":
            return {}
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        return int(value)
    if value.startswith(('"', "'")):
        if value.startswith("'"):
            if not value.endswith("'"):
                raise YamlFailure(f"unterminated string at line {line}")
            return value[1:-1].replace("''", "'")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise YamlFailure(f"invalid quoted string at line {line}") from error
        if not isinstance(parsed, str):
            raise YamlFailure(f"quoted scalar must be a string at line {line}")
        return parsed
    if contract and any(character in value for character in "{}[]`"):
        raise YamlFailure(f"flow values, scripts, and expressions are not allowed at line {line}")
    return value


def _pair(content: str, line: int) -> tuple[str, str]:
    if ":" not in content:
        raise YamlFailure(f"mapping entry lacks ':' at line {line}")
    key, value = content.split(":", 1)
    if not key or key.strip() != key or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
        raise YamlFailure(f"invalid mapping key at line {line}")
    return key, value.lstrip(" ")


def _parse_node(lines: _Lines, index: int, indent: int, *, contract: bool) -> tuple[Any, int]:
    if index >= len(lines.items) or lines.items[index][0] != indent:
        raise YamlFailure("invalid indentation")
    if lines.items[index][1].startswith("- "):
        return _parse_sequence(lines, index, indent, contract=contract)
    return _parse_mapping(lines, index, indent, contract=contract)


def _value_after_pair(
    lines: _Lines,
    index: int,
    indent: int,
    value: str,
    line: int,
    *,
    contract: bool,
) -> tuple[Any, int]:
    if value in {"|", ">"}:
        if contract:
            raise YamlFailure(f"block scalars are not allowed at line {line}")
        collected: list[str] = []
        next_index = index + 1
        while next_index < len(lines.items) and lines.items[next_index][0] > indent:
            collected.append(lines.items[next_index][1])
            next_index += 1
        return "\n".join(collected), next_index
    if value:
        return _scalar(value, line, contract=contract), index + 1
    next_index = index + 1
    if next_index < len(lines.items) and lines.items[next_index][0] > indent:
        child_indent = lines.items[next_index][0]
        if child_indent != indent + 2:
            raise YamlFailure(f"invalid nested indentation after line {line}")
        return _parse_node(lines, next_index, child_indent, contract=contract)
    return None, next_index


def _parse_mapping(lines: _Lines, index: int, indent: int, *, contract: bool) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines.items):
        current_indent, content, line = lines.items[index]
        if current_indent < indent:
            break
        if current_indent != indent or content.startswith("- "):
            break
        key, raw_value = _pair(content, line)
        if key in result:
            raise YamlFailure(f"duplicate key {key!r} at line {line}")
        result[key], index = _value_after_pair(
            lines, index, indent, raw_value, line, contract=contract
        )
    return result, index


def _parse_sequence(lines: _Lines, index: int, indent: int, *, contract: bool) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines.items):
        current_indent, content, line = lines.items[index]
        if current_indent < indent:
            break
        if current_indent != indent or not content.startswith("- "):
            break
        item = content[2:]
        if not item:
            if index + 1 >= len(lines.items) or lines.items[index + 1][0] != indent + 2:
                raise YamlFailure(f"empty sequence item at line {line}")
            value, index = _parse_node(lines, index + 1, indent + 2, contract=contract)
            result.append(value)
            continue
        if ":" in item and re.match(r"[A-Za-z0-9_.-]+:", item):
            key, raw_value = _pair(item, line)
            mapping: dict[str, Any] = {}
            mapping[key], index = _value_after_pair(
                lines, index, indent, raw_value, line, contract=contract
            )
            if index < len(lines.items) and lines.items[index][0] == indent + 2:
                continuation, index = _parse_mapping(lines, index, indent + 2, contract=contract)
                for continuation_key, continuation_value in continuation.items():
                    if continuation_key in mapping:
                        raise YamlFailure(f"duplicate key {continuation_key!r}")
                    mapping[continuation_key] = continuation_value
            result.append(mapping)
        else:
            result.append(_scalar(item, line, contract=contract))
            index += 1
    return result, index


def parse_bounded_yaml(text: str, *, contract: bool) -> Any:
    lines = _Lines(text, contract=contract)
    if not lines.items:
        raise YamlFailure("YAML document is empty")
    if lines.items[0][0] != 0:
        raise YamlFailure("top-level content must start at column zero")
    value, index = _parse_node(lines, 0, 0, contract=contract)
    if index != len(lines.items):
        raise YamlFailure(f"unparsed content at line {lines.items[index][2]}")
    return value


def _require_keys(value: Any, required: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputFailure(f"{where} must be a mapping")
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    if missing:
        raise InputFailure(f"{where} missing keys: {', '.join(missing)}")
    if unknown:
        raise InputFailure(f"{where} unknown keys: {', '.join(unknown)}")
    return value


def _path(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise InputFailure(f"{where} must be a non-empty repository-relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or "\\" in value
        or "//" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise InputFailure(f"{where} is not a normalized repository-relative path")
    return value


def _string_list(value: Any, where: str, *, paths: bool = False, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise InputFailure(f"{where} must be {'a non-empty ' if nonempty else ''}list")
    result: list[str] = []
    for index, item in enumerate(value):
        if paths:
            result.append(_path(item, f"{where}[{index}]"))
        elif not isinstance(item, str) or not item:
            raise InputFailure(f"{where}[{index}] must be a non-empty string")
        else:
            result.append(item)
    if len(result) != len(set(result)):
        raise InputFailure(f"{where} contains duplicates")
    return result


def _validate_test(value: Any, where: str, expected_directory: str) -> dict[str, list[str]]:
    mapping = _require_keys(value, {"command"}, where)
    command = _string_list(mapping["command"], f"{where}.command", nonempty=True)
    if len(command) != 7 or command[:5] != ["python3", "-m", "unittest", "discover", "-s"] or command[-1] != "-v":
        raise InputFailure(f"{where}.command must be a bounded unittest argument array")
    _path(command[5], f"{where}.command test directory")
    if command[5] != expected_directory:
        raise InputFailure(f"{where}.command must select {expected_directory}")
    return {"command": command}


def validate_contract(value: Any, schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict) or schema.get("title") != "Proofrail step preflight contract":
        raise InputFailure("step contract schema source is invalid")
    root = _require_keys(
        value,
        {"version", "step", "base-sha", "workflow", "tests", "authorized-files", "expectations", "security", "stale-identifiers"},
        "contract",
    )
    if root["version"] != 1:
        raise InputFailure("contract.version must equal 1")
    if isinstance(root["step"], bool) or not isinstance(root["step"], int) or root["step"] < 1:
        raise InputFailure("contract.step must be a positive integer")
    if not isinstance(root["base-sha"], str) or not SHA_RE.fullmatch(root["base-sha"]):
        raise InputFailure("contract.base-sha must be a full lowercase Git SHA")
    workflow = _require_keys(root["workflow"], {"path"}, "contract.workflow")
    workflow_path = _path(workflow["path"], "contract.workflow.path")
    tests = _require_keys(root["tests"], {"action", "end-to-end", "policy"}, "contract.tests")
    directories = {"action": "tests/action", "end-to-end": "tests/end_to_end", "policy": "tests/policy"}
    validated_tests = {
        name: _validate_test(tests[name], f"contract.tests.{name}", directories[name]) for name in tests
    }
    authorized = _string_list(root["authorized-files"], "contract.authorized-files", paths=True, nonempty=True)

    expectations = _require_keys(
        root["expectations"],
        {"claim-statuses", "overall-verdict", "policy-accepted", "allowed-statuses-source", "exceptions-applied", "fixture-verdicts"},
        "contract.expectations",
    )
    claims = expectations["claim-statuses"]
    if not isinstance(claims, dict) or not claims:
        raise InputFailure("contract.expectations.claim-statuses must be a non-empty mapping")
    for claim_id, status in claims.items():
        if not isinstance(claim_id, str) or not claim_id or status not in VALID_STATUSES:
            raise InputFailure("contract.expectations.claim-statuses contains an invalid claim or status")
    if expectations["overall-verdict"] not in VALID_VERDICTS:
        raise InputFailure("contract.expectations.overall-verdict is invalid")
    if not isinstance(expectations["policy-accepted"], bool):
        raise InputFailure("contract.expectations.policy-accepted must be boolean")
    if not isinstance(expectations["allowed-statuses-source"], str) or not expectations["allowed-statuses-source"]:
        raise InputFailure("contract.expectations.allowed-statuses-source must be a non-empty string")
    exceptions = _string_list(expectations["exceptions-applied"], "contract.expectations.exceptions-applied")
    fixtures = expectations["fixture-verdicts"]
    if not isinstance(fixtures, dict) or not fixtures or any(
        not isinstance(key, str) or not key or verdict not in VALID_VERDICTS for key, verdict in fixtures.items()
    ):
        raise InputFailure("contract.expectations.fixture-verdicts is invalid")

    security = _require_keys(root["security"], {"permissions", "approved-actions", "fetch-depth", "persist-credentials"}, "contract.security")
    permissions = security["permissions"]
    if not isinstance(permissions, dict) or not permissions or any(
        not isinstance(key, str) or not key or access not in {"read", "none"} for key, access in permissions.items()
    ):
        raise InputFailure("contract.security.permissions is invalid")
    approved_actions = _string_list(security["approved-actions"], "contract.security.approved-actions", nonempty=True)
    if isinstance(security["fetch-depth"], bool) or not isinstance(security["fetch-depth"], int) or security["fetch-depth"] < 0:
        raise InputFailure("contract.security.fetch-depth must be a non-negative integer")
    if not isinstance(security["persist-credentials"], bool):
        raise InputFailure("contract.security.persist-credentials must be boolean")

    stale = root["stale-identifiers"]
    if not isinstance(stale, list):
        raise InputFailure("contract.stale-identifiers must be a list")
    stale_values: set[str] = set()
    validated_stale: list[dict[str, Any]] = []
    for index, entry in enumerate(stale):
        item = _require_keys(entry, {"value", "owner-step", "allowed-files"}, f"contract.stale-identifiers[{index}]")
        if not isinstance(item["value"], str) or not item["value"]:
            raise InputFailure(f"contract.stale-identifiers[{index}].value must be a non-empty string")
        if item["value"] in stale_values:
            raise InputFailure("contract.stale-identifiers contains duplicate values")
        stale_values.add(item["value"])
        if isinstance(item["owner-step"], bool) or not isinstance(item["owner-step"], int) or item["owner-step"] < 1:
            raise InputFailure(f"contract.stale-identifiers[{index}].owner-step must be positive")
        validated_stale.append({
            "value": item["value"],
            "owner-step": item["owner-step"],
            "allowed-files": _string_list(item["allowed-files"], f"contract.stale-identifiers[{index}].allowed-files", paths=True),
        })

    return {
        "version": 1,
        "step": root["step"],
        "base-sha": root["base-sha"],
        "workflow": {"path": workflow_path},
        "tests": validated_tests,
        "authorized-files": authorized,
        "expectations": {
            "claim-statuses": dict(claims),
            "overall-verdict": expectations["overall-verdict"],
            "policy-accepted": expectations["policy-accepted"],
            "allowed-statuses-source": expectations["allowed-statuses-source"],
            "exceptions-applied": exceptions,
            "fixture-verdicts": dict(fixtures),
        },
        "security": {
            "permissions": dict(permissions),
            "approved-actions": approved_actions,
            "fetch-depth": security["fetch-depth"],
            "persist-credentials": security["persist-credentials"],
        },
        "stale-identifiers": validated_stale,
    }


def _inside(repository: Path, supplied: str, *, must_exist: bool, reject_symlink: bool) -> tuple[Path, str]:
    relative = _path(supplied, "path")
    candidate = repository / relative
    if reject_symlink and candidate.is_symlink():
        raise InputFailure(f"symlink path is not allowed: {relative}")
    parent = candidate.parent.resolve(strict=True)
    root = repository.resolve(strict=True)
    if parent != root and root not in parent.parents:
        raise InputFailure(f"path escapes repository: {relative}")
    if must_exist and not candidate.is_file():
        raise InputFailure(f"file does not exist: {relative}")
    if must_exist and candidate.resolve(strict=True) != candidate.absolute():
        raise InputFailure(f"symlink component is not allowed: {relative}")
    return candidate, relative


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def _git(repository: Path, arguments: list[str], *, binary: bool = False) -> bytes | str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *arguments]
    try:
        completed = subprocess.run(command, cwd=repository, env=_git_env(), shell=False, capture_output=True)
    except OSError as error:
        raise ExecutionFailure("failed to launch Git") from error
    if completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
        sys.stderr.buffer.flush()
    if completed.returncode:
        raise ExecutionFailure(f"Git command failed: {' '.join(arguments)}")
    if binary:
        return completed.stdout
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExecutionFailure("Git output was not UTF-8") from error


def _run_test(repository: Path, command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command, cwd=repository, env=_git_env(), shell=False, capture_output=True
        )
    except OSError as error:
        raise ExecutionFailure("failed to launch test command") from error
    if completed.stdout:
        sys.stdout.buffer.write(completed.stdout)
        sys.stdout.buffer.flush()
    if completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
        sys.stderr.buffer.flush()
    summaries = re.findall(rb"Ran ([0-9]+) tests? in ", completed.stdout + completed.stderr)
    ran_tests = bool(summaries) and int(summaries[-1]) > 0
    return completed.returncode == 0 and ran_tests


def _result(step: int | None, base_sha: str | None, contract: str) -> dict[str, Any]:
    return {
        "preflight_version": 1,
        "step": step,
        "base_sha": base_sha,
        "contract": contract,
        "status": "FAIL",
        "checks": [{"id": check, "status": "NOT_RUN", "detail": "not run"} for check in CHECK_IDS],
        "failure": None,
    }


def _failure(check: str, reason: str, *, file: str | None = None, string: str | None = None, owner_step: int | None = None, missing: list[str] | None = None, unexpected: list[str] | None = None) -> dict[str, Any]:
    return {
        "check": check,
        "file": file,
        "string": string,
        "owner_step": owner_step,
        "reason": reason,
        "missing": sorted(missing or []),
        "unexpected": sorted(unexpected or []),
    }


def _mark(result: dict[str, Any], check: str, status: str, detail: str) -> None:
    entry = next(item for item in result["checks"] if item["id"] == check)
    entry["status"] = status
    entry["detail"] = detail


def _fail(result: dict[str, Any], check: str, reason: str, **fields: Any) -> None:
    _mark(result, check, "FAIL", reason)
    result["failure"] = _failure(check, reason, **fields)


def _changed_files(repository: Path, base_sha: str, operational: set[str]) -> list[str]:
    changed = _git(repository, ["diff", "--name-only", "-z", base_sha, "--"], binary=True)
    untracked = _git(repository, ["ls-files", "--others", "-z", "--"], binary=True)
    names: set[str] = set()
    for raw in (changed + untracked).split(b"\0"):
        if not raw:
            continue
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ExecutionFailure("changed path was not UTF-8") from error
        _path(name, "changed path")
        if name not in operational:
            names.add(name)
    return sorted(names)


def _text_file(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _contract_specific_values(contract: dict[str, Any]) -> set[str]:
    values = {
        contract["base-sha"],
        contract["workflow"]["path"],
        contract["expectations"]["allowed-statuses-source"],
        *contract["expectations"]["claim-statuses"].keys(),
        *contract["expectations"]["fixture-verdicts"].keys(),
        *contract["security"]["approved-actions"],
        *(entry["value"] for entry in contract["stale-identifiers"]),
    }
    return {value for value in values if value not in VALID_VERDICTS and len(value) >= 4}


def _walk_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(_walk_key(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_key(item, key))
    return found


def _validate_contract_source(
    contract: dict[str, Any], workflow: dict[str, Any], workflow_text: str, source: str
) -> tuple[str | None, str | None]:
    for value in sorted(_contract_specific_values(contract)):
        for quote in ('"', "'"):
            if f"{quote}{value}{quote}" in source:
                return "step-specific expectation is duplicated inline in implementation", value

    permissions = _walk_key(workflow, "permissions")
    if permissions != [contract["security"]["permissions"]]:
        return "workflow permissions do not match contract", None
    uses = sorted(set(item for item in _walk_key(workflow, "uses") if isinstance(item, str)))
    if uses != sorted(contract["security"]["approved-actions"]):
        return "workflow action set does not match contract", None
    fetch_depths = _walk_key(workflow, "fetch-depth")
    if not fetch_depths or any(value != contract["security"]["fetch-depth"] for value in fetch_depths):
        return "workflow fetch-depth does not match contract", None
    persisted = _walk_key(workflow, "persist-credentials")
    if not persisted or any(value is not contract["security"]["persist-credentials"] for value in persisted):
        return "workflow persist-credentials does not match contract", None
    if "secrets." in workflow_text or "permissions: write" in workflow_text:
        return "workflow references a secret or write permission", None

    expectations = contract["expectations"]
    for claim_id, status in expectations["claim-statuses"].items():
        pair = f"{json.dumps(claim_id)}: {json.dumps(status)}"
        if pair not in workflow_text:
            return "workflow lacks a contract claim-status expectation", claim_id
    if f'= "{expectations["overall-verdict"]}"' not in workflow_text:
        return "workflow lacks the contract overall-verdict expectation", expectations["overall-verdict"]
    policy_value = str(expectations["policy-accepted"]).lower()
    if f'= "{policy_value}"' not in workflow_text:
        return "workflow lacks the contract policy-accepted expectation", policy_value
    if expectations["allowed-statuses-source"] not in workflow_text:
        return "workflow lacks the contract policy rule-source expectation", expectations["allowed-statuses-source"]
    for fixture_id, verdict in expectations["fixture-verdicts"].items():
        if fixture_id not in workflow_text or f'= "{verdict}"' not in workflow_text:
            return "workflow lacks a contract fixture-verdict expectation", fixture_id
    for exception in expectations["exceptions-applied"]:
        if exception not in workflow_text:
            return "workflow lacks a contract exception expectation", exception
    if not expectations["exceptions-applied"] and "exceptions." in workflow_text:
        return "workflow contains an exception absent from the contract", None
    return None, None


def run_preflight(repository_arg: str, contract_arg: str, output_arg: str) -> tuple[dict[str, Any], int, Path | None]:
    result = _result(None, None, contract_arg)
    output_path: Path | None = None
    try:
        repository_input = Path(repository_arg)
        if repository_input.is_symlink():
            raise InputFailure("repository symlink is not allowed")
        repository = repository_input.resolve(strict=True)
        if not repository.is_dir():
            raise InputFailure("repository is not a directory")
        top = _git(repository, ["rev-parse", "--show-toplevel"]).strip()
        if Path(top).resolve(strict=True) != repository:
            raise InputFailure("repository must be the Git worktree root")
        contract_path, contract_relative = _inside(repository, contract_arg, must_exist=True, reject_symlink=True)
        result["contract"] = contract_relative
        output_path, _ = _inside(repository, output_arg, must_exist=False, reject_symlink=True)
        if output_path.exists() or output_path.is_symlink():
            output_path = None
            raise InputFailure("output destination already exists")

        try:
            raw_contract = parse_bounded_yaml(contract_path.read_text(encoding="utf-8"), contract=True)
            schema_path = repository / "contracts/step-contract.schema.json"
            if schema_path.is_symlink() or not schema_path.is_file():
                raise InputFailure("step contract schema source is missing")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            contract = validate_contract(raw_contract, schema)
        except (OSError, UnicodeError, json.JSONDecodeError, YamlFailure) as error:
            raise InputFailure(f"invalid contract: {error}") from error
        result["step"] = contract["step"]
        result["base_sha"] = contract["base-sha"]
        try:
            _git(repository, ["cat-file", "-e", f"{contract['base-sha']}^{{commit}}"])
        except ExecutionFailure as error:
            raise InputFailure("contract base SHA is not an available commit") from error
        _mark(result, "contract", "PASS", "contract loaded and validated")

        check = "workflow-yaml"
        workflow_path, _ = _inside(repository, contract["workflow"]["path"], must_exist=True, reject_symlink=True)
        try:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            workflow = parse_bounded_yaml(workflow_text, contract=False)
        except (OSError, UnicodeError, YamlFailure) as error:
            raise ExecutionFailure(f"workflow YAML is invalid: {error}") from error
        if not isinstance(workflow, dict):
            raise ExecutionFailure("workflow YAML root must be a mapping")
        _mark(result, check, "PASS", "configured workflow YAML parsed")

        for check, test_name in (("action-tests", "action"), ("end-to-end-tests", "end-to-end"), ("policy-tests", "policy")):
            if not _run_test(repository, contract["tests"][test_name]["command"]):
                _fail(result, check, "configured test command failed")
                return result, 1, output_path
            _mark(result, check, "PASS", "configured test command passed")

        check = "diff-check"
        for arguments in (["diff", "--check"], ["diff", "--cached", "--check"]):
            try:
                _git(repository, arguments)
            except ExecutionFailure:
                _fail(result, check, "git diff check failed")
                return result, 1, output_path
        _mark(result, check, "PASS", "working-tree and staged diffs passed whitespace checks")

        check = "authorized-files"
        operational = {contract_relative, output_arg}
        actual = _changed_files(repository, contract["base-sha"], operational)
        expected = sorted(contract["authorized-files"])
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing or unexpected:
            _fail(result, check, "changed-file set does not equal authorized-files", missing=missing, unexpected=unexpected)
            return result, 1, output_path
        _mark(result, check, "PASS", "changed-file set exactly matches authorized-files")

        check = "stale-identifiers"
        _git(repository, ["diff", "--binary", contract["base-sha"], "--"], binary=True)
        for relative in actual:
            candidate = repository / relative
            if candidate.is_symlink():
                text = os.readlink(candidate)
            elif candidate.is_file():
                text = _text_file(candidate)
            else:
                continue
            if text is None:
                continue
            for entry in contract["stale-identifiers"]:
                if relative not in entry["allowed-files"] and entry["value"] in text:
                    reason = "stale identifier survives in a touched text file"
                    _fail(result, check, reason, file=relative, string=entry["value"], owner_step=entry["owner-step"])
                    return result, 1, output_path
        _mark(result, check, "PASS", "no disallowed stale identifier survives")

        check = "contract-source"
        implementation = repository / "scripts/proofrail_step_preflight.py"
        if not implementation.is_file() or implementation.is_symlink():
            raise InputFailure("preflight implementation source is missing")
        source = implementation.read_text(encoding="utf-8")
        reason, offending = _validate_contract_source(contract, workflow, workflow_text, source)
        if reason:
            _fail(result, check, reason, file="scripts/proofrail_step_preflight.py" if "inline" in reason else contract["workflow"]["path"], string=offending)
            return result, 1, output_path
        _mark(result, check, "PASS", "step-specific expectations are sourced only from the contract")
        result["status"] = "PASS"
        return result, 0, output_path
    except InputFailure as error:
        active = next((item["id"] for item in result["checks"] if item["status"] == "NOT_RUN"), "contract")
        _fail(result, active, str(error))
        return result, 3, output_path
    except (ExecutionFailure, OSError, UnicodeError) as error:
        active = next((item["id"] for item in result["checks"] if item["status"] == "NOT_RUN"), "contract")
        _fail(result, active, str(error))
        return result, 4, output_path


def publish_report(path: Path, result: dict[str, Any]) -> None:
    payload = (json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        temporary = None
    except (OSError, KeyboardInterrupt) as error:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(error, KeyboardInterrupt):
            raise
        raise PublicationFailure("could not publish report") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", default=".proofrail/preflight-result.json")
    parser.add_argument("--repository", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    result, exit_code, output_path = run_preflight(arguments.repository, arguments.contract, arguments.output)
    if output_path is None:
        return exit_code
    try:
        publish_report(output_path, result)
    except PublicationFailure:
        return 5
    return exit_code


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    raise SystemExit(main())
