"""Render bounded acceptance-policy decisions deterministically."""

from __future__ import annotations

import json
from typing import Any


def render_policy_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_policy_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Proofrail acceptance policy: {result['case_id']}",
        "",
        f"**Policy accepted:** `{'true' if result['accepted'] else 'false'}`",
        "",
        "## Claim decisions",
        "",
    ]
    for decision in result["claim_decisions"]:
        lines.append(
            f"- `{decision['claim_id']}`: `{decision['status']}` — "
            f"{'accepted' if decision['accepted'] else 'rejected'} "
            f"by `{decision['rule']}`"
        )
    overall = result["overall_decision"]
    lines.extend(
        [
            "",
            "## Overall decision",
            "",
            f"- `{overall['verdict']}` — "
            f"{'accepted' if overall['accepted'] else 'rejected'}",
            "",
            "## Reasons",
            "",
        ]
    )
    reasons = result["reasons"]
    lines.extend(f"- {reason}" for reason in reasons)
    if not reasons:
        lines.append("- All claim and overall rules accepted the completed result.")
    return "\n".join(lines) + "\n"
