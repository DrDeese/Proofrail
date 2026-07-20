"""Parse the explicit, non-inferential completion-claim format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .preparation_errors import InvalidPreparationInput


EXPECTED_CHANGES = {"added", "modified", "deleted", "present", "absent"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FIELD = re.compile(r"^(?P<indent>- |  )(?P<name>[a-z-]+): (?P<value>.+)$")


@dataclass(frozen=True)
class AtomicClaim:
    claim_id: str
    statement: str
    expected_path: str
    expected_change: str


@dataclass(frozen=True)
class ParsedClaim:
    text: str
    overall_statement: str
    atomic_claims: tuple[AtomicClaim, ...]


def _validate_expected_path(value: str) -> str:
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise InvalidPreparationInput("expected-path must be a portable repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {"", "."} or ".." in path.parts:
        raise InvalidPreparationInput("expected-path must stay inside the repository")
    normalized = path.as_posix()
    if normalized != value or value.endswith("/"):
        raise InvalidPreparationInput("expected-path must be normalized and identify a file")
    return normalized


def parse_claim_file(path: Path) -> ParsedClaim:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidPreparationInput(f"cannot read claim file: {error}") from error
    if "\x00" in text:
        raise InvalidPreparationInput("claim file contains a NUL byte")
    lines = text.splitlines()
    if not lines or lines[0] != "# Completion claim":
        raise InvalidPreparationInput("claim file must start with '# Completion claim'")
    headings = [index for index, line in enumerate(lines) if line == "## Atomic claims"]
    if len(headings) != 1:
        raise InvalidPreparationInput("claim file must contain one '## Atomic claims' heading")
    atomic_heading = headings[0]
    overall = "\n".join(lines[1:atomic_heading]).strip()
    if not overall:
        raise InvalidPreparationInput("completion statement must not be empty")

    content = [line for line in lines[atomic_heading + 1 :] if line.strip()]
    claims: list[AtomicClaim] = []
    seen_ids: set[str] = set()
    index = 0
    expected_fields = ("id", "statement", "expected-path", "expected-change")
    while index < len(content):
        if index + 4 > len(content):
            raise InvalidPreparationInput("atomic claim is incomplete")
        values: dict[str, str] = {}
        for offset, (line, expected_name) in enumerate(
            zip(content[index : index + 4], expected_fields)
        ):
            match = FIELD.fullmatch(line)
            expected_indent = "- " if offset == 0 else "  "
            if (
                match is None
                or match.group("indent") != expected_indent
                or match.group("name") != expected_name
            ):
                raise InvalidPreparationInput(
                    "atomic claims must contain id, statement, expected-path, and "
                    "expected-change in order"
                )
            values[expected_name] = match.group("value").strip()
        claim_id = values["id"]
        if SAFE_ID.fullmatch(claim_id) is None:
            raise InvalidPreparationInput(f"invalid atomic claim id: {claim_id!r}")
        if claim_id in seen_ids:
            raise InvalidPreparationInput(f"duplicate atomic claim id: {claim_id}")
        if not values["statement"]:
            raise InvalidPreparationInput(f"claim {claim_id!r} has an empty statement")
        expected_change = values["expected-change"]
        if expected_change not in EXPECTED_CHANGES:
            raise InvalidPreparationInput(
                f"claim {claim_id!r} has unsupported expected-change {expected_change!r}"
            )
        claims.append(
            AtomicClaim(
                claim_id=claim_id,
                statement=values["statement"],
                expected_path=_validate_expected_path(values["expected-path"]),
                expected_change=expected_change,
            )
        )
        seen_ids.add(claim_id)
        index += 4
    if not claims:
        raise InvalidPreparationInput("claim file must contain at least one atomic claim")
    return ParsedClaim(text=text, overall_statement=overall, atomic_claims=tuple(claims))
