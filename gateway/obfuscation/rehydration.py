"""Rehydration engine (spec Sections 7.10, 12, 17.7).

Converts synthetic LLM output back into business terms for AUTHORIZED users. Real dollar values are
inserted by the caller from local calculations only — the LLM's text never carries real numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

from .aliases import AliasVault

_SYNTH_RE = re.compile(r"\b(?:CAT|VENDOR|CLIENT|DEPT|BANK|BANK_ACCOUNT|CC|KPI)_\d{3}\b")
_PERIOD_RE = re.compile(r"\bP(\d{2})\b")


@dataclass
class Permissions:
    """What real entity types a given user/audience may see. Unviewable types get a safe label."""
    role: str = "cfo"
    viewable: Set[str] = field(default_factory=lambda: {"account", "department", "vendor", "customer", "bank"})
    audience: str = "internal"   # internal | board

    @classmethod
    def for_role(cls, role: str) -> "Permissions":
        role = role.lower()
        presets = {
            "cfo":   {"account", "department", "vendor", "customer", "bank"},
            "admin": {"account", "department", "vendor", "customer", "bank"},
            "fpa_director": {"account", "department", "vendor", "customer"},
            "finance_manager": {"account", "department", "vendor"},
            "department_manager": {"account", "department"},
            # Board sees structure (accounts, departments) but not counterparty identities.
            "board": {"account", "department"},
        }
        audience = "board" if role == "board" else "internal"
        return cls(role=role, viewable=presets.get(role, {"account", "department"}), audience=audience)

    def can_view(self, entity_type: str) -> bool:
        return entity_type in self.viewable


_SAFE_LABELS = {
    "customer": "Top Customer",
    "vendor": "Key Vendor",
    "bank": "Primary Bank",
    "department": "a department",
    "account": "a cost category",
}


def _safe_label(entity_type: Optional[str], synthetic: str) -> str:
    base = _SAFE_LABELS.get(entity_type or "", "an entity")
    m = re.search(r"_(\d{3})$", synthetic)
    if entity_type in ("customer", "vendor") and m:
        return f"{base} {int(m.group(1))}"
    return base


def rehydrate_text(
    text: str,
    vault: AliasVault,
    permissions: Permissions,
    period_alias_inverse: Optional[Dict[str, str]] = None,
) -> str:
    """Replace synthetic identifiers (and optionally period aliases) with authorized real terms."""
    def repl_entity(m: re.Match) -> str:
        synth = m.group(0)
        etype = vault.entity_type(synth)
        real = vault.real_name(synth)
        if real is not None and etype is not None and permissions.can_view(etype):
            return real
        return _safe_label(etype, synth)

    out = _SYNTH_RE.sub(repl_entity, text)

    if period_alias_inverse:
        def repl_period(m: re.Match) -> str:
            return period_alias_inverse.get(m.group(0), m.group(0))
        out = _PERIOD_RE.sub(repl_period, out)

    return out


def rehydrate_response(
    response: Any,
    vault: AliasVault,
    permissions: Permissions,
    period_alias_inverse: Optional[Dict[str, str]] = None,
) -> Any:
    """Recursively rehydrate every string in an LLM response object."""
    if isinstance(response, dict):
        return {k: rehydrate_response(v, vault, permissions, period_alias_inverse) for k, v in response.items()}
    if isinstance(response, list):
        return [rehydrate_response(v, vault, permissions, period_alias_inverse) for v in response]
    if isinstance(response, str):
        return rehydrate_text(response, vault, permissions, period_alias_inverse)
    return response
