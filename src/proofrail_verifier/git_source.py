"""Read deterministic evidence from local committed Git objects only."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .preparation_errors import InvalidPreparationInput, PreparationFailure


@dataclass(frozen=True)
class Blob:
    mode: str
    content: bytes


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        }
    )
    return environment


def _git(
    repository: Path,
    arguments: Sequence[str],
    *,
    invalid: bool = False,
    accepted: tuple[int, ...] = (0,),
) -> tuple[int, bytes]:
    command = [
        "git",
        "-c",
        "color.ui=false",
        "-c",
        "core.quotepath=false",
        "-C",
        str(repository),
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_environment(),
            check=False,
        )
    except OSError as error:
        raise PreparationFailure(f"cannot execute Git: {error}") from error
    if completed.returncode not in accepted:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        error_type = InvalidPreparationInput if invalid else PreparationFailure
        raise error_type(
            f"Git {arguments[0]} failed with exit {completed.returncode}: "
            f"{message or 'no diagnostic'}"
        )
    if completed.stderr:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PreparationFailure(f"Git {arguments[0]} wrote unexpected stderr: {message}")
    return completed.returncode, completed.stdout


def resolve_repository(path: Path) -> Path:
    if path.is_symlink():
        raise InvalidPreparationInput("repository path must not be a symbolic link")
    try:
        candidate = path.resolve(strict=True)
    except OSError as error:
        raise InvalidPreparationInput(f"repository does not exist: {path}") from error
    if not candidate.is_dir():
        raise InvalidPreparationInput("repository path must be a directory")
    _, bare_output = _git(candidate, ["rev-parse", "--is-bare-repository"], invalid=True)
    bare = bare_output.decode("ascii", errors="strict").strip() == "true"
    if bare:
        return candidate
    _, root_output = _git(candidate, ["rev-parse", "--show-toplevel"], invalid=True)
    try:
        return Path(root_output.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidPreparationInput("Git repository root is not a valid local path") from error


def resolve_commit(repository: Path, reference: str, label: str) -> str:
    if not reference or "\x00" in reference:
        raise InvalidPreparationInput(f"{label} ref must not be empty")
    _, output = _git(
        repository,
        ["rev-parse", "--verify", "--end-of-options", f"{reference}^{{commit}}"],
        invalid=True,
    )
    sha = output.decode("ascii", errors="strict").strip()
    if re.fullmatch(r"[0-9a-f]{40,64}", sha) is None:
        raise InvalidPreparationInput(f"{label} ref did not resolve to a full commit SHA")
    return sha


def validate_range(repository: Path, base_sha: str, head_sha: str) -> None:
    if base_sha == head_sha:
        raise InvalidPreparationInput("base and head must identify different commits")
    code, _ = _git(
        repository,
        ["merge-base", "--is-ancestor", base_sha, head_sha],
        invalid=True,
        accepted=(0, 1),
    )
    if code == 1:
        raise InvalidPreparationInput("base commit is not an ancestor of head commit")


def validate_commit_trees(repository: Path, base_sha: str, head_sha: str) -> None:
    """Require both committed trees to be locally available without lazy fetching."""

    for label, sha in (("base", base_sha), ("head", head_sha)):
        _git(repository, ["cat-file", "-e", f"{sha}^{{tree}}"], invalid=True)


def changed_paths(repository: Path, base_sha: str, head_sha: str) -> list[dict[str, str]]:
    _, output = _git(
        repository,
        [
            "diff",
            "--name-status",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            base_sha,
            head_sha,
            "--",
        ],
    )
    tokens = output.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    if len(tokens) % 2:
        raise PreparationFailure("Git returned malformed changed-path evidence")
    status_map = {"A": "added", "M": "modified", "T": "modified", "D": "deleted"}
    changes: list[dict[str, str]] = []
    for index in range(0, len(tokens), 2):
        try:
            status = tokens[index].decode("ascii")
            path = tokens[index + 1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidPreparationInput("Git paths must be valid UTF-8") from error
        normalized = status_map.get(status)
        if normalized is None:
            raise InvalidPreparationInput(f"unsupported Git path status: {status!r}")
        changes.append({"path": path, "status": normalized})
    return sorted(changes, key=lambda item: item["path"])


def commit_metadata(repository: Path, sha: str) -> dict[str, str]:
    _, output = _git(
        repository,
        [
            "show",
            "--no-show-signature",
            "-s",
            "--format=%H%x00%an%x00%ae%x00%aI",
            sha,
            "--",
        ],
    )
    try:
        values = output.rstrip(b"\n").decode("utf-8").split("\0")
    except UnicodeDecodeError as error:
        raise InvalidPreparationInput("commit metadata must be valid UTF-8") from error
    if len(values) != 4 or values[0] != sha:
        raise PreparationFailure("Git returned malformed commit metadata")
    return {
        "sha": values[0],
        "author_name": values[1],
        "author_email": values[2],
        "authored_at": values[3],
    }


def blob_at(repository: Path, sha: str, path: str) -> Blob | None:
    _, output = _git(repository, ["ls-tree", "-z", sha, "--", path])
    exact: list[tuple[str, str]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            decoded_path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise InvalidPreparationInput("Git tree contains an unsupported path record") from error
        if decoded_path == path:
            exact.append((mode, object_type + ":" + object_id))
    if not exact:
        return None
    if len(exact) != 1:
        raise InvalidPreparationInput(f"claim path is ambiguous in the committed tree: {path}")
    mode, typed_object = exact[0]
    object_type, object_id = typed_object.split(":", 1)
    if object_type != "blob":
        raise InvalidPreparationInput(f"claim path does not identify a committed file: {path}")
    _, content = _git(repository, ["cat-file", "blob", object_id])
    return Blob(mode=mode, content=content)


def diff_patch(repository: Path, base_sha: str, head_sha: str) -> bytes:
    _, output = _git(
        repository,
        [
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            base_sha,
            head_sha,
            "--",
        ],
    )
    return output
