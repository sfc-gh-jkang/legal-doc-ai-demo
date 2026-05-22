# Risk Register — Legal Doc AI AI Pipeline

## Summary

10 optimization levers, each with identified risks, probability assessments, and specific mitigations. Risk scores based on measured data from the 5-document benchmark corpus and eval framework results.

---

## Risk Matrix

| # | Lever | Risk | Probability | Impact | Mitigation | Owner | Status |
|---|-------|------|:-----------:|:------:|------------|-------|:------:|
| 1 | Parse Cache | Stale cache serves outdated extraction when source PDF is amended | Low | Medium | SHA256 keyed on file content (not filename); any byte change triggers fresh parse | Customer IT | Mitigated |
| 2 | Smart Routing | Scanned PDF misclassified as digital, producing garbled text via LAYOUT mode | Low | High | Confidence threshold at 0.95; documents below threshold route to OCR mode; `ROUTING_LOG` captures every decision for audit | Legal Doc AI Tech | Mitigated |
| 3 | Cheaper Scorer (haiku) | Quality degrades on multilingual or complex tabular documents not represented in the 5-doc eval corpus | Medium | High | Smart router sends non-English docs to claude-4-sonnet (gold); drift monitor detects degradation within 1 week; cross-judge bias report runs quarterly | Customer Compliance | Monitoring |
| 4 | Structured Outputs | Snowflake deprecates `response_format` parameter or changes JSON schema enforcement | Low | Low | Currently MOOT (free-text retry rate <3%); if re-enabled, fallback to prompt-only extraction with retry logic | Snowflake SE | Accepted |
| 5 | Retrieval (Cortex Search) | Recall degrades as corpus grows beyond 15 documents; chunk boundaries split critical legal clauses | Medium | Medium | Eval QA framework (30 pairs) reruns weekly via drift monitor; chunk overlap of 200 chars preserves clause continuity; recall@5 gate at 0.85 blocks promotion if violated | Legal Doc AI Tech | Monitoring |
| 6 | Cortex Agent | Agent hallucinates legal citations not present in corpus; user trusts fabricated references | Medium | Critical | Agent constrained to Cortex Search retrieval (no free generation); grounded Q&A eval validates factual accuracy; agent responses include source chunk references for human verification | Customer Compliance | Monitoring |
| 7 | Token Preflight | Overly aggressive blocking prevents processing of legitimately large but critical documents (e.g., 900-page Affordable Care Act) | Low | Medium | Block threshold at 2.5 credits logs to `PREFLIGHT_LOG` with `block` decision; manual override available; smaller docs (e.g., cfr_title12_part1_banking.pdf at 0.07 credits) pass freely | Customer IT | Mitigated |
| 8 | Completion Cache | Cache poisoning — incorrect completion cached and served repeatedly for identical prompts | Low | High | Cache keyed on exact prompt hash (SHA256); any prompt variation generates fresh completion; `TRUNCATE TABLE COMPLETION_CACHE` available as emergency purge; TTL-based expiry configurable | Customer IT | Mitigated |
| 9 | Batch Inference | SET-based batch call fails atomically — one malformed document in batch fails entire batch of 5 | Low | Low | Batch size limited to 5 documents; on batch failure, automatic fallback to sequential loop mode (14.0s vs 3.7s, same credits); `BATCH_DEMO_LOG` records both modes | Customer IT | Mitigated |
| 10 | Resource Monitor | Hard suspend at 100% cancels in-flight critical compliance query mid-execution | Low | Medium | 4-tier escalation (50% notify → 75% notify → 90% soft suspend → 100% hard suspend); soft suspend at 90% allows in-flight queries to complete; budget sized at 2x projected monthly spend | Customer Finance | Mitigated |

---

## Cross-Cutting Risks

| Risk | Probability | Impact | Mitigation | Owner |
|------|:-----------:|:------:|------------|-------|
| Model deprecation (claude-haiku-4-5 EOL) | Medium | Medium | Pareto frontier includes 4 alternative models; llama3.3-70b (89.5% savings) is next-best drop-in replacement | Snowflake SE |
| Snowflake AI credit pricing increase | Low | Medium | Resource monitor caps absolute spend regardless of rate changes; contract lock-in at current rates recommended | Customer Finance |
| Eval framework becomes stale (corpus no longer representative) | Medium | High | Corpus extended to 15 documents (fetch_corpus.py); quarterly corpus refresh from new filings; drift monitor alerts on quality degradation | Legal Doc AI Tech |
| Single-judge bias in eval scoring | Medium | Medium | Cross-judge bias report identifies mistral-large2 bias delta of 0.18 (HIGH_BIAS); multi-judge ensemble with majority vote recommended for production eval runs | Snowflake SE |
| pypdf extraction fails on future PDF format versions | Low | Low | Fallback to AI_PARSE_DOCUMENT automatically via `EXTRACTION_PATH_LOG` routing; pypdf failure logged, not fatal | Customer IT |
| Concurrent access contention on PARSED_CACHE during bulk loads | Low | Low | Table uses MERGE (upsert) pattern; Snowflake handles row-level locking; bulk loads batched at 5 docs | Customer IT |

---

## Risk Scoring Legend

| Probability | Definition |
|-------------|------------|
| Low | <15% chance of occurring in next 12 months |
| Medium | 15–50% chance of occurring in next 12 months |
| High | >50% chance of occurring in next 12 months |

| Impact | Definition |
|--------|------------|
| Low | Minor / <1 day recovery / negligible credit overspend |
| Medium | Noticeable degradation / 1–3 day recovery / moderate credit overspend |
| High | Significant impact / 3–7 day recovery / material credit overspend |
| Critical | >7 day recovery OR compliance exposure OR customer-impacting breach |

---

## Acceptance Criteria

- All "Mitigated" risks: mitigation implemented and tested in benchmark environment
- All "Monitoring" risks: drift monitor + eval framework configured to detect within 7 days
- All "Accepted" risks: documented trade-off acknowledged by the customer stakeholder
- No "Critical" impact risks without active monitoring in place

---

## Review Cadence

| Review | Frequency | Participants | Trigger for Ad-Hoc Review |
|--------|-----------|--------------|---------------------------|
| Drift monitor check | Weekly (automated) | System alert → Customer IT | Any dimension >5% drift |
| Cost telemetry review | Monthly | Customer Finance + IT | Spend exceeds 75% of monthly budget |
| Cross-judge bias refresh | Quarterly | Snowflake SE + Customer Compliance | New scorer model introduced |
| Corpus representativeness | Quarterly | Legal Doc AI Tech | >10 new document types filed |
| Full risk register review | Semi-annually | All stakeholders | Major pipeline architecture change |
