from __future__ import annotations

import re
import runpy
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    REPOSITORY_ROOT
    / ".codex"
    / "skills"
    / "proofrail-scope-escalation"
    / "SKILL.md"
)


class ScopeEscalationSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        if not cls.text.startswith("---\n"):
            raise AssertionError("skill must have bounded YAML front matter")
        closing = cls.text.find("\n---\n", len("---\n"))
        if closing < 0:
            raise AssertionError("skill must have bounded YAML front matter")
        cls.body = cls.text[closing + len("\n---\n") :]
        parser = runpy.run_path(
            str(REPOSITORY_ROOT / "scripts" / "proofrail_step_preflight.py")
        )["parse_bounded_yaml"]
        cls.front_matter = parser(
            cls.text[len("---\n") : closing], contract=False
        )

    def test_front_matter_and_heading_structure(self) -> None:
        self.assertEqual(
            set(self.front_matter),
            {"name", "description"},
        )
        self.assertEqual(
            self.front_matter["name"],
            "proofrail-scope-escalation",
        )
        self.assertEqual(
            re.findall(r"^# .+$", self.body, flags=re.MULTILINE),
            ["# Proofrail scope escalation"],
        )

    def test_fixed_scope_halt_report_contains_required_evidence(self) -> None:
        required_lines = (
            "SCOPE HALT",
            "step: <current-step-number>",
            "status: HALTED",
            "reason: out-of-scope dependency",
            "required_scope:",
            "  - path: <repository-relative-path>",
            "    blocking_content: |",
            "      <exact verbatim string or exact relevant block>",
            "    proposed_change: <minimal concrete change>",
            "    contradiction: <specific reason no valid in-scope alternative exists>",
            "invariants_preserved:",
            "  - <exact invariant that must not be weakened>",
            "state:",
            "  branch: <current-branch>",
            "  working_tree: <clean-or-concise-status>",
            "  files_modified_outside_scope: none",
            "  staged: <none-or-exact-status>",
            "  commit_created: no",
            "  pushed: no",
            "  pull_request_opened: no",
            "  merged: no",
            "  permissions_changed: no",
            "  approved_actions_changed: no",
            "  repair_rounds_consumed_for_halt: 0",
        )
        positions = [self.text.index(line) for line in required_lines]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.text.count("SCOPE HALT"), 1)

    def test_halt_requires_exact_bounded_scope_evidence(self) -> None:
        for requirement in (
            "exact repository-relative paths outside the current authorized scope",
            "exact blocking or stale content from each path",
            "minimal concrete change required in each path",
            "specific contradiction proving no valid in-scope alternative exists",
            "current repair-round count",
            "confirmation of repository state and prohibited actions not taken",
        ):
            self.assertIn(requirement, self.text)

    def test_halt_prohibits_mutation_and_continuation(self) -> None:
        prohibition = (
            "never edit files, prepare patches, stage or commit changes, push, open or "
            "modify a pull request, alter permissions or approved actions, deploy, "
            "merge, broaden scope, consume a repair round for the contradiction itself, "
            "or continue implementation after the halt"
        )
        self.assertIn(prohibition, self.text)
        self.assertIn("repair_rounds_consumed_for_halt: 0", self.text)

    def test_approval_is_exact_and_grants_no_broader_authority(self) -> None:
        self.assertIn(
            "A human reply of `approved` grants authority only for the exact paths and "
            "minimal changes named in `required_scope`",
            self.text,
        )
        self.assertIn(
            "it does not grant authority for any other file, repair, commit, push, pull "
            "request, deployment, permission change, approved-action change, or merge",
            self.text,
        )

    def test_structure_matches_existing_repository_skills(self) -> None:
        for relative in (
            ".codex/skills/proofrail-autonomous-step/SKILL.md",
            ".codex/skills/proofrail-step-preflight/SKILL.md",
            ".codex/skills/proofrail-scope-escalation/SKILL.md",
        ):
            text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: proofrail-"))
            self.assertEqual(text.count("\n# "), 1)
            self.assertIn("Require", text)
            self.assertIn("Follow", text)
            self.assertIn("In the final", text)

    def test_no_unresolved_placeholders_or_executable_instructions(self) -> None:
        self.assertTrue(self.text.endswith("Placeholders to resolve:\n\n- None.\n"))
        for unsafe in (
            "```",
            "$(",
            "${",
            "curl ",
            "wget ",
            "http://",
            "https://",
        ):
            self.assertNotIn(unsafe, self.text)


if __name__ == "__main__":
    unittest.main()
