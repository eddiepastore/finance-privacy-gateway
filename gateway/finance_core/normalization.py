"""Ingest raw CSVs into the canonical finance model.

Money is carried as Decimal end-to-end to avoid float penny drift (CTO decision over spec).
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

# ---- Canonical column synonyms for auto-mapping (Section 14.3) ---------------------------------
COLUMN_SYNONYMS = {
    "account": {"account", "account name", "account_name", "gl account", "line item", "category"},
    "account_type": {"account_type", "type", "account type", "statement_type"},
    "department": {"department", "dept", "cost center", "cost_center", "team", "business unit"},
    "period": {"period", "month", "date", "fiscal period", "fiscal_period"},
    "amount": {"amount", "actual", "actual amount", "value", "amount_usd", "$"},
}

REVENUE_TYPES = {"revenue", "income", "sales"}


def _to_decimal(raw: str) -> Decimal:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if s == "":
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Cannot parse numeric value: {raw!r}")


@dataclass(frozen=True)
class FinancialFact:
    scenario: str          # actual | budget | forecast
    period: str            # e.g. 2026-03
    account: str           # real account name (sensitive)
    account_type: str      # revenue | cogs | opex
    department: str        # real department name (sensitive)
    amount: Decimal

    @property
    def is_revenue(self) -> bool:
        return self.account_type.lower() in REVENUE_TYPES


@dataclass(frozen=True)
class KpiFact:
    kpi: str
    period: str
    actual: Decimal
    budget: Decimal
    unit: str = ""
    higher_is_better: bool = True


@dataclass(frozen=True)
class Concentration:
    """A counterparty concentration record (customer or vendor)."""
    entity_type: str       # customer | vendor
    name: str              # real name (sensitive)
    amount: Decimal

    def pct_of(self, total: Decimal) -> float:
        if total == 0:
            return 0.0
        return float(self.amount / total * 100)


@dataclass
class CanonicalModel:
    organization: str = "ORG"
    facts: List[FinancialFact] = field(default_factory=list)
    kpis: List[KpiFact] = field(default_factory=list)
    customers: List[Concentration] = field(default_factory=list)
    vendors: List[Concentration] = field(default_factory=list)

    # --- lookups -------------------------------------------------------------------------------
    def periods(self) -> List[str]:
        return sorted({f.period for f in self.facts})

    def accounts(self) -> List[str]:
        # preserve first-seen order for stable aliasing
        seen: Dict[str, None] = {}
        for f in self.facts:
            seen.setdefault(f.account, None)
        return list(seen)

    def departments(self) -> List[str]:
        seen: Dict[str, None] = {}
        for f in self.facts:
            seen.setdefault(f.department, None)
        return list(seen)

    def account_type(self, account: str) -> str:
        for f in self.facts:
            if f.account == account:
                return f.account_type
        return "opex"

    def department_of(self, account: str) -> str:
        for f in self.facts:
            if f.account == account:
                return f.department
        return ""

    def amount(self, scenario: str, period: str, account: str) -> Optional[Decimal]:
        total = None
        for f in self.facts:
            if f.scenario == scenario and f.period == period and f.account == account:
                total = (total or Decimal("0")) + f.amount
        return total

    def actual_revenue(self, period: str) -> Decimal:
        return sum(
            (f.amount for f in self.facts
             if f.scenario == "actual" and f.period == period and f.is_revenue),
            Decimal("0"),
        )


def auto_map_columns(headers: Iterable[str]) -> Dict[str, str]:
    """Map source headers -> canonical field names using COLUMN_SYNONYMS. Best-effort."""
    mapping: Dict[str, str] = {}
    for h in headers:
        key = h.strip().lower()
        for canonical, synonyms in COLUMN_SYNONYMS.items():
            if key == canonical or key in synonyms:
                mapping[h] = canonical
                break
    return mapping


def _load_facts(path: str, scenario: str) -> List[FinancialFact]:
    facts: List[FinancialFact] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cmap = auto_map_columns(reader.fieldnames or [])
        rev = {v: k for k, v in cmap.items()}  # canonical -> source header
        required = {"account", "department", "period", "amount"}
        missing = required - set(cmap.values())
        if missing:
            raise ValueError(f"{os.path.basename(path)} missing columns for: {sorted(missing)}")
        for row in reader:
            facts.append(
                FinancialFact(
                    scenario=scenario,
                    period=row[rev["period"]].strip(),
                    account=row[rev["account"]].strip(),
                    account_type=(row.get(rev.get("account_type", ""), "opex") or "opex").strip(),
                    department=row[rev["department"]].strip(),
                    amount=_to_decimal(row[rev["amount"]]),
                )
            )
    return facts


def _load_kpis(path: str) -> List[KpiFact]:
    out: List[KpiFact] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(
                KpiFact(
                    kpi=row["kpi"].strip(),
                    period=row["period"].strip(),
                    actual=_to_decimal(row["actual"]),
                    budget=_to_decimal(row["budget"]),
                    unit=row.get("unit", "").strip(),
                    higher_is_better=str(row.get("higher_is_better", "1")).strip() in ("1", "true", "True"),
                )
            )
    return out


def _load_concentration(path: str, entity_type: str, amount_col: str) -> List[Concentration]:
    out: List[Concentration] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            name = row[entity_type].strip()
            out.append(Concentration(entity_type=entity_type, name=name, amount=_to_decimal(row[amount_col])))
    return out


def load_package(data_dir: str) -> CanonicalModel:
    """Load the standard demo package from a directory of CSVs into a CanonicalModel."""
    model = CanonicalModel()
    plan = [("actuals.csv", "actual"), ("budget.csv", "budget"), ("forecast.csv", "forecast")]
    for fname, scenario in plan:
        path = os.path.join(data_dir, fname)
        if os.path.exists(path):
            model.facts.extend(_load_facts(path, scenario))

    kpi_path = os.path.join(data_dir, "kpis.csv")
    if os.path.exists(kpi_path):
        model.kpis = _load_kpis(kpi_path)

    cust_path = os.path.join(data_dir, "customers.csv")
    if os.path.exists(cust_path):
        model.customers = _load_concentration(cust_path, "customer", "revenue")

    vend_path = os.path.join(data_dir, "vendors.csv")
    if os.path.exists(vend_path):
        model.vendors = _load_concentration(vend_path, "vendor", "spend")

    company_path = os.path.join(data_dir, "company.txt")
    if os.path.exists(company_path):
        with open(company_path) as fh:
            model.organization = fh.read().strip()

    return model
