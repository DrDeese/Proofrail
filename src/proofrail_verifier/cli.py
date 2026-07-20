"""Command-line interface for the offline deterministic verifier."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .artifacts import ArtifactInspectionError
from .evaluation import VerificationError, evaluate_case
from .loading import FixtureLoadError, load_case_directory
from .rendering import render_json, render_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofrail_verifier")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify a supported local case directory")
    verify.add_argument("case_directory", type=Path)
    verify.add_argument("--format", choices=("json", "markdown"), default="json")
    verify.add_argument("--output", type=Path)
    return parser


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def write_atomic(path: Path, content: str, case_directory: Path) -> None:
    destination = path.resolve()
    if _inside(destination, case_directory.resolve()):
        raise OSError("refusing to write output inside the case directory")
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        bundle = load_case_directory(arguments.case_directory)
    except FixtureLoadError as error:
        print(f"proofrail: invalid case: {error}", file=sys.stderr)
        return 3

    try:
        result = evaluate_case(bundle)
    except (VerificationError, ArtifactInspectionError, OSError, UnicodeError) as error:
        print(f"proofrail: verification failed: {error}", file=sys.stderr)
        return 4
    except (KeyError, TypeError, ValueError) as error:
        print(f"proofrail: invalid case: {error}", file=sys.stderr)
        return 3

    rendered = render_json(result) if arguments.format == "json" else render_markdown(result)
    try:
        if arguments.output is None:
            sys.stdout.write(rendered)
        else:
            write_atomic(arguments.output, rendered, bundle.fixture_dir)
    except OSError as error:
        print(f"proofrail: output write failed: {error}", file=sys.stderr)
        return 5
    return 0
