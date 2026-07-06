"""End-to-end CLI demo (spec Sections 32, 33).

Runs the full gateway pipeline on the sample data and proves the core claim: the outbound packet
preserves reasoning value while removing identification value. Writes artifacts to output/.

Run: python3 scripts/run_demo.py [--period 2026-03] [--privacy-mode generalized_semantic_labels]
                                  [--llm mock|auto] [--role cfo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gateway.db import Database  # noqa: E402
from gateway.finance_core import load_package  # noqa: E402
from gateway.obfuscation import build_forbidden_terms, scan_for_leaks  # noqa: E402
from gateway.pipeline import format_money, run_pipeline  # noqa: E402

BAR = "=" * 70


def _preview_rows(model, result):
    """Build the side-by-side real -> LLM-safe preview (Screen 14.4)."""
    period = result.period
    base = None
    rows = [("Company name", model.organization, "ORG_001 (withheld)"),
            ("Reporting period", period, result.packet["periods"][-1] + " (abstracted)")]
    # a couple of account/value examples
    examples = ["Subscription Revenue", "Payroll", "Cloud Infrastructure", "Marketing Programs"]
    sm = {m["metric"]: m for m in result.packet["summary_metrics"]}
    from gateway.obfuscation.aliases import generalize_account
    for acct in examples:
        amt = model.amount("actual", period, acct)
        label = generalize_account(acct)
        idx = sm.get(label, {}).get("actual_index", "n/a")
        rows.append((f"Account: {acct}", format_money(amt), f"{label} = {idx} index pts"))
    if model.customers:
        rows.append(("Top customer", model.customers[0].name,
                     result.packet["customer_concentration"][0]["label"]))
    if model.vendors:
        top_v = max(model.vendors, key=lambda v: v.amount)
        rows.append(("Top vendor", top_v.name, result.packet["vendor_concentration"][0]["label"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="2026-03")
    ap.add_argument("--privacy-mode", default="generalized_semantic_labels")
    ap.add_argument("--llm", default="mock", choices=["mock", "auto", "openai"])
    ap.add_argument("--role", default="cfo")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "sample_data"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "output"))
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    model = load_package(args.data_dir)
    print(BAR)
    print("FINANCIAL SEMANTIC OBFUSCATION GATEWAY — end-to-end demo")
    print(BAR)
    print(f"Loaded: {len(model.facts)} facts, {len(model.kpis)} KPIs, "
          f"{len(model.customers)} customers, {len(model.vendors)} vendors")
    print(f"Company (local only): {model.organization}")

    result = run_pipeline(
        model, args.period,
        privacy_mode=args.privacy_mode, viewer_role=args.role, llm_preference=args.llm,
    )

    # 1. Obfuscation preview
    print("\n" + BAR + "\nOBFUSCATION PREVIEW  (real  ->  LLM-safe)\n" + BAR)
    print(f"{'Field':<28}{'Real (local)':<26}{'Sent to LLM':<28}")
    print("-" * 70)
    for field, real, safe in _preview_rows(model, result):
        print(f"{field:<28}{str(real):<26}{str(safe):<28}")

    # 2. Privacy gate
    print("\n" + BAR + "\nPRIVACY GATE\n" + BAR)
    forbidden = build_forbidden_terms(model, args.privacy_mode)
    leaks = scan_for_leaks(result.packet, forbidden)
    hard = [l for l in leaks if l.kind in ("raw_dollar", "entity_name", "company_name")]
    print(f"Packet risk level     : {result.risk.level.upper()} (score {result.risk.score})")
    print(f"Raw dollars sent?     : {'NO' if not result.risk.signals['contains_raw_dollars'] else 'YES'}")
    print(f"Real entities sent?   : {'NO' if not result.risk.signals['contains_real_entity_names'] else 'YES'}")
    print(f"Hard leaks found      : {len(hard)}  (must be 0)")
    print(f"Packet sent to LLM    : {'YES — ' + result.llm_provider if result.sent_to_llm else 'NO (gate blocked)'}")
    print(f"Output validation     : {'PASSED' if result.validation_ok else 'FAILED ' + str(result.validation_errors)}")

    # 3. Material issues
    print("\n" + BAR + "\nMATERIAL VARIANCES (local calculation)\n" + BAR)
    print(f"{'Severity':<10}{'Account':<24}{'Dept':<18}{'vs Budget':<14}{'%':<8}")
    print("-" * 70)
    for v in sorted(result.material_variances, key=lambda x: x.contribution_to_total_variance_pct, reverse=True):
        if v.severity in ("high", "medium"):
            pct = f"{v.variance_vs_budget_pct:.1f}%" if v.variance_vs_budget_pct is not None else "n/a"
            print(f"{v.severity:<10}{v.account:<24}{v.department:<18}"
                  f"{format_money(v.variance_vs_budget_amount):<14}{pct:<8}")

    # 4. Rehydrated commentary sample
    if result.review_items:
        print("\n" + BAR + "\nREHYDRATED COMMENTARY (sample — authorized view)\n" + BAR)
        ri = result.review_items[0]
        print(f"[{ri['severity'].upper()}] {ri['title']}  (status: {ri['status']})")
        print("AI draft : " + ri["draft_text"])
        if ri.get("local_facts"):
            lf = ri["local_facts"]
            print(f"Local facts: {lf['variance_vs_budget']} ({lf['variance_vs_budget_pct']}%), "
                  f"contribution {lf['contribution_to_total_variance_pct']}%")

    # 5. Persist + write artifacts
    db = Database(os.path.join(args.out_dir, "gateway_demo.db"))
    db.persist_run(result)
    db.close()

    with open(os.path.join(args.out_dir, "outbound_packet.json"), "w") as fh:
        json.dump(result.packet, fh, indent=2)
    with open(os.path.join(args.out_dir, "llm_response_obfuscated.json"), "w") as fh:
        json.dump(result.llm_response_obfuscated, fh, indent=2)
    with open(os.path.join(args.out_dir, "review_items.json"), "w") as fh:
        json.dump(result.review_items, fh, indent=2)
    with open(os.path.join(args.out_dir, "audit_log.json"), "w") as fh:
        json.dump(result.audit_log, fh, indent=2)
    with open(os.path.join(args.out_dir, "board_narrative.md"), "w") as fh:
        fh.write(result.board_markdown)

    print("\n" + BAR + "\nARTIFACTS WRITTEN to output/\n" + BAR)
    for f in ["outbound_packet.json", "llm_response_obfuscated.json", "review_items.json",
              "audit_log.json", "board_narrative.md", "gateway_demo.db"]:
        print("  output/" + f)
    print("\nDone. The board narrative carries real dollars (local); the AI saw only index points.")


if __name__ == "__main__":
    main()
