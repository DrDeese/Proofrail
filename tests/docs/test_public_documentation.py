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
        self.claude_code = (
            REPOSITORY_ROOT / "docs" / "CLAUDE_CODE.md"
        ).read_text(encoding="utf-8")
        self.claude_instructions_path = (
            REPOSITORY_ROOT / "docs" / "claude-code-instructions.md"
        )
        self.claude_instructions = self.claude_instructions_path.read_text(
            encoding="utf-8"
        )
        self.status = (REPOSITORY_ROOT / "docs" / "PROJECT_STATUS.md").read_text(
            encoding="utf-8"
        )
        self.pilot = (REPOSITORY_ROOT / "docs" / "PILOT_GUIDE.md").read_text(
            encoding="utf-8"
        )
        self.agents = (REPOSITORY_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def test_readme_has_first_time_visitor_facts(self) -> None:
        self.assertIn("Acceptance verification for AI-generated code changes.", self.readme)
        self.assertIn("pip install proofrail", self.readme)
        self.assertIn("proofrail verify --demo", self.readme)
        self.assertNotIn("Internal Alpha", self.readme)
        self.assertNotIn("not on PyPI", self.readme)
        for status in ("verified", "unsupported", "contradicted", "human_review_required"):
            self.assertIn(f"`{status}`", self.readme)
        for outcome in ("obsolete lockfile deletion", "workflow trigger update", "green run proves the new trigger"):
            self.assertIn(outcome, self.readme.lower())
        self.assertIn("`partially_verified`", self.readme)

    def test_readme_links_to_public_guides(self) -> None:
        for relative in (
            ".codex/skills/proofrail-acceptance/SKILL.md",
            "docs/CLAUDE_CODE.md",
            "docs/QUICKSTART.md",
            "docs/PROJECT_STATUS.md",
            "docs/PILOT_GUIDE.md",
            "docs/examples/partial-workflow-fix.md",
        ):
            self.assertIn(
                f"https://github.com/DrDeese/Proofrail/blob/main/{relative}",
                self.readme,
            )
            self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)

    def test_claude_code_integration_has_required_structure(self) -> None:
        blocked = (
            "Proofrail acceptance: blocked — the intended delivery is uncommitted, "
            "so no exact committed Git range exists for verification."
        )
        guide_headings = set(re.findall(r"^#{1,6} (.+)$", self.claude_code, re.MULTILINE))
        for heading in (
            "Use Proofrail with Claude Code",
            "Add the acceptance boundary to `CLAUDE.md`",
            "Run the workflow",
            "Handle the result",
            "Final-response template",
            "Current limitations",
        ):
            self.assertIn(heading, guide_headings)

        instruction_headings = set(
            re.findall(r"^#{1,6} (.+)$", self.claude_instructions, re.MULTILINE)
        )
        for heading in (
            "Proofrail acceptance boundary",
            "Status handling",
            "Final response",
        ):
            self.assertIn(heading, instruction_headings)

        self.assertTrue(self.claude_instructions_path.is_file())
        self.assertIn(blocked, self.claude_instructions)
        for status in (
            "`verified`",
            "`unsupported`",
            "`contradicted`",
            "`human_review_required`",
        ):
            self.assertIn(status, self.claude_instructions)
        for section in (
            "Exact Git range inspected",
            "What changed",
            "What Proofrail verified",
            "What remains unsupported or contradicted",
            "What requires human review",
            "result artifact",
        ):
            self.assertIn(section, self.claude_instructions)
            self.assertIn(section, self.claude_code)

    def test_claude_code_commands_resolve(self) -> None:
        documentation = self.claude_code + self.claude_instructions
        for command in ("draft-claims", "check-claims", "verify-change"):
            self.assertIn(f"$PROOFRAIL_CMD {command}", documentation)
            completed = subprocess.run(
                [sys.executable, "-m", "proofrail_verifier", command, "--help"],
                cwd=REPOSITORY_ROOT,
                env={**__import__("os").environ, "PYTHONPATH": "src"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_public_documentation_local_links_exist(self) -> None:
        sources = (
            (REPOSITORY_ROOT / "README.md", self.readme),
            (REPOSITORY_ROOT / "docs" / "CLAUDE_CODE.md", self.claude_code),
            (REPOSITORY_ROOT / "docs" / "QUICKSTART.md", self.quickstart),
            (
                REPOSITORY_ROOT / "docs" / "RELEASING.md",
                (REPOSITORY_ROOT / "docs" / "RELEASING.md").read_text(
                    encoding="utf-8"
                ),
            ),
        )
        for source, documentation in sources:
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", documentation):
                github_prefix = "https://github.com/DrDeese/Proofrail/blob/main/"
                if target.startswith(github_prefix):
                    resolved = REPOSITORY_ROOT / target.removeprefix(github_prefix)
                    self.assertTrue(resolved.exists(), f"{source}: {target}")
                    continue
                if "://" in target or target.startswith("#"):
                    continue
                resolved = (source.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(resolved.exists(), f"{source}: {target}")

    def test_public_acceptance_skill_is_operational_and_bounded(self) -> None:
        skill = (
            REPOSITORY_ROOT / ".codex" / "skills" / "proofrail-acceptance" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("after implementing any bounded repository change", skill)
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

    def test_acceptance_boundary_handles_uncommitted_delivery(self) -> None:
        skill = (
            REPOSITORY_ROOT / ".codex" / "skills" / "proofrail-acceptance" / "SKILL.md"
        ).read_text(encoding="utf-8")
        blocked = (
            "Proofrail acceptance: blocked — the intended delivery is uncommitted, "
            "so no exact committed Git range exists for verification."
        )
        self.assertIn(
            "All intended delivery changes are contained in an exact committed Git range",
            self.agents,
        )
        self.assertIn(
            "Acceptance verification is explicitly reported as blocked",
            self.agents,
        )
        self.assertIn(blocked, self.agents)
        self.assertIn(blocked, skill)
        description = skill.split("---", 2)[1]
        self.assertIn("committed or uncommitted", description)
        self.assertIn("exact committed Git range when available", description)
        self.assertIn("request commit authorization", description)
        self.assertIn("Never commit automatically", description)
        self.assertIn(
            "staged or unstaged work as Proofrail-verified",
            description,
        )
        self.assertIn("do not create a commit", skill)
        self.assertIn(
            "do not create one and do not run Proofrail against `HEAD`, staged files, or unstaged files",
            self.agents,
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
            if line.strip().startswith("pip install ")
        ]
        self.assertTrue(pip_install_lines)
        for line in pip_install_lines:
            self.assertEqual(line, "pip install proofrail")

    def test_maturity_and_pilot_boundaries_are_explicit(self) -> None:
        prohibited = ("production-ready", "enterprise-ready", "guarantees correctness", "universal verifier")
        for value in prohibited:
            self.assertNotIn(value, self.readme.lower())
        self.assertIn("Published PyPI package with a local `proofrail` command.", self.status)
        self.assertIn("**Public alpha**", self.status)
        for limitation in (
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
        self.assertLess(self.readme.index("pip install proofrail"), self.readme.index("| Claim | Proofrail result |"))
        self.assertLess(self.readme.index("| Claim | Proofrail result |"), self.readme.index("## What Proofrail is"))
        self.assertLess(self.readme.index("## What Proofrail is"), self.readme.index("## Development and contributing"))
        for path in (REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "docs" / "CLAUDE_CODE.md", REPOSITORY_ROOT / "docs" / "claude-code-instructions.md", REPOSITORY_ROOT / "docs" / "QUICKSTART.md", REPOSITORY_ROOT / "docs" / "PROJECT_STATUS.md", REPOSITORY_ROOT / "docs" / "PILOT_GUIDE.md", REPOSITORY_ROOT / "docs" / "examples" / "partial-workflow-fix.md"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"/(Users|home|private)/")

    def test_fixture_commands_execute(self) -> None:
        for fixture in ("001-partial-workflow-fix", "002-incapable-validation-command"):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofrail_verifier",
                    "verify",
                    f"tests/fixtures/{fixture}",
                    "--format",
                    "json",
                ],
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
