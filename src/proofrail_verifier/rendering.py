"""Render verifier results as stable JSON, text, or plain Markdown."""

from __future__ import annotations

import json
import shutil
import textwrap
from typing import Any


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _text_layout(
    rows: list[tuple[str, str, str]],
) -> tuple[int, int, int, int]:
    headers = ("Claim ID", "Status", "Finding")
    claim_width = max(len(headers[0]), *(len(row[0]) for row in rows))
    status_width = max(len(headers[1]), *(len(row[1]) for row in rows))
    fixed_width = claim_width + status_width + 6
    longest_finding = max(len(row[2]) for row in rows)
    longest_finding_word = max(
        len(word)
        for row in rows
        for word in row[2].split()
    )
    terminal_width = max(
        60,
        shutil.get_terminal_size(fallback=(80, 24)).columns,
    )
    output_width = max(
        terminal_width,
        fixed_width + longest_finding_word,
    )
    finding_width = min(longest_finding, output_width - fixed_width)
    return output_width, claim_width, status_width, finding_width


def render_text(result: dict[str, Any]) -> str:
    headers = ("Claim ID", "Status", "Finding")
    rows = [
        (claim["claim_id"], claim["status"], claim["finding"])
        for claim in result["claims"]
    ]
    output_width, claim_width, status_width, finding_width = _text_layout(rows)

    def wrap(value: str, width: int = output_width) -> list[str]:
        return textwrap.wrap(
            value,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]

    table_lines = [
        f"{headers[0].ljust(claim_width)} | {headers[1].ljust(status_width)} | {headers[2]}",
        f"{'-' * claim_width}-+-{'-' * status_width}-+-{'-' * finding_width}",
    ]
    continuation_prefix = (
        f"{' ' * claim_width} | {' ' * status_width} | "
    )
    for claim_id, status, finding in rows:
        finding_lines = wrap(finding, finding_width)
        table_lines.append(
            f"{claim_id.ljust(claim_width)} | "
            f"{status.ljust(status_width)} | {finding_lines[0]}"
        )
        table_lines.extend(
            continuation_prefix + line for line in finding_lines[1:]
        )

    lines = [
        *wrap(f"Case ID: {result['case_id']}"),
        "",
        *table_lines,
        "",
        *wrap(
            f"Overall verdict: {result['overall_verdict']} - some claims are "
            "supported, while others are not or still need human review."
        ),
        "",
        *wrap(f"Provenance limitations: {len(result['provenance_limitations'])}"),
        *wrap(
            "Full JSON: re-run this command with --format json for per-claim "
            "evidence references, source hashes, and provenance limitations."
        ),
    ]
    return "\n".join(lines) + "\n"


def render_demo_text(result: dict[str, Any]) -> str:
    rows = [
        (claim["claim_id"], claim["status"], claim["finding"])
        for claim in result["claims"]
    ]
    output_width, _, _, _ = _text_layout(rows)

    def wrap(value: str) -> list[str]:
        return textwrap.wrap(
            value,
            width=output_width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]

    preamble = (
        "Demo: deterministic reconstruction of a real incident.",
        "Agent claim: the obsolete lockfile was deleted and two workflow triggers were updated.",
        "Actual result: only the deletion landed; CI passed because the old trigger watched the deleted file, so green CI did not prove the new triggers worked.",
    )
    next_step = (
        "Next: run proofrail draft-claims, then proofrail check-claims, then "
        "proofrail verify-change on a real committed range: "
        "https://github.com/DrDeese/Proofrail"
    )
    preamble_lines = [line for statement in preamble for line in wrap(statement)]
    return (
        "\n".join(preamble_lines)
        + "\n\n"
        + render_text(result)
        + "\n"
        + "\n".join(wrap(next_step))
        + "\n"
    )


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
