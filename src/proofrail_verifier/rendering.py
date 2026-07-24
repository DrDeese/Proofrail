"""Render verifier results as stable JSON, text, or plain Markdown."""

from __future__ import annotations

import json
from typing import Any


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_text(result: dict[str, Any]) -> str:
    headers = ("Claim ID", "Status", "Finding")
    rows = [
        (claim["claim_id"], claim["status"], claim["finding"])
        for claim in result["claims"]
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    def table_row(values: tuple[str, str, str]) -> str:
        return " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ).rstrip()

    lines = [
        f"Case ID: {result['case_id']}",
        "",
        table_row(headers),
        "-+-".join("-" * width for width in widths),
        *(table_row(row) for row in rows),
        "",
        (
            f"Overall verdict: {result['overall_verdict']} - "
            "only part of the claims are supported."
        ),
        "",
        f"Provenance limitations: {len(result['provenance_limitations'])}",
        (
            "Full JSON: re-run this command with --format json for per-claim "
            "evidence references, source hashes, and provenance limitations."
        ),
    ]
    return "\n".join(lines) + "\n"


def render_demo_text(result: dict[str, Any]) -> str:
    preamble = (
        "Demo: deterministic reconstruction of a real incident.\n"
        "Agent claim: the obsolete lockfile was deleted and two workflow triggers were updated.\n"
        "Actual result: only the deletion landed; CI passed because the old trigger watched the deleted file.\n\n"
    )
    next_step = (
        "\nNext: run proofrail draft-claims, then proofrail check-claims, then "
        "proofrail verify-change on a real committed range: "
        "https://github.com/DrDeese/Proofrail\n"
    )
    return preamble + render_text(result) + next_step


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Proofrail case: {result['case_id']}",
        "",
        f"**Overall verdict:** `{result['overall_verdict']}`",
    ]
    for claim in result["claims"]:
        lines.extend(
            [
                "",
                f"## Claim: {claim['claim_id']}",
                "",
                f"- Status: `{claim['status']}`",
                f"- Finding: {claim['finding']}",
                "- Evidence references: "
                + (", ".join(f"`{item}`" for item in claim["evidence_ids"]) or "None"),
                "- Provenance limitations:",
            ]
        )
        limitations = claim["provenance_limitations"]
        lines.extend(f"  - {item}" for item in limitations)
        if not limitations:
            lines.append("  - None reported.")

    lines.extend(["", "## What remains unverified", ""])
    unverified = [claim for claim in result["claims"] if claim["status"] != "verified"]
    lines.extend(
        f"- `{claim['claim_id']}` remains `{claim['status']}`: {claim['finding']}"
        for claim in unverified
    )
    lines.extend(f"- Provenance limitation: {item}" for item in result["provenance_limitations"])
    if not unverified and not result["provenance_limitations"]:
        lines.append("- Nothing remains unverified in the supplied offline evidence.")
    return "\n".join(lines) + "\n"
