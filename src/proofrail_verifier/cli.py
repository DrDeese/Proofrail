"""Command-line interface for the offline deterministic verifier."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .artifacts import ArtifactInspectionError
from .change_verification import verify_change
from .evaluation import VerificationError, evaluate_case
from .loading import FixtureLoadError, load_case_directory
from .preparation import (
    InvalidPreparationInput,
    OutputWriteFailure,
    PreparationFailure,
    prepare_case,
)
from .policy import (
    PolicyEvaluationError,
    PolicyInputError,
    PolicyOutputError,
    evaluate_policy,
    load_policy,
    load_result,
    write_new_atomic,
)
from .policy_rendering import render_policy_json, render_policy_markdown
from .rendering import render_json, render_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofrail_verifier")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify a supported local case directory")
    verify.add_argument("case_directory", type=Path)
    verify.add_argument("--format", choices=("json", "markdown"), default="json")
    verify.add_argument("--output", type=Path)
    prepare = commands.add_parser(
        "prepare-case", help="prepare a case from a local committed Git range"
    )
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--head", required=True)
    prepare.add_argument("--claim-file", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    change = commands.add_parser(
        "verify-change", help="prepare and verify a local committed Git range"
    )
    change.add_argument("--repo", type=Path, required=True)
    change.add_argument("--base", required=True)
    change.add_argument("--head", required=True)
    change.add_argument("--claim-file", type=Path, required=True)
    change.add_argument("--format", choices=("json", "markdown"), default="json")
    change.add_argument("--output", type=Path)
    change.add_argument("--keep-case", type=Path)
    change.add_argument("--policy", type=Path)
    enforce = commands.add_parser(
        "enforce", help="evaluate an acceptance policy against a completed result"
    )
    enforce.add_argument("--result", type=Path, required=True)
    enforce.add_argument("--policy", type=Path, required=True)
    enforce.add_argument("--format", choices=("json", "markdown"), default="json")
    enforce.add_argument("--output", type=Path)
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


def _verify(arguments: argparse.Namespace) -> int:
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
    except (OSError, UnicodeError) as error:
        print(f"proofrail: output write failed: {error}", file=sys.stderr)
        return 5
    return 0


def _prepare(arguments: argparse.Namespace) -> int:
    try:
        result = prepare_case(
            arguments.repo,
            arguments.base,
            arguments.head,
            arguments.claim_file,
            arguments.output_dir,
        )
    except InvalidPreparationInput as error:
        print(f"proofrail: invalid preparation input: {error}", file=sys.stderr)
        return 3
    except PreparationFailure as error:
        print(f"proofrail: preparation failed: {error}", file=sys.stderr)
        return 4
    except OutputWriteFailure as error:
        print(f"proofrail: output write failed: {error}", file=sys.stderr)
        return 5
    print(f"case id: {result.case_id}")
    print(f"base sha: {result.base_sha}")
    print(f"head sha: {result.head_sha}")
    print(f"output directory: {arguments.output_dir}")
    print(f"atomic claims: {result.claim_count}")
    print(f"changed paths: {result.changed_path_count}")
    return 0


def _verify_change(arguments: argparse.Namespace) -> int:
    try:
        completed = verify_change(
            arguments.repo,
            arguments.base,
            arguments.head,
            arguments.claim_file,
            result_format=arguments.format,
            output=arguments.output if arguments.policy is None else None,
            keep_case=arguments.keep_case,
        )
    except InvalidPreparationInput as error:
        print(f"proofrail: invalid change input: {error}", file=sys.stderr)
        return 3
    except PreparationFailure as error:
        print(f"proofrail: change verification failed: {error}", file=sys.stderr)
        return 4
    except OutputWriteFailure as error:
        print(f"proofrail: output write failed: {error}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        print("proofrail: change verification failed: interrupted", file=sys.stderr)
        return 4
    if arguments.policy is None:
        try:
            if arguments.output is None:
                sys.stdout.write(completed.rendered)
        except (OSError, UnicodeError) as error:
            print(f"proofrail: output write failed: {error}", file=sys.stderr)
            return 5
        return 0
    return _evaluate_and_publish_policy(
        completed.result,
        arguments.policy,
        arguments.format,
        arguments.output,
        protected=(arguments.policy,),
    )


def _evaluate_and_publish_policy(
    result: dict[str, object],
    policy_path: Path,
    result_format: str,
    output: Path | None,
    *,
    protected: tuple[Path, ...],
) -> int:
    try:
        policy = load_policy(policy_path)
        decision = evaluate_policy(result, policy)
    except PolicyInputError as error:
        print(f"proofrail: invalid policy input: {error}", file=sys.stderr)
        return 3
    except PolicyEvaluationError as error:
        print(f"proofrail: policy evaluation failed: {error}", file=sys.stderr)
        return 4
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        print(f"proofrail: policy evaluation failed: {error}", file=sys.stderr)
        return 4

    try:
        rendered = (
            render_policy_json(decision)
            if result_format == "json"
            else render_policy_markdown(decision)
        )
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        print(f"proofrail: policy evaluation failed: {error}", file=sys.stderr)
        return 4
    try:
        if output is None:
            sys.stdout.write(rendered)
        else:
            write_new_atomic(output, rendered, protected)
    except (PolicyOutputError, OSError, UnicodeError) as error:
        print(f"proofrail: output write failed: {error}", file=sys.stderr)
        return 5
    return 0 if decision["accepted"] else 1


def _enforce(arguments: argparse.Namespace) -> int:
    try:
        result = load_result(arguments.result)
    except PolicyInputError as error:
        print(f"proofrail: invalid policy input: {error}", file=sys.stderr)
        return 3
    return _evaluate_and_publish_policy(
        result,
        arguments.policy,
        arguments.format,
        arguments.output,
        protected=(arguments.result, arguments.policy),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "prepare-case":
        return _prepare(arguments)
    if arguments.command == "verify-change":
        return _verify_change(arguments)
    if arguments.command == "enforce":
        return _enforce(arguments)
    return _verify(arguments)
