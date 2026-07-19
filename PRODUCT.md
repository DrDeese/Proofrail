# Proofrail

## Product definition

Proofrail verifies whether the artifacts delivered by an AI agent support the agent's claims about what it completed.

It also evaluates whether the evidence submitted by the agent actually tests the claimed result.

## Core problem

AI agents can report that work is complete even when:

- part of the requested change is missing;
- the final commit differs from the working tree the agent inspected;
- a test passed for an unrelated reason;
- the validation method could not observe the claimed outcome;
- an agent mistakes attempted work for completed work.

The human reviewer must currently reconstruct the evidence manually.

## Core promise

Proofrail helps a human answer:

> Does the delivered artifact support what the agent claims, and does the evidence actually prove it?

## Initial customer

The initial customer is an engineer or engineering team allowing AI coding agents to create commits and pull requests.

## Initial product

The first product will evaluate AI-generated GitHub pull requests.

It will compare:

1. the requested work;
2. the agent's completion claims;
3. the final Git diff and commit;
4. the commands and checks that ran;
5. the relevance of those checks;
6. the resulting evidence.

## Initial output

Each claim will receive one of these statuses:

- Verified
- Partially verified
- Unsupported
- Contradicted
- Human review required

## Product principles

1. Artifacts outrank agent explanations.
2. A passing command is not automatically proof.
3. Deterministic checks come before model judgment.
4. Evidence must directly relate to the claim.
5. Unsupported claims must remain visible.
6. The product should show exact evidence, not only a confidence score.

## Not included in version one

Proofrail is not:

- a general-purpose coding agent;
- a general code-review chatbot;
- a replacement for automated tests;
- an agent-observability platform;
- a universal truth detector;
- an autonomous merge system;
- a browser automation platform.

## First narrow use case

Given an AI-authored pull request and its completion statement, Proofrail identifies claims that are not supported by the final commit or by relevant execution evidence.
