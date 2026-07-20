---
name: proofrail-step-preflight
description: Run the deterministic, fail-closed Proofrail pre-commit gate for a fully specified numbered step using an exact caller-provided contract. Use after implementation and before staging when the caller names a contracts/step-<number>.yml file and wants only a machine-readable PASS or FAIL report, without repairs, Git mutations, pushes, pull requests, deployments, or merges.
---

# Proofrail step preflight

Read the active step authorization and the exact contract path named by the caller. Read `PRODUCT.md`, `ACCEPTANCE_MODEL.md`, `AGENTS.md`, and the repository workflow before running the gate.

Require:

- an explicit `contracts/step-<number>.yml` path;
- the matching numbered-step authorization;
- an implemented but unstaged or staged bounded change;
- a new repository-relative report path, or the default `.proofrail/preflight-result.json`.

Refuse to infer missing paths, commands, claims, statuses, verdicts, policy expectations, security settings, or stale identifiers. Never select the highest-numbered contract, follow an implicit current-contract symlink, or derive a contract from a branch name, workflow history, prior output, or inline constants.

Follow this process:

1. Confirm the requested contract and report paths are explicit and bounded.
2. Run `PYTHONPATH=src python3 scripts/proofrail_step_preflight.py --contract <exact-contract> --output <new-report>` after implementation and before staging.
3. Read only the deterministic JSON report.
4. Return the report verbatim and stop.

Stop on `FAIL`. While acting under this skill, never edit or repair files, stage or commit changes, push, open a pull request, alter permissions or approved actions, deploy, merge, or broaden scope. Require separate human authorization for every repair, contract change, or scope change. A `PASS` report grants no commit, push, pull-request, deployment, or merge authority.

In the final response, return only the deterministic report. Do not reinterpret a failed check, substitute another command, or supplement contract expectations from memory or inference.
