"""The hard privacy gate (spec Sections 26.2, 26.5).

Uses the SAME leak_scanner that the runtime gate uses, so enforcement and testing cannot drift.
If this test ever fails, the product's core promise is broken — treat as release-blocking.
"""
import json
import os
import unittest
from decimal import Decimal

from gateway.finance_core import classify_materiality, compute_variances, DEFAULT_RULES, load_package
from gateway.obfuscation import (
    AliasVault, build_forbidden_terms, build_packet, scan_for_leaks, select_base_amount,
)
from tests.helpers import tiny_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARD_KINDS = ("raw_dollar", "entity_name", "company_name")


def _packet_for(model, privacy_mode="generalized_semantic_labels"):
    variances = [classify_materiality(v, DEFAULT_RULES) for v in compute_variances(model, "2026-03")]
    base = select_base_amount(model, "2026-03")
    packet, _ = build_packet(model, variances, "2026-03", AliasVault(),
                             privacy_mode=privacy_mode, base_amount=base)
    return packet


class TestPrivacyRegression(unittest.TestCase):
    def _assert_clean(self, model, privacy_mode="generalized_semantic_labels"):
        packet = _packet_for(model, privacy_mode)
        forbidden = build_forbidden_terms(model, privacy_mode)
        leaks = scan_for_leaks(packet, forbidden)
        hard = [l for l in leaks if l.kind in HARD_KINDS]
        self.assertEqual(hard, [], f"hard leaks in packet: {[(l.kind, l.path, l.sample) for l in hard]}")

        blob = json.dumps(packet)
        # No currency symbol anywhere.
        self.assertNotIn("$", blob)
        # No real entity / company names anywhere.
        self.assertNotIn(model.organization, blob)
        for c in model.customers:
            self.assertNotIn(c.name, blob)
        for v in model.vendors:
            self.assertNotIn(v.name, blob)
        return packet

    def test_tiny_model_clean(self):
        self._assert_clean(tiny_model())

    def test_tiny_model_high_privacy_clean(self):
        self._assert_clean(tiny_model(), privacy_mode="high_privacy")

    def test_sample_data_clean(self):
        data_dir = os.path.join(ROOT, "sample_data")
        if not os.path.exists(os.path.join(data_dir, "actuals.csv")):
            self.skipTest("sample_data not generated; run scripts/generate_sample_data.py")
        model = load_package(data_dir)
        packet = self._assert_clean(model)
        # Spot check: the planted real values must not appear.
        blob = json.dumps(packet)
        for sensitive in ("12,400,000", "12400000", "Northstar", "Northwind", "Amazon Web Services"):
            self.assertNotIn(sensitive, blob)

    def test_reasoning_value_preserved(self):
        # The packet must still carry enough structure to reason: indexed metrics + variance %s.
        packet = _packet_for(tiny_model())
        self.assertTrue(packet["summary_metrics"])
        self.assertTrue(any(m.get("variance_vs_budget_pct") is not None for m in packet["summary_metrics"]))
        self.assertTrue(packet["material_items"])


if __name__ == "__main__":
    unittest.main()
