"""Check strict path claims against an exact committed Git range."""

from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path

from .claim_file import AtomicClaim, parse_claim_file
from .git_source import (
    changed_paths,
    resolve_commit,
    resolve_repository,
    validate_commit_trees,
    validate_range,
)
from .preparation_errors import InvalidPreparationInput, OutputWriteFailure, PreparationFailure


class ClaimComparisonFailure(PreparationFailure):
    """Raised when claim comparison cannot complete deterministically."""


def _byte_key(value: str) -> bytes:
    return value.encode("utf-8")


def _claim_key(claim: AtomicClaim) -> tuple[bytes, bytes, bytes]:
    return (
        _byte_key(claim.expected_path),
        _byte_key(claim.expected_change),
        _byte_key(claim.claim_id),
    )


def check_claims(
    repository_path: Path,
    base_ref: str,
    head_ref: str,
    claim_file: Path,
) -> dict[str, object]:
    """Compare strict expected path changes with the exact Git range."""

    if claim_file.is_symlink():
        raise InvalidPreparationInput("claim file must not be a symbolic link")
    parsed = parse_claim_file(claim_file)
    repository = resolve_repository(repository_path)
    base_sha = resolve_commit(repository, base_ref, "base")
    head_sha = resolve_commit(repository, head_ref, "head")
    validate_range(repository, base_sha, head_sha)
    validate_commit_trees(repository, base_sha, head_sha)
    changes = sorted(
        changed_paths(repository, base_sha, head_sha),
        key=lambda item: (_byte_key(item["path"]), _byte_key(item["status"])),
    )
    claims = sorted(parsed.atomic_claims, key=_claim_key)

    actual_by_path = {item["path"]: item["status"] for item in changes}
    claims_by_predicate: dict[tuple[str, str], list[AtomicClaim]] = {}
    for claim in claims:
        claims_by_predicate.setdefault(
            (claim.expected_path, claim.expected_change), []
        ).append(claim)

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    duplicates: list[dict[str, object]] = [
        {
            "path": path,
            "change": change,
            "claim_ids": [claim.claim_id for claim in grouped],
        }
        for (path, change), grouped in sorted(
            claims_by_predicate.items(),
            key=lambda item: (_byte_key(item[0][0]), _byte_key(item[0][1])),
        )
        if len(grouped) > 1
    ]
    for change in changes:
        matching = claims_by_predicate.get((change["path"], change["status"]), [])
        if len(matching) == 1:
            matched.append(
                {
                    "claim_id": matching[0].claim_id,
                    "path": change["path"],
                    "change": change["status"],
                }
            )
        elif not matching:
            missing.append({"path": change["path"], "change": change["status"]})

    stale: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    for claim in claims:
        actual = actual_by_path.get(claim.expected_path)
        if actual is None:
            stale.append(
                {
                    "claim_id": claim.claim_id,
                    "path": claim.expected_path,
                    "expected_change": claim.expected_change,
                    "reason": "path is unchanged in the selected range",
                }
            )
        elif actual != claim.expected_change:
            conflicts.append(
                {
                    "claim_id": claim.claim_id,
                    "path": claim.expected_path,
                    "expected_change": claim.expected_change,
                    "actual_change": actual,
                }
            )

    synchronized = not (missing or stale or conflicts or duplicates)
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "synchronized": synchronized,
        "changed_path_count": len(changes),
        "claim_predicate_count": len(claims),
        "matched": matched,
        "missing": missing,
        "stale": stale,
        "conflicts": conflicts,
        "duplicates": duplicates,
    }


def render_claim_check_json(result: dict[str, object]) -> str:
    """Render stable, compact machine-readable claim-check output."""

    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_claim_check_markdown(result: dict[str, object]) -> str:
    """Render a stable human-readable claim-check report."""

    lines = [
        "# Proofrail claim freshness",
        "",
        f"- Base: `{result['base_sha']}`",
        f"- Head: `{result['head_sha']}`",
        f"- Synchronized: `{'true' if result['synchronized'] else 'false'}`",
        f"- Changed paths: {result['changed_path_count']}",
        f"- Claim predicates: {result['claim_predicate_count']}",
        "",
    ]
    sections = (
        ("Matched", "matched"),
        ("Missing", "missing"),
        ("Stale", "stale"),
        ("Conflicts", "conflicts"),
        ("Duplicates", "duplicates"),
    )
    for title, key in sections:
        lines.extend((f"## {title}", ""))
        items = result[key]
        if not isinstance(items, list):
            raise ClaimComparisonFailure(f"claim-check {key} have an invalid shape")
        if not items:
            lines.extend(("None.", ""))
            continue
        for item in items:
            serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
            lines.append(f"- <code>{html.escape(serialized)}</code>")
        lines.append("")
    return "\n".join(lines)


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def write_claim_check_output(path: Path, content: str, repository: Path) -> None:
    """Publish a new report outside the source repository without overwriting."""

    source = repository.resolve(strict=True)
    if path.is_symlink() or os.path.lexists(path):
        raise OutputWriteFailure("output path already exists; refusing to overwrite it")
    if not path.name or path.parent.is_symlink():
        raise OutputWriteFailure("output path must identify a new file in a real directory")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise OutputWriteFailure(f"output parent is unavailable: {error}") from error
    destination = parent / path.name
    if _inside(destination, source):
        raise OutputWriteFailure("output path must be outside the source repository")

    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            descriptor = -1
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        if os.path.lexists(destination):
            raise OutputWriteFailure("output path appeared during publication")
        os.link(temporary, destination)
        os.unlink(temporary)
        temporary = None
    except OutputWriteFailure:
        raise
    except OSError as error:
        raise OutputWriteFailure(f"cannot publish claim-check output: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
