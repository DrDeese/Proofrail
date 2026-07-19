# Proofrail case schema

`case.schema.json` is the smallest provider-neutral JSON Schema needed to represent regression fixture 001. It uses JSON Schema Draft 2020-12 and models six concepts: a case, its atomic claims, evidence, findings, provenance, and the overall verdict.

## Acceptance stages

The schema records the five ordered acceptance stages explicitly:

1. `attempted`
2. `executed`
3. `artifact_changed`
4. `claim_supported`
5. `outcome_verified`

An evidence item or finding identifies the stage it can observe. Recording a later stage does not imply that evidence for an earlier stage proves it.

## Statuses and provenance

Atomic claims use `verified`, `unsupported`, `contradicted`, or `human_review_required`. Overall case verdicts use a separate enum that also permits `partially_verified`.

Evidence kinds distinguish artifact-derived evidence, execution evidence, scenario-provided evidence, authenticated external evidence, and unauthenticated external evidence. Every claim, evidence item, and finding has provenance recording its source type, authentication state, independent-verification state, and limitations.

Claims also declare a small evaluation predicate and the observation capability they require. Evidence declares how it was obtained and what it can observe. The supported capabilities are deliberately limited to the two current fixtures: file contents, static response bodies, client-rendered DOM, command exit status, workflow trigger events, and merge records. A successful command cannot verify a claim requiring an observation capability the command lacks.

IDs connect claims to evidence and findings. The fixture validation test checks that those references resolve and that IDs are unique; Draft 2020-12 does not provide database-style foreign-key constraints.

## Offline validation

Run:

```sh
python3 tests/schema/validate-fixture-001.py
```

The test uses only the Python standard library. It loads `schemas/case.schema.json`, validates fixture 001 against the schema keywords used by this schema, checks reference integrity, and confirms that deliberately invalid in-memory cases are rejected. It does not contact a schema registry or any external provider.

This schema does not yet model provider APIs, database storage, workflow execution authentication, merge authentication, or general-purpose verification rules.
