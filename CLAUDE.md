# CLAUDE.md — Finance Privacy Gateway

Guidance for AI coding sessions (and human contributors) working in this repo.

## Read first
1. `changelog.md` — the canonical session handoff, newest on top. Read the top 2–3 entries before
   changing anything.
2. `README.md` — user-facing; keep it accurate (verify test counts and feature claims before citing).
3. `docs/` — architecture, API contracts, threat model, demo script.

## Hard constraints
- **Pure Python 3.10+ standard library. No pip dependencies. Ever.** The zero-dependency design is a
  deliberate feature (auditability, deployability). The server is stdlib `http.server`.
- **The privacy gate is the product.** The packet risk gate and the privacy regression tests share the
  same leak-scanner code (`gateway/obfuscation/leak_scanner.py`) — never let runtime and tests drift
  apart. The privacy regression test is release-blocking; a red run means do not ship.
- The LLM must never see a real dollar figure or entity name. All rehydration happens locally,
  permission-aware at view time (e.g. CFO sees the real customer name; a board viewer sees a
  generalized label).

## Commands
- `make serve` (or `python3 scripts/serve.py`) → http://127.0.0.1:8770 (env: `GATEWAY_HOST`/`GATEWAY_PORT`)
- `python3 -m unittest discover tests` — full suite; must stay green
- Real-LLM mode is OpenAI-compatible (set `OPENAI_API_KEY`), with graceful mock fallback.

## Conventions
- Sample/synthetic data only — never commit real financial data.
- After meaningful work: run the test suite, then append a changelog entry (what was built /
  decisions / verification / next step — match the existing format).
