import json
import os
import unittest

from gateway.web.api import build_dashboard_payload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestWebApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(ROOT, "sample_data", "actuals.csv")):
            raise unittest.SkipTest("sample_data not generated")
        cls.payload = build_dashboard_payload()

    def test_gate_clean_and_sent(self):
        g = self.payload["gate"]
        self.assertEqual(g["hard_leaks"], 0)
        self.assertFalse(g["raw_dollars_sent"])
        self.assertFalse(g["real_entities_sent"])
        self.assertTrue(g["sent_to_llm"])
        self.assertTrue(g["validation_ok"])

    def test_sections_present(self):
        for key in ("preview", "variances", "packet", "review_items", "board_markdown", "audit_log"):
            self.assertIn(key, self.payload)
            self.assertTrue(self.payload[key])

    def test_board_audience_redacts_customers(self):
        board = build_dashboard_payload(role="board")
        blob = json.dumps(board["review_items"]) + board["board_markdown"]
        self.assertNotIn("Northwind", blob)        # real customer name never surfaces to board audience

    def test_packet_has_no_dollar_sign(self):
        self.assertNotIn("$", json.dumps(self.payload["packet"]))

    def test_view_time_role_rehydration_board_vs_cfo(self):
        cfo = build_dashboard_payload(role="cfo")
        board = build_dashboard_payload(role="board")
        # The mock cites the top customer by alias; CFO sees the real name, board sees a safe label.
        self.assertIn("Northwind", cfo["board_markdown"])
        self.assertNotIn("Northwind", board["board_markdown"])
        self.assertIn("Top Customer", board["board_markdown"])

    def test_available_periods_present(self):
        self.assertIn("2026-03", self.payload["available_periods"])
        self.assertEqual(len(self.payload["available_periods"]), 3)

    def test_gate_surfaces_provider_and_model(self):
        self.assertEqual(self.payload["gate"]["llm_provider"], "mock")
        self.assertTrue(self.payload["gate"]["llm_model"])  # model name surfaced

    def test_high_privacy_preview_shows_cat_and_withholds_name(self):
        hp = build_dashboard_payload(privacy_mode="high_privacy")
        payroll = next(r for r in hp["preview"] if r["field"] == "Account: Payroll")
        self.assertIn("CAT_", payroll["safe"])
        self.assertIn("withheld", payroll["safe"])
        # the packet itself uses CAT_### categories and no dollar sign
        self.assertTrue(all(m["metric"].startswith("CAT_") for m in hp["packet"]["summary_metrics"]))
        self.assertNotIn("$", json.dumps(hp["packet"]))

    def test_get_client_falls_back_to_mock_without_key(self):
        import os
        from gateway.llm_client import get_client, MockLLM
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            self.assertIsInstance(get_client("auto"), MockLLM)   # no key -> mock
            self.assertIsInstance(get_client("mock"), MockLLM)
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved

    def test_dashboard_payload_has_packet_meta_and_model_status(self):
        auto = build_dashboard_payload(llm_preference="auto")
        self.assertIn("packet_meta", auto)
        self.assertIn("packet_sha256", auto["packet_meta"])
        self.assertIn("model_status_message", auto["gate"])
        self.assertIn("model_fallback", auto["gate"])

    def test_static_ui_exposes_privacy_proof_packet_tools_and_publication_gate(self):
        with open(os.path.join(ROOT, "gateway", "web", "static", "index.html")) as fh:
            html = fh.read()
        for snippet in (
            "Privacy Proof",
            "copyPacketJson",
            "downloadPacketJson",
            "Re-run with selected privacy mode",
            "Publication Gate",
            "packet_sha256",
        ):
            self.assertIn(snippet, html)


if __name__ == "__main__":
    unittest.main()
