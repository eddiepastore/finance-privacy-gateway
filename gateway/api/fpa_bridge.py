"""Stateless FP&A → gateway bridge (spec: docs PRIVACY_GATEWAY_INTEGRATION in the FP&A repo).

Takes an already-computed FP&A variance set, runs it through the REAL obfuscation pipeline
(alias + index → leak gate → model → validate → rehydrate), and returns rehydrated drafts plus a
privacy proof. The frontier model only ever receives aliased categories/departments and indexed
values — never real names or dollars. Backs `POST /api/fpa/commentary`.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from ..finance_core import (
    CanonicalModel, Concentration, DEFAULT_RULES, FinancialFact, KpiFact,
    classify_materiality, compute_variances,
)
from ..llm_client import SYSTEM_PROMPT, MockLLM, build_user_prompt, get_client, validate_response
from ..obfuscation import (
    AliasVault, Permissions, build_forbidden_terms, build_packet, can_send_packet,
    rehydrate_response, scan_for_leaks, score_packet, select_base_amount,
)

POLICY_VERSION = "fpa-bridge-1.0"
HARD_KINDS = ("raw_dollar", "entity_name", "company_name")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _account_type(category: str) -> str:
    c = (category or "").lower()
    if "revenue" in c:
        return "revenue"
    if "cogs" in c or "delivery" in c or "cost of" in c:
        return "cogs"
    return "opex"


def _build_model(payload: Dict[str, Any], period: str) -> CanonicalModel:
    facts: List[FinancialFact] = []
    for v in payload.get("variances", []):
        dept = str(v.get("department", "Department"))
        acct = str(v.get("account", "Account"))
        # Composite account keeps each FP&A line distinct; it is aliased to CAT_### so the real
        # name never reaches the model.
        line = f"{dept} / {acct}"
        atype = _account_type(v.get("category", ""))
        facts.append(FinancialFact("actual", period, line, atype, dept, _dec(v.get("actual"))))
        facts.append(FinancialFact("budget", period, line, atype, dept, _dec(v.get("budget"))))
    customers, vendors = [], []
    for c in payload.get("concentration", []):
        rec = Concentration(c.get("entity_type", "customer"), str(c.get("name", "Counterparty")), _dec(c.get("amount", 1)))
        (vendors if rec.entity_type == "vendor" else customers).append(rec)
    kpis = [KpiFact(str(k.get("name", "KPI")), period, _dec(k.get("actual")), _dec(k.get("budget", 0)),
                    str(k.get("unit", "")), bool(k.get("higher_is_better", True))) for k in payload.get("kpis", [])]
    return CanonicalModel(organization=str(payload.get("company", "Demo Co")), facts=facts,
                          kpis=kpis, customers=customers, vendors=vendors)


def fpa_commentary(payload: Dict[str, Any]) -> Dict[str, Any]:
    period = str(payload.get("period", "P01"))
    # Default to high_privacy so arbitrary FP&A account names are aliased (CAT_###), not passed through.
    privacy_mode = payload.get("privacy_mode", "high_privacy")
    viewer_role = payload.get("viewer_role", "cfo")
    requested_provider = payload.get("model_provider", "mock")

    model = _build_model(payload, period)
    variances = [classify_materiality(v, DEFAULT_RULES) for v in compute_variances(model, period)]
    base = select_base_amount(model, period)
    vault = AliasVault()
    packet, period_alias = build_packet(model, variances, period, vault,
                                        privacy_mode=privacy_mode, base_amount=base)

    # Forbidden-term set: the gateway's defaults PLUS every real account/department/company name,
    # marked entity-level so any leak HARD-blocks the send regardless of privacy mode.
    forbidden = build_forbidden_terms(model, privacy_mode)
    for name in model.accounts() + model.departments() + [model.organization]:
        if name:
            forbidden[name.strip().lower()] = "entity_name"

    risk = score_packet(packet, forbidden)
    hard = [l for l in scan_for_leaks(packet, forbidden) if l.kind in HARD_KINDS]
    packet_sha = hashlib.sha256(json.dumps(packet, sort_keys=True, default=str).encode()).hexdigest()

    proof: Dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "packet_sha256": packet_sha,
        "privacy_mode": privacy_mode,
        "risk_level": risk.level,
        "hard_leaks": len(hard),
        "raw_dollars_sent": bool(risk.signals.get("contains_raw_dollars", False)) or any(l.kind == "raw_dollar" for l in hard),
        "real_entities_sent": len(hard) > 0,
        "sent_to_model": False,
        "provider": "none",
        "model": "",
        "model_fallback": False,
        "validation_ok": None,
    }

    if hard or not can_send_packet(risk):
        proof["blocked"] = True
        return {"drafts": [], "executive_summary": "", "proof": proof,
                "outbound_packet": packet, "blocked_reason": "packet failed the privacy gate; nothing sent to the model"}

    client = get_client(requested_provider)
    provider = getattr(client, "provider", "?")
    model_name = getattr(client, "model", "?")
    fallback = False
    try:
        resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
    except Exception:  # real endpoint failure -> deterministic mock
        client = MockLLM()
        provider, model_name, fallback = client.provider, client.model, True
        resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
    if requested_provider in ("auto", "openai", "real") and provider == "mock":
        fallback = True  # real requested but no key configured

    vr = validate_response(resp, packet)
    proof.update({"sent_to_model": True, "provider": provider, "model": model_name,
                  "model_fallback": fallback, "validation_ok": vr.ok})

    perms = Permissions.for_role(viewer_role)
    period_inv = {alias: real for real, alias in period_alias.items()}
    rehydrated = rehydrate_response(resp, vault, perms, period_inv) if vr.ok else resp

    # Reproduce build_packet's ISSUE ordering to map drafts back to FP&A lines.
    ordered = sorted(variances, key=lambda x: x.contribution_to_total_variance_pct, reverse=True)
    issue_map: Dict[str, Any] = {}
    n = 1
    for it in ordered:
        if it.severity in ("high", "medium", "low"):
            issue_map[f"ISSUE_{n:03d}"] = it
            n += 1

    drafts = []
    for c in rehydrated.get("material_variance_commentary", []):
        it = issue_map.get(c.get("issue_id"))
        drafts.append({
            "issue_key": it.account if it else c.get("issue_id"),   # "Dept / Account" — FP&A matches on this
            "summary": c.get("summary", ""),
            "likely_drivers": c.get("likely_drivers", []),
            "recommended_action": c.get("recommended_action", ""),
            "forecast_adjustment": c.get("forecast_adjustment_recommendation", {}),
        })

    return {"drafts": drafts, "executive_summary": rehydrated.get("executive_summary", ""),
            "proof": proof, "outbound_packet": packet}
