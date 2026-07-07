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
    "Never invent synthetic identifiers: every DEPT_/CLIENT_/VENDOR_/ISSUE_/ORG_ code you mention "
    "must appear verbatim somewhere in the packet.\n"
    "In your response, reference each finding through its \"issue_id\" field, copying the value "
    "from the packet's material_items[].item_id (e.g. ISSUE_001).\n"
    "Return output strictly in the requested JSON schema, with no prose outside the JSON.\n"
    "Focus on variance commentary, likely drivers, management questions, forecast implications, "
    "and a board-ready narrative."
)

# Exact response contract. Mirrors gateway/llm_client/schemas.py (REQUIRED_OUTPUT_KEYS + shapes) —
# keep the two in sync. Spelling the shapes out matters: smaller/local models improvise structure
# when given key names alone.
RESPONSE_TEMPLATE = """{
  "executive_summary": "<2-4 sentence plain string summarizing overall performance vs budget>",
  "material_variance_commentary": [
    {
      "issue_id": "<copy the item_id of one material item from the packet, e.g. ISSUE_001>",
      "summary": "<what happened and why it matters, as one plain string>",
      "likely_drivers": ["<driver>", "..."],
      "management_questions": ["<question for management>", "..."],
      "recommended_action": "<suggested management action>",
      "forecast_adjustment_recommendation": {
        "recommended": true,
        "direction": "<decrease | increase | unchanged>",
        "reason": "<why>"
      }
    }
  ],
  "board_narrative": { "draft": "<board-ready narrative as one string>" },
  "risks_to_monitor": ["<risk>", "..."],
  "open_questions": ["<question>", "..."]
}"""


def build_user_prompt(packet: Dict[str, Any]) -> str:
    return (
        "Analyze the following obfuscated FP&A packet and return the required JSON.\n\n"
        "PACKET:\n"
        + json.dumps(packet, indent=2)
        + "\n\nReturn ONLY a JSON object with EXACTLY this structure (these five top-level keys, "
        "no others):\n"
        + RESPONSE_TEMPLATE
        + "\n\nRules:\n"
        "- executive_summary must be a plain string, not an object.\n"
        "- Every material_variance_commentary entry MUST include \"issue_id\", copied verbatim "
        "from a material_items[].item_id in the packet. Cover each material item once.\n"
        "- board_narrative must be an object with a single string field \"draft\".\n"
        "- risks_to_monitor and open_questions must be arrays of strings.\n"
        "- Do not add any other top-level keys. Do not output currency amounts."
    )


def build_repair_prompt(packet: Dict[str, Any], errors: list) -> str:
    """One-shot retry prompt: feed validation errors back for a corrected response."""
    return (
        build_user_prompt(packet)
        + "\n\nYour previous response FAILED validation with these errors:\n- "
        + "\n- ".join(str(e) for e in errors[:12])
        + "\n\nReturn the corrected JSON object only. Fix every error. Use only synthetic "
        "identifiers that appear verbatim in the packet."
    )
