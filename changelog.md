# Changelog — Financial Semantic Obfuscation Gateway

Purpose: seamless handoff. If this session times out or another model picks up, read this file
top-to-bottom, then `README.md`, then `FULL_..._Spec.md`. Newest entries on top.

Format: each sprint records what was built, key decisions, how to run, and the exact next step.

---

## ✅ REAL-LLM VERIFICATION SPRINT 2026-07-06 — live end-to-end runs + robustness hardening (test suite 82/82)

First live verification of the real-LLM path (previously only the deterministic mock had ever run).
Exercised end-to-end against a local OpenAI-compatible endpoint (Ollama, `gpt-oss:20b`); repeated
runs now pass with real AI commentary flowing through obfuscation → LLM → validation → rehydration →
review items → board narrative. Every failure mode observed fails closed (validation refuses, or
visible mock fallback). A hosted-OpenAI attempt was blocked by account quota (`insufficient_quota`),
not by code; the protocol is identical.

**Found & fixed by live testing:**
- `LLMClient` timeout was hardcoded 60s (local models need more) → `GATEWAY_LLM_TIMEOUT` env,
  default unchanged.
- System prompt told the model to reference findings by `item_id` while the validator required
  `issue_id` → prompt corrected; user prompt now embeds the full response template
  (`prompts.RESPONSE_TEMPLATE`) instead of naming keys only.
- **Crash bug:** `build_board_markdown` assumed `risks_to_monitor` items are objects and
  `forecast_adjustment_recommendation` is always a dict — a schema-valid response with string risks
  crashed the pipeline after validation passed. Now renders both shapes.
- Review items read `summary` but the template asked for `commentary` → template aligned to the
  mock's field vocabulary (`summary`/`reason`), so real-model commentary actually reaches
  `draft_text`.

**New robustness layers (all engine-agnostic):**
- `normalize_response()` (validator.py): mechanical shape repair before strict validation — known
  contract keys in camelCase renamed, `item_id`→`issue_id`, `commentary`→`summary`,
  `rationale`→`reason`, bare-string forecast recommendation coerced to an object, string
  `board_narrative` wrapped as `{"draft": ...}`. Never invents content.
- Validation-guided single retry (pipeline.py): on a real-endpoint validation failure, the errors
  are sent back once via `build_repair_prompt`; mock is exempt (deterministic). Audit actions:
  `response_validation_retry` / `response_validation_retry_failed`.
- Decoder-enforced structured outputs (client.py): requests `response_format: json_schema`
  (`RESPONSE_JSON_SCHEMA`, strict) with graceful fallback to `json_object` on 400/404/422 or
  malformed content. Anti-hallucination checks caught a real incident during testing: a free-form
  response containing invented dollar figures was rejected by the validator.

**Verification:** 82/82 tests (new `tests/test_validator_normalization.py`); repeated live demo runs
with `--llm openai` against Ollama passing end-to-end. README "Use a real LLM" section updated with
local-endpoint config and the fail-closed contract. **Next step:** optional — verify against a
hosted OpenAI/Anthropic endpoint once an API key with quota is available (protocol-identical).

---

## ✅ REVIEW SPRINT 2026-07-02 — tab deep links + working "Request revision" (test suite 72/72)

Part of a cross-project executive review driven from a cross-project executive review of the finance apps'
operating desk. Two findings fixed: dashboard tabs were not URL-addressable
(blocked deep-linking from the desk), and the **Request revision** button in Commentary Review was a
dead control — no handler, no backend. Test suite is now **72/72** (was 71; +1 revision-flow test).

**Built:**
- **Hash-based tab deep links** (`gateway/web/static/index.html`): tabs map to slugs
  `#data #preview #variances #packet #review #board #audit`. Selecting a tab writes the hash via
  `history.replaceState`; opening a URL with a hash lands on that tab; a `hashchange` listener handles
  back/forward. Programmatic tab switches (seed, upload-and-run, generate board) also update the hash.
- **Request revision, end to end:**
  - `POST /api/review-items/{id}/request-revision` (route in `gateway/api/app.py`, body:
    `{reason, reviewer_id}`) → `ApiService.request_revision` → `Repository.request_revision_review_item`.
  - Sets status `revision_requested` and **withdraws any prior approval** (`approved_text`,
    `approved_by`, `approved_at` cleared) — conservative governance reading: a revised item must be
    approved again. Logs `review_item_revision_requested` with the reviewer's reason in the audit trail.
  - Board narrative generation with `include_only_approved_items` already filters on
    `status == "approved"`, so revision-requested items are excluded automatically.
  - UI wired: prompts for the reason, shows "↺ Revision requested — excluded from the board narrative
    until approved" with a re-approve button. In stateless demo mode it degrades to local state plus a
    local audit entry (no persistence, consistent with demo-mode approve).

**Verification:**
- `python3 -m unittest discover -s tests` → **72 tests OK**, including new
  `test_request_revision_reopens_item_and_excludes_it_from_board` (reopen, approval withdrawal, board
  exclusion, audit event, 404 on unknown id).
- Live HTTP smoke on port 8770: seeded dataset → request-revision → status `revision_requested`,
  audit event present; served index.html contains the slug/hash and revision wiring.

**Remaining caveats:**
- Revision reasons live only in the audit log; there is no per-item "revision notes" field shown on the
  review card yet.

---

## ✅ FP&A BRIDGE — new `POST /api/fpa/commentary` endpoint (real cross-app integration)

Added 2026-06-14 to make the FP&A app's AI commentary genuinely private from frontier LLMs. **Test
suite now 71/71** (was 66; +5 bridge tests).

- **`gateway/api/fpa_bridge.py`** (`fpa_commentary`): stateless — takes an already-computed FP&A variance
  set (no dataset/CSV/DB lifecycle), builds a CanonicalModel, runs the existing pipeline
  (`build_packet` → `score_packet`/`scan_for_leaks` gate → `get_client` mock/real → `validate_response`
  → `rehydrate_response`), and returns `{drafts, executive_summary, proof, outbound_packet}`.
  - Defaults to **high_privacy** so arbitrary FP&A account names are aliased to `CAT_###` (never sent).
  - **Augments the forbidden-term list** with every real account/department/company name as entity-level,
    so any leak HARD-blocks the send regardless of privacy mode (verified: `standard_finance` blocks).
  - `proof`: `packet_sha256`, `risk_level`, `raw_dollars_sent`, `real_entities_sent`, `provider`/`model`,
    `model_fallback`, `validation_ok`.
- **Route** added in `gateway/api/app.py` (`POST /api/fpa/commentary`).
- **`tests/test_fpa_bridge.py`** (5): no real names/$ in packet; clean+sent proof; rehydrated drafts;
  gate blocks a name-leaking mode; real-requested-without-key → mock fallback flagged.
- Verified over HTTP (gateway 8770) and through the FP&A Vite `/gw` proxy end-to-end.
- FP&A side (in the FP&A repo): `src/gatewayClient.ts`, `vite.config.ts` `/gw` proxy, and a Privacy Mode
  proof panel. See `FP&A/docs/PRIVACY_GATEWAY_INTEGRATION.md` and `FP&A/changelog.md`.

---

## ✅ CTO SPRINT 8 — COMPLETE: privacy controls, fallback clarity, publication gate, payload proof tools

Completed and verified 2026-06-14 as CTO sprint. Test suite is now **66/66 passing**.

**Built/fixed:**
- **Privacy selector now re-runs persisted datasets.** Changing privacy mode no longer only changes the stateless demo path; `/api/datasets/{id}/run` accepts `privacy_mode`, persists it, regenerates the obfuscated packet, and the UI includes **Re-run with selected privacy mode**.
- **Model fallback is explicit.** If Real/OpenAI-compatible is requested without a configured key or after endpoint failure, dashboard gate payload and banner surface `model_fallback=true` plus a clear **Mock fallback used** message.
- **Board publication gate added.** Board narrative generation now scans reviewer/local narrative output for real company/customer/vendor/bank names, returns `publication_gate`, and provides `safe_markdown` redaction for board-safe sharing.
- **Review queue ordering made CFO-prioritized.** Review items sort by severity, contribution to total variance, unfavorable priority, then title.
- **Packet proof tooling added.** Dashboard exposes a **Privacy Proof** panel, `policy_version`, `packet_sha256`, obfuscation `run_id`, created timestamp, copy/download JSON controls, and publication gate status.
- README quickstart test count updated to 66.

**Verification:**
- `python3 -m unittest discover -s tests` → **66 tests OK**.
- `make test && make demo` → passed; demo artifacts regenerated in `output/`.
- `python3 -m compileall .` → `compileall_ok=True`.
- Browser smoke at `http://127.0.0.1:8781` verified Privacy Proof panel, Outbound Packet copy/download controls, Board Narrative publication gate, Real-model fallback banner, and zero console/JS errors.

**Remaining caveats:**
- Real-LLM live run still requires Eddie-provided `OPENAI_API_KEY`/endpoint.
- Docker credential issue remains environmental from the Sprint-7 note.

---

## ⏸ AWAITING USER INSTRUCTION (Sprints 1–8 complete) — read this first

The autonomous build is **paused as planned** after Sprint 8. No cron jobs are scheduled; nothing will
run until you give direction.

**What this is:** a complete, runnable, **zero-dependency** (Python 3 stdlib) AI-native FP&A privacy
gateway. Local finance math → semantic obfuscation → privacy gate → frontier LLM (mock or real) →
response validation → permission-aware rehydration → human approval → board narrative, with multi-dataset
SQLite persistence, multi-period analysis, and a browser UI — all on one server.

**Run it:** `make serve` → http://127.0.0.1:8770 → Data tab →
**Load sample dataset** → walk the tabs. CLI proof: `make demo`. Tests: `make test` (**71 passing**,
incl. the release-blocking privacy regression and the FP&A bridge endpoint).

**Post-Sprint-7 note (2026-06-14):** moved the gateway's default port **8765 → 8770** to avoid colliding
with an unrelated `http.server --directory web` (another local static server) that was already on 8765. Updated
`scripts/serve.py`, README, `docs/api_contracts.md`, `docs/demo_script.md`, `Dockerfile`, `Makefile`.
`GATEWAY_PORT`/positional-arg overrides still work. (`scripts/serve_api.py` stays on 8780.)

**Two known caveats (environmental, not code bugs):**
1. `docker build` fails in this WSL env — Docker references `docker-credential-desktop.exe` (not on
   PATH). Fix on host: remove `"credsStore": "desktop.exe"` from `~/.docker/config.json` (or `docker
   logout`), then `make docker-build`. The Dockerfile is correct (stdlib-only; local serve verified).
2. Real-LLM not live-tested — no `OPENAI_API_KEY` here. Wired + fallback-tested; set the key and pick
   **Real** in the UI Model selector to use it.

**Suggested next options (your call):**
- Have me fix the local Docker cred config (needs your OK to edit `~/.docker/config.json`) and verify the build.
- Provide an `OPENAI_API_KEY` (or a local OpenAI-compatible endpoint) so I can run a real-LLM live smoke.
- Polish for portfolio/demo: a short screen capture, a one-page case study, or push to a git repo.
- New features: Excel ingest (needs `openpyxl` — blocked while pip is disabled), more KPIs/charts,
  scenario/what-if, or multi-user auth.

Per-sprint detail is below (newest first).

---

## ⭐ SPRINT 7 — COMPLETE: packaging + demo/docs polish

Started early (user override), then user said finish in one go (cron cancelled). **59/59 tests green.**

**Packaging:**
- `Dockerfile` (zero-dependency `python:3.12-slim`, no pip; generates sample data at build),
  `Makefile` (`serve|demo|test|data|docker-build|docker-run|clean`), `.dockerignore`,
  README **"Run in 30 seconds"**. Server honors `GATEWAY_HOST`/`GATEWAY_PORT` (default `127.0.0.1`;
  Docker sets `0.0.0.0`).

**Demo/docs polish:**
- README Status now reflects Sprints 1–7 + correct test count (59); `make serve` is the headline entry.
- `docs/api_contracts.md`: primary entry is `serve.py`/`:8770`; endpoint table now lists `/`, `/api/run`,
  `/api/demo/seed`, `/api/datasets`, `/api/datasets/{id}/run`, `/api/datasets/{id}/dashboard`, plus the
  `period`/`role`/`model_provider` params. `docs/architecture.md`: added the `api` layer + shared preview.
- UI empty-states for periods with no material variances (Variance + Commentary tabs no longer blank).

**Caveats:** docker-build host cred issue and no-API-key (both documented in the pause note above).

---

## ⭐ SPRINT 6 — COMPLETE: high-privacy rendering + in-browser column mapping

Both Sprint-5-deferred tasks landed and are verified over HTTP. **59/59 tests green.**

**(2) High-privacy `CAT_###` + descriptor rendering.** Consolidated the obfuscation-preview into ONE
mode-aware builder, `gateway/web/api.py::build_preview_rows` (used by both the stateless and persisted
paths via a rebuilt deterministic vault). In `high_privacy` the preview now shows e.g. `Account: Payroll
→ CAT_004 · recurring people operating cost = 36.4 idx · real name withheld`; the Outbound Packet uses
`CAT_###` categories + `category_descriptor`. Verified the high-privacy packet still passes the leak
scanner (0 hard leaks). For authorized internal viewers, commentary rehydrates `CAT_###`→real account
(privacy is about the model, not the viewer). Deleted the duplicate `_preview_rows` in service.py.

**(3) In-browser Column-Mapping screen.** The Data tab is now a two-phase flow: **Upload & map columns**
→ the dashboard shows a per-file mapping grid (source header → `account`/`account_type`/`department`/
`period`/`amount`, with sensible auto-guesses) → **Save mappings & run pipeline** (POSTs each mapping to
`/api/datasets/{id}/mappings`, then `/run`). Verified over HTTP: a dataset with non-canonical headers
("GL Name", "Team", "Month", …) fails to compute *without* mapping and finds the 2 material variances
*with* mapping. New test `test_column_mapping_enables_noncanonical_headers`.

Also: `_preview_rows` is now shared (no drift); board permissions stay realistic; new tests for
high-privacy preview + mapping. **Per user pacing: Sprint 6 ends here; a 5-hour wait precedes Sprint 7.**

---

## ⭐ SPRINT 5 — task (1) COMPLETE: real LLM wired through the UI

Real OpenAI-compatible LLM runs are now selectable from the dashboard. **57/57 tests green.**

- Header **Model** control (Mock / Real OpenAI-compatible), threaded as `model_provider` through
  `/api/run`, `/api/demo/seed`, `/api/datasets/{id}/run`, `/api/analysis-runs` into `get_client`.
- The gate banner now shows the **provider + model** actually used (e.g. `mock · mock-fp&a-analyst-v1`
  or `openai_compatible · gpt-4o-mini`). `llm_model` added to `PipelineResult` and both gate payloads.
- **Graceful fallback** (verified over HTTP): requesting "Real" with no `OPENAI_API_KEY` falls back to
  the deterministic mock; a real-endpoint exception also falls back (try/except in both `pipeline.run_pipeline`
  and `service.analyze`, logged as `llm_request_failed`). To use a real model: set `OPENAI_API_KEY`
  (+ optional `OPENAI_BASE_URL`, `GATEWAY_MODEL`) and pick "Real" in the UI.
- Tests added: gate surfaces provider+model; `get_client("auto")` → mock without a key.

**Deferred to Sprint 6 (were Sprint-5 tasks 2 & 3):** High-privacy `CAT_###`+descriptor rendering in
the Obfuscation Preview/commentary; an in-browser column-mapping screen driving `/api/datasets/{id}/mappings`.

**Per user pacing:** Sprint 5 ends here.

---

## Pacing (re-updated by user 2026-06-14, mid-Sprint-5)

- Finish Sprint 5 with ~20k more tokens, **then wait 4 hours** before Sprint 6.
- **Sprint 6: 100,000 tokens**, then **wait 5 hours** before Sprint 7.
- **Sprint 7: 100,000 tokens**, then **PAUSE and wait for user instruction** (do NOT auto-schedule Sprint 8).
- 4h/5h waits exceed ScheduleWakeup's 1h cap → use `CronCreate` one-shot jobs at the target time.

---

## ⭐ SPRINT 4 — COMPLETE & VERIFIED: multi-period + view-time rehydration (read this first)

Two real features landed, both verified end-to-end over HTTP. **55/55 tests green.**

**(c) Multi-period.** `period` is now threaded through calculate → obfuscate → analyze → dashboard
and persisted per run/review-item (schema migrated with a self-healing `_migrate()` that ALTERs older
DBs). The dashboard has a **Period selector** (Jan/Feb/Mar in the sample). Periods are isolated:
running 2026-01 leaves 2026-03's review items intact (verified). On-plan months correctly show 0
material variances. `dashboard`/`review-items`/`run`/`board-narrative` all accept `period`.

**(a) View-time per-role re-rehydration (resolves the Sprint-3 limitation).** Review-item text is now
**stored OBFUSCATED** and rehydrated **per requested role at read time** (`list_review_items(role)`,
`dashboard_payload(role)`, `approve(role)`, `board_narrative(audience)` all rebuild the deterministic
vault and rehydrate). Verified: a draft stored with `DEPT_xxx` is rehydrated to the real department
for CFO on read; and in the board narrative the top customer shows as the real name for **CFO** but as
**"Top Customer 1"** for **Board** (`tests/test_web_api.py::test_view_time_role_rehydration_board_vs_cfo`).
Board permissions made realistic (see structure: accounts/departments; redact customers/vendors/banks).
The mock LLM now cites the top customer by alias so the redaction is demonstrable.

**Files touched:** `gateway/api/repository.py` (period columns + `_migrate` + `get_review_item` +
`delete_review_items` + period-filtered `latest_*`/`review_items`), `gateway/api/service.py` (period
threading, store-obfuscated, `_rebuild_vault`, view-time rehydration in list/approve/board/dashboard,
`available_periods`), `gateway/api/app.py` (period/role query+body params), `gateway/web/api.py`
(`available_periods`), `gateway/web/static/index.html` (Period selector + wiring), `gateway/llm_client/
mock_llm.py` (customer-concentration line), `gateway/obfuscation/rehydration.py` (realistic board perms).

**Op note:** delete a stale `output/gateway_api.db` from older sprints if present — `_migrate()` now
heals it automatically, but the demo DBs were cleared during this sprint.

**NEXT (Sprint 5, ~150k tokens):** options — real OpenAI-compatible run wired through the UI (Settings
toggle + `OPENAI_API_KEY`); High-privacy `CAT_###`+descriptor rendering in the UI; CSV column-mapping
screen in the browser (endpoint exists); Excel ingest (needs openpyxl — defer, pip blocked); a
Dockerfile + a short screen capture. Recommend the real-LLM toggle first (biggest credibility win).

---

## ⭐ SPRINT 3 — COMPLETE & VERIFIED: one unified product

The two servers are now **one product**. `python3 scripts/serve.py` (port 8765) serves the dashboard
UI **and** the Section-15 API **and** persistence — a user can upload CSVs in the browser (or one-click
"Load sample dataset") and get a persisted dataset with variances, the obfuscated packet, AI review
drafts, human approval, and a board narrative.

**Verified end-to-end over HTTP:** GET / (dashboard), /api/run (stateless demo), POST /api/demo/seed →
persisted dataset, GET /api/datasets/{id}/dashboard (0 hard leaks, 14 review items), approve, board
narrative (local dollars), board-role customer redaction. Zero server errors. **51/51 tests green**
(added 3 unified-dashboard tests).

**What changed:**
- `gateway/api/app.py` now also serves the static dashboard (`/`), the stateless `/api/run`, and new
  endpoints: `POST /api/demo/seed`, `POST /api/datasets/{id}/run` (calculate+obfuscate+analyze in one),
  `GET /api/datasets/{id}/dashboard` (persisted dashboard payload), `GET /api/datasets`.
- `gateway/api/service.py`: `seed_sample_dataset`, `run_pipeline_steps`, `dashboard_payload` (rebuilds
  the dashboard view from persisted state), plus a persisted `_preview_rows`.
- `gateway/api/repository.py`: `latest_obfuscation_run` / `latest_analysis_run` /
  `latest_board_narrative` / `list_datasets`.
- `gateway/web/static/index.html`: new **Data** tab (seed + file-upload flow), persisted mode, real
  Approve (`/api/review-items/{id}/approve`) and **Generate board narrative** button.
- `scripts/serve.py` now launches the unified product (was the stateless-only demo server). The old
  `gateway/web/server.py` is legacy/unused but left in place; `scripts/serve_api.py` still works (8780).

**Known limitation (documented, not a bug):** in persisted mode, review-item text is rehydrated at
*analysis* time for the analyzing role (default CFO); the dashboard's role selector changes the
*board-narrative* audience and the stateless demo, but does not re-redact already-stored drafts. Full
view-time multi-audience re-rehydration (rebuild vault on read) is a future enhancement. The hard
privacy guarantee (packet has no real entities/dollars) holds regardless and is enforced by tests.

**NEXT (Sprint 4, ~150k tokens):** options — (a) view-time per-role re-rehydration in persisted mode;
(b) real OpenAI-compatible run through the UI (`--llm auto`, needs OPENAI_API_KEY); (c) multi-period
selector (sample data already has 2026-01..03); (d) High-privacy `CAT_###`+descriptor rendering in UI;
(e) packaging/Dockerfile + a short screen-capture demo. Recommend (c) then (a).

---

## ⭐ SPRINT 1 FINAL — COMPLETE & VERIFIED (read this first)

A fully runnable, dependency-free (stdlib Python 3.12) AI-native FP&A privacy gateway. Proves the
spec's core thesis: the outbound LLM packet preserves reasoning value while removing identification
value. **43/43 tests green**, including the release-blocking privacy regression.

**Delivered:** finance engine (variance/materiality/trends/**local forecast adjustment**), semantic
obfuscation (aliases, value indexing, unified leak scanner, risk gate, packet builder, permission-aware
rehydration), mock + OpenAI-compatible LLM client, response validator, human-review drafts, board
narrative, SQLite audit trail, synthetic dataset, **CLI demo**, **dependency-free web dashboard**, and
`docs/` (architecture, threat model, demo script).

**Run it:**
```bash
cd <repo root>
python3 scripts/generate_sample_data.py
python3 scripts/run_demo.py            # MEDIUM risk, 0 hard leaks, SENT, validation PASSED
python3 scripts/serve.py               # dashboard at http://127.0.0.1:8765
python3 -m unittest discover -s tests  # 43 passing
```

**SPRINT 2 (DONE):** Section 15 REST backend on stdlib (`gateway/api/`), full multi-dataset lifecycle
persisted in SQLite, verified end-to-end over HTTP, **48/48 tests**. Run: `python3 scripts/serve_api.py`.
See the "Sprint 2 — COMPLETE" section below and `docs/api_contracts.md`.

**NEXT (Sprint 3, ~150k tokens):** recommended = wire the `gateway/web` dashboard to the persistent
API (Upload + Map-Columns screens driving real endpoints) so the two servers become one product. The
dashboard JS already renders all the result sections; it needs an upload flow + a "run pipeline"
trigger hitting `/api/datasets...`. Alternatives: real OpenAI-compatible run through the API; Excel
ingest (needs openpyxl — not installable here, so defer); High-privacy `CAT_###` descriptor rendering.

---

## Sprint 1 — STRETCH delivered: dependency-free web UI ✅

Built a local dashboard with **zero dependencies** (stdlib `http.server`), since FastAPI/Next.js would
need installs. Covers the Section 14 screens as tabs: Obfuscation Preview (real→LLM-safe), Variance
Dashboard, **Outbound Packet** (the exact JSON the model receives — "make trust visible"), Commentary
Review (AI draft + local facts side-by-side, Approve action), Board Narrative (rendered markdown),
Audit Log. Live controls for privacy mode + audience role; a prominent privacy-gate banner.

- `gateway/web/api.py` (payload builder, pure fn), `gateway/web/server.py` (routes incl. POST approve),
  `gateway/web/static/index.html` (single-page app), `scripts/serve.py` (launcher).
- Run: `python3 scripts/serve.py` → http://127.0.0.1:8765
- Smoke-tested: GET /, GET /api/run (medium risk, 0 hard leaks, sent, valid), POST approve, and
  **board-audience customer redaction verified** (no real customer names surface to the board view).
- **39/39 tests green** (added `tests/test_web_api.py`).

This means the morning review has a clickable UI, not just a CLI. Sprint 1 over-delivered vs plan.

---

## Pacing (re-updated by user 2026-06-14, mid-build)

- Sprint 1 ran to 160k tokens (done). User then said **skip the 15-min wait** and continue.
- **This Sprint 2 continuation: ~100,000 tokens**, building now (no wait).
- **Every sprint after that: ~150,000 tokens.** (Earlier 5.2h-gap instruction superseded by "build now"; treat sprints as continuous unless the user re-introduces waits.)
- Note: a 15-min `ScheduleWakeup` from before may still fire; if it does mid-build, just keep going.

---

## Sprint 2 — Section 15 REST API backend ✅ COMPLETE & VERIFIED

Full stateful backend over the gateway core, stdlib-only, persisted in SQLite. **Verified end-to-end
over HTTP**: create dataset → upload 6 CSVs → calculate (14 material / 8 high / 5 medium) → obfuscate
(MEDIUM risk, no raw dollars, no real entities) → analyze (14 review items, validation ok) → approve
→ board narrative (approved-only, local dollars present). Zero server errors. **48/48 tests green**
(added `tests/test_api.py`, 6 lifecycle tests incl. stored-packet-is-clean + column-mapping-applied).

**New files:** `gateway/api/repository.py` (SQLite lifecycle: datasets, files, mappings, calc/obf/
analysis runs, review items, board narratives, audit), `gateway/api/service.py` (the 9 ops; rebuilds
the model deterministically from uploaded files; reuses pipeline helpers), `gateway/api/app.py`
(stdlib HTTP router; raw-CSV upload via query params, no multipart dep), `scripts/serve_api.py`,
`docs/api_contracts.md`.

**Robustness fix:** `calculate`/`obfuscate` now reject a dataset with no data for the period with a
clear message instead of a cryptic `KeyError` (added `_require_data`). Found via the HTTP smoke test.

**Endpoints:** see `docs/api_contracts.md`. Run: `python3 scripts/serve_api.py` (port 8780).

**NEXT (next sprint, ~150k tokens):** Sprint 3 options — (a) point the `gateway/web` dashboard at the
persistent API so the UI drives real datasets (upload screen + map-columns screen wired to endpoints);
(b) real OpenAI-compatible LLM run through the API; (c) Excel ingest; (d) High-privacy `CAT_###`
descriptor rendering in the UI. Recommend (a) first — unifies the two servers into one product.

### original notes:
## Sprint 2 — Section 15 REST API backend (build notes)

**Decision (CTO):** FastAPI is not installed and pip is blocked (PEP 668 externally-managed env).
To preserve the zero-install-risk guarantee, the Section 15 API is built on the **stdlib http.server**
with full multi-dataset persistence in SQLite. Same contracts the spec specifies; no dependencies.

**Approach:** a `gateway/api/` package — `repository.py` (SQLite data access for the whole dataset
lifecycle), `service.py` (the 9 Section-15 operations, reusing the `gateway/` core), `app.py` (stdlib
HTTP router incl. multipart upload). Each step persists its artifact (uploaded files, mappings,
calculation/obfuscation/analysis runs, review items, board narratives, audit events). The model is
rebuilt deterministically from uploaded files per call (aliasing is insertion-order stable), so
rehydration stays consistent without serializing the vault.

---

## Sprint 1 — Core engine + obfuscation + mock-LLM pipeline ✅ COMPLETE (core)

**Result:** Full pipeline runs end-to-end on synthetic data. `run_demo.py` → MEDIUM risk, **0 hard
leaks**, packet SENT to mock LLM, output validation PASSED, rehydrated board narrative with real local
dollars, 10-step audit trail. **35/35 tests green**, including the release-blocking privacy regression.

**Verified facts (sample data, 2026-03):** Subscription Revenue −$700K/−5.3%, Payroll +$335K/+6.9%,
Cloud +$250K/+23.8%, Marketing −$250K/−22.7% (favorable). LLM packet carries only index points + %s.

**Bugs found & fixed during verification:**
- Leak scanner false positives (generic words "sales"/"travel" inside safe generalized labels) →
  restricted forbidden list to high-specificity identifiers (entities + company + raw dollars) +
  word-boundary matching. Departments are aliased by construction; account generalization verified by test.
- Gate over-blocked small datasets (low-row-count signal) → default block threshold = `critical`
  (spec 10.2: High = "approve", Critical = "block"); hard leaks always block. High is logged for approval.
- KPI trend wording for inverse metrics (churn) → `favorable_to_plan` / `unfavorable_to_plan`.
- Board "Performance vs Plan" now shows absolute magnitude (favorability word carries direction).

**Files:** see "Build order" below — all delivered. README.md written (demo script + guarantee).

### Original build order (this sprint)

**Goal:** Prove the spec's core thesis (Section 32) — the outbound LLM packet preserves reasoning
value while removing identification value — with a fully runnable, stdlib-only Python pipeline and
an end-to-end CLI demo, covered by tests including a hard privacy-regression gate.

**Stack decision (CTO):** Pure stdlib Python 3.12 (`csv`, `sqlite3`, `dataclasses`, `json`,
`decimal`, `hashlib`, `re`). No pandas/pydantic/fastapi yet — guarantees it runs tonight with zero
install/network risk. FastAPI + Next.js layer is deferred to a later sprint, built on this proven core.
This matches the spec's Engineering Priorities (Section 32): engine first, UI last.

**Material improvements over spec (executive decisions):**
- `Decimal` money math (no float penny drift).
- One shared `leak_scanner` is BOTH the runtime packet gate and the privacy-regression test — keeps
  enforcement and testing from drifting apart.
- End-to-end CLI (`scripts/run_demo.py`) so the whole pipeline is demonstrable without a browser.
- Customer/vendor concentration included in V1 (spec deferred to V2) — sample data supports it.
- Adopted spec's recommended answers for all open decisions (Section 35).

**Status:** see entries below as files land.

### Build order (this sprint)
1. [x] Project meta (README, .gitignore, changelog)
2. [x] Synthetic sample dataset + generator
3. [x] finance_core: normalization, calculations, materiality
4. [x] obfuscation: aliases, indexing, leak_scanner, risk_scoring, packet_builder, rehydration
5. [x] llm_client: schemas, prompts, mock_llm, validator, client
6. [x] pipeline orchestrator + SQLite persistence/audit log
7. [x] CLI demo runner
8. [x] tests (calc, materiality, obfuscation/privacy, rehydration, e2e) — 35/35 green
9. [ ] STRETCH (budget permitting): dependency-free local web UI (stdlib http.server) for the
       Section 14 screens — obfuscation preview, variance dashboard, commentary review, board narrative

### How to run (once built)
```bash
cd <repo root>
python3 scripts/generate_sample_data.py      # writes sample_data/*.csv
python3 scripts/run_demo.py                   # full pipeline -> output/
python3 -m unittest discover -s tests -v      # test suite
```

### Next step for whoever resumes
If Sprint 1 incomplete: continue at the first unchecked box above.
If Sprint 1 complete: Sprint 2 = FastAPI backend exposing Section 15 API contracts over this core,
then Sprint 3 = Next.js UI (Section 14 screens). Real OpenAI-compatible client to replace/augment mock.
