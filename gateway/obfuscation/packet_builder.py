"""Build the minimal obfuscated analysis packet sent to the LLM (spec Section 11).

Guarantees by construction: no raw dollars (only index points), no real entity names (aliased),
no rehydration key. risk_scoring still independently verifies this before any send.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from ..finance_core.calculations import VarianceItem
from ..finance_core.materiality import kpi_severity
from .aliases import AliasVault, generalize_account
from .indexing import index_amount, privacy_round, select_base_amount

PACKET_VERSION = "1.0"


def _aggregate_by_label(items: List[VarianceItem], privacy_mode: str, vault: AliasVault):
    """Group account-level variances into the category label the LLM will see."""
    groups: Dict[str, Dict[str, Any]] = {}
    for it in items:
        label = _category_label(it.account, privacy_mode, vault)
        g = groups.setdefault(label, {
            "label": label,
            "actual": Decimal("0"), "budget": Decimal("0"), "forecast": Decimal("0"),
            "has_budget": False, "has_forecast": False,
            "is_revenue": it.is_revenue,
        })
        g["actual"] += it.actual
        if it.budget is not None:
            g["budget"] += it.budget
            g["has_budget"] = True
        if it.forecast is not None:
            g["forecast"] += it.forecast
            g["has_forecast"] = True
    return groups


def _category_label(account: str, privacy_mode: str, vault: AliasVault) -> str:
    if privacy_mode == "standard_finance":
        return account.strip()
    if privacy_mode in ("high_privacy", "board"):
        return vault.alias("account", account)
    return generalize_account(account)  # generalized_semantic_labels (default)


def _pct(a: Optional[Decimal], b: Optional[Decimal]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round(float((a - b) / abs(b) * 100), 1)


def build_packet(
    model,
    variances: List[VarianceItem],
    period: str,
    vault: AliasVault,
    *,
    privacy_mode: str = "generalized_semantic_labels",
    base_amount: Optional[Decimal] = None,
    abstract_periods: bool = True,
    include_concentration: bool = True,
    only_material: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    if base_amount is None:
        base_amount = select_base_amount(model, period)

    # Period aliasing
    period_alias = {p: f"P{idx + 1:02d}" for idx, p in enumerate(model.periods())}
    period_label = period_alias[period] if abstract_periods else period

    def idx(v: Optional[Decimal]):
        return privacy_round(index_amount(v, base_amount)) if v is not None else None

    # ---- summary metrics (aggregated by category label) --------------------------------------
    groups = _aggregate_by_label(variances, privacy_mode, vault)
    summary_metrics = []
    for g in groups.values():
        summary_metrics.append({
            "metric": g["label"],
            "period": period_label,
            "actual_index": idx(g["actual"]),
            "budget_index": idx(g["budget"]) if g["has_budget"] else None,
            "forecast_index": idx(g["forecast"]) if g["has_forecast"] else None,
            "variance_vs_budget_pct": _pct(g["actual"], g["budget"]) if g["has_budget"] else None,
            "variance_vs_forecast_pct": _pct(g["actual"], g["forecast"]) if g["has_forecast"] else None,
        })

    # ---- material items (per-account, with stable ISSUE ids) ---------------------------------
    material_levels = {"high", "medium"} if only_material else {"high", "medium", "low"}
    material_items = []
    issue_index = 1
    for it in sorted(variances, key=lambda x: x.contribution_to_total_variance_pct, reverse=True):
        if it.severity not in material_levels:
            continue
        item = {
            "item_id": f"ISSUE_{issue_index:03d}",
            "category": _category_label(it.account, privacy_mode, vault),
            "department": vault.alias("department", it.department),
            "severity": it.severity,
            "variance_direction": it.favorability,
            "variance_vs_budget_pct": it.variance_vs_budget_pct
                if it.variance_vs_budget_pct is None else round(it.variance_vs_budget_pct, 1),
            "variance_vs_forecast_pct": it.variance_vs_forecast_pct
                if it.variance_vs_forecast_pct is None else round(it.variance_vs_forecast_pct, 1),
            "contribution_to_total_variance_pct": it.contribution_to_total_variance_pct,
            "known_driver_notes": [],
        }
        desc = vault.descriptors.get(item["category"])
        if desc:
            item["category_descriptor"] = desc
        material_items.append(item)
        issue_index += 1

    # ---- KPIs (indexed to their own budget) --------------------------------------------------
    kpis = []
    for k in model.kpis:
        if k.period != period:
            continue
        kpis.append({
            "name": k.kpi,
            "period": period_label,
            "actual_index": round(float(k.actual / k.budget * 100), 1) if k.budget else None,
            "budget_index": 100.0 if k.budget else None,
            "variance_vs_budget_pct": _pct(k.actual, k.budget),
            # Unfavorable exactly when a higher-is-better KPI is below plan, or a lower-is-better KPI is above plan.
            "trend": "unfavorable_to_plan" if (k.actual < k.budget) == k.higher_is_better else "favorable_to_plan",
            "materiality": kpi_severity(k.actual, k.budget, k.higher_is_better),
        })

    packet: Dict[str, Any] = {
        "packet_version": PACKET_VERSION,
        "privacy_mode": privacy_mode,
        "company_context": {
            "company_label": "ORG_001",
            "industry_context": "B2B SaaS company",
            "size_band": "not_disclosed",
            "currency": "INDEX_POINTS",
        },
        "periods": [period_alias[p] if abstract_periods else p for p in model.periods()],
        "baseline": {
            "base_metric": "current_period_actual_revenue",
            "base_value_sent_to_model": 100.0,
            "real_base_value_disclosed": False,
        },
        "summary_metrics": summary_metrics,
        "material_items": material_items,
        "kpis": kpis,
        "requested_outputs": [
            "variance_commentary", "forecast_adjustments", "board_narrative", "questions_for_management",
        ],
        "output_rules": {
            "do_not_invent_numbers": True,
            "reference_only_known_item_ids": True,
            "return_json": True,
            "do_not_request_raw_financial_data": True,
        },
    }

    # ---- concentration (V1 inclusion — CTO decision) -----------------------------------------
    if include_concentration:
        if model.customers:
            total = sum((c.amount for c in model.customers), Decimal("0"))
            packet["customer_concentration"] = [
                {"label": vault.alias("customer", c.name), "revenue_pct": round(c.pct_of(total), 1)}
                for c in sorted(model.customers, key=lambda c: c.amount, reverse=True)
            ]
        if model.vendors:
            total = sum((v.amount for v in model.vendors), Decimal("0"))
            packet["vendor_concentration"] = [
                {"label": vault.alias("vendor", v.name), "spend_pct": round(v.pct_of(total), 1)}
                for v in sorted(model.vendors, key=lambda v: v.amount, reverse=True)
            ]

    return packet, period_alias
