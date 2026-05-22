---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section {
    font-family: 'Inter', 'Segoe UI', sans-serif;
  }
  h1, h2, h3 {
    color: #11567f;
  }
  section.lead h1 {
    color: #29b5e8;
    font-size: 2.5em;
  }
  section.lead h2 {
    color: #11567f;
    font-size: 1.2em;
    font-weight: normal;
  }
  table {
    font-size: 0.7em;
  }
  code {
    background: #f0f4ff;
    color: #11567f;
  }
  .savings {
    color: #4caf50;
    font-weight: bold;
  }
---

<!-- _class: lead -->

# Optimizing Cortex AI Costs Without Sacrificing Quality

## US Regulatory & Regulatory Committee — Legal PDF Pipeline

John Kang · Snowflake Solutions Engineering
<!-- TODO: fill date -->

---

# Your Current Pattern

```
PDF → AI_PARSE_DOCUMENT(OCR)     ─┐
                                   ├─→ AI_COMPLETE(claude-4-sonnet) → "best mode" → result
PDF → AI_PARSE_DOCUMENT(LAYOUT)  ─┘
```

**What's happening:**
- Every PDF runs **both** parse modes (~1.57 credits/doc — OCR ~0.21 + LAYOUT ~1.36)
- `claude-4-sonnet` scores both extractions (~0.007 credits/doc, 4K-char prompt)
- Dev reloads re-parse all 260 documents from scratch
- Q&A stuffs full documents into context (~0.04 credits/question, 50K-char context)

**Total per-doc baseline:** ~1.58 credits ingest + ~0.04 credits per Q&A question

> Numbers measured on the 9-doc federal-regulatory corpus via `ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY`.

---

# The 6-Lever Framework

| # | Lever | Savings Target | Risk Level |
|---|---|---|---|
| 1 | Parse cache (hash dedup) | 100% on repeats | None |
| 2 | Smart routing (digital→LAYOUT only) | ~13% on this all-digital corpus; up to ~87% on OCR-routed docs | Low |
| 3 | Cheaper scorer (haiku vs sonnet) | 85-95% on score | Low |
| 4 | Structured outputs (response_format) | 10-20% on output | None |
| 5 | Embed + Cortex Search (retrieval Q&A) | 90%+ on Q&A | Medium |
| 6 | Cost telemetry (usage views) | Visibility | None |

Each lever has an independent quality gate.
No lever ships without passing all 3 eval layers.

---

# Quality Didn't Move

**3-layer eval framework:**

1. **Quantitative** — `AI_SIMILARITY` vs gold reference (per-doc mean/p10/p50/p90)
2. **LLM-as-Judge** — cross-family scoring (Claude ↔ Mistral) on 4 rubric dimensions
3. **Domain Spot-Check** — programmatic: defined-term count, numeric fidelity, table integrity

<!-- TODO: insert chart from benchmark run — cost on X, quality on Y, Pareto frontier labeled -->

**Cross-family judging eliminates self-preference bias** (Zheng et al. 2023):
a model never evaluates its own output.

---

# Lever 1: Parse Cache

**Mechanism:** MD5(path + size + last_modified) → lookup `PARSED_CACHE` → skip AI call on hit

**Savings:** 100% on dev reloads (260 docs × 2 modes = 520 calls → 0)

**Quality gate:** `AI_SIMILARITY = 1.000` (byte-identical by construction)

**Status:** <!-- TODO: PASS/FAIL -->

```sql
-- From sql/11_cache_layer.sql
CALL PARSE_WITH_CACHE('customer_bylaws.pdf', 'LAYOUT');
-- Returns: {"source": "cache", "tokens_saved": 12500}
```

---

# Lever 2: Smart Routing

**Mechanism:** Try LAYOUT first → if character yield >500 chars, doc is digital (skip OCR). Low yield → fall back to OCR.

**Savings:** ~50% on parse step (digital docs skip OCR entirely; LAYOUT probe becomes the result)

**Quality gate:** routing agreement ≥ 95% | p10 similarity ≥ 0.85 | numeric fidelity ≥ 99%

**Status:** <!-- TODO: PASS/FAIL -->

Your corpus is predominantly digital (bylaws, charter, codes).
Only older scanned CAS rulings route to OCR.

---

# Lever 3: Cheaper Scorer

**Mechanism:** Replace `claude-4-sonnet` with `claude-haiku-4-5` for "which extraction is better?" scoring.

**Savings:** 85-95% on scoring step (0.000012 → 0.000001 credits/token)

**Quality gate:** Agreement with gold ≥ 95% | Pareto frontier non-empty | cross-judge ≥ 3.8/5.0

**Status:** <!-- TODO: PASS/FAIL -->

| Model | Credits/token | Agreement | On Frontier |
|---|---|---|---|
| claude-4-sonnet | 0.000012 | 100% (ref) | <!-- TODO --> |
| claude-haiku-4-5 | 0.000001 | <!-- TODO --> | <!-- TODO --> |
| mistral-large2 | 0.000005 | <!-- TODO --> | <!-- TODO --> |

---

# Lever 4: Structured Outputs

**Mechanism:** `response_format => TYPE OBJECT(best_mode STRING, confidence FLOAT, reasoning STRING)` — guaranteed valid JSON, zero retries.

**Savings:** 10-20% on output tokens (eliminates retry loop)

**Quality gate:** Field identity ≥ 98% | Free-text retry rate ≥ 3% (else MOOT)

**Status:** <!-- TODO: PASS/FAIL/MOOT -->

If your prompts already produce valid JSON 97%+ of the time, this lever saves almost nothing. We measure your actual retry rate to determine if it's worth claiming.

---

# Lever 5: Embed + Cortex Search

**Mechanism:** Chunk (1500 chars, 200 overlap) → embed (`snowflake-arctic-embed-l-v2.0`) → Cortex Search Service → retrieve top-5 chunks per question.

**Savings:** 90%+ on Q&A (50,000 tokens/question → 1,875 tokens/question)

**Quality gate:** Recall@5 ≥ 0.85 | MRR ≥ 0.7 | E2E similarity ≥ 90% of full-doc

**Status:** <!-- TODO: PASS/FAIL -->

```sql
-- sql/15_embed_search.sql
CREATE CORTEX SEARCH SERVICE LEGAL_DOC_AI_SEARCH
    ON chunk_text
    ATTRIBUTES doc_name, page_no
    TARGET_LAG = '1 hour'
    AS SELECT chunk_text, doc_name, page_no FROM LEGAL_CHUNKS;
```

---

# Lever 6: Cost Telemetry

**Mechanism:** `CORTEX_FUNCTIONS_USAGE_HISTORY` → daily-aggregated view by function + model

**Savings:** None directly — visibility enables ongoing optimization

```sql
-- sql/20_cost_telemetry.sql
SELECT usage_date, FUNCTION_NAME, MODEL_NAME,
       call_count, total_tokens, total_credits
FROM DAILY_AI_COST
ORDER BY usage_date DESC;
```

Monitor for: parse call spikes (cache bypass), sonnet calls (scorer fallback), embed volume vs. upload cadence.

---

# Cumulative Savings Projection

| Scenario | Baseline | Optimized | Reduction |
|---|---|---|---|
| 1 new document (parse + score + embed) | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| 260-doc dev reload | <!-- TODO --> | ~0 (cached) | ~100% |
| Annual production (1,825 docs) | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| Annual Q&A (10 questions/doc/year) | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

*All numbers populated by `scripts/benchmark.py` after deployment.*

---

# Where You Go Next

**Already built:**
- `LEGAL_DOC_AI_SEARCH` — Cortex Search Service over chunked corpus
- `LEGAL_DOC_AI_AGENT` — conversational Q&A with source citations

**What this enables:**
1. Users ask legal questions in natural language
2. Agent retrieves relevant chunks (not full docs)
3. Answers include `doc_name` + `page_no` citations
4. New documents auto-index within 1-hour TARGET_LAG

**Architecture shift:** per-document cost → per-question cost.
The more your corpus is reused, the better the economics.

---

# Code Review Checklist

See `docs/code-review-checklist.md` — take-home reference for your engineering team.

7 anti-patterns with fixes, quality regression tests, and links to implementation files.

**Priority order:**
1. Cache (zero risk, 100% dev savings)
2. Smart routing (~50% parse, low risk)
3. Cheap scorer (85-95% scoring, run A/B first)
4. Retrieval (90%+ Q&A, one-time setup)
5. Structured outputs (10-20%, validate retry rate)
6. Telemetry (free, always deploy)
7. Batch processing (architectural, longer-term)

---

<!-- _class: lead -->

# Next Steps

1. Deploy SQL pipeline (`sql/01` → `sql/20`)
2. Run benchmark (`scripts/benchmark.py`)
3. Review eval results (`EVAL_SUMMARY_V`)
4. Adopt levers that pass quality gates
5. Monitor via `DAILY_AI_COST`

**Render this deck:** `marp --pdf slides/legal-doc-ai-cost-optimization.md`
