# Code Review Checklist — Legal Doc AI PDF Pipeline

Anti-pattern → fix table for your codebase. Each fix includes a quality regression test proving the optimization doesn't degrade output.

---

## Anti-Pattern Table

| # | Anti-Pattern | Fix | Quality Regression Test | Impl | Test |
|---|---|---|---|---|---|
| 1 | **1-doc-at-a-time Python loop** — sequential `AI_PARSE_DOCUMENT` calls via connector, one file per iteration | Batch SQL over directory table: `SELECT ... FROM DIRECTORY(@PDF_STAGE)` drives a set-based procedure that processes all files in a single transaction | Assert per-call latency < 2x single-doc baseline (parallelism shouldn't make individual calls slower) | [`sql/99_compare_all.sql`](../sql/99_compare_all.sql) | [`scripts/benchmark.py`](../scripts/benchmark.py) — timing assertions |
| 2 | **Re-parsing same PDF on dev reloads** — every pipeline run calls `AI_PARSE_DOCUMENT` regardless of whether the file changed | File-hash cache: MD5 of (path + size + last_modified) → lookup in `PARSED_CACHE` before calling AI | `AI_SIMILARITY` between cached output and fresh parse = 1.000 (byte-identical by construction) | [`sql/11_cache_layer.sql`](../sql/11_cache_layer.sql) | [`eval/31_lever1_cache_identity.sql`](../eval/31_lever1_cache_identity.sql) |
| 3 | **OCR + LAYOUT on every doc** — running both parse modes when only one is needed for the document type | Smart routing: try LAYOUT first, check character yield (>500 chars = digital, skip OCR) | Routing agreement with always-both baseline ≥ 95%; numeric fidelity ≥ 99% | [`sql/12_smart_routing.sql`](../sql/12_smart_routing.sql) | [`eval/32_lever2_routing_agreement.sql`](../eval/32_lever2_routing_agreement.sql) |
| 4 | **claude-4-sonnet for routine scoring** — using a frontier model for straightforward binary classification (pick best extraction mode) | Cheaper model (claude-haiku-4-5) after A/B testing across 5 candidates with Pareto frontier analysis | Agreement with claude-4-sonnet on holdout corpus ≥ 95%; cross-family judge score ≥ 3.8/5.0 | [`sql/13_cheap_scorer.sql`](../sql/13_cheap_scorer.sql) | [`eval/33_lever3_model_matrix.sql`](../eval/33_lever3_model_matrix.sql) + [`eval/40_pareto_frontier.sql`](../eval/40_pareto_frontier.sql) |
| 5 | **Free-text JSON output + Python regex parse** — prompting for JSON in prose, then regex/`json.loads` with try/except retry loop | `response_format => TYPE OBJECT(best_mode STRING, confidence FLOAT, reasoning STRING)` — schema-guaranteed valid JSON, zero retries | Field-level identity ≥ 98% vs. free-text parsed output; JSON schema validation passes 100% (by construction) | [`sql/14_structured_outputs.sql`](../sql/14_structured_outputs.sql) | [`eval/34_lever4_structured_fielddiff.sql`](../eval/34_lever4_structured_fielddiff.sql) |
| 6 | **AI_COMPLETE over full doc per Q&A** — stuffing a 200-page PDF into context for every question | Embed + retrieve via Cortex Search: chunk (1500 chars/200 overlap), embed with `snowflake-arctic-embed-l-v2.0`, search top-5 chunks per question | Recall@5 ≥ 0.85; MRR ≥ 0.7; end-to-end answer similarity ≥ 90% of full-doc baseline | [`sql/15_embed_search.sql`](../sql/15_embed_search.sql) + [`sql/16_agent.sql`](../sql/16_agent.sql) | [`eval/35_lever5_retrieval_quality.sql`](../eval/35_lever5_retrieval_quality.sql) |
| 7 | **No cost telemetry** — no visibility into per-model, per-function AI spend over time | `CORTEX_FUNCTIONS_USAGE_HISTORY` views aggregated by function + model + day | No regression test needed (visibility only, doesn't change pipeline behavior) | [`sql/20_cost_telemetry.sql`](../sql/20_cost_telemetry.sql) | n/a |

---

## How to Apply

### Priority order (most savings first)

1. **Cache** (#2) — zero cost for dev reloads. Deploy immediately. No quality risk.
2. **Smart routing** (#3) — ~50% parse savings. Low risk (heuristic is conservative).
3. **Cheap scorer** (#4) — 85-95% scoring savings. Run the A/B matrix on your corpus first.
4. **Retrieval** (#6) — 90%+ Q&A savings. Requires one-time chunking + embedding + search service creation.
5. **Structured outputs** (#5) — 10-20% output savings. Quick change, but validate your actual retry rate first (if <3%, the lever is moot).
6. **Telemetry** (#7) — deploy the view regardless. It costs nothing and enables monitoring.
7. **Batch processing** (#1) — architectural lift but eliminates Python-loop overhead and enables warehouse auto-scaling.

### Testing each fix

Before deploying any lever to production:

1. Run the corresponding eval SQL on your held-out corpus
2. Check `EVAL_SUMMARY_V` for PASS/FAIL/MOOT per lever
3. If FAIL: examine `EVAL_PER_DOC` for which documents failed and why
4. Only deploy levers that pass all applicable quality gates

### Combining levers

Levers are designed to compose. The optimized pipeline runs:
```
PARSE_WITH_CACHE → SMART_PARSE → SCORE_STRUCTURED (haiku) → CHUNK_AND_EMBED → Cortex Search
```

Each lever's quality gate is measured independently (with prior levers active), ensuring the combined pipeline maintains quality at every step.

---

## What We Didn't Change

These decisions in your pipeline are correct and should stay:

- **X-Small warehouse** — Cortex AI functions are serverless; warehouse size affects only orchestration SQL, not AI compute. X-Small is appropriate for your volume.
- **SSE-encrypted stage** — Required for `AI_PARSE_DOCUMENT` compatibility. CME-encrypted stages are not supported.
- **claude-4-sonnet for the Cortex Agent** — The conversational Q&A agent needs reasoning depth for synthesis across chunks. The scoring step doesn't. Different tasks, different model requirements.
