#!/usr/bin/env python3
"""Build reproducible Proofrail wheel and source-distribution artifacts offline."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import BinaryIO


NORMALIZED_MTIME = 315532800
DIRECTORY_MODE = 0o755
FILE_MODE = 0o644


class ReleaseBuildError(RuntimeError):
    """Raised when release artifacts cannot be built safely."""


def _normalized_name(raw_name: str) -> str:
    name = raw_name.replace("\\", "/")
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReleaseBuildError(f"unsafe source-distribution member: {raw_name!r}")
    return path.as_posix()


def _read_regular_members(raw_sdist: Path) -> list[tuple[str, bool, bytes]]:
    members: list[tuple[str, bool, bytes]] = []
    seen: set[str] = set()
    top_levels: set[str] = set()
    try:
        with tarfile.open(raw_sdist, mode="r:gz") as archive:
            for member in archive.getmembers():
                name = _normalized_name(member.name)
                if name in seen:
                    raise ReleaseBuildError(
                        f"duplicate normalized source-distribution member: {name!r}"
                    )
                seen.add(name)
                top_levels.add(PurePosixPath(name).parts[0])
                if member.issym() or member.islnk():
                    raise ReleaseBuildError(
                        f"source-distribution links are not allowed: {name!r}"
                    )
                if member.isdir():
                    members.append((name, True, b""))
                    continue
                if not member.isfile():
                    raise ReleaseBuildError(
                        f"unsupported source-distribution member type: {name!r}"
                    )
                source = archive.extractfile(member)
                if source is None:
                    raise ReleaseBuildError(
                        f"cannot read source-distribution member: {name!r}"
                    )
                members.append((name, False, source.read()))
    except (OSError, tarfile.TarError) as error:
        raise ReleaseBuildError(f"cannot read raw source distribution: {error}") from error
    if len(top_levels) != 1 or not members:
        raise ReleaseBuildError(
            "source distribution must contain one non-empty top-level directory"
        )
    top_level = next(iter(top_levels))
    if not any(name == top_level and is_directory for name, is_directory, _ in members):
        raise ReleaseBuildError(
            "source distribution must declare its top-level directory"
        )
    return sorted(members, key=lambda item: item[0])


def _write_normalized_tar(stream: BinaryIO, members: list[tuple[str, bool, bytes]]) -> None:
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, is_directory, content in members:
            member = tarfile.TarInfo(name=name)
            member.mtime = NORMALIZED_MTIME
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mode = DIRECTORY_MODE if is_directory else FILE_MODE
            if is_directory:
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = len(content)
                with tempfile.SpooledTemporaryFile() as payload:
                    payload.write(content)
                    payload.seek(0)
                    archive.addfile(member, payload)


def normalize_sdist(raw_sdist: Path, destination: Path) -> None:
    """Atomically write a safe, deterministic sdist from a backend-produced sdist."""
    members = _read_regular_members(raw_sdist)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=output,
                mtime=NORMALIZED_MTIME,
            ) as compressed:
                _write_normalized_tar(compressed, members)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    except OSError as error:
        raise ReleaseBuildError(f"cannot publish normalized source distribution: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _copy_source(repository: Path, destination: Path) -> None:
    ignored_names = {
        ".git",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in ignored_names
            or name.endswith((".egg-info", ".pyc", ".pyo"))
        }

    shutil.copytree(repository, destination, ignore=ignore, symlinks=False)


def _build_raw_artifacts(source: Path, output: Path) -> tuple[Path, Path]:
    output.mkdir()
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(NORMALIZED_MTIME)
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            "from setuptools.build_meta import build_sdist, build_wheel; "
            "out = Path('raw-dist'); "
            "print(build_sdist(str(out))); print(build_wheel(str(out)))"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=source,
            env=environment,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        raise ReleaseBuildError(f"cannot launch local PEP 517 backend: {error}") from error
    if completed.returncode != 0:
        raise ReleaseBuildError(
            f"local PEP 517 backend failed with exit code {completed.returncode}"
        )
    sdists = sorted(output.glob("*.tar.gz"))
    wheels = sorted(output.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        raise ReleaseBuildError("local PEP 517 backend did not produce one wheel and one sdist")
    return sdists[0], wheels[0]


def _atomic_copy(source: Path, destination: Path) -> None:
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    except OSError as error:
        raise ReleaseBuildError(f"cannot publish wheel: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_release_artifacts(repository: Path, output_directory: Path) -> tuple[Path, Path]:
    repository = repository.resolve(strict=True)
    if not repository.is_dir() or not (repository / "pyproject.toml").is_file():
        raise ReleaseBuildError("repository must contain pyproject.toml")
    if output_directory.is_symlink():
        raise ReleaseBuildError("output directory must not be a symbolic link")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_directory = output_directory.resolve(strict=True)
    published: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="proofrail-release-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "source"
        _copy_source(repository, source)
        raw_output = source / "raw-dist"
        raw_sdist, raw_wheel = _build_raw_artifacts(source, raw_output)
        wheel_destination = output_directory / raw_wheel.name
        sdist_destination = output_directory / raw_sdist.name
        for destination in (wheel_destination, sdist_destination):
            if destination.exists() or destination.is_symlink():
                raise ReleaseBuildError(f"refusing to overwrite release artifact: {destination.name}")
        normalized_sdist = temporary_root / raw_sdist.name
        normalize_sdist(raw_sdist, normalized_sdist)
        try:
            _atomic_copy(raw_wheel, wheel_destination)
            published.append(wheel_destination)
            _atomic_copy(normalized_sdist, sdist_destination)
            published.append(sdist_destination)
        except BaseException:
            for path in published:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise
    return wheel_destination, sdist_destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic Proofrail release artifacts offline."
    )
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        wheel, sdist = build_release_artifacts(
            arguments.repository, arguments.output_dir
        )
    except (OSError, ReleaseBuildError) as error:
        print(f"proofrail release build failed: {error}", file=sys.stderr)
        return 1
    for path in (wheel, sdist):
        print(f"{path.name} sha256={_sha256(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
