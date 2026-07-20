"""Prepare and verify a committed Git change in one offline operation."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactInspectionError
from .evaluation import VerificationError, evaluate_case
from .git_source import resolve_repository
from .loading import FixtureLoadError, load_case_directory
from .preparation import prepare_case
from .preparation_errors import (
    InvalidPreparationInput,
    OutputWriteFailure,
    PreparationFailure,
)
from .rendering import render_json, render_markdown


@dataclass(frozen=True)
class ChangeVerificationResult:
    """The derived verifier result and its deterministic rendering."""

    result: dict[str, Any]
    rendered: str


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _destination(path: Path, label: str, repository: Path) -> Path:
    if path.is_symlink():
        raise OutputWriteFailure(f"{label} must not be a symbolic link")
    if path.exists():
        raise OutputWriteFailure(f"{label} already exists; refusing to overwrite it")
    if not path.name:
        raise OutputWriteFailure(f"{label} must identify a new path")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise OutputWriteFailure(f"{label} parent is unavailable: {error}") from error
    if not parent.is_dir():
        raise OutputWriteFailure(f"{label} parent is not a directory")
    resolved = parent / path.name
    if _inside(resolved, repository):
        raise OutputWriteFailure(f"{label} must be outside the source repository")
    return resolved


def _stage_file(destination: Path, content: str) -> Path:
    descriptor = -1
    staging_name: str | None = None
    try:
        descriptor, staging_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        return Path(staging_name)
    except OSError as error:
        if staging_name is not None:
            Path(staging_name).unlink(missing_ok=True)
        raise OutputWriteFailure(f"cannot stage output file: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _stage_case(source: Path, destination: Path) -> Path:
    staging: Path | None = None
    try:
        if any(path.is_symlink() for path in source.rglob("*")):
            raise OutputWriteFailure("generated case unexpectedly contains a symbolic link")
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
        )
        shutil.copytree(source, staging, dirs_exist_ok=True)
        return staging
    except OutputWriteFailure:
        raise
    except OSError as error:
        cleanup_error: OSError | None = None
        if staging is not None:
            try:
                shutil.rmtree(staging)
            except OSError as cleanup:
                cleanup_error = cleanup
        detail = f"cannot stage preserved case: {error}"
        if cleanup_error is not None:
            detail += f"; staging cleanup failed: {cleanup_error}"
        raise OutputWriteFailure(detail) from error


def _remove_published(path: Path, is_directory: bool) -> str | None:
    try:
        if is_directory:
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as error:
        return str(error)
    return None


def _publish(
    content: str,
    case_directory: Path,
    output: Path | None,
    keep_case: Path | None,
) -> None:
    staged_output: Path | None = None
    staged_case: Path | None = None
    published: list[tuple[Path, bool]] = []
    try:
        if output is not None:
            staged_output = _stage_file(output, content)
        if keep_case is not None:
            staged_case = _stage_case(case_directory, keep_case)
        if output is not None and staged_output is not None:
            if output.exists() or output.is_symlink():
                raise OutputWriteFailure("output appeared before publication")
            os.replace(staged_output, output)
            staged_output = None
            published.append((output, False))
        if keep_case is not None and staged_case is not None:
            if keep_case.exists() or keep_case.is_symlink():
                raise OutputWriteFailure("preserved case appeared before publication")
            os.replace(staged_case, keep_case)
            staged_case = None
            published.append((keep_case, True))
    except (OSError, OutputWriteFailure) as error:
        cleanup_errors = [
            message
            for path, is_directory in reversed(published)
            if (message := _remove_published(path, is_directory)) is not None
        ]
        for path, is_directory in (
            (staged_output, False),
            (staged_case, True),
        ):
            if path is not None:
                message = _remove_published(path, is_directory)
                if message is not None:
                    cleanup_errors.append(message)
        detail = f"cannot publish output: {error}"
        if cleanup_errors:
            detail += "; rollback or staging cleanup failed: " + "; ".join(
                cleanup_errors
            )
        raise OutputWriteFailure(detail) from error


def verify_change(
    repository_path: Path,
    base_ref: str,
    head_ref: str,
    claim_file: Path,
    *,
    result_format: str = "json",
    output: Path | None = None,
    keep_case: Path | None = None,
) -> ChangeVerificationResult:
    """Prepare, verify, render, and optionally publish one committed change."""

    if result_format not in {"json", "markdown"}:
        raise InvalidPreparationInput(f"unsupported result format: {result_format}")
    repository = resolve_repository(repository_path)
    resolved_output = (
        _destination(output, "output", repository) if output is not None else None
    )
    resolved_keep = (
        _destination(keep_case, "preserved case", repository)
        if keep_case is not None
        else None
    )
    if resolved_output is not None and resolved_keep is not None:
        if resolved_output == resolved_keep or _inside(resolved_output, resolved_keep):
            raise OutputWriteFailure("output and preserved-case destinations overlap")

    try:
        with tempfile.TemporaryDirectory(prefix="proofrail-verify-change-") as temporary:
            case_directory = Path(temporary) / "case"
            try:
                prepare_case(
                    repository,
                    base_ref,
                    head_ref,
                    claim_file,
                    case_directory,
                )
            except OutputWriteFailure as error:
                raise PreparationFailure(
                    f"cannot generate temporary case: {error}"
                ) from error
            try:
                bundle = load_case_directory(case_directory)
            except FixtureLoadError as error:
                raise InvalidPreparationInput(
                    f"generated case is invalid: {error}"
                ) from error
            try:
                result = evaluate_case(bundle)
            except (VerificationError, ArtifactInspectionError, OSError, UnicodeError) as error:
                raise PreparationFailure(f"verification failed: {error}") from error
            except (KeyError, TypeError, ValueError) as error:
                raise InvalidPreparationInput(
                    f"generated case is invalid: {error}"
                ) from error
            try:
                rendered = (
                    render_json(result)
                    if result_format == "json"
                    else render_markdown(result)
                )
            except (KeyError, TypeError, ValueError, UnicodeError) as error:
                raise PreparationFailure(f"result rendering failed: {error}") from error
            _publish(rendered, case_directory, resolved_output, resolved_keep)
            return ChangeVerificationResult(result=result, rendered=rendered)
    except (InvalidPreparationInput, PreparationFailure, OutputWriteFailure):
        raise
    except OSError as error:
        raise PreparationFailure(f"temporary case cleanup failed: {error}") from error
