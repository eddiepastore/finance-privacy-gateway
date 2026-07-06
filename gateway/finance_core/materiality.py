"""Materiality engine — flags issues worth human attention (spec Section 7.4).

Runs on REAL pre-obfuscation numbers (percentage + absolute-dollar thresholds), with per-account
overrides. Returns severity: high | medium | low | immaterial.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

from .calculations import VarianceItem


@dataclass
class Thresholds:
    high_pct: float
    medium_pct: float
    low_pct: float
    high_abs: Decimal
    medium_abs: Decimal
    low_abs: Decimal


@dataclass
class MaterialityRules:
    default: Thresholds
    # account-name (case-insensitive) -> Thresholds override
    overrides: Dict[str, Thresholds] = field(default_factory=dict)

    def for_account(self, account: str) -> Thresholds:
        return self.overrides.get(account.strip().lower(), self.default)


# Sensible defaults. Revenue/payroll/cash are more sensitive => lower percentage triggers.
DEFAULT_RULES = MaterialityRules(
    default=Thresholds(
        high_pct=10.0, medium_pct=5.0, low_pct=2.0,
        high_abs=Decimal("250000"), medium_abs=Decimal("100000"), low_abs=Decimal("25000"),
    ),
    overrides={
        "subscription revenue": Thresholds(3.0, 2.0, 1.0, Decimal("200000"), Decimal("100000"), Decimal("25000")),
        "services revenue":     Thresholds(3.0, 2.0, 1.0, Decimal("100000"), Decimal("50000"),  Decimal("15000")),
        "payroll":              Thresholds(5.0, 3.0, 1.5, Decimal("150000"), Decimal("75000"),  Decimal("25000")),
    },
)


def classify_materiality(item: VarianceItem, rules: MaterialityRules = DEFAULT_RULES) -> VarianceItem:
    """Mutates and returns the VarianceItem with severity + reason set, based on vs-budget variance."""
    t = rules.for_account(item.account)
    pct = abs(item.variance_vs_budget_pct or 0.0)
    amt = abs(item.variance_vs_budget_amount or Decimal("0"))

    def hit(level_pct: float, level_abs: Decimal) -> bool:
        # An item is material at a level if it clears EITHER the % or the $ bar at that level.
        return pct >= level_pct or amt >= level_abs

    if hit(t.high_pct, t.high_abs):
        sev, reason = "high", f"{pct:.1f}% / ${amt:,.0f} vs budget exceeds high threshold"
    elif hit(t.medium_pct, t.medium_abs):
        sev, reason = "medium", f"{pct:.1f}% / ${amt:,.0f} vs budget exceeds medium threshold"
    elif hit(t.low_pct, t.low_abs):
        sev, reason = "low", f"{pct:.1f}% / ${amt:,.0f} vs budget exceeds low threshold"
    else:
        sev, reason = "immaterial", "below materiality thresholds"

    item.severity = sev
    item.materiality_reason = reason
    return item


def kpi_severity(actual: Decimal, budget: Decimal, higher_is_better: bool,
                 rules: MaterialityRules = DEFAULT_RULES) -> str:
    if budget == 0:
        return "immaterial"
    pct = float((actual - budget) / abs(budget) * 100)
    # Reframe so "unfavorable" is always a negative pct regardless of direction.
    unfav = pct if higher_is_better else -pct
    t = rules.default
    mag = abs(unfav)
    if mag >= t.high_pct:
        return "high"
    if mag >= t.medium_pct:
        return "medium"
    if mag >= t.low_pct:
        return "low"
    return "immaterial"
