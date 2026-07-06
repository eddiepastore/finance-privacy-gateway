import unittest
from decimal import Decimal

from gateway.finance_core import classify_materiality, compute_variances, DEFAULT_RULES
from gateway.finance_core.materiality import kpi_severity
from tests.helpers import tiny_model


class TestMateriality(unittest.TestCase):
    def test_revenue_override_is_stricter(self):
        # Subscription Revenue -16.7% — well past its 3% high override.
        model = tiny_model()
        items = {v.account: classify_materiality(v, DEFAULT_RULES)
                 for v in compute_variances(model, "2026-03")}
        self.assertEqual(items["Subscription Revenue"].severity, "high")

    def test_payroll_override(self):
        model = tiny_model()
        items = {v.account: classify_materiality(v, DEFAULT_RULES)
                 for v in compute_variances(model, "2026-03")}
        # Payroll +20% exceeds the 5% high override.
        self.assertEqual(items["Payroll"].severity, "high")

    def test_immaterial_below_thresholds(self):
        from gateway.finance_core.calculations import VarianceItem
        item = VarianceItem(
            account="Facilities", account_type="opex", department="G&A", period="2026-03",
            is_revenue=False, actual=Decimal("1010"), budget=Decimal("1000"), forecast=None,
            variance_vs_budget_amount=Decimal("10"), variance_vs_budget_pct=1.0,
            variance_vs_forecast_amount=None, variance_vs_forecast_pct=None,
        )
        classify_materiality(item, DEFAULT_RULES)
        self.assertEqual(item.severity, "immaterial")

    def test_kpi_severity_inverse_metric(self):
        # Logo churn rose 33% (lower is better) => unfavorable, high severity.
        self.assertEqual(kpi_severity(Decimal("2.4"), Decimal("1.8"), higher_is_better=False), "high")
        # On-plan churn => immaterial.
        self.assertEqual(kpi_severity(Decimal("1.8"), Decimal("1.8"), higher_is_better=False), "immaterial")


if __name__ == "__main__":
    unittest.main()
