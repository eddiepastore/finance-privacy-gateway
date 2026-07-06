"""Local forecast-adjustment math (spec Section 28).

The LLM may recommend a reforecast *direction*; the dollar *range* is computed here, locally, and
never by the model. Conservative run-rate carry with a sensitivity band.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple

from .calculations import VarianceItem

# Sensitivity band applied to the run-rate carry (e.g. pipeline-conversion uncertainty).
DEFAULT_SENSITIVITY = (Decimal("0.75"), Decimal("1.25"))


def suggested_quarter_adjustment(
    variance_amount: Decimal,
    *,
    quarter_months: int = 3,
    sensitivity: Tuple[Decimal, Decimal] = DEFAULT_SENSITIVITY,
) -> Tuple[Decimal, Decimal]:
    """Carry the period variance across the remaining quarter, with a low/high sensitivity band.

    Returns a (low, high) range ordered low-to-high by magnitude-signed value.
    """
    base = variance_amount * quarter_months
    a, b = base * sensitivity[0], base * sensitivity[1]
    return (a, b) if a <= b else (b, a)


def forecast_adjustment_for(item: VarianceItem) -> Optional[dict]:
    """Suggested local reforecast range for a material item, signed to reflect the variance direction.

    Revenue shortfalls => downward revenue revision (negative); expense overruns => upward expense
    revision (positive). Returns None when there is no budget variance to carry.
    """
    if item.variance_vs_budget_amount is None or item.variance_vs_budget_amount == 0:
        return None
    low, high = suggested_quarter_adjustment(item.variance_vs_budget_amount)
    direction = "decrease" if (item.is_revenue and item.variance_vs_budget_amount < 0) else \
                "increase" if (not item.is_revenue and item.variance_vs_budget_amount > 0) else \
                "review"
    return {"low": low, "high": high, "direction": direction}
