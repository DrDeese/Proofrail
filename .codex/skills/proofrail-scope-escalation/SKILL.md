---
name: proofrail-scope-escalation
description: Emit a deterministic, minimal halt report when a fully specified Proofrail step cannot continue within its authorized file scope. Use at the first point an out-of-scope file is required, before editing that file or attempting a weakening workaround, so a human can approve or reject the exact scope expansion without re-specifying the step. This skill grants no authority to edit, repair, commit, push, open a pull request, alter permissions or approved actions, deploy, or merge.
---

# Proofrail scope escalation

Read the active step authorization, the exact allowed file scope, the current branch and worktree state, and the blocking file contents before reporting the halt.

Require:

- one or more exact repository-relative paths outside the current authorized scope;
- the exact blocking or stale content from each path;
- the minimal concrete change required in each path;
- the specific contradiction proving no valid in-scope alternative exists;
- the current repair-round count;
- confirmation of repository state and prohibited actions not taken.

Refuse to invent file paths, contradiction types, stale identifiers, proposed edits, or alternative resolutions. Do not rationalize an in-scope workaround that weakens an existing invariant, preserves dead assertions, restores stale exceptions, retains misleading strings, bypasses current dogfood expectations, or special-cases evaluator behavior merely to avoid requesting scope.

Follow this process:

1. Stop at the first proven out-of-scope dependency.
2. Confirm the blocking path is outside the active authorized scope.
3. Read the exact stale or blocking content from that path.
4. State the smallest concrete change required without editing or preparing it.
5. State the exact contradiction that makes every in-scope alternative invalid.
6. Confirm what was not done, including out-of-scope edits, staging, commit, push, pull request, merge, permission changes, approved-action changes, and repair-round consumption caused only by the scope contradiction.
7. Emit the fixed halt report and stop.

Use exactly this report shape:

SCOPE HALT

step: <current-step-number>
status: HALTED
reason: out-of-scope dependency

required_scope:
  - path: <repository-relative-path>
    blocking_content: |
      <exact verbatim string or exact relevant block>
    proposed_change: <minimal concrete change>
    contradiction: <specific reason no valid in-scope alternative exists>

invariants_preserved:
  - <exact invariant that must not be weakened>

state:
  branch: <current-branch>
  working_tree: <clean-or-concise-status>
  files_modified_outside_scope: none
  staged: <none-or-exact-status>
  commit_created: no
  pushed: no
  pull_request_opened: no
  merged: no
  permissions_changed: no
  approved_actions_changed: no
  repair_rounds_consumed_for_halt: 0

When multiple files are required, list them in deterministic repository-relative path order. Quote the smallest exact blocking string or block sufficient to explain the contradiction. Do not summarize content when a verbatim assertion, claim, exception, expected verdict, or required path predicate is available.

The contradiction must be specific. Supported shapes include:

- leaving a stale claim unchanged forces a deterministic `contradicted` result that the active policy rejects;
- leaving a stale policy exception unchanged makes evaluation invalid because the exception references an absent claim;
- removing a stale workflow assertion while leaving an out-of-scope test unchanged causes that test to require dead Step-N content;
- satisfying an out-of-scope test without editing it would require retaining a misleading string or weakening evaluator semantics;
- proceeding without the required file would make the current step’s contract, claim set, workflow assertion, or hosted acceptance criteria internally inconsistent.

Do not pre-commit to a resolution that trades away an invariant. State the minimal file change and the invariant to preserve so the human can authorize the correct scope expansion. For example, prefer removing a stale exception over weakening the rule that absent-claim exceptions are invalid, and prefer updating an obsolete test over retaining dead assertion text.

While acting under this skill, never edit files, prepare patches, stage or commit changes, push, open or modify a pull request, alter permissions or approved actions, deploy, merge, broaden scope, consume a repair round for the contradiction itself, or continue implementation after the halt. Human approval is required before any scope expansion or repair.

In the final response, return only the halt report. Do not add prose before or after it. A human reply of `approved` grants authority only for the exact paths and minimal changes named in `required_scope`; it does not grant authority for any other file, repair, commit, push, pull request, deployment, permission change, approved-action change, or merge.

Placeholders to resolve:

- None.
