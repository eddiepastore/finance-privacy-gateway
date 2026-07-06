"""Builds the JSON payload that backs the web dashboard. Pure function over the pipeline result,
so it is reusable and testable without binding a socket.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List

from ..finance_core import load_package
from ..obfuscation import (
    AliasVault, build_forbidden_terms, build_packet, scan_for_leaks, select_base_amount,
)
from ..obfuscation.aliases import generalize_account
from ..obfuscation.publication_gate import POLICY_VERSION, assess_publication_safety
from ..pipeline import format_money, run_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DIR = os.path.join(ROOT, "sample_data")

PREVIEW_ACCOUNTS = ["Subscription Revenue", "Payroll", "Cloud Infrastructure", "Marketing Programs"]


def rebuild_vault(model, variances, period, privacy_mode):
    """Rebuild the deterministic alias vault that build_packet would have produced for this run."""
    vault = AliasVault()
    base = select_base_amount(model, period)
    build_packet(model, variances, period, vault, privacy_mode=privacy_mode, base_amount=base)
    return vault


def build_preview_rows(model, period, privacy_mode, vault, packet) -> List[Dict[str, str]]:
    """Mode-aware real -> LLM-safe preview. In high_privacy, accounts show as CAT_### + descriptor
    with the real name withheld; in generalized mode, as the generalized semantic label; in standard
    mode, the real account name is retained. Always the single source of truth for the preview screen."""
    sm = {m["metric"]: m for m in packet.get("summary_metrics", [])}
    periods = packet.get("periods", [])
    rows = [
        {"field": "Company name", "real": model.organization, "safe": "ORG_001 (withheld)"},
        {"field": "Reporting period", "real": period,
         "safe": (periods[-1] if periods else "P0x") + " (abstracted)"},
    ]
    for acct in PREVIEW_ACCOUNTS:
        amt = model.amount("actual", period, acct)
        if amt is None:
            continue
        if privacy_mode == "standard_finance":
            label = acct
            idx = sm.get(label, {}).get("actual_index", "n/a")
            safe = f"{label} = {idx} index pts"
        elif privacy_mode in ("high_privacy", "board"):
            cat = vault.alias("account", acct)        # existing alias (deterministic)
            desc = vault.descriptors.get(cat)
            idx = sm.get(cat, {}).get("actual_index", "n/a")
            safe = f"{cat}" + (f" · {desc}" if desc else "") + f" = {idx} idx · real name withheld"
        else:  # generalized_semantic_labels
            label = generalize_account(acct)
            idx = sm.get(label, {}).get("actual_index", "n/a")
            safe = f"{label} = {idx} index pts"
        rows.append({"field": f"Account: {acct}", "real": format_money(amt), "safe": safe})
    if model.customers and packet.get("customer_concentration"):
        rows.append({"field": "Top customer", "real": model.customers[0].name,
                     "safe": packet["customer_concentration"][0]["label"]})
    if model.vendors and packet.get("vendor_concentration"):
        top_v = max(model.vendors, key=lambda v: v.amount)
        rows.append({"field": "Top vendor", "real": top_v.name,
                     "safe": packet["vendor_concentration"][0]["label"]})
    return rows


def build_dashboard_payload(period: str = "2026-03",
                            privacy_mode: str = "generalized_semantic_labels",
                            role: str = "cfo",
                            llm_preference: str = "mock",
                            data_dir: str = SAMPLE_DIR) -> Dict[str, Any]:
    model = load_package(data_dir)
    result = run_pipeline(model, period, privacy_mode=privacy_mode, viewer_role=role,
                          llm_preference=llm_preference)

    forbidden = build_forbidden_terms(model, privacy_mode)
    leaks = scan_for_leaks(result.packet, forbidden)
    hard = [l for l in leaks if l.kind in ("raw_dollar", "entity_name", "company_name")]

    variances = []
    for v in sorted(result.material_variances,
                    key=lambda x: x.contribution_to_total_variance_pct, reverse=True):
        variances.append({
            "severity": v.severity,
            "account": v.account,
            "department": v.department,
            "favorability": v.favorability,
            "variance": format_money(abs(v.variance_vs_budget_amount)) if v.variance_vs_budget_amount is not None else "n/a",
            "variance_pct": round(v.variance_vs_budget_pct, 1) if v.variance_vs_budget_pct is not None else None,
            "contribution_pct": v.contribution_to_total_variance_pct,
        })

    packet_blob = json.dumps(result.packet, sort_keys=True, separators=(",", ":"))
    model_fallback = llm_preference in ("auto", "openai") and result.llm_provider == "mock"
    publication = assess_publication_safety(result.board_markdown, model, audience=role)

    return {
        "company": model.organization,
        "period": period,
        "available_periods": model.periods(),
        "privacy_mode": privacy_mode,
        "role": role,
        "gate": {
            "risk_level": result.risk.level,
            "risk_score": result.risk.score,
            "hard_leaks": len(hard),
            "raw_dollars_sent": result.risk.signals["contains_raw_dollars"],
            "real_entities_sent": result.risk.signals["contains_real_entity_names"],
            "sent_to_llm": result.sent_to_llm,
            "llm_provider": result.llm_provider,
            "llm_model": result.llm_model,
            "model_fallback": model_fallback,
            "model_status_message": "Mock fallback used — real OpenAI-compatible model was requested but is not configured or failed."
                if model_fallback else f"Using {result.llm_provider} · {result.llm_model}",
            "validation_ok": result.validation_ok,
            "validation_errors": result.validation_errors,
        },
        "packet_meta": {
            "policy_version": POLICY_VERSION,
            "run_id": "stateless_demo",
            "created_at": result.audit_log[-1]["ts"] if result.audit_log else "",
            "packet_sha256": hashlib.sha256(packet_blob.encode("utf-8")).hexdigest(),
            "model_provider": result.llm_provider,
            "model_name": result.llm_model,
        },
        "preview": build_preview_rows(
            model, period, privacy_mode,
            rebuild_vault(model, result.variances, period, privacy_mode), result.packet),
        "variances": variances,
        "packet": result.packet,
        "review_items": result.review_items,
        "board_markdown": result.board_markdown,
        "publication_gate": {k: v for k, v in publication.items() if k != "safe_markdown"},
        "safe_board_markdown": publication.get("safe_markdown", ""),
        "audit_log": result.audit_log,
    }
