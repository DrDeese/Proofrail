#!/usr/bin/env python3
"""Run Proofrail safely inside a GitHub composite action."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ActionUsageError(ValueError):
    """Raised for an invalid action invocation."""


SAFE_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SAFE_VERDICT = re.compile(r"[a-z_]+\Z")
GIT_INPUTS = ("INPUT_REPO", "INPUT_BASE", "INPUT_HEAD", "INPUT_CLAIM_FILE")


@dataclass(frozen=True)
class ActionConfiguration:
    workspace: Path
    mode: str
    result_format: str
    output_file: Path
    summary_file: Path
    case_directory: Path | None = None
    repository: Path | None = None
    base: str | None = None
    head: str | None = None
    claim_file: Path | None = None


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not value:
        raise ActionUsageError(f"missing required environment variable {name}")
    if "\n" in value or "\r" in value:
        raise ActionUsageError(f"environment variable {name} contains a newline")
    return value


def _optional(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if "\n" in value or "\r" in value:
        raise ActionUsageError(f"environment variable {name} contains a newline")
    return value


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _workspace_path(workspace: Path, value: str, label: str) -> Path:
    supplied = Path(value)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise ActionUsageError(
            f"{label} must be workspace-relative without parent traversal"
        )
    candidate = workspace / supplied
    if candidate.is_symlink():
        raise ActionUsageError(f"{label} must not be a symbolic link")
    resolved = candidate.resolve(strict=False)
    if not _inside(resolved, workspace):
        raise ActionUsageError(f"{label} resolves outside GITHUB_WORKSPACE")
    return resolved


def _configuration(environment: Mapping[str, str]) -> ActionConfiguration:
    workspace_value = _required(environment, "GITHUB_WORKSPACE")
    output_value = _required(environment, "GITHUB_OUTPUT")
    summary_value = _required(environment, "GITHUB_STEP_SUMMARY")
    result_format = _optional(environment, "INPUT_FORMAT") or "json"
    if result_format not in ("json", "markdown"):
        raise ActionUsageError(f"unsupported format {result_format!r}")

    try:
        workspace = Path(workspace_value).resolve(strict=True)
    except OSError as error:
        raise ActionUsageError(f"invalid GITHUB_WORKSPACE: {error}") from error
    if not workspace.is_dir():
        raise ActionUsageError("GITHUB_WORKSPACE is not a directory")

    case_value = _optional(environment, "INPUT_CASE_DIRECTORY")
    git_values = {name: _optional(environment, name) for name in GIT_INPUTS}
    supplied_git = [name for name, value in git_values.items() if value]
    if case_value and supplied_git:
        raise ActionUsageError(
            "case-directory cannot be combined with repo, base, head, or claim-file"
        )
    if case_value:
        return ActionConfiguration(
            workspace=workspace,
            mode="prepared-case",
            result_format=result_format,
            output_file=Path(output_value),
            summary_file=Path(summary_value),
            case_directory=_workspace_path(
                workspace, case_value, "case-directory"
            ),
        )
    if len(supplied_git) != len(GIT_INPUTS):
        if supplied_git:
            missing = [name.removeprefix("INPUT_").lower() for name in GIT_INPUTS if not git_values[name]]
            raise ActionUsageError(
                "Git-change mode requires repo, base, head, and claim-file; missing "
                + ", ".join(missing)
            )
        raise ActionUsageError(
            "select prepared-case mode with case-directory or Git-change mode with "
            "repo, base, head, and claim-file"
        )
    return ActionConfiguration(
        workspace=workspace,
        mode="git-change",
        result_format=result_format,
        output_file=Path(output_value),
        summary_file=Path(summary_value),
        repository=_workspace_path(workspace, git_values["INPUT_REPO"], "repo"),
        base=git_values["INPUT_BASE"],
        head=git_values["INPUT_HEAD"],
        claim_file=_workspace_path(
            workspace, git_values["INPUT_CLAIM_FILE"], "claim-file"
        ),
    )


def _append(path: Path, content: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as destination:
        destination.write(content)
        destination.flush()
        os.fsync(destination.fileno())


def _write_atomic(path: Path, content: str) -> None:
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as destination:
            descriptor = -1
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _safe_output_value(label: str, value: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise OSError(f"unsafe {label} output value")
    return value


def _metadata_destination(path: Path, label: str) -> Path:
    if path.is_dir():
        raise OSError(f"{label} must be a file")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise OSError(f"{label} parent is unavailable: {error}") from error
    if not parent.is_dir():
        raise OSError(f"{label} parent is not a directory")
    return path.resolve()


def _prepared_result(configuration: ActionConfiguration) -> tuple[dict[str, Any], Path]:
    from proofrail_verifier.artifacts import ArtifactInspectionError
    from proofrail_verifier.evaluation import VerificationError, evaluate_case
    from proofrail_verifier.loading import FixtureLoadError, load_case_directory

    assert configuration.case_directory is not None
    try:
        bundle = load_case_directory(configuration.case_directory)
    except FixtureLoadError as error:
        raise InvalidCaseError(str(error)) from error
    try:
        result = evaluate_case(bundle)
    except (VerificationError, ArtifactInspectionError, OSError, UnicodeError) as error:
        raise ActionVerificationError(str(error)) from error
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidCaseError(str(error)) from error
    return result, bundle.fixture_dir


def _git_change_result(configuration: ActionConfiguration) -> tuple[dict[str, Any], Path]:
    from proofrail_verifier.change_verification import verify_change
    from proofrail_verifier.preparation_errors import (
        InvalidPreparationInput,
        OutputWriteFailure,
        PreparationFailure,
    )

    assert configuration.repository is not None
    assert configuration.base is not None
    assert configuration.head is not None
    assert configuration.claim_file is not None
    try:
        completed = verify_change(
            configuration.repository,
            configuration.base,
            configuration.head,
            configuration.claim_file,
        )
    except InvalidPreparationInput as error:
        raise InvalidCaseError(str(error)) from error
    except PreparationFailure as error:
        raise ActionVerificationError(str(error)) from error
    except OutputWriteFailure as error:
        raise ActionOutputError(str(error)) from error
    except KeyboardInterrupt as error:
        raise ActionVerificationError("interrupted") from error
    return completed.result, configuration.repository


class InvalidCaseError(ValueError):
    """Raised when the selected case or Git-change input is invalid."""


class ActionVerificationError(RuntimeError):
    """Raised when Proofrail cannot complete verification."""


class ActionOutputError(OSError):
    """Raised when Proofrail cannot publish action outputs."""


def main(environment: Mapping[str, str] | None = None) -> int:
    values = os.environ if environment is None else environment
    try:
        configuration = _configuration(values)
    except ActionUsageError as error:
        print(f"proofrail action: usage error: {error}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(configuration.workspace / "src"))
    try:
        from proofrail_verifier.rendering import render_json, render_markdown
    except ImportError as error:
        print(f"proofrail action: verification failed: {error}", file=sys.stderr)
        return 4

    try:
        if configuration.mode == "prepared-case":
            result, protected_directory = _prepared_result(configuration)
        else:
            result, protected_directory = _git_change_result(configuration)
    except InvalidCaseError as error:
        label = "invalid case" if configuration.mode == "prepared-case" else "invalid change input"
        print(f"proofrail action: {label}: {error}", file=sys.stderr)
        return 3
    except ActionVerificationError as error:
        print(f"proofrail action: verification failed: {error}", file=sys.stderr)
        return 4
    except ActionOutputError as error:
        print(f"proofrail action: output error: {error}", file=sys.stderr)
        return 5

    try:
        case_id = result["case_id"]
        verdict = result["overall_verdict"]
        if not isinstance(case_id, str) or SAFE_CASE_ID.fullmatch(case_id) is None:
            raise InvalidCaseError("case id is unsafe for an output path")
        if not isinstance(verdict, str) or SAFE_VERDICT.fullmatch(verdict) is None:
            raise ActionVerificationError("unsafe verdict output")
        json_result = render_json(result)
        markdown_result = render_markdown(result)
    except InvalidCaseError as error:
        label = "invalid case" if configuration.mode == "prepared-case" else "invalid change input"
        print(f"proofrail action: {label}: {error}", file=sys.stderr)
        return 3
    except (ActionVerificationError, KeyError, TypeError, ValueError, UnicodeError) as error:
        print(f"proofrail action: verification failed: {error}", file=sys.stderr)
        return 4

    result_directory = configuration.workspace / ".proofrail" / "results"
    result_path = result_directory / f"{case_id}.json"
    relative_result_path = result_path.relative_to(configuration.workspace).as_posix()
    try:
        resolved_result_path = result_path.resolve(strict=False)
        if not _inside(resolved_result_path, configuration.workspace):
            raise OSError("result path resolves outside GITHUB_WORKSPACE")
        metadata_candidates = (
            configuration.output_file.resolve(strict=False),
            configuration.summary_file.resolve(strict=False),
        )
        for destination in metadata_candidates:
            if _inside(destination, protected_directory):
                raise OSError("refusing to write action metadata inside the selected source")
        if metadata_candidates[0] == metadata_candidates[1]:
            raise OSError("GITHUB_OUTPUT and GITHUB_STEP_SUMMARY must be different files")
        if resolved_result_path in metadata_candidates:
            raise OSError("action metadata path collides with the JSON result path")
        _metadata_destination(configuration.output_file, "GITHUB_OUTPUT")
        _metadata_destination(configuration.summary_file, "GITHUB_STEP_SUMMARY")
        if configuration.mode == "git-change" and result_path.exists():
            raise OSError("Git-change result path already exists; refusing to overwrite source")
        result_directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(result_path, json_result)
        _append(configuration.summary_file, markdown_result)
        output_lines = (
            f"overall-verdict={_safe_output_value('overall-verdict', verdict)}\n"
            f"result-json-path={_safe_output_value('result-json-path', relative_result_path)}\n"
        )
        _append(configuration.output_file, output_lines)
        sys.stdout.write(
            json_result if configuration.result_format == "json" else markdown_result
        )
    except (OSError, UnicodeError) as error:
        print(f"proofrail action: output error: {error}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
