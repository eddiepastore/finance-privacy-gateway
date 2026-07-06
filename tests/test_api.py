import json
import os
import unittest

from gateway.api.repository import Repository
from gateway.api.service import ApiService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "sample_data")


def _read(name):
    with open(os.path.join(SAMPLE, name)) as fh:
        return fh.read()


class TestApiLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(SAMPLE, "actuals.csv")):
            raise unittest.SkipTest("sample_data not generated")

    def setUp(self):
        self.svc = ApiService(Repository(":memory:"))
        ds = self.svc.create_dataset("March Review", "2026-03",
                                     "generalized_semantic_labels", "Northstar Health Analytics, Inc.")
        self.did = ds["id"]
        for ftype, fname in [("actuals", "actuals.csv"), ("budget", "budget.csv"),
                             ("forecast", "forecast.csv"), ("kpi", "kpis.csv"),
                             ("customer", "customers.csv"), ("vendor", "vendors.csv")]:
            self.svc.upload_file(self.did, ftype, fname, _read(fname))

    def test_full_lifecycle(self):
        calc = self.svc.calculate(self.did)
        self.assertEqual(calc["status"], "completed")
        self.assertGreater(calc["summary"]["material_issues"], 0)

        obf = self.svc.obfuscate(self.did, calc["calculation_run_id"])
        self.assertFalse(obf["raw_dollars_sent"])
        self.assertFalse(obf["real_entities_sent"])

        an = self.svc.analyze(self.did, obf["obfuscation_run_id"])
        self.assertTrue(an["validation_ok"])
        self.assertGreater(an["review_items_created"], 0)

        items = self.svc.list_review_items(self.did)["review_items"]
        self.assertTrue(items)
        self.assertEqual(items[0]["status"], "draft")

        res = self.svc.approve(items[0]["review_item_id"], None, "cfo_user")
        self.assertEqual(res["status"], "approved")

        board = self.svc.board_narrative(self.did, include_only_approved=True)
        self.assertIn("# Operating Review", board["markdown"])
        self.assertIn("$", board["markdown"])  # local dollars present

    def test_request_revision_reopens_item_and_excludes_it_from_board(self):
        self.svc.run_pipeline_steps(self.did)
        items = self.svc.list_review_items(self.did)["review_items"]
        rid = items[0]["review_item_id"]

        self.svc.approve(rid, None, "cfo_user")
        res = self.svc.request_revision(rid, "Tone down the driver claim", "cfo_user")
        self.assertEqual(res["status"], "revision_requested")

        refreshed = self.svc.list_review_items(self.did)["review_items"]
        item = next(i for i in refreshed if i["review_item_id"] == rid)
        self.assertEqual(item["status"], "revision_requested")
        self.assertIsNone(item["approved_text"])  # prior approval withdrawn

        board = self.svc.board_narrative(self.did, include_only_approved=True)
        self.assertNotIn(items[0]["title"], board["markdown"])

        audit = self.svc.repo.audit(self.did)
        self.assertTrue(any(e["action"] == "review_item_revision_requested" for e in audit))
        self.assertIsNone(self.svc.request_revision("missing-id", "n/a", "cfo_user"))

    def test_stored_packet_is_clean(self):
        calc = self.svc.calculate(self.did)
        obf = self.svc.obfuscate(self.did, calc["calculation_run_id"])
        run = self.svc.repo.get_obfuscation_run(obf["obfuscation_run_id"])
        blob = run["packet_json"]
        self.assertNotIn("$", blob)
        for sensitive in ("Northstar", "Northwind", "Amazon Web Services", "12400000"):
            self.assertNotIn(sensitive, blob)

    def test_uploaded_file_column_detection(self):
        files = self.svc.repo.files(self.did)
        actuals = next(f for f in files if f["file_type"] == "actuals")
        cols = json.loads(actuals["columns_json"])
        self.assertIn("account", cols)
        self.assertGreater(actuals["row_count"], 0)

    def test_column_mapping_applied(self):
        # Upload a file with a non-canonical header and map it; calculate should still work.
        svc = self.svc
        content = "GL Name,account_type,Team,Month,Actual Amount\nSubscription Revenue,revenue,Sales,2026-03,1000\n"
        up = svc.upload_file(self.did, "actuals", "weird.csv", content)
        svc.save_mapping(self.did, up["file_id"], {"GL Name": "account", "Team": "department",
                                                   "Month": "period", "Actual Amount": "amount"})
        # mapping_for returns the latest; calculate must not raise
        calc = svc.calculate(self.did)
        self.assertEqual(calc["status"], "completed")

    def test_audit_trail_recorded(self):
        calc = self.svc.calculate(self.did)
        obf = self.svc.obfuscate(self.did, calc["calculation_run_id"])
        self.svc.analyze(self.did, obf["obfuscation_run_id"])
        actions = {e["action"] for e in self.svc.repo.audit(self.did)}
        for expected in ("dataset_created", "file_uploaded", "calculation_run_created",
                         "obfuscation_run_created", "analysis_run_created"):
            self.assertIn(expected, actions)


class TestUnifiedDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(SAMPLE, "actuals.csv")):
            raise unittest.SkipTest("sample_data not generated")

    def setUp(self):
        self.svc = ApiService(Repository(":memory:"))

    def test_seed_then_dashboard(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        d = self.svc.dashboard_payload(did, role="cfo")
        self.assertTrue(d["persisted"])
        self.assertEqual(d["gate"]["hard_leaks"], 0)
        self.assertTrue(d["gate"]["sent_to_llm"])
        self.assertTrue(d["gate"]["validation_ok"])
        self.assertTrue(d["review_items"])
        self.assertTrue(d["preview"])
        self.assertNotIn("$", json.dumps(d["packet"]))

    def test_run_pipeline_steps(self):
        ds = self.svc.create_dataset("X", "2026-03", "generalized_semantic_labels", "Co")
        for ftype, fname in [("actuals", "actuals.csv"), ("budget", "budget.csv")]:
            self.svc.upload_file(ds["id"], ftype, fname, _read(fname))
        out = self.svc.run_pipeline_steps(ds["id"])
        self.assertEqual(out["analysis"]["status"], "completed")
        self.assertGreater(out["analysis"]["review_items_created"], 0)

    def test_dashboard_board_role_redacts_customers(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        # approve everything so review items carry rehydrated text, then view as board
        for ri in self.svc.list_review_items(did)["review_items"]:
            self.svc.approve(ri["review_item_id"], None, "board")
        d = self.svc.dashboard_payload(did, role="board")
        self.assertNotIn("Northwind", json.dumps(d["review_items"]))

    def test_period_isolation(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]   # analyzes 2026-03
        n3 = len(self.svc.list_review_items(did, period="2026-03")["review_items"])
        self.assertGreater(n3, 0)
        self.svc.run_pipeline_steps(did, period="2026-01")        # analyze a different period
        # 2026-03's review items survive (delete only cleared 2026-01)
        self.assertEqual(len(self.svc.list_review_items(did, period="2026-03")["review_items"]), n3)
        d1 = self.svc.dashboard_payload(did, period="2026-01")
        self.assertEqual(d1["period"], "2026-01")
        self.assertIn("2026-02", d1["available_periods"])

    def test_run_pipeline_can_change_persisted_privacy_mode(self):
        did = self.svc.seed_sample_dataset(SAMPLE, privacy_mode="generalized_semantic_labels")["dataset_id"]
        self.svc.run_pipeline_steps(did, privacy_mode="high_privacy", period="2026-03")
        d = self.svc.dashboard_payload(did, role="cfo", period="2026-03")
        self.assertEqual(d["privacy_mode"], "high_privacy")
        self.assertEqual(d["packet"]["privacy_mode"], "high_privacy")
        self.assertTrue(all(m["metric"].startswith("CAT_") for m in d["packet"]["summary_metrics"]))

    def test_auto_model_fallback_is_explicit_in_dashboard_gate(self):
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            did = self.svc.seed_sample_dataset(SAMPLE, llm_preference="auto")["dataset_id"]
            d = self.svc.dashboard_payload(did, role="cfo")
            self.assertTrue(d["gate"]["model_fallback"])
            self.assertIn("Mock fallback", d["gate"]["model_status_message"])
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved

    def test_publication_gate_flags_reviewer_entered_customer_name_for_board(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        item = next(i for i in self.svc.list_review_items(did)["review_items"] if "Subscription Revenue" in i["title"])
        self.svc.approve(item["review_item_id"], "Revenue miss tied to Northwind Health Systems renewal timing.", "qa")
        board = self.svc.board_narrative(did, include_only_approved=True, audience="board")
        self.assertIn("Northwind Health Systems", board["markdown"])
        self.assertEqual(board["publication_gate"]["status"], "needs_redaction")
        self.assertIn("entity_name", {f["kind"] for f in board["publication_gate"]["findings"]})
        self.assertIn("Top Customer", board["safe_markdown"])
        self.assertNotIn("Northwind Health Systems", board["safe_markdown"])

    def test_review_items_are_sorted_by_cfo_priority(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        items = self.svc.list_review_items(did, role="cfo", period="2026-03")["review_items"]
        self.assertEqual(items[0]["title"], "Subscription Revenue variance commentary")
        self.assertGreaterEqual(items[0]["local_facts"]["contribution_to_total_variance_pct"],
                                items[1]["local_facts"]["contribution_to_total_variance_pct"])

    def test_dashboard_exposes_packet_metadata_for_audit(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        d = self.svc.dashboard_payload(did, role="cfo")
        meta = d["packet_meta"]
        self.assertEqual(meta["policy_version"], "privacy_policy_v1.0")
        self.assertEqual(len(meta["packet_sha256"]), 64)
        self.assertTrue(meta["run_id"].startswith("obf_"))
        self.assertIn("created_at", meta)

    def test_column_mapping_enables_noncanonical_headers(self):
        svc = ApiService(Repository(":memory:"))
        ds = svc.create_dataset("M", "2026-03", "generalized_semantic_labels", "Mapped Co")
        A = ("GL Name,Type,Team,Month,Actual Amount\n"
             "Subscription Revenue,revenue,Sales,2026-03,12400000\n"
             "Payroll,opex,Engineering,2026-03,5200000\n")
        B = ("GL Name,Type,Team,Month,Actual Amount\n"
             "Subscription Revenue,revenue,Sales,2026-03,13100000\n"
             "Payroll,opex,Engineering,2026-03,4865000\n")
        fa = svc.upload_file(ds["id"], "actuals", "a.csv", A)
        fb = svc.upload_file(ds["id"], "budget", "b.csv", B)
        with self.assertRaises(ValueError):       # headers don't auto-map -> no data for the period
            svc.calculate(ds["id"])
        m = {"GL Name": "account", "Type": "account_type", "Team": "department",
             "Month": "period", "Actual Amount": "amount"}
        svc.save_mapping(ds["id"], fa["file_id"], m)
        svc.save_mapping(ds["id"], fb["file_id"], m)
        out = svc.calculate(ds["id"])             # now it maps and computes
        self.assertEqual(out["summary"]["material_issues"], 2)

    def test_review_items_stored_obfuscated_rehydrated_on_read(self):
        did = self.svc.seed_sample_dataset(SAMPLE)["dataset_id"]
        raw = self.svc.repo.review_items(did)                      # straight from DB
        self.assertTrue(any("DEPT_" in r["draft_text"] for r in raw), "drafts must be stored obfuscated")
        shown = self.svc.list_review_items(did, role="cfo")["review_items"]
        self.assertFalse(any("DEPT_" in r["draft_text"] for r in shown), "must be rehydrated on read")


if __name__ == "__main__":
    unittest.main()
