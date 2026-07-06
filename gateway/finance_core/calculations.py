"""Deterministic local finance calculations. The LLM never does this math (spec Section 5.1)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from .normalization import CanonicalModel


def _pct(amount_variance: Decimal, base: Decimal) -> Optional[float]:
    if base == 0:
        return None
    return float(amount_variance / abs(base) * 100)


@dataclass
class VarianceItem:
    account: str
    account_type: str
    department: str
    period: str
    is_revenue: bool
    actual: Decimal
    budget: Optional[Decimal]
    forecast: Optional[Decimal]
    variance_vs_budget_amount: Optional[Decimal]
    variance_vs_budget_pct: Optional[float]
    variance_vs_forecast_amount: Optional[Decimal]
    variance_vs_forecast_pct: Optional[float]
    contribution_to_total_variance_pct: float = 0.0
    severity: str = "immaterial"
    materiality_reason: str = ""

    @property
    def favorability(self) -> str:
        """favorable / unfavorable / neutral vs budget, respecting revenue vs expense sign."""
        v = self.variance_vs_budget_amount
        if v is None or v == 0:
            return "neutral"
        positive = v > 0
        # revenue: actual above budget is favorable; expense: actual above budget is unfavorable
        favorable = positive if self.is_revenue else (not positive)
        return "favorable" if favorable else "unfavorable"


def compute_variances(model: CanonicalModel, period: str) -> List[VarianceItem]:
    """Compute actual-vs-budget and actual-vs-forecast variances for every account in a period."""
    items: List[VarianceItem] = []
    for account in model.accounts():
        actual = model.amount("actual", period, account)
        if actual is None:
            continue
        budget = model.amount("budget", period, account)
        forecast = model.amount("forecast", period, account)

        var_b = (actual - budget) if budget is not None else None
        var_f = (actual - forecast) if forecast is not None else None

        items.append(
            VarianceItem(
                account=account,
                account_type=model.account_type(account),
                department=model.department_of(account),
                period=period,
                is_revenue=model.account_type(account).lower() in ("revenue", "income", "sales"),
                actual=actual,
                budget=budget,
                forecast=forecast,
                variance_vs_budget_amount=var_b,
                variance_vs_budget_pct=_pct(var_b, budget) if budget is not None else None,
                variance_vs_forecast_amount=var_f,
                variance_vs_forecast_pct=_pct(var_f, forecast) if forecast is not None else None,
            )
        )

    # Contribution to total absolute budget variance (so issues can be ranked by impact).
    total_abs = sum((abs(i.variance_vs_budget_amount) for i in items
                     if i.variance_vs_budget_amount is not None), Decimal("0"))
    if total_abs > 0:
        for i in items:
            if i.variance_vs_budget_amount is not None:
                i.contribution_to_total_variance_pct = round(
                    float(abs(i.variance_vs_budget_amount) / total_abs * 100), 1
                )
    return items


def compute_mom_trend(model: CanonicalModel, account: str, scenario: str = "actual") -> Dict[str, Optional[float]]:
    """Month-over-month percentage change for an account across all available periods."""
    periods = model.periods()
    trend: Dict[str, Optional[float]] = {}
    prev: Optional[Decimal] = None
    for p in periods:
        cur = model.amount(scenario, p, account)
        if cur is None:
            trend[p] = None
        elif prev is None or prev == 0:
            trend[p] = None
        else:
            trend[p] = round(float((cur - prev) / abs(prev) * 100), 1)
        if cur is not None:
            prev = cur
    return trend
