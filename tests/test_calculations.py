import unittest
from decimal import Decimal

from gateway.finance_core import compute_variances
from gateway.finance_core.calculations import compute_mom_trend
from tests.helpers import tiny_model


class TestCalculations(unittest.TestCase):
    def setUp(self):
        self.model = tiny_model()
        self.items = {v.account: v for v in compute_variances(self.model, "2026-03")}

    def test_budget_variance_amount_and_pct(self):
        rev = self.items["Subscription Revenue"]
        self.assertEqual(rev.variance_vs_budget_amount, Decimal("-20"))
        self.assertAlmostEqual(rev.variance_vs_budget_pct, -16.6667, places=3)

        pay = self.items["Payroll"]
        self.assertEqual(pay.variance_vs_budget_amount, Decimal("10"))
        self.assertAlmostEqual(pay.variance_vs_budget_pct, 20.0, places=6)

    def test_forecast_variance(self):
        rev = self.items["Subscription Revenue"]
        self.assertEqual(rev.variance_vs_forecast_amount, Decimal("-10"))
        self.assertAlmostEqual(rev.variance_vs_forecast_pct, -9.0909, places=3)

    def test_favorability_sign_conventions(self):
        # Revenue below budget is unfavorable; expense above budget is unfavorable.
        self.assertEqual(self.items["Subscription Revenue"].favorability, "unfavorable")
        self.assertEqual(self.items["Payroll"].favorability, "unfavorable")

    def test_favorable_cases(self):
        from decimal import Decimal as D
        from gateway.finance_core.normalization import FinancialFact
        m = tiny_model()
        # Add an expense under budget (favorable) and revenue over budget (favorable).
        m.facts.append(FinancialFact("actual", "2026-03", "Marketing", "opex", "Marketing", D("80")))
        m.facts.append(FinancialFact("budget", "2026-03", "Marketing", "opex", "Marketing", D("100")))
        items = {v.account: v for v in compute_variances(m, "2026-03")}
        self.assertEqual(items["Marketing"].favorability, "favorable")

    def test_contribution_sums_to_100(self):
        total = sum(v.contribution_to_total_variance_pct for v in self.items.values())
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_zero_budget_yields_none_pct(self):
        from gateway.finance_core.normalization import FinancialFact
        m = tiny_model()
        m.facts.append(FinancialFact("actual", "2026-03", "NewLine", "opex", "G&A", Decimal("10")))
        m.facts.append(FinancialFact("budget", "2026-03", "NewLine", "opex", "G&A", Decimal("0")))
        items = {v.account: v for v in compute_variances(m, "2026-03")}
        self.assertIsNone(items["NewLine"].variance_vs_budget_pct)

    def test_mom_trend(self):
        from gateway.finance_core.normalization import FinancialFact
        m = tiny_model()
        # add a prior period for Payroll: 50 -> 60 is +20%
        m.facts.append(FinancialFact("actual", "2026-02", "Payroll", "opex", "Engineering", Decimal("50")))
        trend = compute_mom_trend(m, "Payroll")
        self.assertIsNone(trend["2026-02"])      # first available period has no prior
        self.assertAlmostEqual(trend["2026-03"], 20.0, places=6)


if __name__ == "__main__":
    unittest.main()
