import unittest

from gateway.llm_client.validator import normalize_response


def _resp(far):
    return {
        "executive_summary": "Summary.",
        "material_variance_commentary": [
            {"issue_id": "ISSUE_001", "commentary": "c", "forecast_adjustment_recommendation": far}
        ],
        "board_narrative": {"draft": "d"},
        "risks_to_monitor": [],
        "open_questions": [],
    }


class TestNormalizeResponse(unittest.TestCase):
    def test_bare_direction_string_becomes_object(self):
        r = _resp("decrease")
        normalize_response(r)
        far = r["material_variance_commentary"][0]["forecast_adjustment_recommendation"]
        self.assertEqual(far, {"direction": "decrease"})

    def test_direction_string_is_case_insensitive(self):
        r = _resp(" Increase ")
        normalize_response(r)
        far = r["material_variance_commentary"][0]["forecast_adjustment_recommendation"]
        self.assertEqual(far, {"direction": "increase"})

    def test_non_direction_string_becomes_reason(self):
        r = _resp("hold flat until pipeline recovers")
        normalize_response(r)
        far = r["material_variance_commentary"][0]["forecast_adjustment_recommendation"]
        self.assertEqual(far, {"reason": "hold flat until pipeline recovers"})

    def test_well_formed_object_untouched(self):
        far_in = {"direction": "unchanged", "reason": "r"}
        r = _resp(dict(far_in))
        normalize_response(r)
        self.assertEqual(r["material_variance_commentary"][0]["forecast_adjustment_recommendation"], far_in)

    def test_rationale_key_renamed_to_reason(self):
        r = _resp({"direction": "unchanged", "rationale": "r"})
        normalize_response(r)
        self.assertEqual(
            r["material_variance_commentary"][0]["forecast_adjustment_recommendation"],
            {"direction": "unchanged", "reason": "r"},
        )

    def test_malformed_top_level_is_ignored_safely(self):
        normalize_response("not a dict")
        normalize_response({"material_variance_commentary": "not a list"})

    def test_camelcase_contract_keys_are_renamed(self):
        r = {
            "executiveSummary": "s",
            "materialVarianceCommentary": [
                {"issueId": "ISSUE_001", "commentary": "c",
                 "likelyDrivers": ["d"], "managementQuestions": ["q"],
                 "forecastAdjustmentRecommendation": "increase"}
            ],
            "boardNarrative": {"draft": "d"},
            "risksToMonitor": ["r"],
            "openQuestions": ["q"],
        }
        normalize_response(r)
        self.assertEqual(r["executive_summary"], "s")
        item = r["material_variance_commentary"][0]
        self.assertEqual(item["issue_id"], "ISSUE_001")
        self.assertEqual(item["likely_drivers"], ["d"])
        self.assertEqual(item["forecast_adjustment_recommendation"], {"direction": "increase"})
        self.assertEqual(r["board_narrative"], {"draft": "d"})
        self.assertNotIn("executiveSummary", r)

    def test_item_id_variant_maps_to_issue_id(self):
        r = _resp({"direction": "unchanged"})
        r["material_variance_commentary"][0].pop("issue_id")
        r["material_variance_commentary"][0]["item_id"] = "ISSUE_002"
        normalize_response(r)
        self.assertEqual(r["material_variance_commentary"][0]["issue_id"], "ISSUE_002")


if __name__ == "__main__":
    unittest.main()


class TestBoardMarkdownRealModelShapes(unittest.TestCase):
    """build_board_markdown must render every shape the response contract allows."""

    def test_string_risks_and_rationale_far_do_not_crash(self):
        from gateway.pipeline import build_board_markdown, run_pipeline
        from tests.helpers import tiny_model
        model = tiny_model()
        result = run_pipeline(model, "2026-03", llm_preference="mock")
        rehydrated = dict(result.rehydrated_response)
        rehydrated["risks_to_monitor"] = ["churn may accelerate", "vendor concentration"]
        for c in rehydrated.get("material_variance_commentary", []):
            c["forecast_adjustment_recommendation"] = {"direction": "decrease", "rationale": "softening demand"}
        from gateway.obfuscation import Permissions
        md = build_board_markdown(model, result.period, rehydrated, {}, Permissions.for_role("cfo"))
        self.assertIn("churn may accelerate", md)
        self.assertIn("softening demand", md)
