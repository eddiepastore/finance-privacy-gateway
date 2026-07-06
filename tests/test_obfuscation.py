import unittest
from decimal import Decimal

from gateway.finance_core import classify_materiality, compute_variances, DEFAULT_RULES
from gateway.obfuscation import (
    AliasVault, build_packet, generalize_account, index_amount, select_base_amount,
)
from gateway.obfuscation.indexing import privacy_round
from tests.helpers import tiny_model


class TestAliases(unittest.TestCase):
    def test_determinism_and_no_collision(self):
        v = AliasVault()
        a1 = v.alias("customer", "Acme")
        a2 = v.alias("customer", "Acme")
        b = v.alias("customer", "Globex")
        self.assertEqual(a1, a2)               # deterministic within a run
        self.assertNotEqual(a1, b)             # distinct entities, distinct aliases

    def test_prefix_by_type(self):
        v = AliasVault()
        self.assertTrue(v.alias("customer", "X").startswith("CLIENT_"))
        self.assertTrue(v.alias("vendor", "Y").startswith("VENDOR_"))
        self.assertTrue(v.alias("department", "Z").startswith("DEPT_"))

    def test_reverse_resolution(self):
        v = AliasVault()
        syn = v.alias("vendor", "Amazon Web Services")
        self.assertEqual(v.real_name(syn), "Amazon Web Services")
        self.assertEqual(v.entity_type(syn), "vendor")


class TestIndexing(unittest.TestCase):
    def test_ratio_preserved(self):
        base = Decimal("1000")
        self.assertEqual(index_amount(Decimal("500"), base), 50.0)
        self.assertEqual(index_amount(Decimal("1000"), base), 100.0)

    def test_privacy_round_buckets(self):
        self.assertEqual(privacy_round(0.02), "<0.1")
        self.assertEqual(privacy_round(600.0), ">500 (large outlier)")
        self.assertEqual(privacy_round(41.9354), 41.9)


class TestGeneralization(unittest.TestCase):
    def test_account_generalization(self):
        self.assertEqual(generalize_account("Payroll"), "People Costs")
        self.assertEqual(generalize_account("Cloud Infrastructure"), "Technical Infrastructure")
        # Unknown accounts pass through unchanged.
        self.assertEqual(generalize_account("Mystery Line"), "Mystery Line")


class TestPacketStructure(unittest.TestCase):
    def setUp(self):
        self.model = tiny_model()
        self.variances = [classify_materiality(v, DEFAULT_RULES)
                          for v in compute_variances(self.model, "2026-03")]
        self.base = select_base_amount(self.model, "2026-03")
        self.vault = AliasVault()
        self.packet, self.alias = build_packet(
            self.model, self.variances, "2026-03", self.vault,
            privacy_mode="generalized_semantic_labels", base_amount=self.base,
        )

    def test_base_amount_not_disclosed(self):
        # The model is told the base is 100 index points, and the real base is never disclosed.
        # (The strong "real large base value absent" check lives in test_privacy_regression with
        # realistic millions-scale sample data; tiny_model's base of 100 collides with the index.)
        self.assertFalse(self.packet["baseline"]["real_base_value_disclosed"])
        self.assertEqual(self.packet["baseline"]["base_value_sent_to_model"], 100.0)

    def test_revenue_indexes_to_100(self):
        rev = next(m for m in self.packet["summary_metrics"] if m["metric"] == "Revenue")
        self.assertEqual(rev["actual_index"], 100.0)   # base is current-period actual revenue

    def test_departments_aliased(self):
        for item in self.packet["material_items"]:
            self.assertTrue(item["department"].startswith("DEPT_"))


if __name__ == "__main__":
    unittest.main()
