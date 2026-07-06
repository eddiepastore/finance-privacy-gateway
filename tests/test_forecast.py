import unittest
from decimal import Decimal

from gateway.finance_core.calculations import VarianceItem
from gateway.finance_core.forecast import forecast_adjustment_for, suggested_quarter_adjustment


def _item(is_revenue, var_amount):
    return VarianceItem(
        account="X", account_type="revenue" if is_revenue else "opex", department="D", period="2026-03",
        is_revenue=is_revenue, actual=Decimal("0"), budget=Decimal("0"), forecast=None,
        variance_vs_budget_amount=Decimal(str(var_amount)), variance_vs_budget_pct=-5.0,
        variance_vs_forecast_amount=None, variance_vs_forecast_pct=None,
    )


class TestForecast(unittest.TestCase):
    def test_quarter_carry_band_ordered(self):
        low, high = suggested_quarter_adjustment(Decimal("-700000"))
        self.assertLess(low, high)
        # -700k * 3 = -2.1M; band 0.75..1.25 => -1.575M .. -2.625M
        self.assertEqual(low, Decimal("-2625000.00"))
        self.assertEqual(high, Decimal("-1575000.00"))

    def test_revenue_shortfall_decreases(self):
        fa = forecast_adjustment_for(_item(True, -700000))
        self.assertEqual(fa["direction"], "decrease")

    def test_expense_overrun_increases(self):
        fa = forecast_adjustment_for(_item(False, 335000))
        self.assertEqual(fa["direction"], "increase")

    def test_zero_variance_returns_none(self):
        self.assertIsNone(forecast_adjustment_for(_item(True, 0)))


if __name__ == "__main__":
    unittest.main()
