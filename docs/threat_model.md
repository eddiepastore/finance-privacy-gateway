# Threat Model (Section 19)

## Protected assets
Raw files, parsed facts, real dollars, vendor/customer/bank names, payroll & headcount, KPI data, the
alias vault, the indexing base amount, rehydrated reports, review comments.

## Threat actors
External LLM provider; over-curious provider employee; future model training/retention; unauthorized
internal user; compromised logs/DB; prompt injection in uploaded files; competitor obtaining a packet.

## Key threats & controls
| Threat | Control | Where |
|---|---|---|
| Model receives raw financials | Packet gate blocks raw dollars & real names | `obfuscation/risk_scoring.py`, `leak_scanner.py` |
| Model infers company identity | Entity aliasing + category generalization | `obfuscation/aliases.py`, `packet_builder.py` |
| Model infers company scale | Indexed values; base amount never sent | `obfuscation/indexing.py` |
| Model infers exact period | Period aliases P01/P02 (default on) | `packet_builder.py` |
| Model hallucinates numbers/entities | Response validator; local-only dollar insertion | `llm_client/validator.py`, `pipeline.py` |
| Unauthorized user sees customer names | Permission-aware rehydration | `obfuscation/rehydration.py` |
| Logs leak raw prompt | Store prompt hash by default (raw optional/encrypted) | `db.py` (`llm_requests.prompt_hash`) |
| Prompt injection via spreadsheet | Data-only parsing; raw memos not sent in MVP | `finance_core/normalization.py` |

## Residual risk
A highly unique company with unusual metrics can still be fingerprintable if too much detail is sent.
Mitigated by aggregation, privacy rounding, category abstraction, and high-risk packet blocking. For
the most sensitive workflows (M&A, fundraising, liquidity, layoffs) use local-only mode — no external
call at all.
