"""Response Validator (spec Section 7.9). Validates LLM output BEFORE rehydration."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ..obfuscation.leak_scanner import _MONEY_RE
from ..obfuscation.rehydration import _SYNTH_RE
from .schemas import validate_output_schema

_RAW_ACCESS_PHRASES = ["raw financial", "actual dollars", "real company name", "send me the raw",
                       "provide the actual", "underlying ledger"]


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _collect_synthetics(node: Any, acc: Set[str]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            _collect_synthetics(v, acc)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _collect_synthetics(v, acc)
    elif isinstance(node, str):
        acc.update(_SYNTH_RE.findall(node))


def _collect_strings(node: Any, acc: List[str]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            _collect_strings(v, acc)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _collect_strings(v, acc)
    elif isinstance(node, str):
        acc.append(node)


def validate_response(response: Dict[str, Any], packet: Dict[str, Any]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    schema_ok, schema_errors = validate_output_schema(response)
    errors.extend(schema_errors)
    if not schema_ok:
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    # 1. Known issue ids
    known_issue_ids = {m["item_id"] for m in packet.get("material_items", [])}
    for item in response.get("material_variance_commentary", []):
        iid = item.get("issue_id")
        if iid not in known_issue_ids:
            errors.append(f"references unknown issue_id: {iid}")

    # 2. Synthetic identifiers must exist in the packet (no hallucinated entities)
    known_synthetics: Set[str] = set()
    _collect_synthetics(packet, known_synthetics)
    used_synthetics: Set[str] = set()
    _collect_synthetics(response, used_synthetics)
    for s in used_synthetics - known_synthetics:
        errors.append(f"references unknown synthetic identifier: {s}")

    # 3. No raw currency in output
    strings: List[str] = []
    _collect_strings(response, strings)
    for s in strings:
        if _MONEY_RE.search(s):
            errors.append(f"output contains a raw currency/large-number pattern: {s[:60]!r}")
            break

    # 4. No requests for raw data / identity claims
    blob = " ".join(strings).lower()
    for phrase in _RAW_ACCESS_PHRASES:
        if phrase in blob:
            warnings.append(f"output mentions restricted concept: {phrase!r}")

    return ValidationResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)
