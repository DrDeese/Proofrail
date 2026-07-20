# Proofrail pilot guide

Run a controlled pilot across three repositories:

1. Proofrail itself.
2. One ordinary application repository.
3. One repository with a materially different stack or CI workflow.

## Pilot setup

Keep the pilot read-only. Use an exact committed range and structured path claims for each evaluated pull request. Record the verifier result, policy decision, developer interpretation, setup effort, and ongoing maintenance effort. Do not use a pilot result as proof that Proofrail covers behavior outside the evidence it inspected.

## Evaluation targets

The following are future evaluation targets, not completed results:

- Written setup is completed without repository-specific code changes where possible.
- At least ten real pull requests are evaluated.
- No observed false `verified` outcome occurs.
- Developers understand `unsupported` and `contradicted` findings.
- Claim freshness catches stale claim files.
- Scope halts can be approved from the fixed report.
- Setup and maintenance time are recorded.
- Fork-pull-request behavior is tested.
- One version-to-version upgrade is eventually demonstrated.

## Review questions

For each result, ask:

1. Was the claim precise enough for the available artifact evidence?
2. Did a passing command directly observe the claimed result?
3. Was a finding `unsupported` because evidence was missing, rather than because the implementation was known to be wrong?
4. Did policy acceptance preserve the distinction between verification and team approval?

At the end of the pilot, decide whether the evidence supports continued controlled use. It does not establish production readiness or prove behavior Proofrail did not inspect.
