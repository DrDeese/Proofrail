from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class PublicDocumentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.quickstart = (REPOSITORY_ROOT / "docs" / "QUICKSTART.md").read_text(
            encoding="utf-8"
        )
        self.status = (REPOSITORY_ROOT / "docs" / "PROJECT_STATUS.md").read_text(
            encoding="utf-8"
        )
        self.pilot = (REPOSITORY_ROOT / "docs" / "PILOT_GUIDE.md").read_text(
            encoding="utf-8"
        )

    def test_readme_has_first_time_visitor_facts(self) -> None:
        self.assertIn("Acceptance verification for AI-generated code changes.", self.readme)
        self.assertIn("Internal Alpha", self.readme)
        for status in ("verified", "unsupported", "contradicted", "human_review_required"):
            self.assertIn(f"`{status}`", self.readme)
        for outcome in ("obsolete lockfile deletion", "workflow trigger update", "green run proves the new trigger"):
            self.assertIn(outcome, self.readme.lower())
        self.assertIn("`partially_verified`", self.readme)

    def test_readme_links_to_public_guides(self) -> None:
        for relative in (
            ".codex/skills/proofrail-acceptance/SKILL.md",
            "docs/QUICKSTART.md",
            "docs/PROJECT_STATUS.md",
            "docs/PILOT_GUIDE.md",
            "docs/examples/partial-workflow-fix.md",
        ):
            self.assertIn(relative, self.readme)
            self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)

    def test_public_acceptance_skill_is_operational_and_bounded(self) -> None:
        skill = (
            REPOSITORY_ROOT / ".codex" / "skills" / "proofrail-acceptance" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("after implementing a bounded change", skill)
        self.assertIn("before reporting the task as complete", skill)
        self.assertIn('PROOFRAIL_CMD="proofrail"', skill)
        self.assertIn('PROOFRAIL_CMD="python3 -m proofrail_verifier"', skill)
        self.assertIn('export PYTHONPATH="/absolute/path/to/Proofrail/src"', skill)
        self.assertIn(
            "`PYTHONPATH` identifies the `src` directory in the Proofrail source checkout",
            skill,
        )
        self.assertIn(
            "`--repo` argument identifies the separate software repository",
            skill,
        )
        for command in ("draft-claims", "check-claims", "verify-change"):
            self.assertIn(f"$PROOFRAIL_CMD {command}", skill)
        for status in (
            "`verified`",
            "`unsupported`",
            "`contradicted`",
            "`human_review_required`",
        ):
            self.assertIn(status, skill)
        for category in (
            "What changed",
            "What Proofrail verified",
            "What remains unsupported or contradicted",
            "What requires human review",
            "Exact Git range inspected",
        ):
            self.assertIn(category, skill)
        for prohibited in ("automatically commit", "push", "merge", "publish", "deploy"):
            self.assertIn(prohibited, skill)
        self.assertIn(
            "Do not place unsupported or contradicted claims under “What Proofrail verified,”",
            skill,
        )
        self.assertIn(
            "A diff shows what changed. Proofrail checks whether the agent's stated claims are supported by what changed.",
            self.readme,
        )

    def test_documented_commands_are_real_and_safe(self) -> None:
        help_text = subprocess.run(
            [sys.executable, "-m", "proofrail_verifier", "--help"],
            cwd=REPOSITORY_ROOT,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        for command in (
            "verify",
            "prepare-case",
            "verify-change",
            "draft-claims",
            "check-claims",
            "enforce",
        ):
            self.assertIn(command, help_text)
            self.assertIn(f"proofrail {command}", self.readme + self.quickstart)
        self.assertIn("python3 -m proofrail_verifier", self.readme + self.quickstart)
        self.assertIn("PYTHONPATH=src", self.readme + self.quickstart)
        documentation = self.readme + self.quickstart
        self.assertNotRegex(documentation, r"\b(brew install|npm install|docker pull)\b")
        pip_install_lines = [
            line.strip()
            for line in documentation.splitlines()
            if "pip install" in line
        ]
        self.assertTrue(pip_install_lines)
        for line in pip_install_lines:
            self.assertRegex(
                line,
                r"^python3 -m pip install --no-index --no-deps dist/proofrail_verifier-[^ ]+\.whl$",
            )

    def test_maturity_and_pilot_boundaries_are_explicit(self) -> None:
        prohibited = ("production-ready", "enterprise-ready", "guarantees correctness", "universal verifier")
        for value in prohibited:
            self.assertNotIn(value, self.readme.lower())
        self.assertIn(
            "Local Internal Alpha wheel and source-distribution artifacts can be built offline.",
            self.status,
        )
        for limitation in (
            "No public package-index distribution; local Internal Alpha artifacts only.",
            "No stable compatibility policy.",
            "No hosted service.",
            "No authentication of authorship or timestamps.",
            "No proof of deployment, browser rendering, external systems, or human intent.",
        ):
            self.assertIn(limitation, self.status)
        self.assertIn("supported general-availability product", self.status)
        self.assertIn("future evaluation targets, not completed results", self.pilot)
        self.assertIn("At least ten real pull requests are evaluated.", self.pilot)

    def test_user_sections_precede_development_and_paths_are_portable(self) -> None:
        self.assertLess(self.readme.index("## What Proofrail is"), self.readme.index("## Development and contributing"))
        self.assertLess(self.readme.index("## Five-minute quick start"), self.readme.index("## Development and contributing"))
        for path in (REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "docs" / "QUICKSTART.md", REPOSITORY_ROOT / "docs" / "PROJECT_STATUS.md", REPOSITORY_ROOT / "docs" / "PILOT_GUIDE.md", REPOSITORY_ROOT / "docs" / "examples" / "partial-workflow-fix.md"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"/(Users|home|private)/")

    def test_fixture_commands_execute(self) -> None:
        for fixture in ("001-partial-workflow-fix", "002-incapable-validation-command"):
            completed = subprocess.run(
                [sys.executable, "-m", "proofrail_verifier", "verify", f"tests/fixtures/{fixture}"],
                cwd=REPOSITORY_ROOT,
                env={**__import__("os").environ, "PYTHONPATH": "src"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('"overall_verdict":"partially_verified"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
