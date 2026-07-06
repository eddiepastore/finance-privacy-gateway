"""End-to-end orchestrator: ingest -> calculate -> materiality -> obfuscate -> gate -> LLM ->
validate -> rehydrate -> review items -> board narrative. Emits an audit trail at every step.

This is the executable proof of the spec's core thesis (Section 32).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .finance_core import (
    CanonicalModel, classify_materiality, compute_variances, DEFAULT_RULES,
)
from .finance_core.calculations import VarianceItem
from .finance_core.forecast import forecast_adjustment_for
from .llm_client import SYSTEM_PROMPT, build_user_prompt, get_client, validate_response
from .obfuscation import (
    AliasVault, build_forbidden_terms, build_packet, can_send_packet, Permissions,
    rehydrate_response, score_packet, select_base_amount,
)
from .obfuscation.risk_scoring import RiskAssessment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_money(amount: Optional[Decimal]) -> str:
    if amount is None:
        return "n/a"
    a = float(abs(amount))
    sign = "-" if amount < 0 else ""
    if a >= 1_000_000:
        return f"{sign}${a/1_000_000:.1f}M"
    if a >= 1_000:
        return f"{sign}${a/1_000:.0f}K"
    return f"{sign}${a:,.0f}"


@dataclass
class PipelineResult:
    dataset_id: str
    period: str
    privacy_mode: str
    variances: List[VarianceItem]
    material_variances: List[VarianceItem]
    packet: Dict[str, Any]
    risk: RiskAssessment
    sent_to_llm: bool
    llm_provider: str
    llm_model: str
    llm_response_obfuscated: Optional[Dict[str, Any]]
    validation_ok: bool
    validation_errors: List[str]
    rehydrated_response: Optional[Dict[str, Any]]
    review_items: List[Dict[str, Any]]
    board_markdown: str
    audit_log: List[Dict[str, str]] = field(default_factory=list)


def _material_issue_map(variances: List[VarianceItem]) -> Dict[str, VarianceItem]:
    """Reproduce packet_builder's issue ordering to pair ISSUE_xxx ids with their VarianceItem."""
    ordered = sorted(variances, key=lambda x: x.contribution_to_total_variance_pct, reverse=True)
    mapping: Dict[str, VarianceItem] = {}
    n = 1
    for it in ordered:
        if it.severity in ("high", "medium", "low"):
            mapping[f"ISSUE_{n:03d}"] = it
            n += 1
    return mapping


def run_pipeline(
    model: CanonicalModel,
    period: str,
    *,
    dataset_id: str = "ds_local",
    privacy_mode: str = "generalized_semantic_labels",
    viewer_role: str = "cfo",
    abstract_periods: bool = True,
    llm_preference: str = "mock",
) -> PipelineResult:
    audit: List[Dict[str, str]] = []

    def log(action: str, detail: str = ""):
        audit.append({"ts": _now(), "actor": "system", "action": action, "detail": detail})

    log("calculation_run_created", f"period={period}")
    variances = compute_variances(model, period)
    for v in variances:
        classify_materiality(v, DEFAULT_RULES)
    material = [v for v in variances if v.severity in ("high", "medium", "low")]
    log("materiality_classified",
        f"{len(material)} material of {len(variances)} ({sum(1 for v in variances if v.severity=='high')} high)")

    vault = AliasVault(dataset_id=dataset_id)
    base = select_base_amount(model, period)
    packet, period_alias = build_packet(
        model, variances, period, vault,
        privacy_mode=privacy_mode, base_amount=base, abstract_periods=abstract_periods,
    )
    log("obfuscation_packet_generated", f"privacy_mode={privacy_mode}, base_hidden=True")

    forbidden = build_forbidden_terms(model, privacy_mode)
    risk = score_packet(packet, forbidden)
    log("packet_risk_scored", f"level={risk.level}, score={risk.score}, hard_leak={risk.has_hard_leak}")

    permissions = Permissions.for_role(viewer_role)
    period_alias_inverse = {v: k for k, v in period_alias.items()}
    issue_map = _material_issue_map(variances)

    sent = False
    llm_resp: Optional[Dict[str, Any]] = None
    rehydrated: Optional[Dict[str, Any]] = None
    validation_ok = False
    validation_errors: List[str] = []
    provider = "none"
    model_name = ""
    review_items: List[Dict[str, Any]] = []
    board_md = ""

    if not can_send_packet(risk):
        log("packet_gate_blocked", f"level={risk.level} — analysis withheld; use local-only mode")
    else:
        if risk.level == "high":
            log("packet_flagged_for_approval", "level=high — sent but flagged; tighten privacy mode if needed")
        client = get_client(llm_preference)
        provider = getattr(client, "provider", "unknown")
        model_name = getattr(client, "model", "")
        log("llm_request_sent", f"provider={provider}, model={model_name}")
        try:
            llm_resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
        except Exception as e:  # real endpoint failed -> fall back to deterministic mock
            from .llm_client import MockLLM
            log("llm_request_failed", f"{provider} error: {e}; falling back to mock")
            client = MockLLM()
            provider, model_name = client.provider, client.model
            llm_resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
        sent = True
        log("llm_response_received", "")

        vr = validate_response(llm_resp, packet)
        validation_ok, validation_errors = vr.ok, vr.errors
        log("response_validation", "passed" if vr.ok else f"failed: {vr.errors}")

        if vr.ok:
            rehydrated = rehydrate_response(llm_resp, vault, permissions, period_alias_inverse)
            log("rehydration_complete", f"viewer_role={viewer_role}")
            review_items = _build_review_items(rehydrated, issue_map, dataset_id)
            log("review_items_created", f"{len(review_items)} drafts (status=draft, unpublished)")
            board_md = build_board_markdown(model, period, rehydrated, issue_map, permissions)
            log("board_narrative_generated", "draft (uses local dollars; approval required to publish)")

    return PipelineResult(
        dataset_id=dataset_id, period=period, privacy_mode=privacy_mode,
        variances=variances, material_variances=material, packet=packet, risk=risk,
        sent_to_llm=sent, llm_provider=provider, llm_model=model_name, llm_response_obfuscated=llm_resp,
        validation_ok=validation_ok, validation_errors=validation_errors,
        rehydrated_response=rehydrated, review_items=review_items, board_markdown=board_md,
        audit_log=audit,
    )


def _build_review_items(rehydrated: Dict[str, Any], issue_map: Dict[str, VarianceItem],
                        dataset_id: str) -> List[Dict[str, Any]]:
    items = []
    for i, c in enumerate(rehydrated.get("material_variance_commentary", []), start=1):
        iid = c.get("issue_id")
        vi = issue_map.get(iid)
        local_facts = None
        if vi is not None:
            local_facts = {
                "account": vi.account,
                "department": vi.department,
                "variance_vs_budget": format_money(vi.variance_vs_budget_amount),
                "variance_vs_budget_pct": round(vi.variance_vs_budget_pct, 1) if vi.variance_vs_budget_pct is not None else None,
                "contribution_to_total_variance_pct": vi.contribution_to_total_variance_pct,
                "severity": vi.severity,
            }
        # The LLM recommends a direction; the dollar range is computed locally (spec Section 28).
        local_fa = None
        if vi is not None and c.get("forecast_adjustment_recommendation", {}).get("recommended"):
            fa = forecast_adjustment_for(vi)
            if fa:
                local_fa = {"direction": fa["direction"],
                            "range": f"{format_money(fa['low'])} to {format_money(fa['high'])} this quarter"}

        items.append({
            "review_item_id": f"rev_{i:03d}",
            "dataset_id": dataset_id,
            "issue_id": iid,
            "title": f"{(vi.account if vi else c.get('issue_id'))} variance commentary",
            "severity": vi.severity if vi else "medium",
            "status": "draft",
            "draft_text": c.get("summary", ""),
            "likely_drivers": c.get("likely_drivers", []),
            "management_questions": c.get("management_questions", []),
            "recommended_action": c.get("recommended_action", ""),
            "forecast_adjustment_recommendation": c.get("forecast_adjustment_recommendation", {}),
            "local_forecast_adjustment": local_fa,
            "local_facts": local_facts,
        })
    return items


def build_board_markdown(model: CanonicalModel, period: str, rehydrated: Dict[str, Any],
                         issue_map: Dict[str, VarianceItem], permissions: Permissions) -> str:
    lines: List[str] = [f"# Operating Review — {period}", ""]
    lines += ["## Executive Summary", "", rehydrated.get("executive_summary", ""), ""]

    lines += ["## Performance vs Plan", ""]
    for iid, vi in issue_map.items():
        if vi.severity not in ("high", "medium"):
            continue
        # Favorability already conveys direction, so show absolute magnitude.
        money = format_money(abs(vi.variance_vs_budget_amount)) if vi.variance_vs_budget_amount is not None else "n/a"
        pct = f"{abs(vi.variance_vs_budget_pct):.1f}%" if vi.variance_vs_budget_pct is not None else "n/a"
        lines.append(f"- **{vi.account}** ({vi.department}) was {vi.favorability} to budget by {money} ({pct}).")
    lines.append("")

    lines += ["## Key Variance Drivers", ""]
    for c in rehydrated.get("material_variance_commentary", []):
        if c.get("forecast_adjustment_recommendation", {}).get("recommended") or True:
            lines.append(f"- {c.get('summary','')}")
    lines.append("")

    fa = [c for c in rehydrated.get("material_variance_commentary", [])
          if c.get("forecast_adjustment_recommendation", {}).get("recommended")]
    if fa:
        lines += ["## Forecast Implications", ""]
        for c in fa:
            rec = c["forecast_adjustment_recommendation"]
            vi = issue_map.get(c.get("issue_id"))
            local = forecast_adjustment_for(vi) if vi is not None else None
            label = vi.account if vi is not None else c.get("issue_id")
            rng = (f" — local run-rate impact {format_money(local['low'])} to "
                   f"{format_money(local['high'])} this quarter") if local else ""
            lines.append(f"- **{label}**: recommend forecast {rec.get('direction')} — {rec.get('reason')}{rng}")
        lines.append("")

    lines += ["## Risks to Monitor", ""]
    for r in rehydrated.get("risks_to_monitor", []):
        lines.append(f"- ({r.get('severity')}) {r.get('risk')} — watch {r.get('watch_metric')}")
    lines.append("")

    lines += ["## Management Actions", ""]
    for c in rehydrated.get("material_variance_commentary", []):
        if c.get("recommended_action"):
            lines.append(f"- {c['recommended_action']}")
    lines.append("")

    lines += ["---", "_Draft. Every dollar figure is computed locally; the AI never received real "
              "financials. Requires human approval before publication._"]
    return "\n".join(lines)
