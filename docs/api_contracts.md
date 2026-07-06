# API Contracts (Section 15)

Stdlib HTTP backend. The unified product serves these endpoints **and** the dashboard UI:
`make serve` (or `python3 scripts/serve.py`) → `http://127.0.0.1:8770`. (`scripts/serve_api.py` runs the
same app on `:8780` if you want an API-only port.) All bodies/responses are JSON, except file upload
which takes a **raw CSV body** with query params (`?file_type=&filename=`) to avoid a multipart dependency.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | dashboard UI (single-page app) |
| GET | `/api/health` | liveness |
| GET | `/api/run?privacy_mode=&role=&period=&model_provider=` | stateless demo payload (no persistence) |
| POST | `/api/demo/seed` | create a dataset from bundled sample CSVs + run the pipeline |
| GET | `/api/datasets` | list datasets |
| POST | `/api/datasets` | create dataset |
| POST | `/api/datasets/{id}/files?file_type=&filename=` | upload a CSV (raw body) |
| POST | `/api/datasets/{id}/mappings` | save column mapping |
| POST | `/api/datasets/{id}/calculate` | local variance + materiality run (body: `period?`) |
| POST | `/api/datasets/{id}/obfuscation-runs` | build + risk-score the obfuscated packet (body: `period?`) |
| POST | `/api/datasets/{id}/run` | calculate + obfuscate + analyze in one (body: `period?`, `viewer_role?`, `model_provider?`) |
| POST | `/api/analysis-runs` | gate → LLM → validate → rehydrate → review items |
| GET | `/api/datasets/{id}/review-items?role=&period=` | list review drafts (rehydrated per role) |
| POST | `/api/review-items/{id}/approve` | approve a draft (body: `approved_text?`, `reviewer_id?`, `role?`) |
| GET | `/api/datasets/{id}/dashboard?role=&period=` | persisted dashboard payload for a dataset |
| POST | `/api/datasets/{id}/board-narrative` | generate board markdown from approved items (body: `period?`, `audience?`) |
| GET | `/api/datasets/{id}/audit` | audit trail |

`file_type` ∈ `actuals | budget | forecast | kpi | customer | vendor`.
`model_provider` ∈ `mock` (default) | `auto` (real OpenAI-compatible if `OPENAI_API_KEY` set, else mock).

## End-to-end with curl

```bash
B=http://127.0.0.1:8770
DS=$(curl -s -X POST $B/api/datasets \
  -d '{"name":"March Review","reporting_period":"2026-03","company_name":"Acme, Inc."}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['dataset_id'])")

for t in actuals budget forecast; do
  curl -s -X POST "$B/api/datasets/$DS/files?file_type=$t&filename=$t.csv" \
    --data-binary @sample_data/$t.csv >/dev/null; done
curl -s -X POST "$B/api/datasets/$DS/files?file_type=kpi&filename=kpis.csv" --data-binary @sample_data/kpis.csv

CID=$(curl -s -X POST $B/api/datasets/$DS/calculate | python3 -c "import sys,json;print(json.load(sys.stdin)['calculation_run_id'])")
OID=$(curl -s -X POST $B/api/datasets/$DS/obfuscation-runs -d "{\"calculation_run_id\":\"$CID\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['obfuscation_run_id'])")
curl -s -X POST $B/api/analysis-runs -d "{\"dataset_id\":\"$DS\",\"obfuscation_run_id\":\"$OID\"}"
curl -s $B/api/datasets/$DS/review-items
# approve a review item id, then:
curl -s -X POST $B/api/datasets/$DS/board-narrative -d '{"include_only_approved_items":true}'
```

## Guarantees enforced server-side
- `calculate`/`obfuscate` reject a dataset with no data for the period (clear 500 message, not a crash).
- The persisted `obfuscation_runs.packet_json` contains no raw dollars and no real entity names
  (verified by `tests/test_api.py::test_stored_packet_is_clean`).
- `analysis-runs` will not call the model if the packet fails the gate; the run is stored as `blocked`.
- No review draft is published; the board narrative defaults to approved-only items.
