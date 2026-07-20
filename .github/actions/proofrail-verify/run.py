#!/usr/bin/env python3
"""Run Proofrail safely inside a GitHub composite action."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Mapping


class ActionUsageError(ValueError):
    """Raised for an invalid action invocation."""


SAFE_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SAFE_VERDICT = re.compile(r"[a-z_]+\Z")


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not value:
        raise ActionUsageError(f"missing required environment variable {name}")
    if "\n" in value or "\r" in value:
        raise ActionUsageError(f"environment variable {name} contains a newline")
    return value


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _configuration(environment: Mapping[str, str]) -> tuple[Path, Path, str, Path, Path]:
    workspace_value = _required(environment, "GITHUB_WORKSPACE")
    case_value = _required(environment, "INPUT_CASE_DIRECTORY")
    output_value = _required(environment, "GITHUB_OUTPUT")
    summary_value = _required(environment, "GITHUB_STEP_SUMMARY")
    result_format = environment.get("INPUT_FORMAT", "json") or "json"
    if result_format not in ("json", "markdown"):
        raise ActionUsageError(f"unsupported format {result_format!r}")
    if "\n" in result_format or "\r" in result_format:
        raise ActionUsageError("format contains a newline")

    try:
        workspace = Path(workspace_value).resolve(strict=True)
    except OSError as error:
        raise ActionUsageError(f"invalid GITHUB_WORKSPACE: {error}") from error
    if not workspace.is_dir():
        raise ActionUsageError("GITHUB_WORKSPACE is not a directory")

    supplied_case = Path(case_value)
    if supplied_case.is_absolute() or ".." in supplied_case.parts:
        raise ActionUsageError("case-directory must be workspace-relative without traversal")
    case_directory = (workspace / supplied_case).resolve(strict=False)
    if not _inside(case_directory, workspace):
        raise ActionUsageError("case-directory resolves outside GITHUB_WORKSPACE")

    return (
        workspace,
        case_directory,
        result_format,
        Path(output_value),
        Path(summary_value),
    )


def _append(path: Path, content: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as destination:
        destination.write(content)
        destination.flush()
        os.fsync(destination.fileno())


def _safe_output_value(label: str, value: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise OSError(f"unsafe {label} output value")
    return value


def main(environment: Mapping[str, str] | None = None) -> int:
    values = os.environ if environment is None else environment
    try:
        workspace, case_directory, result_format, output_file, summary_file = _configuration(
            values
        )
    except ActionUsageError as error:
        print(f"proofrail action: usage error: {error}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(workspace / "src"))
    try:
        from proofrail_verifier.artifacts import ArtifactInspectionError
        from proofrail_verifier.cli import write_atomic
        from proofrail_verifier.evaluation import VerificationError, evaluate_case
        from proofrail_verifier.loading import FixtureLoadError, load_case_directory
        from proofrail_verifier.rendering import render_json, render_markdown
    except ImportError as error:
        print(f"proofrail action: verification failed: {error}", file=sys.stderr)
        return 4

    try:
        bundle = load_case_directory(case_directory)
    except FixtureLoadError as error:
        print(f"proofrail action: invalid case: {error}", file=sys.stderr)
        return 3

    try:
        result = evaluate_case(bundle)
    except (VerificationError, ArtifactInspectionError, OSError, UnicodeError) as error:
        print(f"proofrail action: verification failed: {error}", file=sys.stderr)
        return 4
    except (KeyError, TypeError, ValueError) as error:
        print(f"proofrail action: invalid case: {error}", file=sys.stderr)
        return 3

    case_id = result["case_id"]
    verdict = result["overall_verdict"]
    if not isinstance(case_id, str) or SAFE_CASE_ID.fullmatch(case_id) is None:
        print("proofrail action: invalid case: case id is unsafe for an output path", file=sys.stderr)
        return 3
    if not isinstance(verdict, str) or SAFE_VERDICT.fullmatch(verdict) is None:
        print("proofrail action: verification failed: unsafe verdict output", file=sys.stderr)
        return 4

    json_result = render_json(result)
    markdown_result = render_markdown(result)
    result_directory = workspace / ".proofrail" / "results"
    result_path = result_directory / f"{case_id}.json"
    relative_result_path = result_path.relative_to(workspace).as_posix()

    try:
        resolved_result_path = result_path.resolve(strict=False)
        if not _inside(resolved_result_path, workspace):
            raise OSError("result path resolves outside GITHUB_WORKSPACE")
        metadata_destinations = (output_file.resolve(), summary_file.resolve())
        for destination in metadata_destinations:
            if _inside(destination, bundle.fixture_dir):
                raise OSError("refusing to write action metadata inside the case directory")
        if metadata_destinations[0] == metadata_destinations[1]:
            raise OSError("GITHUB_OUTPUT and GITHUB_STEP_SUMMARY must be different files")
        if resolved_result_path in metadata_destinations:
            raise OSError("action metadata path collides with the JSON result path")
        result_directory.mkdir(parents=True, exist_ok=True)
        write_atomic(result_path, json_result, bundle.fixture_dir)
        _append(summary_file, markdown_result)
        output_lines = (
            f"overall-verdict={_safe_output_value('overall-verdict', verdict)}\n"
            f"result-json-path={_safe_output_value('result-json-path', relative_result_path)}\n"
        )
        _append(output_file, output_lines)
        sys.stdout.write(json_result if result_format == "json" else markdown_result)
    except OSError as error:
        print(f"proofrail action: output error: {error}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
