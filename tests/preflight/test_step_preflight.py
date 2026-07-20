from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "proofrail_step_preflight.py"
SPEC = importlib.util.spec_from_file_location("proofrail_step_preflight", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class RepositoryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.contract_path = ".proofrail/test-contract.yml"
        self.output_path = ".proofrail/result.json"
        self.claim_id = "current-artifact-modified"
        self.authorized = ["artifact.txt"]
        self.stale: list[tuple[str, int, list[str]]] = []
        self.commands = {
            "action": ["python3", "-m", "unittest", "discover", "-s", "tests/action", "-v"],
            "end-to-end": ["python3", "-m", "unittest", "discover", "-s", "tests/end_to_end", "-v"],
            "policy": ["python3", "-m", "unittest", "discover", "-s", "tests/policy", "-v"],
        }

    def git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=check, text=True, capture_output=True
        )

    def initialize(self) -> None:
        self.git("init", "-q")
        self.git("config", "user.name", "Proofrail test")
        self.git("config", "user.email", "proofrail@example.invalid")
        (self.root / "contracts").mkdir()
        shutil.copy2(ROOT / "contracts" / "step-contract.schema.json", self.root / "contracts")
        (self.root / "scripts").mkdir()
        shutil.copy2(SCRIPT, self.root / "scripts")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/test.yml").write_text(
            "name: Test\n"
            "on:\n  push:\n"
            "permissions:\n  contents: read\n"
            "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n          fetch-depth: 0\n          persist-credentials: false\n"
            "      - name: Assert contract values\n        run: |\n"
            "          test \"$VERDICT\" = \"verified\"\n"
            "          test \"$POLICY\" = \"true\"\n"
            "          test \"$FIXTURE\" = \"partially_verified\"\n"
            "          fixture-one\n"
            "          claims.allowed-statuses\n"
            "          \"current-artifact-modified\": \"verified\"\n",
            encoding="utf-8",
        )
        for suite in ("action", "end_to_end", "policy"):
            directory = self.root / "tests" / suite
            directory.mkdir(parents=True)
            (directory / "test_pass.py").write_text(
                "import unittest\n\nclass PassTest(unittest.TestCase):\n"
                "    def test_pass(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
        (self.root / "artifact.txt").write_text("before\n", encoding="utf-8")
        (self.root / ".proofrail").mkdir()
        (self.root / ".proofrail/.keep").write_text("", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.root / "artifact.txt").write_text("after\n", encoding="utf-8")
        self.write_contract()

    def contract_text(self) -> str:
        lines = [
            "version: 1",
            "step: 99",
            f"base-sha: {self.base}",
            "",
            "workflow:",
            "  path: .github/workflows/test.yml",
            "",
            "tests:",
        ]
        for name in ("action", "end-to-end", "policy"):
            lines.extend([f"  {name}:", "    command:"])
            lines.extend(f"      - {argument}" for argument in self.commands[name])
        lines.extend(["", "authorized-files:"])
        lines.extend(f"  - {path}" for path in self.authorized)
        lines.extend(
            [
                "",
                "expectations:",
                "  claim-statuses:",
                f"    {self.claim_id}: verified",
                "  overall-verdict: verified",
                "  policy-accepted: true",
                "  allowed-statuses-source: claims.allowed-statuses",
                "  exceptions-applied: []",
                "  fixture-verdicts:",
                "    fixture-one: partially_verified",
                "",
                "security:",
                "  permissions:",
                "    contents: read",
                "  approved-actions:",
                "    - actions/checkout@v4",
                "  fetch-depth: 0",
                "  persist-credentials: false",
                "",
                "stale-identifiers:",
            ]
        )
        if not self.stale:
            lines[-1] = "stale-identifiers: []"
        else:
            for value, owner, allowed in self.stale:
                encoded = json.dumps(value) if any(character in value for character in ':"') else value
                lines.extend([f"  - value: {encoded}", f"    owner-step: {owner}", "    allowed-files:"])
                if allowed:
                    lines.extend(f"      - {path}" for path in allowed)
                else:
                    lines[-1] = "    allowed-files: []"
        return "\n".join(lines) + "\n"

    def write_contract(self, text: str | None = None) -> None:
        (self.root / self.contract_path).write_text(text or self.contract_text(), encoding="utf-8")

    def run(self, *, output: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--repository",
                str(self.root),
                "--contract",
                self.contract_path,
                "--output",
                output or self.output_path,
            ],
            text=True,
            capture_output=True,
        )

    def report(self, output: str | None = None) -> dict[str, object]:
        return json.loads((self.root / (output or self.output_path)).read_text(encoding="utf-8"))


class StepPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = RepositoryFixture(Path(self.temporary.name) / "repo")
        self.repository.root.mkdir()
        self.repository.initialize()

    def assert_failure(self, expected_check: str, expected_exit: int = 1) -> dict[str, object]:
        completed = self.repository.run()
        self.assertEqual(expected_exit, completed.returncode, completed.stderr)
        result = self.repository.report()
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(expected_check, result["failure"]["check"])
        statuses = [entry["status"] for entry in result["checks"]]
        failure_index = next(index for index, status in enumerate(statuses) if status == "FAIL")
        self.assertTrue(all(status == "NOT_RUN" for status in statuses[failure_index + 1 :]))
        return result

    def test_valid_contract_parses_and_all_values_are_loaded(self) -> None:
        value = PREFLIGHT.parse_bounded_yaml(
            (self.repository.root / self.repository.contract_path).read_text(), contract=True
        )
        schema = json.loads((self.repository.root / "contracts/step-contract.schema.json").read_text())
        contract = PREFLIGHT.validate_contract(value, schema)
        self.assertEqual(self.repository.commands["action"], contract["tests"]["action"]["command"])
        self.assertEqual(self.repository.claim_id, next(iter(contract["expectations"]["claim-statuses"])))

    def test_workflow_yaml_parses(self) -> None:
        workflow = PREFLIGHT.parse_bounded_yaml(
            (self.repository.root / ".github/workflows/test.yml").read_text(), contract=False
        )
        self.assertEqual("Test", workflow["name"])

    def test_pass_is_deterministic_relative_and_exit_zero(self) -> None:
        first = self.repository.run(output=".proofrail/one.json")
        one = (self.repository.root / ".proofrail/one.json").read_bytes()
        (self.repository.root / ".proofrail/one.json").unlink()
        second = self.repository.run(output=".proofrail/two.json")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        two = (self.repository.root / ".proofrail/two.json").read_bytes()
        self.assertEqual(one, two)
        self.assertNotIn(str(self.repository.root).encode(), one)
        report = json.loads(one)
        self.assertEqual("PASS", report["status"])
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))

    def test_exact_authorized_path_with_spaces_passes(self) -> None:
        (self.repository.root / "artifact.txt").write_text("before\n", encoding="utf-8")
        (self.repository.root / "path with spaces.txt").write_text("new\n", encoding="utf-8")
        self.repository.authorized = ["path with spaces.txt"]
        self.repository.write_contract()
        completed = self.repository.run()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_binary_authorized_file_does_not_crash_stale_sweep(self) -> None:
        (self.repository.root / "artifact.txt").write_bytes(b"after\0binary\xff")
        self.repository.stale = [("old-step-claim", 12, [])]
        self.repository.write_contract()
        completed = self.repository.run()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_missing_contract_exits_three(self) -> None:
        (self.repository.root / self.repository.contract_path).unlink()
        completed = self.repository.run()
        self.assertEqual(3, completed.returncode)
        self.assertFalse((self.repository.root / self.repository.output_path).exists())

    def test_invalid_yaml(self) -> None:
        self.repository.write_contract("version 1\n")
        self.assert_failure("contract", 3)

    def test_yaml_aliases_are_rejected(self) -> None:
        self.repository.write_contract(self.repository.contract_text().replace("version: 1", "version: &v 1\ncopy: *v"))
        self.assert_failure("contract", 3)

    def test_yaml_tags_and_constructors_are_rejected(self) -> None:
        self.repository.write_contract(self.repository.contract_text().replace("step: 99", "step: !!python/object 99"))
        self.assert_failure("contract", 3)

    def test_unknown_key(self) -> None:
        self.repository.write_contract(self.repository.contract_text() + "unknown: value\n")
        self.assert_failure("contract", 3)

    def test_missing_required_key(self) -> None:
        text = self.repository.contract_text().replace("version: 1\n", "")
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)

    def test_wrong_version(self) -> None:
        self.repository.write_contract(self.repository.contract_text().replace("version: 1", "version: 2"))
        self.assert_failure("contract", 3)

    def test_short_and_invalid_base_sha(self) -> None:
        for value in ("abc", "G" * 40):
            with self.subTest(value=value):
                output = f".proofrail/{value[:3]}.json"
                text = self.repository.contract_text().replace(self.repository.base, value)
                self.repository.write_contract(text)
                completed = self.repository.run(output=output)
                self.assertEqual(3, completed.returncode)
        self.repository.write_contract()

    def test_missing_base_commit(self) -> None:
        self.repository.write_contract(self.repository.contract_text().replace(self.repository.base, "0" * 40))
        self.assert_failure("contract", 3)

    def test_absolute_authorized_path(self) -> None:
        self.repository.authorized = ["/tmp/file"]
        self.repository.write_contract()
        self.assert_failure("contract", 3)

    def test_dot_dot_traversal(self) -> None:
        self.repository.authorized = ["../file"]
        self.repository.write_contract()
        self.assert_failure("contract", 3)

    def test_duplicate_authorized_file(self) -> None:
        self.repository.authorized = ["artifact.txt", "artifact.txt"]
        self.repository.write_contract()
        self.assert_failure("contract", 3)

    def test_duplicate_claim_id_and_stale_value_are_rejected(self) -> None:
        text = self.repository.contract_text().replace(
            f"    {self.repository.claim_id}: verified",
            f"    {self.repository.claim_id}: verified\n    {self.repository.claim_id}: unsupported",
        )
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)
        (self.repository.root / self.repository.output_path).unlink()
        self.repository.stale = [("duplicate-old-id", 11, []), ("duplicate-old-id", 12, [])]
        self.repository.write_contract()
        self.assert_failure("contract", 3)

    def test_invalid_status_and_verdict_are_rejected(self) -> None:
        text = self.repository.contract_text().replace(
            f"    {self.repository.claim_id}: verified", f"    {self.repository.claim_id}: maybe"
        )
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)
        (self.repository.root / self.repository.output_path).unlink()
        text = self.repository.contract_text().replace("  overall-verdict: verified", "  overall-verdict: maybe")
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)

    def test_test_command_cannot_be_shell_string(self) -> None:
        text = self.repository.contract_text().replace(
            "    command:\n      - python3\n      - -m\n      - unittest\n      - discover\n      - -s\n      - tests/action\n      - -v",
            "    command: python3 -m unittest discover -s tests/action -v",
            1,
        )
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)

    def test_test_command_cannot_select_an_unapproved_suite(self) -> None:
        text = self.repository.contract_text().replace("      - tests/action", "      - tests/policy", 1)
        self.repository.write_contract(text)
        self.assert_failure("contract", 3)

    def test_empty_test_suite_cannot_produce_pass(self) -> None:
        (self.repository.root / "tests/action/test_pass.py").write_text("# no tests\n", encoding="utf-8")
        self.repository.authorized.append("tests/action/test_pass.py")
        self.repository.write_contract()
        self.assert_failure("action-tests")

    def test_missing_workflow(self) -> None:
        (self.repository.root / ".github/workflows/test.yml").unlink()
        self.assert_failure("workflow-yaml", 3)

    def test_invalid_workflow_yaml(self) -> None:
        (self.repository.root / ".github/workflows/test.yml").write_text("name Test\n", encoding="utf-8")
        self.assert_failure("workflow-yaml", 4)

    def _make_suite_fail(self, suite: str) -> None:
        (self.repository.root / "tests" / suite / "test_pass.py").write_text(
            "import unittest\n\nclass FailTest(unittest.TestCase):\n"
            "    def test_fail(self):\n        self.fail('expected')\n",
            encoding="utf-8",
        )
        self.repository.authorized.append(f"tests/{suite}/test_pass.py")
        self.repository.write_contract()

    def test_action_tests_fail(self) -> None:
        self._make_suite_fail("action")
        self.assert_failure("action-tests")

    def test_end_to_end_tests_fail(self) -> None:
        self._make_suite_fail("end_to_end")
        self.assert_failure("end-to-end-tests")

    def test_policy_tests_fail(self) -> None:
        self._make_suite_fail("policy")
        self.assert_failure("policy-tests")

    def test_git_diff_check_fails(self) -> None:
        (self.repository.root / "artifact.txt").write_text("trailing \n", encoding="utf-8")
        self.assert_failure("diff-check")

    def test_unexpected_changed_file(self) -> None:
        (self.repository.root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        result = self.assert_failure("authorized-files")
        self.assertEqual(["unexpected.txt"], result["failure"]["unexpected"])

    def test_missing_authorized_changed_file(self) -> None:
        self.repository.authorized.append("missing.txt")
        self.repository.write_contract()
        result = self.assert_failure("authorized-files")
        self.assertEqual(["missing.txt"], result["failure"]["missing"])

    def test_untracked_unexpected_file(self) -> None:
        (self.repository.root / "untracked file.txt").write_text("new\n", encoding="utf-8")
        self.assert_failure("authorized-files")

    def test_ignored_untracked_file_is_still_unexpected(self) -> None:
        (self.repository.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        self.repository.git("add", ".gitignore")
        self.repository.git("commit", "-q", "-m", "ignore baseline")
        self.repository.base = self.repository.git("rev-parse", "HEAD").stdout.strip()
        (self.repository.root / "artifact.txt").write_text("after again\n", encoding="utf-8")
        (self.repository.root / "ignored.txt").write_text("ignored but changed\n", encoding="utf-8")
        self.repository.write_contract()
        result = self.assert_failure("authorized-files")
        self.assertEqual(["ignored.txt"], result["failure"]["unexpected"])

    def test_stale_identifier_in_diff(self) -> None:
        (self.repository.root / "artifact.txt").write_text("old-step-claim\n", encoding="utf-8")
        self.repository.stale = [("old-step-claim", 12, [])]
        self.repository.write_contract()
        result = self.assert_failure("stale-identifiers")
        self.assertEqual("artifact.txt", result["failure"]["file"])

    def test_stale_identifier_surviving_in_touched_file(self) -> None:
        self.repository.git("checkout", self.repository.base, "--", "artifact.txt")
        (self.repository.root / "artifact.txt").write_text("old-step-claim\nbefore\n", encoding="utf-8")
        self.repository.git("add", "artifact.txt")
        self.repository.git("commit", "-q", "-m", "stale base")
        self.repository.base = self.repository.git("rev-parse", "HEAD").stdout.strip()
        (self.repository.root / "artifact.txt").write_text("old-step-claim\nafter\n", encoding="utf-8")
        self.repository.stale = [("old-step-claim", 12, [])]
        self.repository.write_contract()
        self.assert_failure("stale-identifiers")

    def test_stale_identifier_in_symlink_target_is_detected_without_following(self) -> None:
        (self.repository.root / "artifact.txt").unlink()
        (self.repository.root / "artifact.txt").symlink_to("old-step-claim")
        self.repository.stale = [("old-step-claim", 12, [])]
        self.repository.write_contract()
        result = self.assert_failure("stale-identifiers")
        self.assertEqual("artifact.txt", result["failure"]["file"])

    def test_explicitly_allowed_stale_identifier_passes(self) -> None:
        (self.repository.root / "artifact.txt").write_text("old-step-claim\n", encoding="utf-8")
        self.repository.stale = [("old-step-claim", 12, ["artifact.txt"])]
        self.repository.write_contract()
        completed = self.repository.run()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_inline_step_specific_expected_value_is_detected(self) -> None:
        source = self.repository.root / "scripts/proofrail_step_preflight.py"
        source.write_text(source.read_text() + '\nINLINE_EXPECTATION = "current-artifact-modified"\n', encoding="utf-8")
        self.repository.authorized.append("scripts/proofrail_step_preflight.py")
        self.repository.write_contract()
        self.assert_failure("contract-source")

    def test_existing_report_path(self) -> None:
        (self.repository.root / self.repository.output_path).write_text("existing\n", encoding="utf-8")
        completed = self.repository.run()
        self.assertEqual(3, completed.returncode)
        self.assertEqual("existing\n", (self.repository.root / self.repository.output_path).read_text())

    def test_report_symlink(self) -> None:
        target = self.repository.root / ".proofrail/target.json"
        target.write_text("target\n", encoding="utf-8")
        (self.repository.root / self.repository.output_path).symlink_to(target)
        completed = self.repository.run()
        self.assertEqual(3, completed.returncode)
        self.assertEqual("target\n", target.read_text())

    def test_output_parent_symlink_escape(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.repository.root / "linked").symlink_to(outside, target_is_directory=True)
        completed = self.repository.run(output="linked/result.json")
        self.assertEqual(3, completed.returncode)
        self.assertFalse((outside / "result.json").exists())

    def test_interrupted_publication_cleans_temporary_file(self) -> None:
        output = self.repository.root / ".proofrail/interrupted.json"
        with mock.patch.object(PREFLIGHT.os, "link", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                PREFLIGHT.publish_report(output, {"status": "PASS"})
        self.assertEqual([], list(output.parent.glob(f".{output.name}.*")))

    def test_no_check_after_first_failure_executes(self) -> None:
        marker = self.repository.root / "later-ran"
        self._make_suite_fail("action")
        later = self.repository.root / "tests/end_to_end/test_pass.py"
        later.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8")
        self.repository.run()
        self.assertFalse(marker.exists())

    def test_fail_exits_one(self) -> None:
        self._make_suite_fail("action")
        self.assertEqual(1, self.repository.run().returncode)

    def test_launch_failure_exits_four(self) -> None:
        with mock.patch.object(PREFLIGHT, "_run_test", side_effect=PREFLIGHT.ExecutionFailure("failed to launch test command")):
            result, code, _ = PREFLIGHT.run_preflight(
                str(self.repository.root), self.repository.contract_path, self.repository.output_path
            )
        self.assertEqual(4, code)
        self.assertEqual("action-tests", result["failure"]["check"])

    def test_publication_failure_exits_five(self) -> None:
        result = PREFLIGHT._result(1, "0" * 40, "contract.yml")
        with mock.patch.object(PREFLIGHT, "run_preflight", return_value=(result, 0, self.repository.root / ".proofrail/new.json")), mock.patch.object(
            PREFLIGHT, "publish_report", side_effect=PREFLIGHT.PublicationFailure("no")
        ):
            self.assertEqual(5, PREFLIGHT.main(["--contract", "contract.yml"]))

    def test_contract_shell_text_remains_inert(self) -> None:
        marker = self.repository.root / "shell-ran"
        text = self.repository.contract_text().replace(
            "      - tests/action", f"      - $(touch {marker})", 1
        )
        self.repository.write_contract(text)
        completed = self.repository.run()
        self.assertEqual(3, completed.returncode)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
