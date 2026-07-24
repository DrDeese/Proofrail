from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_release_artifacts.py"
BUILD_MODULE = runpy.run_path(str(BUILD_SCRIPT))
ReleaseBuildError = BUILD_MODULE["ReleaseBuildError"]
normalize_sdist = BUILD_MODULE["normalize_sdist"]
NORMALIZED_MTIME = BUILD_MODULE["NORMALIZED_MTIME"]
VERSION = "0.1.0a1"
DEMO_RELATIVE_FILES = (
    "actual.patch",
    "case.json",
    "initial/.github/workflows/ci.yml",
    "initial/bun.lock",
    "initial/bun.lockb",
)


class DistributionTests(unittest.TestCase):
    def _project_copy(self, root: Path) -> Path:
        project = root / "project"
        shutil.copytree(
            REPOSITORY_ROOT,
            project,
            ignore=shutil.ignore_patterns(
                ".git", "build", "dist", "*.egg-info", "__pycache__", "*.pyc"
            ),
        )
        return project

    @staticmethod
    def _digest_tree(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _build_release(self, project: Path, output: Path) -> tuple[Path, Path]:
        completed = subprocess.run(
            [
                sys.executable,
                str(project / "scripts" / "build_release_artifacts.py"),
                "--repository",
                str(project),
                "--output-dir",
                str(output),
            ],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        wheel = next(output.glob("proofrail-*.whl"), None)
        sdist = next(output.glob("proofrail-*.tar.gz"), None)
        self.assertIsNotNone(wheel)
        self.assertIsNotNone(sdist)
        self.assertEqual(sorted(path.name for path in output.iterdir()), sorted([wheel.name, sdist.name]))
        return wheel, sdist

    def _build_raw_artifacts(self, project: Path, output: Path) -> tuple[Path, Path]:
        output.mkdir()
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = str(NORMALIZED_MTIME)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from setuptools.build_meta import build_sdist, build_wheel; print(build_sdist('raw-dist')); print(build_wheel('raw-dist'))",
            ],
            cwd=project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return next(output.glob("*.tar.gz")), next(output.glob("*.whl"))

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _regular_files(path: Path) -> dict[str, bytes]:
        with tarfile.open(path, mode="r:gz") as archive:
            result: dict[str, bytes] = {}
            for member in archive.getmembers():
                if member.isfile():
                    source = archive.extractfile(member)
                    if source is None:
                        raise AssertionError(member.name)
                    result[member.name.replace("\\", "/")] = source.read()
            return result

    @staticmethod
    def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_helper_builds_byte_identical_complete_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_project = self._project_copy(root / "first")
            first_before = self._digest_tree(first_project)
            first_wheel, first_sdist = self._build_release(first_project, root / "first-release")
            self.assertEqual(first_before, self._digest_tree(first_project))

            second_project = self._project_copy(root / "second")
            second_before = self._digest_tree(second_project)
            second_wheel, second_sdist = self._build_release(second_project, root / "second-release")
            self.assertEqual(second_before, self._digest_tree(second_project))

            self.assertEqual(self._sha256(first_wheel), self._sha256(second_wheel))
            self.assertEqual(self._sha256(first_sdist), self._sha256(second_sdist))

            with tarfile.open(first_sdist) as source:
                names = set(source.getnames())
            prefix = f"proofrail-{VERSION}/"
            required_sdist = {
                f"{prefix}CHANGELOG.md",
                f"{prefix}LICENSE",
                f"{prefix}README.md",
                f"{prefix}docs/PROJECT_STATUS.md",
                f"{prefix}docs/QUICKSTART.md",
                f"{prefix}docs/RELEASING.md",
                f"{prefix}schemas/case.schema.json",
                f"{prefix}src/proofrail_verifier/cli.py",
                f"{prefix}src/proofrail_verifier/loading.py",
                f"{prefix}src/proofrail_verifier/preparation.py",
            }
            required_sdist.update(
                f"{prefix}src/proofrail_verifier/demo/001-partial-workflow-fix/{relative}"
                for relative in DEMO_RELATIVE_FILES
            )
            self.assertTrue(required_sdist.issubset(names))
            self.assertFalse(any("tests/" in name or "fixtures/" in name for name in names))

            with zipfile.ZipFile(first_wheel) as source:
                wheel_names = set(source.namelist())
                metadata = source.read(
                    f"proofrail-{VERSION}.dist-info/METADATA"
                ).decode("utf-8")
            self.assertIn("proofrail_verifier/cli.py", wheel_names)
            self.assertIn(
                f"proofrail-{VERSION}.data/data/proofrail_verifier/case.schema.json",
                wheel_names,
            )
            self.assertIn(f"proofrail-{VERSION}.dist-info/LICENSE", wheel_names)
            for relative in DEMO_RELATIVE_FILES:
                self.assertIn(
                    f"proofrail_verifier/demo/001-partial-workflow-fix/{relative}",
                    wheel_names,
                )
            self.assertFalse(any(name.startswith("tests/") for name in wheel_names))
            for expected_metadata in (
                "Name: proofrail",
                f"Version: {VERSION}",
                "Home-page: https://github.com/DrDeese/Proofrail",
                "License: Apache-2.0",
                "Project-URL: Source, https://github.com/DrDeese/Proofrail",
                "Project-URL: Issues, https://github.com/DrDeese/Proofrail/issues",
                "Project-URL: Documentation, https://github.com/DrDeese/Proofrail#readme",
            ):
                self.assertIn(expected_metadata, metadata)

    def test_packaged_demo_resources_match_fixture_byte_for_byte(self) -> None:
        fixture = REPOSITORY_ROOT / "tests" / "fixtures" / "001-partial-workflow-fix"
        packaged = (
            REPOSITORY_ROOT
            / "src"
            / "proofrail_verifier"
            / "demo"
            / "001-partial-workflow-fix"
        )
        for relative in DEMO_RELATIVE_FILES:
            with self.subTest(relative=relative):
                self.assertEqual(
                    (packaged / relative).read_bytes(),
                    (fixture / relative).read_bytes(),
                )

    def test_normalized_sdist_preserves_files_and_has_fixed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project_copy(root / "raw")
            raw_sdist, raw_wheel = self._build_raw_artifacts(project, project / "raw-dist")
            release_project = self._project_copy(root / "release")
            final_wheel, final_sdist = self._build_release(release_project, root / "release-artifacts")
            self.assertEqual(raw_wheel.read_bytes(), final_wheel.read_bytes())
            self.assertEqual(self._regular_files(raw_sdist), self._regular_files(final_sdist))

            header = final_sdist.read_bytes()[:10]
            self.assertEqual(header[3] & 0x08, 0)
            self.assertEqual(int.from_bytes(header[4:8], "little"), NORMALIZED_MTIME)
            with tarfile.open(final_sdist, mode="r:gz") as archive:
                members = archive.getmembers()
                self.assertEqual([member.name for member in members], sorted(member.name for member in members))
                for member in members:
                    self.assertEqual(member.mtime, NORMALIZED_MTIME)
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    self.assertEqual((member.uname, member.gname), ("", ""))
                    self.assertEqual(member.mode, 0o755 if member.isdir() else 0o644)

            extracted = root / "extracted"
            extracted.mkdir()
            with tarfile.open(final_sdist, mode="r:gz") as archive:
                archive.extractall(extracted)
            source_root = extracted / f"proofrail-{VERSION}"
            wheel_output = source_root / "validation-wheel"
            wheel_output.mkdir()
            environment = os.environ.copy()
            environment["SOURCE_DATE_EPOCH"] = str(NORMALIZED_MTIME)
            rebuilt = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from setuptools.build_meta import build_wheel; print(build_wheel('validation-wheel'))",
                ],
                cwd=source_root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            self.assertEqual(len(list(wheel_output.glob("*.whl"))), 1)

    def test_unsafe_archives_are_rejected_and_partial_outputs_are_cleaned(self) -> None:
        cases = (
            ("absolute", "/escape"),
            ("traversal", "root/../escape"),
            ("backslash-traversal", "root\\..\\escape"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, unsafe_name in cases:
                with self.subTest(label=label):
                    raw = root / f"{label}.tar.gz"
                    with tarfile.open(raw, mode="w:gz") as archive:
                        directory = tarfile.TarInfo("root")
                        directory.type = tarfile.DIRTYPE
                        archive.addfile(directory)
                        member = tarfile.TarInfo(unsafe_name)
                        member.size = 1
                        archive.addfile(member, io.BytesIO(b"x"))
                    destination = root / f"{label}-final.tar.gz"
                    with self.assertRaises(ReleaseBuildError):
                        normalize_sdist(raw, destination)
                    self.assertFalse(destination.exists())
                    self.assertEqual(list(root.glob(f".{destination.name}.*")), [])

            link_raw = root / "link.tar.gz"
            with tarfile.open(link_raw, mode="w:gz") as archive:
                directory = tarfile.TarInfo("root")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
                link = tarfile.TarInfo("root/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../escape"
                archive.addfile(link)
            with self.assertRaises(ReleaseBuildError):
                normalize_sdist(link_raw, root / "link-final.tar.gz")

            duplicate_raw = root / "duplicate.tar.gz"
            with tarfile.open(duplicate_raw, mode="w:gz") as archive:
                directory = tarfile.TarInfo("root")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
                for name in ("root/file", "root\\file"):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaises(ReleaseBuildError):
                normalize_sdist(duplicate_raw, root / "duplicate-final.tar.gz")

    def test_clean_wheel_runs_every_command_without_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project_copy(root / "build")
            wheel, _ = self._build_release(project, root / "release")
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            installations: list[tuple[Path, Path, Path]] = []
            outputs: list[str] = []
            demo_outputs: list[str] = []
            text_outputs: list[str] = []
            schema_hashes: list[str] = []
            for name in ("first-clean-install", "second-clean-install-with-different-path"):
                venv_dir = root / name
                venv.EnvBuilder(with_pip=True).create(venv_dir)
                interpreter = venv_dir / "bin" / "python"
                command = venv_dir / "bin" / "proofrail"
                installed = self._run(
                    [str(interpreter), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(installed.returncode, 0, installed.stderr)
                version = self._run(
                    [str(command), "--version"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(version.returncode, 0, version.stderr)
                self.assertEqual(version.stdout, f"{VERSION}\n")
                self.assertEqual(version.stderr, "")
                demo = self._run(
                    [str(command), "verify", "--demo"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(demo.returncode, 0, demo.stderr)
                self.assertEqual(demo.stderr, "")
                self.assertIn(
                    "\nOverall verdict: partially_verified - "
                    "some claims are supported, while others are not or "
                    "still need human review.\n",
                    demo.stdout,
                )
                demo_outputs.append(demo.stdout)
                schema_query = self._run(
                    [str(interpreter), "-c", "import sysconfig; from pathlib import Path; print(Path(sysconfig.get_path('data')) / 'proofrail_verifier' / 'case.schema.json')"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(schema_query.returncode, 0, schema_query.stderr)
                schema_path = Path(schema_query.stdout.strip())
                installations.append((interpreter, command, schema_path))

                case = root / f"case-{name}"
                shutil.copytree(REPOSITORY_ROOT / "tests" / "fixtures" / "001-partial-workflow-fix", case)
                verified = self._run(
                    [str(command), "verify", str(case), "--format", "json"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(verified.returncode, 0, verified.stderr)
                result = json.loads(verified.stdout)
                self.assertEqual(result["overall_verdict"], "partially_verified")
                self.assertEqual(
                    result["sources"]["schema"]["path"],
                    "proofrail_verifier/case.schema.json",
                )
                outputs.append(verified.stdout)
                schema_hashes.append(result["sources"]["schema"]["sha256"])
                text = self._run(
                    [str(command), "verify", str(case), "--format", "text"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(text.returncode, 0, text.stderr)
                text_outputs.append(text.stdout)

            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(demo_outputs[0], demo_outputs[1])
            self.assertEqual(text_outputs[0], text_outputs[1])
            self.assertEqual(schema_hashes[0], schema_hashes[1])
            interpreter, command, packaged_schema = installations[0]
            help_result = self._run([str(command), "--help"], cwd=root, environment=environment)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            for subcommand in ("verify", "prepare-case", "verify-change", "draft-claims", "check-claims", "enforce"):
                self.assertIn(subcommand, help_result.stdout)

            repository = root / "source-repository"
            shutil.copytree(REPOSITORY_ROOT / "tests" / "source_repositories" / "partial-workflow-fix", repository)
            base = self._run(["git", "-C", str(repository), "rev-parse", "HEAD^"], cwd=root, environment=environment)
            head = self._run(["git", "-C", str(repository), "rev-parse", "HEAD"], cwd=root, environment=environment)
            self.assertEqual(base.returncode, 0, base.stderr)
            self.assertEqual(head.returncode, 0, head.stderr)
            claims = root / "claims.md"
            common = ["--repo", str(repository), "--base", base.stdout.strip(), "--head", head.stdout.strip()]
            commands = [
                [str(command), "draft-claims", *common, "--output", str(claims)],
                [str(command), "check-claims", *common, "--claim-file", str(claims)],
                [str(command), "prepare-case", *common, "--claim-file", str(claims), "--output-dir", str(root / "case-output")],
                [str(command), "verify-change", *common, "--claim-file", str(claims), "--output", str(root / "result.json")],
                [str(command), "enforce", "--result", str(root / "result.json"), "--policy", str(REPOSITORY_ROOT / ".proofrail" / "policy.yml")],
            ]
            for command_line in commands:
                completed = self._run(command_line, cwd=root, environment=environment)
                self.assertEqual(completed.returncode, 0, completed.stderr)

            original_schema = packaged_schema.read_bytes()
            packaged_schema.write_text("not json\n", encoding="utf-8")
            malformed = self._run(
                [str(command), "verify", str(root / "case-first-clean-install")],
                cwd=root,
                environment=environment,
            )
            self.assertEqual(malformed.returncode, 3)
            self.assertIn("invalid JSON in case.schema.json", malformed.stderr)
            packaged_schema.unlink()
            missing = self._run(
                [str(command), "verify", str(root / "case-first-clean-install")],
                cwd=root,
                environment=environment,
            )
            self.assertEqual(missing.returncode, 3)
            self.assertIn("cannot locate canonical case schema", missing.stderr)
            packaged_schema.write_bytes(original_schema)

            for interpreter, command, _ in installations:
                removed = self._run(
                    [str(interpreter), "-m", "pip", "uninstall", "-y", "proofrail"],
                    cwd=root,
                    environment=environment,
                )
                self.assertEqual(removed.returncode, 0, removed.stderr)
                self.assertFalse(command.exists())

    def test_source_checkout_schema_has_priority(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = "src"
        completed = self._run(
            [
                sys.executable,
                "-c",
                "from proofrail_verifier.loading import resolve_case_schema; print(resolve_case_schema())",
            ],
            cwd=REPOSITORY_ROOT,
            environment=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            Path(completed.stdout.strip()).resolve(),
            (REPOSITORY_ROOT / "schemas" / "case.schema.json").resolve(),
        )
        verified = self._run(
            [
                sys.executable,
                "-m",
                "proofrail_verifier",
                "verify",
                "tests/fixtures/001-partial-workflow-fix",
                "--format",
                "json",
            ],
            cwd=REPOSITORY_ROOT,
            environment=environment,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(
            json.loads(verified.stdout)["sources"]["schema"]["path"],
            "schemas/case.schema.json",
        )


if __name__ == "__main__":
    unittest.main()
