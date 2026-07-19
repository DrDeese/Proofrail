# Acceptance Model

Proofrail separates stages that AI agents and humans often mistakenly treat as equivalent.

## 1. Attempted

The agent tried to perform an action.

Example:

The agent ran a command intended to stage two files.

This does not prove that either file was staged.

## 2. Executed

A command or operation completed.

Example:

A Git commit command exited successfully.

This does not prove that the commit contains every intended change.

## 3. Artifact changed

The final artifact contains a measurable change.

Example:

A file appears in the final commit diff.

This does not prove that the requested behavior was implemented correctly.

## 4. Claim supported

The resulting artifact directly supports the agent's completion claim.

Example:

The agent claims that two workflow triggers were changed, and both changes are present in the final commit.

## 5. Outcome verified

Relevant evidence demonstrates that the requested behavior works.

Example:

A pull request modifying only the active lockfile triggers the intended workflow.

## Critical distinction

These statements are not equivalent:

- I attempted the change.
- A command succeeded.
- A file changed.
- The requested change is present.
- The requested outcome works.

Proofrail must preserve these distinctions in its data model, reports, and verdicts.
