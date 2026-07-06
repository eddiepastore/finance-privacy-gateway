"""Service layer: the nine Section-15 operations over the gateway core.

The CanonicalModel is rebuilt deterministically from the dataset's uploaded files on each step
(aliasing is insertion-order stable), so obfuscation and rehydration stay consistent without ever
serializing the alias vault.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..finance_core import classify_materiality, compute_variances, DEFAULT_RULES, load_package
from ..finance_core.forecast import forecast_adjustment_for
from ..llm_client import SYSTEM_PROMPT, build_user_prompt, get_client, validate_response
from ..obfuscation import (
    AliasVault, build_forbidden_terms, build_packet, can_send_packet, Permissions,
    rehydrate_response, scan_for_leaks, score_packet, select_base_amount,
)
from ..obfuscation.rehydration import rehydrate_text
from ..obfuscation.publication_gate import POLICY_VERSION, assess_publication_safety
from ..obfuscation.aliases import generalize_account
from ..pipeline import _material_issue_map, format_money
from ..web.api import build_preview_rows
from .repository import Repository

FILE_TYPE_TO_NAME = {
    "actuals": "actuals.csv", "budget": "budget.csv", "forecast": "forecast.csv",
    "kpi": "kpis.csv", "customer": "customers.csv", "vendor": "vendors.csv",
}


def apply_mapping(content: str, mapping: Dict[str, str]) -> str:
    """Rewrite the CSV header row using {source_header: canonical_field}."""
    rows = list(csv.reader(io.StringIO(content)))
    if not rows:
        return content
    rows[0] = [mapping.get(h, h) for h in rows[0]]
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


def detect_columns(content: str) -> (int, List[str]):
    rows = list(csv.reader(io.StringIO(content)))
    if not rows:
        return 0, []
    return max(0, len(rows) - 1), rows[0]


class ApiService:
    def __init__(self, repo: Repository):
        self.repo = repo

    # --- model rebuild -----------------------------------------------------------------------
    def _build_model(self, dataset_id: str):
        ds = self.repo.get_dataset(dataset_id)
        tmp = tempfile.mkdtemp(prefix="gw_ds_")
        try:
            for f in self.repo.files(dataset_id):
                name = FILE_TYPE_TO_NAME.get(f["file_type"])
                if not name:
                    continue
                content = f["content"]
                mapping = self.repo.mapping_for(f["id"])
                if mapping:
                    content = apply_mapping(content, mapping)
                with open(os.path.join(tmp, name), "w", newline="") as fh:
                    fh.write(content)
            with open(os.path.join(tmp, "company.txt"), "w") as fh:
                fh.write((ds.get("company_name") or ds["name"]) + "\n")
            return load_package(tmp)
        finally:
            for fn in os.listdir(tmp):
                os.remove(os.path.join(tmp, fn))
            os.rmdir(tmp)

    def _variances(self, model, period):
        return [classify_materiality(v, DEFAULT_RULES) for v in compute_variances(model, period)]

    @staticmethod
    def _require_data(model, period):
        if not model.facts:
            raise ValueError("no financial data uploaded for this dataset")
        if period not in model.periods():
            raise ValueError(f"no data for reporting period {period}; available: {model.periods()}")

    # --- operations --------------------------------------------------------------------------
    def create_dataset(self, name, reporting_period, privacy_mode, company_name=None):
        return self.repo.create_dataset(name, reporting_period, privacy_mode, company_name)

    def upload_file(self, dataset_id, file_type, filename, content):
        rows, cols = detect_columns(content)
        return self.repo.add_file(dataset_id, file_type, filename, content, rows, cols)

    def save_mapping(self, dataset_id, file_id, mapping):
        self.repo.save_mapping(dataset_id, file_id, mapping)
        return {"status": "mapping_saved", "validation_errors": []}

    def _resolve_period(self, ds, period):
        return period or ds["reporting_period"]

    def _rebuild_vault(self, dataset_id, period):
        """Rebuild the deterministic alias vault + period inverse for a dataset/period (for view-time
        rehydration). Aliasing is insertion-order stable, so this matches the analysis-time vault."""
        ds = self.repo.get_dataset(dataset_id)
        model = self._build_model(dataset_id)
        variances = self._variances(model, period)
        base = select_base_amount(model, period)
        vault = AliasVault()
        _, period_alias = build_packet(model, variances, period, vault,
                                       privacy_mode=ds["privacy_mode"], base_amount=base)
        return vault, {v: k for k, v in period_alias.items()}

    def calculate(self, dataset_id, period=None):
        ds = self.repo.get_dataset(dataset_id)
        period = self._resolve_period(ds, period)
        model = self._build_model(dataset_id)
        self._require_data(model, period)
        variances = self._variances(model, period)
        material = [v for v in variances if v.severity in ("high", "medium", "low")]
        summary = {
            "period": period,
            "material_issues": len(material),
            "high_severity_issues": sum(1 for v in variances if v.severity == "high"),
            "medium_severity_issues": sum(1 for v in variances if v.severity == "medium"),
        }
        cid = self.repo.add_calculation_run(dataset_id, summary)
        self.repo.set_dataset_status(dataset_id, "calculated")
        return {"calculation_run_id": cid, "status": "completed", "summary": summary}

    def obfuscate(self, dataset_id, calculation_run_id=None, privacy_mode=None, period=None):
        ds = self.repo.get_dataset(dataset_id)
        period = self._resolve_period(ds, period)
        privacy_mode = privacy_mode or ds["privacy_mode"]
        model = self._build_model(dataset_id)
        self._require_data(model, period)
        variances = self._variances(model, period)
        base = select_base_amount(model, period)
        packet, _ = build_packet(model, variances, period, AliasVault(),
                                 privacy_mode=privacy_mode, base_amount=base)
        forbidden = build_forbidden_terms(model, privacy_mode)
        risk = score_packet(packet, forbidden)
        oid = self.repo.add_obfuscation_run(
            dataset_id, calculation_run_id, privacy_mode, risk.level, risk.score,
            risk.signals["contains_raw_dollars"], risk.signals["contains_real_entity_names"],
            packet, period=period)
        return {
            "obfuscation_run_id": oid, "period": period, "risk_score": risk.level,
            "raw_dollars_sent": risk.signals["contains_raw_dollars"],
            "real_entities_sent": risk.signals["contains_real_entity_names"],
            "packet_preview_available": True,
        }

    def analyze(self, dataset_id, obfuscation_run_id, viewer_role="cfo", llm_preference="mock", period=None):
        ds = self.repo.get_dataset(dataset_id)
        obf = self.repo.get_obfuscation_run(obfuscation_run_id)
        privacy_mode = obf["privacy_mode"]
        period = obf.get("period") or self._resolve_period(ds, period)

        # Rebuild model + packet deterministically (vault is captured but review text is stored OBFUSCATED
        # and rehydrated per-viewer at read time — spec Section 12.4).
        model = self._build_model(dataset_id)
        variances = self._variances(model, period)
        base = select_base_amount(model, period)
        vault = AliasVault()
        packet, period_alias = build_packet(model, variances, period, vault,
                                            privacy_mode=privacy_mode, base_amount=base)
        forbidden = build_forbidden_terms(model, privacy_mode)
        risk = score_packet(packet, forbidden)

        if not can_send_packet(risk):
            aid = self.repo.add_analysis_run(dataset_id, obfuscation_run_id, "none", "", "blocked",
                                             None, {}, period=period)
            self.repo.log(dataset_id, "packet_gate_blocked", f"level={risk.level}")
            return {"analysis_run_id": aid, "status": "blocked", "review_items_created": 0,
                    "risk_level": risk.level}

        client = get_client(llm_preference)
        provider, model_name = getattr(client, "provider", "?"), getattr(client, "model", "?")
        if llm_preference in ("auto", "openai") and provider == "mock":
            model_name = f"{model_name} requested:{llm_preference}"
        self.repo.log(dataset_id, "llm_request_sent", f"provider={provider} model={model_name}")
        try:
            resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
        except Exception as e:  # real endpoint failed -> deterministic mock fallback
            from ..llm_client import MockLLM
            self.repo.log(dataset_id, "llm_request_failed", f"{provider} error: {e}; falling back to mock")
            client = MockLLM()
            provider, model_name = client.provider, f"{client.model} requested:{llm_preference}"
            resp = client.complete(SYSTEM_PROMPT, build_user_prompt(packet), packet)
        vr = validate_response(resp, packet)
        self.repo.log(dataset_id, "response_validation", "passed" if vr.ok else f"failed:{vr.errors}")

        # Store the OBFUSCATED response; rehydration happens per-viewer on read.
        aid = self.repo.add_analysis_run(
            dataset_id, obfuscation_run_id, provider, model_name, "completed", vr.ok, resp, period=period)

        created = 0
        if vr.ok:
            self.repo.delete_review_items(dataset_id, period)  # idempotent re-analysis of a period
            issue_map = _material_issue_map(variances)
            for c in resp.get("material_variance_commentary", []):
                vi = issue_map.get(c.get("issue_id"))
                local_facts = None
                local_fa = None
                if vi is not None:
                    local_facts = {
                        "account": vi.account, "department": vi.department,
                        "favorability": vi.favorability,
                        "variance_vs_budget": format_money(abs(vi.variance_vs_budget_amount))
                            if vi.variance_vs_budget_amount is not None else "n/a",
                        "variance_vs_budget_pct": round(vi.variance_vs_budget_pct, 1)
                            if vi.variance_vs_budget_pct is not None else None,
                        "contribution_to_total_variance_pct": vi.contribution_to_total_variance_pct,
                        "severity": vi.severity,
                    }
                    if c.get("forecast_adjustment_recommendation", {}).get("recommended"):
                        fa = forecast_adjustment_for(vi)
                        if fa:
                            local_fa = {"direction": fa["direction"],
                                        "range": f"{format_money(fa['low'])} to {format_money(fa['high'])} this quarter"}
                self.repo.add_review_item(dataset_id, aid, {
                    "issue_id": c.get("issue_id"),
                    "title": f"{(vi.account if vi else c.get('issue_id'))} variance commentary",
                    "severity": vi.severity if vi else "medium",
                    "draft_text": c.get("summary", ""),
                    "likely_drivers": c.get("likely_drivers", []),
                    "management_questions": c.get("management_questions", []),
                    "recommended_action": c.get("recommended_action", ""),
                    "forecast_adjustment_recommendation": c.get("forecast_adjustment_recommendation", {}),
                    "local_forecast_adjustment": local_fa,
                    "local_facts": local_facts,
                }, period=period)
                created += 1
            self.repo.set_dataset_status(dataset_id, "analyzed")

        return {"analysis_run_id": aid, "status": "completed" if vr.ok else "validation_failed",
                "review_items_created": created, "validation_ok": vr.ok}

    def list_review_items(self, dataset_id, role="cfo", period=None):
        items = self.repo.review_items(dataset_id, period)
        if not items:
            return {"review_items": []}
        # View-time rehydration: stored text is OBFUSCATED; rehydrate per requested role here.
        item_period = period or items[0].get("period")
        vault, period_inv = self._rebuild_vault(dataset_id, item_period)
        perms = Permissions.for_role(role)

        def rh(s):
            return rehydrate_text(s, vault, perms, period_inv) if isinstance(s, str) else s

        out = []
        for it in items:
            ex = it["extra"]
            # approved_text was stored already-rehydrated for the approver; show as-is. Drafts rehydrate now.
            draft = rh(it["draft_text"])
            approved = it["approved_text"]
            out.append({
                "review_item_id": it["id"], "issue_id": it["issue_id"], "title": it["title"],
                "status": it["status"], "severity": it["severity"],
                "draft_text": draft, "approved_text": approved,
                "likely_drivers": [rh(d) for d in ex.get("likely_drivers", [])],
                "management_questions": [rh(q) for q in ex.get("management_questions", [])],
                "recommended_action": ex.get("recommended_action", ""),
                "forecast_adjustment_recommendation": ex.get("forecast_adjustment_recommendation", {}),
                "local_facts": ex.get("local_facts"),
                "local_forecast_adjustment": ex.get("local_forecast_adjustment"),
            })
        severity_rank = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda r: (
            severity_rank.get(r.get("severity"), 9),
            -float((r.get("local_facts") or {}).get("contribution_to_total_variance_pct") or 0),
            0 if ((r.get("local_facts") or {}).get("favorability") == "unfavorable") else 1,
            r.get("title") or "",
        ))
        return {"review_items": out}

    def approve(self, review_item_id, approved_text, reviewer_id, role="cfo"):
        # If no edited text supplied, store the draft rehydrated for the approver's role.
        if approved_text is None:
            item = self.repo.get_review_item(review_item_id)
            if not item:
                return None
            vault, period_inv = self._rebuild_vault(item["dataset_id"], item.get("period"))
            approved_text = rehydrate_text(item["draft_text"], vault, Permissions.for_role(role), period_inv)
        return self.repo.approve_review_item(review_item_id, approved_text, reviewer_id)

    def request_revision(self, review_item_id, reason, reviewer_id):
        return self.repo.request_revision_review_item(review_item_id, reason or "", reviewer_id)

    def run_pipeline_steps(self, dataset_id, viewer_role="cfo", llm_preference="mock", period=None,
                           privacy_mode=None):
        """Convenience: calculate -> obfuscate -> analyze in one call (for the UI 'run' button)."""
        if privacy_mode:
            self.repo.set_dataset_privacy_mode(dataset_id, privacy_mode)
        calc = self.calculate(dataset_id, period=period)
        obf = self.obfuscate(dataset_id, calc["calculation_run_id"], privacy_mode=privacy_mode, period=period)
        an = self.analyze(dataset_id, obf["obfuscation_run_id"],
                          viewer_role=viewer_role, llm_preference=llm_preference, period=period)
        return {"calculation": calc, "obfuscation": obf, "analysis": an}

    def seed_sample_dataset(self, sample_dir, privacy_mode="generalized_semantic_labels",
                            name="Sample — March Operating Review", viewer_role="cfo",
                            llm_preference="mock"):
        """Create a dataset from the bundled sample CSVs and run the full pipeline."""
        company = name
        cpath = os.path.join(sample_dir, "company.txt")
        if os.path.exists(cpath):
            with open(cpath) as fh:
                company = fh.read().strip()
        ds = self.create_dataset(name, "2026-03", privacy_mode, company)
        did = ds["id"]
        for ftype, fname in [("actuals", "actuals.csv"), ("budget", "budget.csv"),
                             ("forecast", "forecast.csv"), ("kpi", "kpis.csv"),
                             ("customer", "customers.csv"), ("vendor", "vendors.csv")]:
            path = os.path.join(sample_dir, fname)
            if os.path.exists(path):
                with open(path) as fh:
                    self.upload_file(did, ftype, fname, fh.read())
        self.run_pipeline_steps(did, viewer_role=viewer_role, llm_preference=llm_preference)
        return {"dataset_id": did}

    def dashboard_payload(self, dataset_id, role="cfo", period=None):
        """Reconstruct the dashboard view (same shape as the stateless web payload) from persisted state."""
        ds = self.repo.get_dataset(dataset_id)
        if not ds:
            raise ValueError("dataset not found")
        model = self._build_model(dataset_id)
        period = self._resolve_period(ds, period)
        self._require_data(model, period)
        variances = self._variances(model, period)

        obf = self.repo.latest_obfuscation_run(dataset_id, period)
        an = self.repo.latest_analysis_run(dataset_id, period)
        packet = json.loads(obf["packet_json"]) if obf else {}
        packet_blob = json.dumps(packet, sort_keys=True, separators=(",", ":")) if packet else ""
        model_fallback = bool(an and an["provider"] == "mock" and "requested:auto" in (an["model"] or ""))
        model_message = (
            "Mock fallback used — real OpenAI-compatible model was requested but is not configured or failed."
            if model_fallback else
            f"Using {an['provider']} · {an['model']}" if an else "No model run yet"
        )
        forbidden = build_forbidden_terms(model, ds["privacy_mode"])
        hard = [l for l in scan_for_leaks(packet, forbidden)
                if l.kind in ("raw_dollar", "entity_name", "company_name")] if packet else []

        material = sorted([v for v in variances if v.severity in ("high", "medium", "low")],
                          key=lambda x: x.contribution_to_total_variance_pct, reverse=True)
        var_rows = [{
            "severity": v.severity, "account": v.account, "department": v.department,
            "favorability": v.favorability,
            "variance": format_money(abs(v.variance_vs_budget_amount)) if v.variance_vs_budget_amount is not None else "n/a",
            "variance_pct": round(v.variance_vs_budget_pct, 1) if v.variance_vs_budget_pct is not None else None,
            "contribution_pct": v.contribution_to_total_variance_pct,
        } for v in material]

        board = self.repo.latest_board_narrative(dataset_id, period)
        board_markdown = board["markdown"] if board else ""
        publication = assess_publication_safety(board_markdown, model, audience=role) if board_markdown else {
            "policy_version": POLICY_VERSION, "audience": role, "status": "not_generated",
            "allows_local_dollars": role in {"board", "cfo", "admin", "fpa_director"}, "findings": [], "safe_markdown": "",
        }
        return {
            "dataset_id": dataset_id,
            "company": ds.get("company_name") or ds["name"],
            "period": period,
            "available_periods": model.periods(),
            "privacy_mode": ds["privacy_mode"],
            "role": role,
            "persisted": True,
            "gate": {
                "risk_level": obf["risk_level"] if obf else "n/a",
                "risk_score": obf["risk_score"] if obf else 0,
                "hard_leaks": len(hard),
                "raw_dollars_sent": bool(obf["raw_dollars_sent"]) if obf else False,
                "real_entities_sent": bool(obf["real_entities_sent"]) if obf else False,
                "sent_to_llm": bool(an and an["status"] == "completed"),
                "llm_provider": an["provider"] if an else "none",
                "llm_model": an["model"] if an else "",
                "model_fallback": model_fallback,
                "model_status_message": model_message,
                "validation_ok": bool(an and an["validation_ok"]),
                "validation_errors": [],
            },
            "packet_meta": {
                "policy_version": POLICY_VERSION,
                "run_id": obf["id"] if obf else "",
                "created_at": obf["created_at"] if obf else "",
                "packet_sha256": hashlib.sha256(packet_blob.encode("utf-8")).hexdigest() if packet_blob else "",
                "model_provider": an["provider"] if an else "none",
                "model_name": an["model"] if an else "",
            },
            "preview": build_preview_rows(
                model, period, ds["privacy_mode"],
                self._rebuild_vault(dataset_id, period)[0], packet) if packet else [],
            "variances": var_rows,
            "packet": packet,
            "review_items": self.list_review_items(dataset_id, role=role, period=period)["review_items"],
            "board_markdown": board_markdown,
            "publication_gate": {k: v for k, v in publication.items() if k != "safe_markdown"},
            "safe_board_markdown": publication.get("safe_markdown", ""),
            "audit_log": self.repo.audit(dataset_id),
        }

    def board_narrative(self, dataset_id, include_only_approved=True, audience="board",
                        tone="concise_board_ready", period=None):
        ds = self.repo.get_dataset(dataset_id)
        period = self._resolve_period(ds, period)
        model = self._build_model(dataset_id)
        items = self.repo.review_items(dataset_id, period)
        if include_only_approved:
            items = [i for i in items if i["status"] == "approved"]
        # Rehydrate obfuscated drafts for the audience; approved_text is already in real terms.
        if items:
            vault, period_inv = self._rebuild_vault(dataset_id, period)
            perms = Permissions.for_role(audience)
            for it in items:
                if not it["approved_text"]:
                    it["draft_text"] = rehydrate_text(it["draft_text"], vault, perms, period_inv)
        markdown = _board_markdown(period, items, audience, include_only_approved)
        gate = assess_publication_safety(markdown, model, audience=audience)
        bid = self.repo.add_board_narrative(dataset_id, audience, markdown, period=period)
        self.repo.log(dataset_id, "publication_gate_checked",
                      f"period={period} audience={audience} status={gate['status']} findings={len(gate['findings'])}")
        return {"board_narrative_id": bid, "status": "draft", "markdown": markdown,
                "publication_gate": {k: v for k, v in gate.items() if k != "safe_markdown"},
                "safe_markdown": gate["safe_markdown"]}


def _board_markdown(period: str, items: List[Dict[str, Any]], audience: str, only_approved: bool) -> str:
    def text(i):
        return i["approved_text"] or i["draft_text"]

    highs = [i for i in items if (i.get("severity") == "high")]
    lines = [f"# Operating Review — {period}", "", "## Executive Summary", ""]
    if items:
        lines.append(f"This {audience} narrative reflects {len(items)} "
                     f"{'approved ' if only_approved else ''}items, including {len(highs)} high-severity. "
                     f"The most material driver is {items[0]['title'].replace(' variance commentary','')}.")
    else:
        lines.append("No items selected. Approve review items before generating the board narrative.")
    lines += ["", "## Performance vs Plan", ""]
    for i in items:
        lf = (i["extra"].get("local_facts") if "extra" in i else None) or {}
        if lf:
            lines.append(f"- **{lf.get('account')}** ({lf.get('department')}) was {lf.get('favorability')} "
                         f"to budget by {lf.get('variance_vs_budget')} ({lf.get('variance_vs_budget_pct')}%).")
    lines += ["", "## Key Variance Drivers", ""]
    for i in items:
        lines.append(f"- {text(i)}")
    fa_items = [i for i in items if (i["extra"].get("local_forecast_adjustment") if "extra" in i else None)]
    if fa_items:
        lines += ["", "## Forecast Implications", ""]
        for i in fa_items:
            fa = i["extra"]["local_forecast_adjustment"]
            lines.append(f"- **{i['title'].replace(' variance commentary','')}**: forecast {fa['direction']} "
                         f"— local run-rate impact {fa['range']}.")
    lines += ["", "## Risks to Monitor", ""]
    for i in highs:
        lines.append(f"- (high) Continued unfavorable trend in {i['title'].replace(' variance commentary','')}.")
    lines += ["", "## Management Actions", ""]
    for i in items:
        ra = i["extra"].get("recommended_action") if "extra" in i else None
        if ra:
            lines.append(f"- {ra}")
    lines += ["", "---", "_Every dollar is computed locally; the AI never received real financials. "
              "Requires approval before publication._"]
    return "\n".join(lines)
