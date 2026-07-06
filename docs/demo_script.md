# Demo Script (Section 33)

A 2-minute walkthrough that proves the core claim.

## Setup
```bash
cd privacy_tool
python3 scripts/generate_sample_data.py
python3 scripts/serve.py          # the unified product -> http://127.0.0.1:8770
```

## Narration

0. **Pick a dataset.** On the **Data** tab, click **Load sample dataset** (persistent) — or upload your
   own actuals/budget CSVs. This creates a stored dataset and runs the full pipeline.

1. **The setup.** "This is the March operating review for a fake company, Northstar Health Analytics.
   Real revenue, real customers, real vendors — none of which we want a frontier model to see."

2. **Obfuscation Preview tab.** "Left column is the real data, held locally. Right column is what the
   model receives. The company becomes ORG_001, $12.4M revenue becomes 100 index points, the top
   customer becomes CLIENT_001, March becomes P03."

3. **Privacy gate banner.** "Before anything leaves, every packet is scanned. Hard leaks: zero. Raw
   dollars sent: no. Real entities sent: no. Only then is it sent to the model."

4. **Outbound Packet tab.** "This is the *exact* JSON the model received. Search it — there is no
   company name, no customer, no vendor, no dollar sign. Just structure and percentages."

5. **Variance Dashboard tab.** "All the math — Subscription Revenue down $700K / 5.3%, Payroll up
   $335K / 6.9% — is computed locally and deterministically. The model never does finance math."

6. **Commentary Review tab.** "The model drafted commentary from the obfuscated packet. We rehydrate
   it for the authorized viewer, and show the local facts side by side. Nothing publishes without a
   human Approve."

7. **Board Narrative tab.** "A board-ready narrative. Notice the forecast section: the model recommended
   a *direction*; the dollar range — −$2.6M to −$1.6M this quarter — was computed locally."

8. **Audience switch → Board.** "Switch the audience to Board and the real customer name disappears —
   permission-aware rehydration."

9. **Close.** "Reasoning value preserved. Identification value destroyed. AI-native FP&A without
   exposing your financials to the model."
