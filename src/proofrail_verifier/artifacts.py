"""Reconstruct fixture 001's final file state from its initial tree and patch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class ArtifactInspectionError(ValueError):
    """Raised when the fixture patch cannot be applied deterministically."""


@dataclass(frozen=True)
class ArtifactState:
    initial_files: frozenset[str]
    final_files: dict[str, str]
    changed_paths: tuple[str, ...]


DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


def _read_initial_files(initial_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(initial_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(initial_dir.rglob("*"))
        if path.is_file()
    }


def _patch_blocks(patch_text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current_path: str | None = None
    current_lines: list[str] = []
    for line in patch_text.splitlines():
        match = DIFF_HEADER.match(line)
        if match:
            if match.group(1) != match.group(2):
                raise ArtifactInspectionError("fixture patch renames are unsupported")
            if current_path is not None:
                blocks.append((current_path, current_lines))
            current_path = match.group(1)
            current_lines = []
        elif current_path is not None:
            current_lines.append(line)
        elif line.strip():
            raise ArtifactInspectionError("fixture patch contains content before a diff header")
    if current_path is not None:
        blocks.append((current_path, current_lines))
    return blocks


def _apply_block(files: dict[str, str], path: str, lines: list[str]) -> None:
    if "deleted file mode 100644" in lines:
        if path not in files:
            raise ArtifactInspectionError(f"cannot delete missing path {path!r}")
        del files[path]
        return

    if path not in files:
        raise ArtifactInspectionError(f"cannot modify missing path {path!r}")
    removals = [line[1:] for line in lines if line.startswith("-") and not line.startswith("---")]
    additions = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
    if len(removals) != len(additions) or not removals:
        raise ArtifactInspectionError(f"unsupported patch shape for {path!r}")

    content = files[path]
    for removed, added in zip(removals, additions):
        needle = f"{removed}\n"
        replacement = f"{added}\n"
        if content.count(needle) < 1:
            raise ArtifactInspectionError(f"patch context not found in {path!r}: {removed!r}")
        content = content.replace(needle, replacement, 1)
    files[path] = content


def inspect_actual_state(fixture_dir: Path) -> ArtifactState:
    initial = _read_initial_files(fixture_dir / "initial")
    final = dict(initial)
    patch_text = (fixture_dir / "actual.patch").read_text(encoding="utf-8")
    blocks = _patch_blocks(patch_text)
    for path, lines in blocks:
        _apply_block(final, path, lines)
    return ArtifactState(
        initial_files=frozenset(initial),
        final_files=final,
        changed_paths=tuple(sorted(path for path, _ in blocks)),
    )


def workflow_trigger_paths(state: ArtifactState) -> dict[str, tuple[str, ...]]:
    workflow = state.final_files.get(".github/workflows/ci.yml")
    if workflow is None:
        return {}
    values: dict[str, list[str]] = {"push": [], "pull_request": []}
    current_event: str | None = None
    in_paths = False
    for line in workflow.splitlines():
        if line in ("  push:", "  pull_request:"):
            current_event = line.strip()[:-1]
            in_paths = False
        elif current_event is not None and line == "    paths:":
            in_paths = True
        elif in_paths and line.startswith("      - "):
            values[current_event].append(line[8:].strip())
        elif current_event is not None and line and not line.startswith("    "):
            current_event = None
            in_paths = False
    return {event: tuple(paths) for event, paths in values.items()}
