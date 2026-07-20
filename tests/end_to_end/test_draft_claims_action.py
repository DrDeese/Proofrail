from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DraftClaimsActionIntegrationTests(unittest.TestCase):
    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise AssertionError(completed.stderr)
        return completed.stdout.strip()

    @classmethod
    def _commit(cls, repository: Path, message: str) -> None:
        cls._git(repository, "add", "--all")
        cls._git(
            repository,
            "-c", "user.name=Proofrail Test",
            "-c", "user.email=test@proofrail.local",
            "commit", "--no-gpg-sign", "-m", message,
        )

    def test_generated_claim_file_works_in_local_action_git_change_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="proofrail-draft-action-") as temporary:
            workspace = Path(temporary) / "workspace"
            repository = workspace / "source-repository"
            repository.mkdir(parents=True)
            template = workspace / "template"
            template.mkdir()
            subprocess.run(
                ["git", "init", "--initial-branch=main", f"--template={template}", str(repository)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            (repository / "artifact.txt").write_text("base", encoding="utf-8")
            self._commit(repository, "base")
            (repository / "artifact.txt").write_text("head", encoding="utf-8")
            (repository / "added.txt").write_text("added", encoding="utf-8")
            self._commit(repository, "head")

            shutil.copytree(ROOT / "src", workspace / "src")
            shutil.copytree(ROOT / "schemas", workspace / "schemas")
            action = workspace / ".github" / "actions" / "proofrail-verify"
            action.parent.mkdir(parents=True)
            shutil.copytree(ROOT / ".github" / "actions" / "proofrail-verify", action)
            claims = workspace / "generated-claims.md"
            draft = subprocess.run(
                [
                    sys.executable, "-m", "proofrail_verifier", "draft-claims",
                    "--repo", str(repository), "--base", "HEAD^", "--head", "HEAD",
                    "--output", str(claims),
                ],
                cwd=workspace,
                env={**os.environ, "PYTHONPATH": str(workspace / "src")},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(draft.returncode, 0, draft.stderr)

            github_output = workspace.parent / "github-output"
            github_summary = workspace.parent / "github-summary"
            github_output.write_text("", encoding="utf-8")
            github_summary.write_text("", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "GITHUB_WORKSPACE": str(workspace),
                    "GITHUB_OUTPUT": str(github_output),
                    "GITHUB_STEP_SUMMARY": str(github_summary),
                    "INPUT_CASE_DIRECTORY": "",
                    "INPUT_REPO": "source-repository",
                    "INPUT_BASE": "HEAD^",
                    "INPUT_HEAD": "HEAD",
                    "INPUT_CLAIM_FILE": "generated-claims.md",
                    "INPUT_POLICY_FILE": "",
                    "INPUT_CHECK_CLAIMS": "true",
                    "INPUT_FORMAT": "json",
                }
            )
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [sys.executable, str(action / "run.py")],
                cwd=workspace,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs = dict(
                line.split("=", 1)
                for line in github_output.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(outputs["claims-synchronized"], "true")
            claim_check = json.loads(
                (workspace / outputs["claim-check-json-path"]).read_text(encoding="utf-8")
            )
            self.assertTrue(claim_check["synchronized"])
            result = json.loads(
                (workspace / outputs["result-json-path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["overall_verdict"], "verified")
            self.assertTrue(all(claim["status"] == "verified" for claim in result["claims"]))
            self.assertEqual(outputs["overall-verdict"], "verified")
            self.assertTrue((workspace / outputs["result-json-path"]).is_file())
            self.assertIn(
                "# Proofrail claim freshness",
                github_summary.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "**Overall verdict:** `verified`",
                github_summary.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
