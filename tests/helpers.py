"""Shared test fixtures."""
from __future__ import annotations

from decimal import Decimal

from gateway.finance_core.normalization import (
    CanonicalModel, Concentration, FinancialFact, KpiFact,
)


def tiny_model() -> CanonicalModel:
    """A minimal two-account, one-period model with a known answer key."""
    m = CanonicalModel(organization="Testco, Inc.")
    P = "2026-03"
    facts = [
        # Subscription Revenue: actual 100 vs budget 120 => -20 / -16.67% (revenue => unfavorable)
        FinancialFact("actual", P, "Subscription Revenue", "revenue", "Sales", Decimal("100")),
        FinancialFact("budget", P, "Subscription Revenue", "revenue", "Sales", Decimal("120")),
        FinancialFact("forecast", P, "Subscription Revenue", "revenue", "Sales", Decimal("110")),
        # Payroll: actual 60 vs budget 50 => +10 / +20% (expense => unfavorable)
        FinancialFact("actual", P, "Payroll", "opex", "Engineering", Decimal("60")),
        FinancialFact("budget", P, "Payroll", "opex", "Engineering", Decimal("50")),
        FinancialFact("forecast", P, "Payroll", "opex", "Engineering", Decimal("55")),
    ]
    m.facts.extend(facts)
    m.kpis = [
        KpiFact("Bookings", P, Decimal("87"), Decimal("100"), "usd", True),       # below plan, unfavorable
        KpiFact("Logo Churn", P, Decimal("2.4"), Decimal("1.8"), "pct", False),    # above plan, unfavorable
    ]
    m.customers = [
        Concentration("customer", "Northwind Health Systems", Decimal("310")),
        Concentration("customer", "Acme Logistics", Decimal("140")),
    ]
    m.vendors = [Concentration("vendor", "Amazon Web Services", Decimal("130"))]
    return m


SAMPLE_DIR = None  # resolved lazily by tests that need real sample data
