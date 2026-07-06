"""Required LLM output schema (spec Section 11.2) + a lightweight stdlib validator."""
from __future__ import annotations

from typing import Any, List, Tuple

REQUIRED_OUTPUT_KEYS = [
    "executive_summary",
    "material_variance_commentary",
    "board_narrative",
    "risks_to_monitor",
    "open_questions",
]


def _is_str(x: Any) -> bool:
    return isinstance(x, str)


def validate_output_schema(obj: Any) -> Tuple[bool, List[str]]:
    """Structural validation only (types/keys). Semantic checks live in validator.py."""
    errors: List[str] = []
    if not isinstance(obj, dict):
        return False, ["response is not a JSON object"]

    for key in REQUIRED_OUTPUT_KEYS:
        if key not in obj:
            errors.append(f"missing required key: {key}")

    if "executive_summary" in obj and not _is_str(obj["executive_summary"]):
        errors.append("executive_summary must be a string")

    mvc = obj.get("material_variance_commentary")
    if mvc is not None:
        if not isinstance(mvc, list):
            errors.append("material_variance_commentary must be a list")
        else:
            for i, item in enumerate(mvc):
                if not isinstance(item, dict):
                    errors.append(f"material_variance_commentary[{i}] must be an object")
                    continue
                if "issue_id" not in item:
                    errors.append(f"material_variance_commentary[{i}] missing issue_id")
                far = item.get("forecast_adjustment_recommendation")
                if far is not None:
                    if not isinstance(far, dict):
                        errors.append(f"material_variance_commentary[{i}].forecast_adjustment_recommendation must be an object")
                    elif far.get("direction") not in ("decrease", "increase", "unchanged", None):
                        errors.append(f"material_variance_commentary[{i}] invalid forecast direction")

    bn = obj.get("board_narrative")
    if bn is not None and not (isinstance(bn, dict) and _is_str(bn.get("draft", ""))):
        errors.append("board_narrative must be an object with a string 'draft'")

    rtm = obj.get("risks_to_monitor")
    if rtm is not None and not isinstance(rtm, list):
        errors.append("risks_to_monitor must be a list")

    oq = obj.get("open_questions")
    if oq is not None and not isinstance(oq, list):
        errors.append("open_questions must be a list")

    return (len(errors) == 0), errors
