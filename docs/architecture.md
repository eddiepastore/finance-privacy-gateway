# Architecture

## Principle
Preserve reasoning value, destroy identification value. The frontier model is an analyst/narrative
engine, never the system of record and never a source of financial truth.

## Layers
1. **finance_core** — ingest CSVs into a canonical model; compute variances, trends, materiality, and
   local forecast adjustments. Decimal math. *Nothing here is ever sent externally.*
2. **obfuscation** — the privacy core: Alias Vault (real⇄synthetic), value indexing against a hidden
   base, the unified `leak_scanner`, the packet risk gate, the Section 11 packet builder, and
   permission-aware rehydration.
3. **llm_client** — prompts, JSON schema, response validator, a deterministic MockLLM, and an
   OpenAI-compatible client. Swappable; the obfuscation contract is identical either way.
4. **pipeline** — orchestrates the gates in order and records an audit trail.
5. **api** — `repository` (SQLite lifecycle: datasets, files, mappings, calc/obfuscation/analysis runs,
   review items, board narratives, audit; self-healing `_migrate`), `service` (the nine Section-15
   operations + multi-period + view-time per-role rehydration), `app` (stdlib HTTP server that also
   serves the dashboard UI and the stateless `/api/run`). This is the unified product entry point.
6. **web** — the dashboard single-page app + `build_dashboard_payload` / `build_preview_rows` (shared,
   mode-aware) used by both the stateless and persisted paths.
7. **db** — the original lightweight SQLite helper used by the CLI demo (the API uses `api/repository`).

## The gate (non-negotiable)
```
ingest → calculate → classify materiality → obfuscate → RISK GATE → LLM → validate → rehydrate → review → board
```
`leak_scanner` is the single source of truth for "what must never leave," used by both the runtime
gate (`risk_scoring`) and the privacy-regression test. Hard leaks (raw dollars, real entity names)
block the send unconditionally; CRITICAL risk blocks; HIGH is sent-but-flagged for approval.

## Key invariants (enforced by tests)
- The outbound packet contains no raw dollars, no real entity names, no company name, no alias vault,
  and not the indexing base value.
- Real dollar values in user-facing output come only from local calculations, never from the model.
- No AI draft is published without human approval.
