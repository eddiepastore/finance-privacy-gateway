import unittest

from gateway.obfuscation import AliasVault, Permissions, rehydrate_text
from gateway.obfuscation.rehydration import rehydrate_response


class TestRehydration(unittest.TestCase):
    def setUp(self):
        self.vault = AliasVault()
        self.dept = self.vault.alias("department", "Engineering")     # DEPT_001
        self.cust = self.vault.alias("customer", "Northwind Health")  # CLIENT_001

    def test_cfo_sees_real_names(self):
        text = f"{self.dept} overspent; {self.cust} is the largest account."
        out = rehydrate_text(text, self.vault, Permissions.for_role("cfo"))
        self.assertIn("Engineering", out)
        self.assertIn("Northwind Health", out)
        self.assertNotIn("DEPT_001", out)

    def test_board_audience_redacts_customer(self):
        text = f"{self.cust} represents a large share of revenue."
        out = rehydrate_text(text, self.vault, Permissions.for_role("board"))
        self.assertNotIn("Northwind Health", out)
        self.assertIn("Top Customer 1", out)

    def test_department_manager_cannot_see_customers(self):
        text = f"{self.dept} and {self.cust}."
        out = rehydrate_text(text, self.vault, Permissions.for_role("department_manager"))
        self.assertIn("Engineering", out)              # can view departments
        self.assertNotIn("Northwind Health", out)      # cannot view customers
        self.assertIn("Top Customer 1", out)

    def test_period_dealias(self):
        out = rehydrate_text("Performance in P03 was soft.", self.vault,
                             Permissions.for_role("cfo"), period_alias_inverse={"P03": "2026-03"})
        self.assertIn("2026-03", out)
        self.assertNotIn("P03", out)

    def test_rehydration_introduces_no_dollars(self):
        resp = {"executive_summary": f"{self.dept} drove the variance.",
                "material_variance_commentary": [{"issue_id": "ISSUE_001", "summary": f"{self.cust} is large."}]}
        out = rehydrate_response(resp, self.vault, Permissions.for_role("cfo"))
        import json
        self.assertNotIn("$", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
