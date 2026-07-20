from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_REPOSITORY = (
    REPOSITORY_ROOT / "tests" / "source_repositories" / "partial-workflow-fix"
)
REFERENCE_CLAIM = (
    REPOSITORY_ROOT
    / "tests"
    / "case_preparation"
    / "claims"
    / "partial-workflow-fix.md"
)
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from proofrail_verifier.cli import main
from proofrail_verifier.policy import PolicyEvaluationError
from proofrail_verifier.preparation_errors import PreparationFailure


class AcceptancePolicyTests(unittest.TestCase):
    @staticmethod
    def _result(
        statuses: tuple[tuple[str, str], ...] = (("claim-one", "verified"),),
        verdict: str = "verified",
    ) -> dict[str, object]:
        return {
            "case_id": "policy-test-case",
            "claims": [
                {
                    "claim_id": claim_id,
                    "status": status,
                    "finding": "Evidence-derived finding.",
                    "evidence_ids": [],
                    "provenance_limitations": [],
                }
                for claim_id, status in statuses
            ],
            "overall_verdict": verdict,
            "provenance_limitations": [],
            "sources": {},
        }

    @staticmethod
    def _policy(
        statuses: tuple[str, ...] = ("verified",),
        verdicts: tuple[str, ...] = ("verified",),
        exceptions: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> str:
        lines = ["version: 1", "", "claims:", "  allowed-statuses:"]
        lines.extend(f"    - {status}" for status in statuses)
        lines.extend(["", "overall:", "  allowed-verdicts:"])
        lines.extend(f"    - {verdict}" for verdict in verdicts)
        if exceptions:
            lines.extend(["", "exceptions:"])
            for claim_id, allowed in exceptions:
                lines.extend(
                    [
                        f"  - claim-id: {claim_id}",
                        "    allowed-statuses:",
                    ]
                )
                lines.extend(f"      - {status}" for status in allowed)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _environment(**updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        environment.update(updates)
        return environment

    @classmethod
    def _run(
        cls,
        result: Path,
        policy: Path,
        *,
        result_format: str = "json",
        output: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "proofrail_verifier",
            "enforce",
            "--result",
            str(result),
            "--policy",
            str(policy),
            "--format",
            result_format,
        ]
        if output is not None:
            command.extend(("--output", str(output)))
        return subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment or cls._environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    @classmethod
    def _write_inputs(
        cls,
        root: Path,
        result: dict[str, object] | None = None,
        policy: str | None = None,
    ) -> tuple[Path, Path]:
        result_path = root / "completed result.json"
        policy_path = root / "acceptance policy.yml"
        result_path.write_text(
            json.dumps(result or cls._result(), indent=2) + "\n", encoding="utf-8"
        )
        policy_path.write_text(policy or cls._policy(), encoding="utf-8")
        return result_path, policy_path

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _tree_digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def test_verified_result_passes_strict_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-verified-") as temporary:
            result, policy = self._write_inputs(Path(temporary))
            completed = self._run(result, policy)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            decision = json.loads(completed.stdout)
            self.assertTrue(decision["accepted"])
            self.assertTrue(decision["claim_decisions"][0]["accepted"])

    def test_partial_result_and_exact_exception_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-exception-") as temporary:
            root = Path(temporary)
            result_value = self._result(
                (("claim-one", "verified"), ("semantic-claim", "unsupported")),
                "partially_verified",
            )
            accepting = self._policy(
                verdicts=("partially_verified",),
                exceptions=(("semantic-claim", ("unsupported",)),),
            )
            result, policy = self._write_inputs(root, result_value, accepting)
            accepted = self._run(result, policy)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            decision = json.loads(accepted.stdout)
            self.assertTrue(decision["accepted"])
            semantic = decision["claim_decisions"][1]
            self.assertEqual(
                semantic["rule"], "exceptions.semantic-claim.allowed-statuses"
            )

            policy.write_text(
                self._policy(verdicts=("partially_verified",)), encoding="utf-8"
            )
            rejected = self._run(result, policy)
            self.assertEqual(rejected.returncode, 1, rejected.stderr)
            self.assertFalse(json.loads(rejected.stdout)["accepted"])

    def test_dogfood_policy_rejects_contradicted_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-contradicted-") as temporary:
            root = Path(temporary)
            result, _ = self._write_inputs(
                root,
                self._result(
                    (
                        ("workflow-policy-wired", "unsupported"),
                        ("unexpected-contradiction", "contradicted"),
                    ),
                    "partially_verified",
                ),
            )
            completed = self._run(result, REPOSITORY_ROOT / ".proofrail" / "policy.yml")
            self.assertEqual(completed.returncode, 1, completed.stderr)
            decision = json.loads(completed.stdout)
            self.assertFalse(decision["accepted"])
            self.assertEqual(
                decision["reasons"],
                ["claim unexpected-contradiction has disallowed status contradicted"],
            )

    def test_multiple_reasons_are_stable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-reasons-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(
                root,
                self._result(
                    (("first", "unsupported"), ("second", "contradicted")),
                    "partially_verified",
                ),
            )
            first = self._run(result, policy)
            second = self._run(result, policy)
            self.assertEqual(first.returncode, 1)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(
                json.loads(first.stdout)["reasons"],
                [
                    "claim first has disallowed status unsupported",
                    "claim second has disallowed status contradicted",
                    "overall verdict partially_verified is disallowed",
                ],
            )

    def test_json_markdown_and_new_output_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-render-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            json_first = self._run(result, policy)
            json_second = self._run(result, policy)
            markdown_first = self._run(result, policy, result_format="markdown")
            markdown_second = self._run(result, policy, result_format="markdown")
            self.assertEqual(json_first.stdout, json_second.stdout)
            self.assertEqual(markdown_first.stdout, markdown_second.stdout)
            self.assertIn("**Policy accepted:** `true`", markdown_first.stdout)
            output = root / "policy decision.json"
            written = self._run(result, policy, output=output)
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(written.stdout, "")
            self.assertEqual(output.read_text(encoding="utf-8"), json_first.stdout)
            for rendered in (json_first.stdout, markdown_first.stdout):
                self.assertNotIn(str(root), rendered)

    def test_direct_enforce_matches_verify_change_policy_integration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-integrated-") as temporary:
            root = Path(temporary)
            verification = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofrail_verifier",
                    "verify-change",
                    "--repo",
                    str(REFERENCE_REPOSITORY),
                    "--base",
                    "HEAD^",
                    "--head",
                    "HEAD",
                    "--claim-file",
                    str(REFERENCE_CLAIM),
                ],
                cwd=REPOSITORY_ROOT,
                env=self._environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(verification.returncode, 0, verification.stderr)
            result = root / "result.json"
            result.write_text(verification.stdout, encoding="utf-8")
            policy = root / "policy.yml"
            policy.write_text(
                self._policy(
                    statuses=("verified", "contradicted"),
                    verdicts=("partially_verified",),
                ),
                encoding="utf-8",
            )
            source_before = self._tree_digest(REFERENCE_REPOSITORY)
            policy_before = policy.read_bytes()
            direct = self._run(result, policy)
            integrated = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofrail_verifier",
                    "verify-change",
                    "--repo",
                    str(REFERENCE_REPOSITORY),
                    "--base",
                    "HEAD^",
                    "--head",
                    "HEAD",
                    "--claim-file",
                    str(REFERENCE_CLAIM),
                    "--policy",
                    str(policy),
                ],
                cwd=REPOSITORY_ROOT,
                env=self._environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(direct.returncode, 0, direct.stderr)
            self.assertEqual(integrated.returncode, 0, integrated.stderr)
            self.assertEqual(integrated.stdout, direct.stdout)
            self.assertEqual(self._tree_digest(REFERENCE_REPOSITORY), source_before)
            self.assertEqual(policy.read_bytes(), policy_before)

    def test_integrated_policy_rejection_is_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-integrated-reject-") as temporary:
            policy = Path(temporary) / "rejecting policy.yml"
            policy.write_text(
                self._policy(verdicts=("partially_verified",)), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofrail_verifier",
                    "verify-change",
                    "--repo",
                    str(REFERENCE_REPOSITORY),
                    "--base",
                    "HEAD^",
                    "--head",
                    "HEAD",
                    "--claim-file",
                    str(REFERENCE_CLAIM),
                    "--policy",
                    str(policy),
                ],
                cwd=REPOSITORY_ROOT,
                env=self._environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse(json.loads(completed.stdout)["accepted"])
            self.assertNotIn("verification failed", completed.stderr)

    def test_integrated_verifier_failure_cannot_become_policy_rejection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-verifier-failure-") as temporary:
            policy = Path(temporary) / "policy.yml"
            policy.write_text(self._policy(), encoding="utf-8")
            arguments = [
                "verify-change",
                "--repo",
                str(REFERENCE_REPOSITORY),
                "--base",
                "HEAD^",
                "--head",
                "HEAD",
                "--claim-file",
                str(REFERENCE_CLAIM),
                "--policy",
                str(policy),
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "proofrail_verifier.cli.verify_change",
                side_effect=PreparationFailure("forced verifier failure"),
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return_code = main(arguments)
            self.assertEqual(return_code, 4)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("change verification failed", stderr.getvalue())

    def test_verify_change_without_policy_is_unchanged(self) -> None:
        command = [
            sys.executable,
            "-m",
            "proofrail_verifier",
            "verify-change",
            "--repo",
            str(REFERENCE_REPOSITORY),
            "--base",
            "HEAD^",
            "--head",
            "HEAD",
            "--claim-file",
            str(REFERENCE_CLAIM),
        ]
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=self._environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"overall_verdict":"partially_verified"', completed.stdout)
        self.assertNotIn("policy_version", completed.stdout)

    def test_paths_with_spaces_policy_shell_text_and_inputs_remain_inert(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail policy inert ") as temporary:
            root = Path(temporary)
            sentinel = root / "policy-command-executed"
            policy_text = (
                f"# $(touch {sentinel})\n"
                + self._policy()
            )
            result, policy = self._write_inputs(root, policy=policy_text)
            before = (self._digest(result), self._digest(policy))
            completed = self._run(result, policy)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual((self._digest(result), self._digest(policy)), before)

    def test_advanced_yaml_interpolation_and_includes_are_rejected(self) -> None:
        scenarios = {
            "alias": "version: 1\nclaims: &claims\n  allowed-statuses:\n    - verified\noverall:\n  allowed-verdicts:\n    - verified\n",
            "constructor": "version: 1\nclaims: !!python/object:builtins.str\n",
            "interpolation": self._policy(statuses=("${PROOFRAIL_STATUS}",)),
            "include": self._policy() + "include: https://example.invalid/policy.yml\n",
            "flow syntax": "version: 1\nclaims:\n  allowed-statuses: [verified]\noverall:\n  allowed-verdicts:\n    - verified\n",
        }
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-yaml-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            for label, content in scenarios.items():
                with self.subTest(label=label):
                    policy.write_text(content, encoding="utf-8")
                    completed = self._run(
                        result,
                        policy,
                        environment=self._environment(PROOFRAIL_STATUS="verified"),
                    )
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_policy_shapes_fail_as_input_errors(self) -> None:
        valid_claims = "claims:\n  allowed-statuses:\n    - verified\n"
        valid_overall = "overall:\n  allowed-verdicts:\n    - verified\n"
        scenarios = {
            "invalid yaml": "version 1\n",
            "wrong version": "version: 2\n" + valid_claims + valid_overall,
            "unknown key": self._policy() + "remote: value\n",
            "missing claims": "version: 1\n" + valid_overall,
            "missing overall": "version: 1\n" + valid_claims,
            "empty statuses": "version: 1\nclaims:\n  allowed-statuses:\n" + valid_overall,
            "empty verdicts": "version: 1\n" + valid_claims + "overall:\n  allowed-verdicts:\n",
            "unknown status": self._policy(statuses=("maybe",)),
            "unknown verdict": self._policy(verdicts=("maybe",)),
            "duplicate exception": self._policy(
                exceptions=(("claim-one", ("unsupported",)), ("claim-one", ("verified",)))
            ),
            "absent exception": self._policy(
                exceptions=(("absent-claim", ("unsupported",)),)
            ),
        }
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-invalid-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            for label, content in scenarios.items():
                with self.subTest(label=label):
                    policy.write_text(content, encoding="utf-8")
                    completed = self._run(result, policy)
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(completed.stdout, "")

    def test_invalid_and_duplicate_result_claims_fail_as_input_errors(self) -> None:
        scenarios = {
            "not object": [],
            "missing claims": {"case_id": "case", "overall_verdict": "verified"},
            "duplicate claims": self._result(
                (("duplicate", "verified"), ("duplicate", "verified"))
            ),
            "unknown claim status": self._result((("claim", "maybe"),)),
            "unknown verdict": self._result(verdict="maybe"),
        }
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-result-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            for label, value in scenarios.items():
                with self.subTest(label=label):
                    result.write_text(json.dumps(value) + "\n", encoding="utf-8")
                    completed = self._run(result, policy)
                    self.assertEqual(completed.returncode, 3, completed.stderr)
                    self.assertEqual(completed.stdout, "")

    def test_missing_inputs_and_cli_usage_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-missing-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            policy.unlink()
            self.assertEqual(self._run(result, policy).returncode, 3)
            policy.write_text(self._policy(), encoding="utf-8")
            result.unlink()
            self.assertEqual(self._run(result, policy).returncode, 3)
        usage = subprocess.run(
            [sys.executable, "-m", "proofrail_verifier", "enforce"],
            cwd=REPOSITORY_ROOT,
            env=self._environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(usage.returncode, 2)

    def test_output_collisions_and_write_failures_exit_five(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-output-") as temporary:
            root = Path(temporary)
            result, policy = self._write_inputs(root)
            existing = root / "existing.json"
            existing.write_text("keep\n", encoding="utf-8")
            self.assertEqual(self._run(result, policy, output=existing).returncode, 5)
            self.assertEqual(existing.read_text(), "keep\n")
            target = root / "target.json"
            target.write_text("outside\n", encoding="utf-8")
            symlink = root / "symlink.json"
            symlink.symlink_to(target)
            self.assertEqual(self._run(result, policy, output=symlink).returncode, 5)
            self.assertEqual(target.read_text(), "outside\n")
            missing_parent = root / "missing" / "output.json"
            self.assertEqual(
                self._run(result, policy, output=missing_parent).returncode, 5
            )

    def test_evaluation_failure_cannot_masquerade_as_rejection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-policy-evaluation-") as temporary:
            result, policy = self._write_inputs(Path(temporary))
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "proofrail_verifier.cli.evaluate_policy",
                side_effect=PolicyEvaluationError("forced failure"),
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return_code = main(
                    ["enforce", "--result", str(result), "--policy", str(policy)]
                )
            self.assertEqual(return_code, 4)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("policy evaluation failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
