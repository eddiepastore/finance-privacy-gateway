"""Single source of truth for "what must never leave the building."

Used BOTH as the runtime packet gate (risk_scoring) AND as the privacy-regression test oracle
(tests/test_privacy_regression.py). Unifying them means enforcement and tests can never drift apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List

# Comma-grouped money (1,234,567), explicit currency symbols, or long bare digit runs (>=6 digits ~ raw $).
_MONEY_RE = re.compile(r"\$|\b\d{1,3}(?:,\d{3})+\b|\b\d{6,}\b")


def _contains_term(haystack_lower: str, term: str) -> bool:
    """Word-boundary-ish containment so a proper noun can't match inside an unrelated word."""
    idx = haystack_lower.find(term)
    while idx != -1:
        before = haystack_lower[idx - 1] if idx > 0 else " "
        after_pos = idx + len(term)
        after = haystack_lower[after_pos] if after_pos < len(haystack_lower) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        idx = haystack_lower.find(term, idx + 1)
    return False
# Numeric threshold above which a bare number cannot be an index point/percent/count we legitimately send.
_NUMERIC_DOLLAR_THRESHOLD = Decimal("10000")


@dataclass(frozen=True)
class Leak:
    kind: str        # raw_dollar | entity_name | company_name | department_name | account_name | memo
    path: str        # JSON-ish path to the offending node
    sample: str      # what was found


def build_forbidden_terms(model, privacy_mode: str = "generalized_semantic_labels") -> Dict[str, str]:
    """Map of lowercased real string -> leak kind.

    Only HIGH-SPECIFICITY identifiers are listed — the spec's Section 4 hard guarantees: company name,
    customer/vendor/bank proper nouns, plus raw-dollar detection (handled numerically in _walk).

    We deliberately do NOT scan for generic account/department *words* (e.g. "sales", "travel"):
      - departments are always aliased to DEPT_xxx in the packet (enforced by packet_builder), and
      - generalized account labels are *meant* to retain semantic meaning (Mode B), so a label like
        "Travel & Entertainment" is safe-by-design and must not be flagged just because it contains
        a real account word. Account generalization is guaranteed by construction and covered by
        test_obfuscation, not by noisy substring scanning here.
    """
    terms: Dict[str, str] = {}

    if model.organization:
        terms[model.organization.strip().lower()] = "company_name"
        # distinctive leading token (e.g. "Northstar") catches partial company leaks
        first_token = model.organization.strip().split(",")[0].split()[0].lower()
        if len(first_token) >= 4:
            terms[first_token] = "company_name"

    for c in model.customers:
        terms[c.name.strip().lower()] = "entity_name"
    for v in model.vendors:
        terms[v.name.strip().lower()] = "entity_name"

    # Never leak obvious bank identifiers even if absent from this dataset.
    for bank in ("chase", "bank of america", "wells fargo", "first republic", "silicon valley bank"):
        terms[bank] = "entity_name"

    return terms


def _walk(node: Any, path: str, forbidden: Dict[str, str], leaks: List[Leak]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, f"{path}.{k}", forbidden, leaks)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", forbidden, leaks)
    elif isinstance(node, str):
        low = node.lower()
        for term, kind in forbidden.items():
            if term and _contains_term(low, term):
                leaks.append(Leak(kind=kind, path=path, sample=node[:80]))
        if _MONEY_RE.search(node):
            leaks.append(Leak(kind="raw_dollar", path=path, sample=node[:80]))
    elif isinstance(node, (int, float, Decimal)) and not isinstance(node, bool):
        if abs(Decimal(str(node))) >= _NUMERIC_DOLLAR_THRESHOLD:
            leaks.append(Leak(kind="raw_dollar", path=path, sample=str(node)))


def scan_for_leaks(obj: Any, forbidden_terms: Dict[str, str]) -> List[Leak]:
    """Recursively scan any JSON-able object for forbidden terms and raw dollar patterns."""
    leaks: List[Leak] = []
    _walk(obj, "$", forbidden_terms, leaks)
    return leaks
