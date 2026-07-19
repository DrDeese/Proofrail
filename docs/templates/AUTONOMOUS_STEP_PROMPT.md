# Autonomous step prompt

Use this template to define a bounded Proofrail step. Once it is completed and available in the task context or repository, the step may be invoked by number with the Proofrail autonomous-step skill.

```text
Complete Step <number> autonomously using the Proofrail autonomous-step skill.

Objective:
<one concrete outcome>

Allowed file scope:
- <exact file or directory boundary>

Required deliverables:
- <artifact>

Required positive tests:
- <command or observable valid behavior>

Required negative tests:
- <command or invalid case that must be rejected>

Prohibited work:
- <explicit exclusions>

Constraints and provenance limits:
- <dependency, network, provider, or evidence limitations>

Commit message:
<exact message>

Do not push. Stop after a verified local commit and final report.
```

All fields are required. Use exact paths rather than descriptions such as “related files.” A directory boundary authorizes changes only inside that directory and only when necessary for the objective. It does not authorize generated caches, dependency changes, unrelated cleanup, or destructive actions.

If the task needs a doctrine change, external mutation, network access, push, merge, or deployment, grant that authority in a separate task; do not hide it in a broad objective. If material issues remain after three repair rounds, stop and define a new bounded task rather than authorizing extra rounds in the current invocation.
