"""Value indexing + privacy rounding (spec Sections 9.3, 9.5, 17.2, 17.3).

Real dollars become index points relative to a locally chosen base that is NEVER sent externally.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Union

Number = Union[int, float, Decimal]


def select_base_amount(model, period: str) -> Decimal:
    """Base selection order (spec 17.3): current-period actual revenue, else total actual expense,
    else prior-period actual revenue, else 1."""
    rev = model.actual_revenue(period)
    if rev and rev != 0:
        return rev

    expense = sum(
        (f.amount for f in model.facts
         if f.scenario == "actual" and f.period == period and not f.is_revenue),
        Decimal("0"),
    )
    if expense and expense != 0:
        return expense

    periods = model.periods()
    if period in periods:
        idx = periods.index(period)
        if idx > 0:
            prev_rev = model.actual_revenue(periods[idx - 1])
            if prev_rev and prev_rev != 0:
                return prev_rev
    return Decimal("1")


def index_amount(amount: Optional[Number], base_amount: Number, precision: int = 1) -> Optional[float]:
    if amount is None:
        return None
    base = Decimal(str(base_amount))
    if base == 0:
        raise ValueError("Base amount cannot be zero")
    return round(float(Decimal(str(amount)) / base * 100), precision)


def privacy_round(index_value: Optional[float]) -> Union[float, str, None]:
    """Reduce inversion risk: bucket tiny values, summarize large outliers (spec 9.5)."""
    if index_value is None:
        return None
    mag = abs(index_value)
    if mag < 0.1:
        return "<0.1"
    if mag > 500:
        return ">500 (large outlier)"
    return round(index_value, 1)
