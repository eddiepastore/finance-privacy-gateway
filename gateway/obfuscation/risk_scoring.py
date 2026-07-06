"""Packet risk scoring + the hard send-gate (spec Sections 10, 17.6).

No packet leaves without passing can_send_packet(). The gate is backed by the shared leak_scanner,
so the runtime guarantee and the test guarantee are the same code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .leak_scanner import Leak, scan_for_leaks


@dataclass
class RiskAssessment:
    score: int
    level: str                      # low | medium | high | critical
    leaks: List[Leak] = field(default_factory=list)
    signals: Dict[str, bool] = field(default_factory=dict)

    @property
    def has_hard_leak(self) -> bool:
        return any(l.kind in ("raw_dollar", "entity_name", "company_name") for l in self.leaks)


def _level_from_score(score: int) -> str:
    if score >= 100:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def score_packet(packet: Dict[str, Any], forbidden_terms: Dict[str, str]) -> RiskAssessment:
    leaks = scan_for_leaks(packet, forbidden_terms)
    kinds = {l.kind for l in leaks}

    signals = {
        "contains_real_entity_names": bool(kinds & {"entity_name", "company_name"}),
        "contains_raw_dollars": "raw_dollar" in kinds,
        "contains_account_names": "account_name" in kinds,
        "contains_department_names": "department_name" in kinds,
        "contains_customer_concentration": bool(packet.get("customer_concentration")),
        "contains_vendor_concentration": bool(packet.get("vendor_concentration")),
        "contains_payroll_or_headcount": _mentions(packet, ("headcount", "people costs", "payroll")),
        "low_row_count": _row_count(packet) < 5,
    }

    score = 0
    if signals["contains_real_entity_names"]:
        score += 100
    if signals["contains_raw_dollars"]:
        score += 100
    if signals["contains_account_names"]:
        score += 40
    if signals["contains_department_names"]:
        score += 25
    if signals["contains_customer_concentration"]:
        score += 20
    if signals["contains_vendor_concentration"]:
        score += 15
    if signals["contains_payroll_or_headcount"]:
        score += 20
    if signals["low_row_count"]:
        score += 15

    return RiskAssessment(score=score, level=_level_from_score(score), leaks=leaks, signals=signals)


def can_send_packet(assessment: RiskAssessment, block_threshold_level: str = "critical") -> bool:
    """Gate decision (spec Section 10.2):
      - any hard leak (raw dollars / real entity names) => block, always;
      - level >= block_threshold_level => block.
    Default blocks only at CRITICAL; HIGH is "allowed but flagged for approval" (logged by the pipeline)."""
    if assessment.has_hard_leak:
        return False
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return order[assessment.level] < order[block_threshold_level]


def _row_count(packet: Dict[str, Any]) -> int:
    return len(packet.get("summary_metrics", []) or []) + len(packet.get("material_items", []) or [])


def _mentions(node: Any, needles) -> bool:
    if isinstance(node, dict):
        return any(_mentions(v, needles) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_mentions(v, needles) for v in node)
    if isinstance(node, str):
        low = node.lower()
        return any(n in low for n in needles)
    return False
