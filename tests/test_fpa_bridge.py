import json
import unittest

from gateway.api.fpa_bridge import fpa_commentary

PAYLOAD = {
    "company": "Atlas HealthTech", "period": "2026-05", "viewer_role": "cfo", "model_provider": "mock",
    "variances": [
        {"department": "Marketing", "account": "Events & Field Marketing", "category": "Sales & Marketing",
         "budget": 12960, "actual": 104960, "variance_abs": 92000, "variance_pct": 7.1, "materiality": "Material"},
        {"department": "Sales", "account": "Subscription Revenue", "category": "Revenue",
         "budget": 1360000, "actual": 1225000, "variance_abs": -135000, "variance_pct": -9.9, "materiality": "Material"},
        {"department": "R&D", "account": "Payroll & Benefits", "category": "Compensation",
         "budget": 195750, "actual": 119750, "variance_abs": -76000, "variance_pct": -38, "materiality": "Material"},
    ],
    "concentration": [{"entity_type": "customer", "name": "Northwind Health", "amount": 310}],
}
REAL_TERMS = ["Atlas HealthTech", "Marketing", "Events & Field Marketing", "Subscription Revenue",
              "Payroll & Benefits", "Northwind"]


class TestFpaBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = fpa_commentary(PAYLOAD)

    def test_outbound_packet_has_no_real_names_or_dollars(self):
        blob = json.dumps(self.result["outbound_packet"])
        self.assertNotIn("$", blob)
        for term in REAL_TERMS:
            self.assertNotIn(term, blob, f"real term leaked into packet: {term}")

    def test_proof_is_clean_and_sent(self):
        p = self.result["proof"]
        self.assertEqual(p["hard_leaks"], 0)
        self.assertFalse(p["raw_dollars_sent"])
        self.assertFalse(p["real_entities_sent"])
        self.assertTrue(p["sent_to_model"])
        self.assertTrue(p["validation_ok"])
        self.assertTrue(p["packet_sha256"])

    def test_drafts_returned_and_rehydrated(self):
        drafts = self.result["drafts"]
        self.assertTrue(drafts)
        self.assertTrue(all(d.get("summary") for d in drafts))
        # CFO view rehydrates real line identity back into the issue_key
        self.assertTrue(any("Subscription Revenue" in d["issue_key"] for d in drafts))

    def test_gate_blocks_a_name_leaking_mode(self):
        # standard_finance retains real account names; the augmented forbidden list must hard-block it.
        bad = dict(PAYLOAD, privacy_mode="standard_finance")
        r = fpa_commentary(bad)
        self.assertTrue(r["proof"].get("blocked"))
        self.assertEqual(r["drafts"], [])

    def test_real_requested_without_key_marks_fallback(self):
        r = fpa_commentary(dict(PAYLOAD, model_provider="auto"))
        # no OPENAI_API_KEY in test env -> mock used, flagged as fallback
        self.assertEqual(r["proof"]["provider"], "mock")
        self.assertTrue(r["proof"]["model_fallback"])


if __name__ == "__main__":
    unittest.main()
