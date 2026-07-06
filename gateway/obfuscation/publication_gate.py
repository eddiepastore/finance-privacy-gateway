"""Audience-aware publication safety gate for local/rehydrated outputs.

The outbound model gate protects data leaving for the LLM. This module protects downstream
human-facing exports (board narratives, packets, commentary) from reviewer-entered sensitive terms.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .leak_scanner import scan_for_leaks

POLICY_VERSION = "privacy_policy_v1.0"


def _contains_boundary(text: str, term: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _replacement_terms(model) -> List[Tuple[str, str, str]]:
    terms: List[Tuple[str, str, str]] = []
    if getattr(model, "organization", None):
        org = model.organization.strip()
        terms.append((org, "company_name", "the Company"))
        first = org.split(",")[0].split()[0]
        if len(first) >= 4:
            terms.append((first, "company_name", "the Company"))
    for i, c in enumerate(getattr(model, "customers", []) or [], start=1):
        terms.append((c.name.strip(), "entity_name", f"Top Customer {i}"))
    for i, v in enumerate(getattr(model, "vendors", []) or [], start=1):
        terms.append((v.name.strip(), "entity_name", f"Key Vendor {i}"))
    for bank in ("Chase", "Bank of America", "Wells Fargo", "First Republic", "Silicon Valley Bank"):
        terms.append((bank, "entity_name", "Primary Bank"))
    # Prefer longer replacements first so "Northstar Health" wins before "Northstar".
    return sorted([t for t in terms if t[0]], key=lambda t: len(t[0]), reverse=True)


def assess_publication_safety(markdown: str, model, audience: str = "board") -> Dict[str, Any]:
    """Return publication gate status plus a redacted safe markdown alternative.

    Board/CFO narratives may intentionally include local dollars, but real counterparties and company
    names are flagged. Less privileged audiences also flag raw dollar-like values.
    """
    audience = (audience or "board").lower()
    allow_local_dollars = audience in {"board", "cfo", "admin", "fpa_director"}
    forbidden = {term.lower(): kind for term, kind, _ in _replacement_terms(model)}
    leaks = scan_for_leaks({"markdown": markdown}, forbidden)
    findings = []
    for leak in leaks:
        if leak.kind == "raw_dollar" and allow_local_dollars:
            continue
        findings.append({"kind": leak.kind, "path": leak.path, "sample": leak.sample})

    safe = markdown
    for term, _kind, repl in _replacement_terms(model):
        if _contains_boundary(safe, term):
            safe = re.sub(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", repl, safe, flags=re.IGNORECASE)

    return {
        "policy_version": POLICY_VERSION,
        "audience": audience,
        "status": "needs_redaction" if findings else "safe_for_publication",
        "allows_local_dollars": allow_local_dollars,
        "findings": findings,
        "safe_markdown": safe,
    }
