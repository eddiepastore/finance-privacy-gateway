"""Deterministic mock LLM (spec Section 7.8 'Mock LLM for demo and tests').

Produces schema-valid commentary from the obfuscated packet WITHOUT network access. It references
only synthetic identifiers and percentages already present in the packet, and never emits currency.
This makes the entire pipeline reproducible and CI-able. A real OpenAI-compatible client (client.py)
is a drop-in replacement.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _direction_phrase(direction: str) -> str:
    return {
        "unfavorable": "came in unfavorable to plan",
        "favorable": "came in favorable to plan",
        "neutral": "was in line with plan",
    }.get(direction, "moved versus plan")


def _forecast_rec(item: Dict[str, Any]) -> Dict[str, Any]:
    sev = item.get("severity")
    direction = item.get("variance_direction")
    if sev == "high" and direction == "unfavorable":
        return {
            "recommended": True,
            "direction": "decrease" if item.get("category", "").lower().startswith("revenue") else "increase",
            "reason": "Material unfavorable variance suggests the current plan assumption needs revision.",
        }
    return {"recommended": False, "direction": "unchanged",
            "reason": "Variance is within a range that does not yet warrant a reforecast."}


class MockLLM:
    provider = "mock"
    model = "mock-fp&a-analyst-v1"

    def complete(self, system_prompt: str, user_prompt: str, packet: Dict[str, Any]) -> Dict[str, Any]:
        material: List[Dict[str, Any]] = packet.get("material_items", [])
        kpis: List[Dict[str, Any]] = packet.get("kpis", [])

        commentary = []
        for it in material:
            pct = it.get("variance_vs_budget_pct")
            pct_txt = f"{pct:.1f}% vs budget" if isinstance(pct, (int, float)) else "a notable amount vs budget"
            cat = it.get("category", "this area")
            commentary.append({
                "issue_id": it["item_id"],
                "summary": f"{cat} in {it.get('department')} {_direction_phrase(it.get('variance_direction',''))} "
                           f"by {pct_txt}, contributing {it.get('contribution_to_total_variance_pct', 0)}% of total variance.",
                "likely_drivers": _drivers_for(it),
                "management_questions": _questions_for(it),
                "recommended_action": "Confirm the driver with the owning team and decide whether a reforecast is needed.",
                "forecast_adjustment_recommendation": _forecast_rec(it),
            })

        kpi_lines = [
            f"{k['name']} is {k.get('trend','').replace('_',' ')} ({k.get('variance_vs_budget_pct')}% vs budget)"
            for k in kpis if k.get("materiality") in ("high", "medium")
        ]

        top_issue = material[0]["category"] if material else "performance"
        conc = packet.get("customer_concentration", [])
        conc_line = ""
        if conc:
            conc_line = (f" Customer concentration is a watch item: {conc[0]['label']} represents "
                         f"{conc[0]['revenue_pct']}% of revenue.")
        exec_summary = (
            f"The period shows {len([m for m in material if m['severity']=='high'])} high-severity and "
            f"{len([m for m in material if m['severity']=='medium'])} medium-severity variances. "
            f"The largest driver is {top_issue}. "
            + ("Leading indicators to watch: " + "; ".join(kpi_lines) + "." if kpi_lines else "")
            + conc_line
        )

        board_draft = _board_draft(material, kpi_lines) + conc_line

        return {
            "executive_summary": exec_summary.strip(),
            "material_variance_commentary": commentary,
            "board_narrative": {"tone": "board_ready", "draft": board_draft},
            "risks_to_monitor": _risks(material, kpis, conc),
            "open_questions": _open_questions(material),
        }


def _drivers_for(item: Dict[str, Any]) -> List[str]:
    cat = item.get("category", "").lower()
    if "revenue" in cat:
        return ["below-plan commercial activity or bookings timing", "possible renewal or conversion slipping out of period"]
    if "people" in cat or "talent" in cat:
        return ["headcount or hiring pace differing from plan"]
    if "infrastructure" in cat or "technical" in cat:
        return ["usage growth or unoptimized consumption above plan"]
    if "demand generation" in cat or "marketing" in cat:
        return ["campaign timing differences versus plan"]
    return ["timing or volume difference versus plan"]


def _questions_for(item: Dict[str, Any]) -> List[str]:
    return [
        f"What specifically drove the {item.get('category')} variance in {item.get('department')}?",
        "Is this timing-related or a structural change to the run-rate?",
    ]


def _board_draft(material: List[Dict[str, Any]], kpi_lines: List[str]) -> str:
    highs = [m for m in material if m["severity"] == "high"]
    parts = ["Performance versus plan was mixed for the period."]
    if highs:
        cats = ", ".join(sorted({m["category"] for m in highs}))
        parts.append(f"The most material drivers were concentrated in {cats}.")
    if kpi_lines:
        parts.append("Leading indicators worth board attention include " + "; ".join(kpi_lines) + ".")
    parts.append("Management is reviewing whether affected lines require a reforecast.")
    return " ".join(parts)


def _risks(material: List[Dict[str, Any]], kpis: List[Dict[str, Any]],
           concentration: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    risks = []
    for m in material:
        if m["severity"] == "high":
            risks.append({
                "risk": f"Continued unfavorable trend in {m['category']}",
                "severity": "high" if m["variance_direction"] == "unfavorable" else "medium",
                "watch_metric": m["category"],
            })
    for k in kpis:
        if k.get("materiality") == "high":
            risks.append({"risk": f"{k['name']} tracking below plan", "severity": "high", "watch_metric": k["name"]})
    if concentration:
        risks.append({"risk": f"Revenue concentration in {concentration[0]['label']} "
                              f"({concentration[0]['revenue_pct']}%)",
                      "severity": "medium", "watch_metric": concentration[0]["label"]})
    return risks or [{"risk": "No material risks identified", "severity": "low", "watch_metric": "n/a"}]


def _open_questions(material: List[Dict[str, Any]]) -> List[str]:
    qs = ["Which variances are timing versus structural?"]
    if any("revenue" in m.get("category", "").lower() for m in material):
        qs.append("Does the revenue shortfall change the full-year outlook?")
    return qs
