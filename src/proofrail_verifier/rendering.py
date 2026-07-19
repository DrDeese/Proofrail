"""Render verifier results as stable JSON or plain Markdown."""

from __future__ import annotations

import json
from typing import Any


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


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
