---
name: proofrail-autonomous-step
description: Complete a fully specified, bounded Proofrail repository step autonomously from planning through a verified local commit. Use when a user invokes the Proofrail autonomous-step skill or asks to complete a numbered Proofrail step with an already-defined objective, exact allowed file scope, positive and negative tests, prohibited work, and commit message. Do not use to infer missing scope, alter product doctrine, push, deploy, merge, or perform external mutations without separate explicit authority.
---

# Proofrail autonomous step

Read `PRODUCT.md`, `ACCEPTANCE_MODEL.md`, `AGENTS.md`, `docs/WORKFLOW.md`, and relevant founder evidence before acting. Read the numbered step definition and every named existing artifact.

Require the step context to define:

- one concrete objective;
- exact allowed paths or directory boundaries;
- required positive and negative tests;
- prohibited work;
- an exact commit message.

If any boundary is missing or product doctrine conflicts with the task, stop without editing and report the blocker. A step number alone does not grant authority unless its full definition is already available and unambiguous.

Follow `docs/WORKFLOW.md` in order:

1. Plan claims, artifacts, direct evidence, scope, and stop conditions.
2. Implement only within the allowed paths.
3. Verify with required positive and negative tests, relevant regression checks, parsing or syntax checks, diff checks, status, and complete diff inspection.
4. Adversarially review for false positives, missing provenance, acceptance-stage conflation, scope creep, hidden errors, and dirty-tree risks.
5. Repair material findings and repeat verification, for at most three repair rounds total.
6. Stage explicit allowed paths, inspect the complete staged diff, rerun direct tests, and create the exact approved local commit only when supported.
7. Inspect the actual commit and stop.

Never suppress stderr from evidence-producing commands. Preserve unrelated work. Do not install dependencies, access the network, open a pull request, deploy, merge, or expand scope unless separately explicit and necessary. Never push as part of this skill; pushing requires a separate follow-up task after the skill stops.

Use `docs/templates/STEP_ACCEPTANCE_CHECKLIST.md` as the completion gate. Use `docs/templates/AUTONOMOUS_STEP_PROMPT.md` when a step definition must be written or repaired.

In the final report, separate artifact-backed and directly tested claims under “What is proven” from provenance-limited, externally dependent, or untested claims under “What remains unverified.” Report unresolved risks explicitly. Stop without committing when material risks remain after three repair rounds.
