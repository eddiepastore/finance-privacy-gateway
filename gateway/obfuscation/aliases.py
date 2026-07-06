"""Alias Vault + category generalization (spec Sections 7.6, 9.1, 9.2).

The vault is the rehydration key. It must NEVER be serialized into an outbound packet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PREFIXES = {
    "account": "CAT",
    "vendor": "VENDOR",
    "customer": "CLIENT",
    "department": "DEPT",
    "bank": "BANK",
    "bank_account": "BANK_ACCOUNT",
    "cost_center": "CC",
    "kpi": "KPI",
}

# Mode B (generalized semantic labels) — preserve meaning, hide exact account structure.
ACCOUNT_GENERALIZATION = {
    "payroll": "People Costs",
    "benefits": "People Costs",
    "sales commissions": "Sales Compensation",
    "marketing programs": "Demand Generation",
    "cloud infrastructure": "Technical Infrastructure",
    "software subscriptions": "Software & Tools",
    "professional services": "Outside Services",
    "travel": "Travel & Entertainment",
    "facilities": "Facilities",
    "legal": "Outside Services",
    "recruiting": "Talent Acquisition",
    "support tooling": "Software & Tools",
    "cost of delivery": "Cost of Delivery",
    "subscription revenue": "Revenue",
    "services revenue": "Revenue",
}

# Mode C descriptors — abstract identifier + a reasoning hint, but no real category name.
ACCOUNT_DESCRIPTOR = {
    "payroll": "recurring people operating cost",
    "benefits": "recurring people operating cost",
    "cloud infrastructure": "recurring technical operating cost",
    "software subscriptions": "recurring commercial software cost",
    "marketing programs": "discretionary growth spend",
    "recruiting": "non-recurring people growth cost",
    "legal": "non-recurring professional cost",
}


def generalize_account(account: str) -> str:
    return ACCOUNT_GENERALIZATION.get(account.strip().lower(), account.strip())


def generalize_department(department: str) -> str:
    return department.strip()


@dataclass
class AliasVault:
    """Bidirectional map between real entities and synthetic labels, scoped to one dataset."""
    dataset_id: str = "ds_local"
    _to_synth: Dict[Tuple[str, str], str] = field(default_factory=dict)
    _to_real: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    _counts: Dict[str, int] = field(default_factory=dict)
    descriptors: Dict[str, str] = field(default_factory=dict)

    def alias(self, entity_type: str, real_name: str) -> str:
        key = (entity_type, real_name)
        if key in self._to_synth:
            return self._to_synth[key]
        prefix = PREFIXES.get(entity_type, "ENT")
        self._counts[entity_type] = self._counts.get(entity_type, 0) + 1
        synth = f"{prefix}_{self._counts[entity_type]:03d}"
        self._to_synth[key] = synth
        self._to_real[synth] = key
        if entity_type == "account":
            desc = ACCOUNT_DESCRIPTOR.get(real_name.strip().lower())
            if desc:
                self.descriptors[synth] = desc
        return synth

    def real_name(self, synthetic: str) -> Optional[str]:
        entry = self._to_real.get(synthetic)
        return entry[1] if entry else None

    def entity_type(self, synthetic: str) -> Optional[str]:
        entry = self._to_real.get(synthetic)
        return entry[0] if entry else None

    def synthetic_labels(self) -> List[str]:
        return list(self._to_real.keys())

    def all_real_names(self) -> List[str]:
        return [real for (_etype, real) in self._to_synth.keys()]

    def reverse_map(self) -> Dict[str, str]:
        """synthetic -> real display name (used by rehydration)."""
        return {synth: real for synth, (_etype, real) in self._to_real.items()}
