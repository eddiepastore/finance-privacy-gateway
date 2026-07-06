"""System prompt + user prompt builder (spec Section 18). Inspectable by the user (open decision #6: yes)."""
from __future__ import annotations

import json
from typing import Any, Dict

SYSTEM_PROMPT = (
    "You are assisting with FP&A analysis using an obfuscated financial packet.\n"
    "All financial values are indexed and do not represent actual currency.\n"
    "Do not infer the company identity.\n"
    "Do not request raw financial data.\n"
    "Do not invent financial values; do not output any currency amounts.\n"
    "Use only the metrics, issue IDs, variance percentages, trend labels, materiality ratings, "
    "and synthetic identifiers provided in the packet.\n"
    "Reference findings by their item_id (e.g. ISSUE_001).\n"
    "Return output strictly in the requested JSON schema, with no prose outside the JSON.\n"
    "Focus on variance commentary, likely drivers, management questions, forecast implications, "
    "and a board-ready narrative."
)


def build_user_prompt(packet: Dict[str, Any]) -> str:
    return (
        "Analyze the following obfuscated FP&A packet and return the required JSON.\n\n"
        "PACKET:\n"
        + json.dumps(packet, indent=2)
        + "\n\nReturn JSON with keys: executive_summary, material_variance_commentary, "
        "board_narrative, risks_to_monitor, open_questions."
    )
