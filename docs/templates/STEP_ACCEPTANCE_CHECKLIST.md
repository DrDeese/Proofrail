# Step acceptance checklist

## Authority and doctrine

- [ ] The objective is concrete and bounded.
- [ ] Exact allowed file paths or directory boundaries are recorded.
- [ ] Required positive and negative tests are recorded.
- [ ] Prohibited work and the exact commit message are recorded.
- [ ] `PRODUCT.md`, `ACCEPTANCE_MODEL.md`, `AGENTS.md`, and relevant founder evidence were read.
- [ ] No contradiction with product doctrine exists; if one exists, work stopped without edits.
- [ ] Pre-existing unrelated work is identified and preserved.

## Implementation

- [ ] Only allowed paths changed.
- [ ] No speculative product architecture, dependency, provider coupling, or external side effect was added.
- [ ] Evidence-producing commands do not suppress stderr.
- [ ] Attempted, executed, artifact-changed, claim-supported, and outcome-verified states remain distinct.

## Verification

- [ ] Every completion claim names its supporting artifact.
- [ ] Required positive tests passed and directly exercised intended behavior.
- [ ] Required negative tests passed by rejecting or safely failing the intended invalid behavior.
- [ ] Relevant existing regression tests passed.
- [ ] Changed structured files parse and changed executable files pass syntax checks.
- [ ] `git diff --check` passed.
- [ ] `git status` was inspected.
- [ ] The complete unstaged diff, including allowed untracked files, was inspected.

## Adversarial review and repair

- [ ] Self-review checked false-positive tests, invalid inputs, provenance gaps, scope creep, hidden stderr, and dirty-tree risks.
- [ ] Every material finding was repaired or listed as unresolved.
- [ ] No more than three repair rounds were performed.
- [ ] Work stopped without committing if a material issue remained after round three.
- [ ] Work stopped for approval if a repair required broader authority.

## Commit evidence

- [ ] Only explicit allowed paths were staged.
- [ ] `git status --short` was inspected before commit.
- [ ] `git diff --cached --stat` was inspected.
- [ ] `git diff --cached --check` passed.
- [ ] `git diff --cached --name-status` and the complete staged diff were inspected.
- [ ] Positive and negative tests were rerun against staged contents where practical.
- [ ] The approved commit message was used.
- [ ] `git show --stat --oneline HEAD` was inspected.
- [ ] `git show --name-status HEAD` and the committed paths were inspected.
- [ ] `git diff HEAD^ HEAD --check` passed.
- [ ] `git status --short --branch` was inspected after commit.
- [ ] No push occurred unless separately and explicitly authorized.

## Final report

- [ ] The commit SHA and exact files changed are reported.
- [ ] Commands are distinguished from the behaviors they directly exercised.
- [ ] Self-review findings and repairs are reported.
- [ ] Unresolved risks and unsupported claims are explicit.
- [ ] “What is proven” is separate from “What remains unverified.”
- [ ] Working-tree cleanliness and ahead/behind state are reported accurately.
