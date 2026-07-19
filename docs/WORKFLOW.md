# Proofrail autonomous engineering workflow

This workflow governs bounded repository tasks performed autonomously from planning through a verified local commit. It supplements `AGENTS.md`; it does not replace product doctrine or expand an agent's authority.

## Invocation contract

Before starting, identify all of the following from the current task, prior approved context, or a repository step specification:

- the concrete objective;
- the exact allowed file paths or path boundaries;
- required positive and negative tests;
- prohibited work;
- the commit message.

A short invocation such as “Complete Step 3 autonomously using the Proofrail autonomous-step skill” is sufficient only when those details are already defined and unambiguous. Otherwise, stop and request the missing authority. Never infer permission for extra files, dependencies, network access, application architecture, destructive actions, pushing, or external side effects.

## Preconditions

1. Read `PRODUCT.md`, `ACCEPTANCE_MODEL.md`, `AGENTS.md`, and relevant founder evidence.
2. Read the step definition and every existing artifact it names.
3. Inspect `git status` and the recent commit history.
4. Preserve unrelated tracked, staged, and untracked changes.
5. If the step contradicts product doctrine, stop without editing and report the exact contradiction.

## Operating loop

### 1. Plan

- Restate the bounded objective and allowed file scope.
- Map each intended completion claim to its supporting artifact and direct verification command.
- Identify required positive tests, required negative tests, known provenance limits, and stop conditions.
- Choose the smallest implementation that satisfies the step; do not add speculative architecture.

Continue without intermediate approval when the invocation explicitly authorizes autonomous completion and all authority boundaries are clear.

### 2. Implement

- Create, modify, or delete only paths explicitly allowed by the step.
- Keep product behavior and terminology consistent with doctrine.
- Do not suppress stderr from any command that will be used as evidence.
- Do not treat attempted work, successful commands, changed artifacts, supported claims, and verified outcomes as equivalent.
- Do not install dependencies, use the network, or mutate external systems unless the step explicitly requires and authorizes it.

### 3. Verify

Run verification proportional to every claim:

- required positive tests that exercise the intended valid behavior;
- required negative tests that demonstrate relevant invalid behavior is rejected or fails safely;
- parsing, syntax, formatting, or static checks for changed artifact types;
- existing regression tests relevant to the change;
- `git diff --check`;
- `git status`;
- complete diff inspection, including untracked allowed files before staging.

Record the exact commands, exit results, and whether each command directly exercises the claimed behavior. An unrelated green command is not completion evidence.

### 4. Adversarial self-review

Review the work as if the completion report may be wrong. At minimum, ask:

1. Can a required invalid input pass?
2. Can a positive test pass without loading or exercising the changed artifact?
3. Are claims supported by the final artifacts rather than intent or command success?
4. Are provenance and remaining uncertainty explicit?
5. Did the change exceed the allowed paths or introduce unrequested architecture?
6. Are errors visible, especially expected failures and evidence-command stderr?
7. Could dirty pre-existing work be staged, overwritten, or misreported?
8. Do the proposed verdict and explanation preserve the acceptance-stage distinctions?

### 5. Repair

- Repair every material issue found, staying within the original allowed scope.
- After each repair, rerun implementation-relevant verification and adversarial self-review.
- Perform at most three repair rounds after the initial verification pass.
- A repair round is one cycle of changes followed by renewed verification and self-review.
- Do not reset the count by renaming, splitting, or restarting the same task.
- If material issues remain after round three, stop without committing and report them as unresolved risks.
- If a repair requires broader scope, new authority, doctrine changes, or external access, stop and request approval instead of expanding the task.

### 6. Commit

Commit only when verification and self-review have no unresolved material failures.

Before committing:

1. Stage explicit allowed paths, never a broad implicit path.
2. Inspect `git status --short`.
3. Inspect `git diff --cached --stat`.
4. Run `git diff --cached --check`.
5. Inspect `git diff --cached --name-status` and the complete staged diff.
6. Confirm every staged path is allowed and no unrelated change is staged.
7. Rerun the direct positive and negative tests against the staged contents where practical.

Use the exact approved commit message. Do not amend unrelated history.

After committing:

1. Inspect `git show --stat --oneline HEAD`.
2. Inspect `git show --name-status HEAD` and, when needed, the complete committed diff.
3. Run `git diff HEAD^ HEAD --check`.
4. Run `git status --short --branch`.
5. Confirm the actual commit contains only allowed paths.

Do not push by default. Pushing requires a separate explicit instruction after commit verification.

### 7. Stop

Stop after either:

- a verified local commit and final report; or
- a blocked report caused by contradiction, missing authority, failed evidence, exhausted repair rounds, or unresolved material risk.

Do not continue into the next step, push, open a pull request, deploy, merge, or broaden the task.

## Final report

Report:

- commit SHA, or why no commit was created;
- exact files changed;
- commands used as evidence and what each directly exercised;
- self-review findings and repairs;
- unresolved risks or unsupported claims;
- repository cleanliness and ahead/behind state;
- confirmation that no push occurred unless separately authorized.

Always separate:

### What is proven

Claims directly supported by inspected artifacts and relevant executed evidence.

### What remains unverified

Claims requiring missing provenance, external state, unexecuted tests, human judgment, or authority outside the step.
