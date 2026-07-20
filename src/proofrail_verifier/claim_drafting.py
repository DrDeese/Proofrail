"""Draft strict artifact-level completion claims from committed Git paths."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .claim_file import parse_claim_file
from .git_source import (
    changed_paths,
    resolve_commit,
    resolve_repository,
    validate_commit_trees,
    validate_range,
)
from .preparation_errors import (
    InvalidPreparationInput,
    OutputWriteFailure,
    PreparationFailure,
)


MAX_CLAIM_ID = 96
HASH_LENGTH = 12
_UNSAFE_TITLE = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_PATH = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class DraftClaimsResult:
    """The exact committed range and generated artifact summary."""

    base_sha: str
    head_sha: str
    claim_count: int
    output_path: Path


class ClaimGenerationFailure(PreparationFailure):
    """Raised when safe deterministic claims cannot be generated."""


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _safe_title(title: str) -> str:
    if not title or title.strip() != title or _UNSAFE_TITLE.search(title):
        raise InvalidPreparationInput("case title must be one non-empty portable line")
    if title.startswith("#"):
        raise InvalidPreparationInput("case title must not create a Markdown heading")
    return title


def _safe_path(path: str) -> str:
    if (
        not path
        or path.strip() != path
        or "\\" in path
        or _UNSAFE_PATH.search(path)
    ):
        raise InvalidPreparationInput(
            "changed path cannot be represented safely in the strict claim format"
        )
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != path:
        raise InvalidPreparationInput("changed path is not a portable repository path")
    return path


def _slug(path: str, change: str) -> str:
    source = f"{path}-{change}".lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", source).strip("-")
    return normalized or "path-change"


def _digest(path: str, change: str) -> str:
    return hashlib.sha256(f"{path}\0{change}".encode("utf-8")).hexdigest()[:HASH_LENGTH]


def _claim_ids(changes: list[dict[str, str]]) -> list[str]:
    slugs = [_slug(item["path"], item["status"]) for item in changes]
    counts: dict[str, int] = {}
    for slug in slugs:
        counts[slug] = counts.get(slug, 0) + 1

    identifiers: list[str] = []
    for item, slug in zip(changes, slugs):
        needs_hash = counts[slug] > 1 or len(slug) > MAX_CLAIM_ID
        if needs_hash:
            digest = _digest(item["path"], item["status"])
            prefix_length = MAX_CLAIM_ID - HASH_LENGTH - 1
            identifier = f"{slug[:prefix_length].rstrip('-')}-{digest}"
        else:
            identifier = slug
        identifiers.append(identifier)
    if len(set(identifiers)) != len(identifiers):
        raise ClaimGenerationFailure("deterministic claim IDs are not unique")
    return identifiers


def render_claims(changes: list[dict[str, str]], title: str) -> str:
    """Render sorted committed path changes in the existing strict format."""

    safe_title = _safe_title(title)
    normalized = [
        {"path": _safe_path(item["path"]), "status": item["status"]}
        for item in changes
    ]
    allowed = {"added", "modified", "deleted"}
    if not normalized:
        raise InvalidPreparationInput("commit range contains no changed paths")
    if any(item["status"] not in allowed for item in normalized):
        raise ClaimGenerationFailure("Git returned an unsupported path change")
    normalized.sort(key=lambda item: (item["path"].encode("utf-8"), item["status"]))
    identifiers = _claim_ids(normalized)
    lines = ["# Completion claim", "", safe_title, "", "## Atomic claims", ""]
    for identifier, item in zip(identifiers, normalized):
        path = item["path"]
        change = item["status"]
        lines.extend(
            (
                f"- id: {identifier}",
                f"  statement: {path} was {change}.",
                f"  expected-path: {path}",
                f"  expected-change: {change}",
                "",
            )
        )
    return "\n".join(lines)


def _destination(output: Path, repository: Path) -> Path:
    if output.is_symlink() or os.path.lexists(output):
        raise OutputWriteFailure("output path already exists; refusing to overwrite it")
    if not output.name:
        raise OutputWriteFailure("output path must identify a new file")
    if output.parent.is_symlink():
        raise OutputWriteFailure("output parent must not be a symbolic link")
    try:
        parent = output.parent.resolve(strict=True)
    except OSError as error:
        raise OutputWriteFailure(f"output parent is unavailable: {error}") from error
    destination = parent / output.name
    if _inside(destination, repository):
        raise OutputWriteFailure("output path must be outside the source repository")
    return destination


def _publish(destination: Path, content: str) -> None:
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
        raise OutputWriteFailure(f"cannot publish claim file: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def draft_claims(
    repository_path: Path,
    base_ref: str,
    head_ref: str,
    output: Path,
    *,
    case_title: str | None = None,
) -> DraftClaimsResult:
    """Draft and atomically publish path claims for an exact committed range."""

    repository = resolve_repository(repository_path)
    base_sha = resolve_commit(repository, base_ref, "base")
    head_sha = resolve_commit(repository, head_ref, "head")
    validate_range(repository, base_sha, head_sha)
    validate_commit_trees(repository, base_sha, head_sha)
    changes = changed_paths(repository, base_sha, head_sha)
    title = (
        f"Changes from {base_sha[:12]} to {head_sha[:12]}"
        if case_title is None
        else case_title
    )
    content = render_claims(changes, title)
    destination = _destination(output, repository)
    _publish(destination, content)

    # Publication is complete only if the real strict parser accepts the bytes.
    try:
        parsed = parse_claim_file(destination)
    except InvalidPreparationInput as error:
        try:
            destination.unlink()
        except OSError as cleanup_error:
            raise ClaimGenerationFailure(
                f"generated claim file is invalid and cleanup failed: {cleanup_error}"
            ) from error
        raise ClaimGenerationFailure(f"generated claim file is invalid: {error}") from error
    if len(parsed.atomic_claims) != len(changes):
        try:
            destination.unlink()
        except OSError as cleanup_error:
            raise ClaimGenerationFailure(
                f"generated claim count changed and cleanup failed: {cleanup_error}"
            )
        raise ClaimGenerationFailure("generated claim count changed after parsing")
    return DraftClaimsResult(base_sha, head_sha, len(changes), destination)


def portable_output_path(requested: Path) -> str:
    """Describe a destination without exposing a checkout-specific absolute prefix."""

    if not requested.is_absolute():
        return requested.as_posix()
    return requested.name
