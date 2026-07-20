"""Load and evaluate the bounded Proofrail acceptance-policy format."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CLAIM_STATUSES = frozenset(
    {"verified", "unsupported", "contradicted", "human_review_required"}
)
OVERALL_VERDICTS = frozenset(CLAIM_STATUSES | {"partially_verified"})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
MAX_POLICY_BYTES = 65_536
MAX_RESULT_BYTES = 2_000_000
MAX_POLICY_LINES = 2_048
MAX_RESULT_CLAIMS = 2_048


class PolicyInputError(ValueError):
    """Raised when a result or policy is missing, malformed, or invalid."""


class PolicyEvaluationError(RuntimeError):
    """Raised when a valid result and policy cannot be evaluated."""


class PolicyOutputError(OSError):
    """Raised when a policy result cannot be published safely."""


@dataclass(frozen=True)
class AcceptancePolicy:
    """The validated, non-executable policy rules."""

    version: int
    allowed_statuses: tuple[str, ...]
    allowed_verdicts: tuple[str, ...]
    exceptions: tuple[tuple[str, tuple[str, ...]], ...]

    def exception_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.exceptions)


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    text: str


def _read_limited(path: Path, label: str, maximum: int) -> bytes:
    try:
        with path.open("rb") as source:
            content = source.read(maximum + 1)
    except OSError as error:
        raise PolicyInputError(
            f"cannot read {label}: {error.strerror or error}"
        ) from error
    if len(content) > maximum:
        raise PolicyInputError(f"{label} exceeds {maximum} bytes")
    return content


def _policy_lines(content: bytes) -> list[_Line]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PolicyInputError(f"policy is not valid UTF-8: {error}") from error
    if "\x00" in text:
        raise PolicyInputError("policy contains a NUL byte")
    raw_lines = text.splitlines()
    if len(raw_lines) > MAX_POLICY_LINES:
        raise PolicyInputError(f"policy exceeds {MAX_POLICY_LINES} lines")
    parsed: list[_Line] = []
    for number, raw in enumerate(raw_lines, 1):
        if "\t" in raw:
            raise PolicyInputError(f"policy line {number} contains a tab")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw.rstrip() != raw:
            raise PolicyInputError(f"policy line {number} has trailing whitespace")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise PolicyInputError(f"policy line {number} has invalid indentation")
        text_value = raw[indent:]
        if any(token in text_value for token in ("&", "*", "!!", "!<", "<<:")):
            raise PolicyInputError(
                f"policy line {number} uses unsupported YAML aliases or tags"
            )
        if any(character in text_value for character in ("[", "]", "{", "}", "|", ">")):
            raise PolicyInputError(
                f"policy line {number} uses unsupported YAML syntax"
            )
        if text_value in {"---", "..."} or text_value.startswith("%"):
            raise PolicyInputError(
                f"policy line {number} uses unsupported YAML directives"
            )
        parsed.append(_Line(number, indent, text_value))
    if not parsed:
        raise PolicyInputError("policy is empty")
    return parsed


def _mapping_entry(line: _Line, indent: int) -> tuple[str, str | None]:
    if line.indent != indent or ":" not in line.text:
        raise PolicyInputError(f"policy line {line.number} is not a valid mapping entry")
    key, separator, remainder = line.text.partition(":")
    if not separator or not key or key.strip() != key:
        raise PolicyInputError(f"policy line {line.number} has an invalid key")
    if not remainder:
        return key, None
    if not remainder.startswith(" ") or remainder[1:] == "":
        raise PolicyInputError(f"policy line {line.number} has an invalid scalar")
    value = remainder[1:]
    if value != value.strip() or ":" in value or " #" in value:
        raise PolicyInputError(f"policy line {line.number} has an invalid scalar")
    return key, value


def _status_list(
    block: list[_Line], heading: str, allowed: frozenset[str]
) -> tuple[str, ...]:
    if not block:
        raise PolicyInputError(f"policy section {heading!r} is empty")
    key, value = _mapping_entry(block[0], 2)
    if key != heading or value is not None:
        raise PolicyInputError(
            f"policy section requires exactly {heading!r} as a nested list"
        )
    values: list[str] = []
    for line in block[1:]:
        if line.indent != 4 or not line.text.startswith("- "):
            raise PolicyInputError(f"policy line {line.number} is not a list item")
        item = line.text[2:]
        if item not in allowed:
            raise PolicyInputError(f"policy line {line.number} has unknown value {item!r}")
        if item in values:
            raise PolicyInputError(f"policy line {line.number} duplicates {item!r}")
        values.append(item)
    if not values:
        raise PolicyInputError(f"policy list {heading!r} must not be empty")
    return tuple(values)


def _exception_list(block: list[_Line]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not block:
        raise PolicyInputError("policy exceptions list must not be empty")
    exceptions: list[tuple[str, tuple[str, ...]]] = []
    index = 0
    seen: set[str] = set()
    while index < len(block):
        line = block[index]
        if line.indent != 2 or not line.text.startswith("- "):
            raise PolicyInputError(f"policy line {line.number} is not an exception item")
        synthetic = _Line(line.number, 2, line.text[2:])
        key, claim_id = _mapping_entry(synthetic, 2)
        if key != "claim-id" or claim_id is None:
            raise PolicyInputError(
                f"policy line {line.number} must define an exception claim-id"
            )
        if IDENTIFIER.fullmatch(claim_id) is None:
            raise PolicyInputError(f"policy line {line.number} has an invalid claim-id")
        if claim_id in seen:
            raise PolicyInputError(f"duplicate exception claim-id {claim_id!r}")
        seen.add(claim_id)
        index += 1
        if index >= len(block):
            raise PolicyInputError(f"exception {claim_id!r} is missing allowed-statuses")
        heading = block[index]
        key, value = _mapping_entry(heading, 4)
        if key != "allowed-statuses" or value is not None:
            raise PolicyInputError(
                f"exception {claim_id!r} requires allowed-statuses"
            )
        index += 1
        values: list[str] = []
        while index < len(block) and block[index].indent == 6:
            item_line = block[index]
            if not item_line.text.startswith("- "):
                raise PolicyInputError(
                    f"policy line {item_line.number} is not a status list item"
                )
            item = item_line.text[2:]
            if item not in CLAIM_STATUSES:
                raise PolicyInputError(
                    f"policy line {item_line.number} has unknown claim status {item!r}"
                )
            if item in values:
                raise PolicyInputError(
                    f"policy line {item_line.number} duplicates {item!r}"
                )
            values.append(item)
            index += 1
        if not values:
            raise PolicyInputError(
                f"exception {claim_id!r} allowed-statuses must not be empty"
            )
        exceptions.append((claim_id, tuple(values)))
    return tuple(exceptions)


def parse_policy(content: bytes) -> AcceptancePolicy:
    """Parse only the documented bounded YAML policy shape."""

    lines = _policy_lines(content)
    sections: dict[str, tuple[str | None, list[_Line]]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        key, value = _mapping_entry(line, 0)
        if key not in {"version", "claims", "overall", "exceptions"}:
            raise PolicyInputError(f"unknown policy key {key!r}")
        if key in sections:
            raise PolicyInputError(f"duplicate policy key {key!r}")
        index += 1
        start = index
        while index < len(lines) and lines[index].indent > 0:
            index += 1
        sections[key] = (value, lines[start:index])

    if "version" not in sections:
        raise PolicyInputError("policy is missing 'version'")
    version, version_block = sections["version"]
    if version_block or version != "1":
        raise PolicyInputError("policy version must equal 1")
    for required in ("claims", "overall"):
        if required not in sections:
            raise PolicyInputError(f"policy is missing {required!r}")
        if sections[required][0] is not None:
            raise PolicyInputError(f"policy section {required!r} must be a mapping")

    allowed_statuses = _status_list(
        sections["claims"][1], "allowed-statuses", CLAIM_STATUSES
    )
    allowed_verdicts = _status_list(
        sections["overall"][1], "allowed-verdicts", OVERALL_VERDICTS
    )
    exceptions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    if "exceptions" in sections:
        if sections["exceptions"][0] is not None:
            raise PolicyInputError("policy exceptions must be a list")
        exceptions = _exception_list(sections["exceptions"][1])
    return AcceptancePolicy(1, allowed_statuses, allowed_verdicts, exceptions)


def load_policy(path: Path) -> AcceptancePolicy:
    return parse_policy(_read_limited(path, "policy", MAX_POLICY_BYTES))


def load_result(path: Path) -> dict[str, Any]:
    content = _read_limited(path, "result", MAX_RESULT_BYTES)
    try:
        result = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyInputError(f"result is not valid JSON: {error}") from error
    validate_result(result)
    return result


def validate_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise PolicyInputError("result must be a JSON object")
    case_id = result.get("case_id")
    if not isinstance(case_id, str) or IDENTIFIER.fullmatch(case_id) is None:
        raise PolicyInputError("result case_id is invalid")
    claims = result.get("claims")
    if not isinstance(claims, list) or not claims:
        raise PolicyInputError("result claims must be a non-empty array")
    if len(claims) > MAX_RESULT_CLAIMS:
        raise PolicyInputError(f"result exceeds {MAX_RESULT_CLAIMS} claims")
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise PolicyInputError(f"result claim at index {index} must be an object")
        claim_id = claim.get("claim_id")
        status = claim.get("status")
        if not isinstance(claim_id, str) or IDENTIFIER.fullmatch(claim_id) is None:
            raise PolicyInputError(f"result claim at index {index} has an invalid claim_id")
        if claim_id in seen:
            raise PolicyInputError(f"result has duplicate claim_id {claim_id!r}")
        seen.add(claim_id)
        if status not in CLAIM_STATUSES:
            raise PolicyInputError(
                f"result claim {claim_id!r} has unknown status {status!r}"
            )
    verdict = result.get("overall_verdict")
    if verdict not in OVERALL_VERDICTS:
        raise PolicyInputError(f"result has unknown overall_verdict {verdict!r}")


def evaluate_policy(
    result: dict[str, Any], policy: AcceptancePolicy
) -> dict[str, Any]:
    """Evaluate acceptance without changing any evidence-derived status."""

    validate_result(result)
    claim_ids = {claim["claim_id"] for claim in result["claims"]}
    exceptions = policy.exception_map()
    absent = [claim_id for claim_id in exceptions if claim_id not in claim_ids]
    if absent:
        raise PolicyInputError(
            "policy exception references absent claim_id " + repr(absent[0])
        )
    decisions: list[dict[str, Any]] = []
    reasons: list[str] = []
    for claim in result["claims"]:
        claim_id = claim["claim_id"]
        status = claim["status"]
        if claim_id in exceptions:
            allowed = exceptions[claim_id]
            rule = f"exceptions.{claim_id}.allowed-statuses"
        else:
            allowed = policy.allowed_statuses
            rule = "claims.allowed-statuses"
        accepted = status in allowed
        decisions.append(
            {
                "accepted": accepted,
                "claim_id": claim_id,
                "rule": rule,
                "status": status,
            }
        )
        if not accepted:
            reasons.append(f"claim {claim_id} has disallowed status {status}")

    verdict = result["overall_verdict"]
    overall_accepted = verdict in policy.allowed_verdicts
    if not overall_accepted:
        reasons.append(f"overall verdict {verdict} is disallowed")
    return {
        "accepted": not reasons,
        "case_id": result["case_id"],
        "claim_decisions": decisions,
        "overall_decision": {
            "accepted": overall_accepted,
            "verdict": verdict,
        },
        "policy_version": policy.version,
        "reasons": reasons,
    }


def write_new_atomic(path: Path, content: str, protected: tuple[Path, ...] = ()) -> None:
    if path.exists() or path.is_symlink():
        raise PolicyOutputError("output already exists; refusing to overwrite it")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise PolicyOutputError(f"output parent is unavailable: {error}") from error
    if not parent.is_dir():
        raise PolicyOutputError("output parent is not a directory")
    destination = parent / path.name
    protected_resolved = {item.resolve(strict=False) for item in protected}
    if destination in protected_resolved:
        raise PolicyOutputError("output must not replace a policy or result input")
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.exists() or path.is_symlink():
            raise PolicyOutputError("output appeared before publication")
        os.replace(temporary_name, destination)
        temporary_name = None
    except PolicyOutputError:
        raise
    except (OSError, UnicodeError) as error:
        raise PolicyOutputError(f"cannot write output: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
