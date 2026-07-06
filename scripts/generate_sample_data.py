"""Generate a synthetic but realistic finance package for the demo.

Deterministic. Writes 6 CSVs into sample_data/. The numbers are fake but shaped to exercise
every demo scenario in the spec (Section 25): a revenue miss, payroll over budget from early
hiring, cloud spend above forecast, marketing under budget, customer concentration, and a
forecast that needs a downward revenue revision.

Run: python3 scripts/generate_sample_data.py
"""
from __future__ import annotations

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "sample_data")

# Synthetic company identity — these strings must NEVER reach the LLM packet.
COMPANY_NAME = "Northstar Health Analytics, Inc."

PERIODS = ["2026-01", "2026-02", "2026-03"]

# March ("2026-03") carries the planted story. (account, type, department, actual, budget, forecast)
MARCH = [
    ("Subscription Revenue", "revenue", "Sales",            12_400_000, 13_100_000, 12_800_000),
    ("Services Revenue",     "revenue", "Services",          1_900_000,  1_850_000,  1_880_000),
    ("Cost of Delivery",     "cogs",    "Services",          2_100_000,  2_000_000,  2_050_000),
    ("Payroll",              "opex",    "Engineering",       5_200_000,  4_865_000,  4_980_000),
    ("Benefits",             "opex",    "Engineering",         980_000,    940_000,    960_000),
    ("Sales Commissions",    "opex",    "Sales",               760_000,    800_000,    780_000),
    ("Marketing Programs",   "opex",    "Marketing",           850_000,  1_100_000,    975_000),
    ("Cloud Infrastructure", "opex",    "Engineering",       1_300_000,  1_050_000,  1_125_000),
    ("Software Subscriptions","opex",   "G&A",                 420_000,    400_000,    410_000),
    ("Professional Services","opex",    "G&A",                 310_000,    350_000,    330_000),
    ("Travel",               "opex",    "Sales",               240_000,    200_000,    220_000),
    ("Facilities",           "opex",    "G&A",                 330_000,    330_000,    330_000),
    ("Legal",                "opex",    "G&A",                 180_000,    150_000,    165_000),
    ("Recruiting",           "opex",    "G&A",                 290_000,    220_000,    250_000),
    ("Support Tooling",      "opex",    "Customer Success",    140_000,    150_000,    145_000),
]

# Jan/Feb are roughly on-plan ramps so March is the focus. Factors applied to each March figure.
RAMP = {"2026-01": 0.90, "2026-02": 0.95, "2026-03": 1.00}


def _rows(scenario_idx: int):
    """scenario_idx: 3=actual, 4=budget, 5=forecast (tuple positions)."""
    out = []
    for period in PERIODS:
        f = RAMP[period]
        for rec in MARCH:
            account, atype, dept = rec[0], rec[1], rec[2]
            if period == "2026-03":
                amount = rec[scenario_idx]
            else:
                # Pre-March: hold to plan ramp (actual == budget == forecast) so variance is a March story.
                amount = round(rec[4] * f)
            out.append([account, atype, dept, period, amount])
    return out


def write_scenario(filename: str, scenario_idx: int):
    path = os.path.join(OUT, filename)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["account", "account_type", "department", "period", "amount"])
        w.writerows(_rows(scenario_idx))
    return path


def write_kpis():
    # kpi, period, actual, budget, unit, higher_is_better
    march = [
        ("ARR",                    49_000_000, 52_000_000, "usd",   1),
        ("Bookings",                3_480_000,  4_000_000, "usd",   1),
        ("Net Revenue Retention",         108,        112, "pct",   1),
        ("Gross Margin",                   76,         78, "pct",   1),
        ("Logo Churn",                    2.4,        1.8, "pct",   0),
        ("Sales Pipeline",         18_000_000, 20_000_000, "usd",   1),
        ("Headcount",                     264,        250, "count", 0),
        ("Cash Runway",                    19,         22, "months",1),
    ]
    path = os.path.join(OUT, "kpis.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["kpi", "period", "actual", "budget", "unit", "higher_is_better"])
        for name, actual, budget, unit, hib in march:
            w.writerow([name, "2026-03", actual, budget, unit, hib])
    return path


def write_customers():
    # Real customer names — must never reach the packet. Concentration is the signal.
    rows = [
        ("Northwind Health Systems", 15_190_000),
        ("Acme Logistics",            6_860_000),
        ("Globex Manufacturing",      4_410_000),
        ("Initech Software",          3_430_000),
        ("Umbrella Retail",           2_940_000),
        ("Soylent Foods",             2_450_000),
        ("Wayne Diagnostics",         1_960_000),
        ("Stark Robotics",            1_470_000),
    ]
    path = os.path.join(OUT, "customers.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["customer", "revenue"])
        w.writerows(rows)
    return path


def write_vendors():
    rows = [
        ("Amazon Web Services", 1_300_000),
        ("Salesforce",            420_000),
        ("WeWork",                330_000),
        ("Deloitte",              310_000),
        ("LinkedIn Recruiter",    290_000),
        ("Outside Counsel LLP",   180_000),
        ("Datadog",                90_000),
        ("Slack",                  60_000),
    ]
    path = os.path.join(OUT, "vendors.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["vendor", "spend"])
        w.writerows(rows)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    written = [
        write_scenario("actuals.csv", 3),
        write_scenario("budget.csv", 4),
        write_scenario("forecast.csv", 5),
        write_kpis(),
        write_customers(),
        write_vendors(),
    ]
    # Stamp the company identity into a sidecar the pipeline reads (kept local, never sent).
    with open(os.path.join(OUT, "company.txt"), "w") as fh:
        fh.write(COMPANY_NAME + "\n")
    for p in written:
        print("wrote", os.path.relpath(p, ROOT))
    print("wrote", os.path.relpath(os.path.join(OUT, "company.txt"), ROOT))


if __name__ == "__main__":
    main()
