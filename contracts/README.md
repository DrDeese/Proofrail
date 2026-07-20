# Proofrail step contracts

Each numbered step contract is named `contracts/step-<number>.yml` and uses schema version 1 from `contracts/step-contract.schema.json`.

The caller must pass the exact contract path to the preflight command. There is no implicit current contract, highest-step resolver, branch-name inference, or symlink convention. Contracts contain only bounded data: an immutable base SHA, exact test argument arrays, exact authorized paths, expected Proofrail results, workflow security expectations, and step-specific stale identifiers.

`contracts/step-13.yml` is the historical contract for Step 13. Its claim IDs and authorized paths come from commit `acd38d7fe488fda6d8705b4982c134d9e2fcd973`; its base is that commit's parent. Its stale identifiers were extracted from the Step 11 and Step 12 claim files, workflow assertions, policy exception rule, and Step 12 count-oriented policy-test identifier. Identifiers deliberately reused by Step 13 and generic Proofrail statuses are not stale merely because an earlier step used them. The old Step 11 exception identifier is preserved only as historical contract data.
