import unittest

from gateway.pipeline import run_pipeline
from tests.helpers import tiny_model


class TestPipelineEndToEnd(unittest.TestCase):
    def setUp(self):
        self.result = run_pipeline(tiny_model(), "2026-03", llm_preference="mock")

    def test_packet_not_hard_blocked(self):
        self.assertFalse(self.result.risk.has_hard_leak)
        self.assertTrue(self.result.sent_to_llm)
        self.assertEqual(self.result.llm_provider, "mock")

    def test_llm_output_validates(self):
        self.assertTrue(self.result.validation_ok, self.result.validation_errors)

    def test_review_items_and_board(self):
        self.assertTrue(self.result.review_items)
        self.assertTrue(self.result.board_markdown.startswith("# Operating Review"))
        # Local dollars present in the board narrative (rehydrated from local calc, not the LLM).
        self.assertIn("$", self.result.board_markdown)

    def test_review_items_carry_local_facts(self):
        ri = self.result.review_items[0]
        self.assertEqual(ri["status"], "draft")     # nothing auto-published
        self.assertIsNotNone(ri["local_facts"])
        self.assertIn("$", ri["local_facts"]["variance_vs_budget"])

    def test_audit_trail_covers_key_steps(self):
        actions = {e["action"] for e in self.result.audit_log}
        for expected in ("materiality_classified", "obfuscation_packet_generated",
                         "packet_risk_scored", "llm_response_received", "board_narrative_generated"):
            self.assertIn(expected, actions)

    def test_blocked_packet_is_not_sent(self):
        # Force a hard leak by injecting raw dollars into the model org name path is hard;
        # instead verify the gate decision function directly.
        from gateway.obfuscation.risk_scoring import RiskAssessment, can_send_packet
        from gateway.obfuscation.leak_scanner import Leak
        bad = RiskAssessment(score=100, level="critical", leaks=[Leak("raw_dollar", "$.x", "12,400,000")])
        self.assertFalse(can_send_packet(bad))


if __name__ == "__main__":
    unittest.main()
