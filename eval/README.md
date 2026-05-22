# Eval Framework — Legal Doc AI PDF Cost Optimization

## Methodology

Every cost lever must prove it doesn't degrade quality before we claim savings.
The framework measures quality at 3 layers, and a lever ships only when all 3 pass.

---

## Layer 1: Quantitative Similarity

**What:** AI_SIMILARITY between optimized output and gold reference (claude-4-sonnet on full pipeline).

**Granularity:** Per-document, aggregated as mean / p10 / p50 / p90.

**Why:** Catches regressions that change content—missing paragraphs, garbled numbers, truncated sections.

**Threshold:** Varies per lever (see table below).

---

## Layer 2: LLM-as-Judge

**What:** AI_AGG with a rubric-prompted judge model scores optimized output on 4 dimensions:
1. **Faithfulness** — no hallucinated facts vs. source PDF
2. **Completeness** — all material content preserved
3. **Structural fidelity** — headings, lists, tables, section order intact
4. **Numeric accuracy** — dollar amounts, dates, percentages, article numbers match

**Cross-family rule:** Claude outputs are judged by Mistral. Mistral outputs are judged by Claude. A model never judges itself — this mitigates self-preference bias documented in the literature.

**Scoring:** 1-5 per dimension, aggregated as geometric mean (penalizes any zero-dimension harder than arithmetic).

---

## Layer 3: Domain Spot-Check

**What:** Programmatic extraction of domain-critical elements + comparison:
- **Defined-term count:** regex for CAPITALIZED TERMS or quoted "defined terms" — count in optimized vs. gold.
- **Numeric fidelity:** extract `$[0-9,]+\.[0-9]{2}`, `[0-9]+%`, dates (`\d{1,2}/\d{1,2}/\d{4}`), article references (`Article \d+`). Element-wise exact-match rate.
- **Signature/party blocks:** presence of "SIGNED BY", "WITNESS", party names in final section.
- **Page-boundary integrity:** `[Page N]` markers preserved and in correct order.
- **Table integrity:** row count in tabular sections (detected by `|` delimiter patterns or indentation alignment).

---

## Per-Lever Quality Gates

| Lever | L1 Threshold | L2 Threshold | L3 Threshold |
|-------|-------------|-------------|-------------|
| 1 - Cache | AI_SIMILARITY = 1.000 (byte-identical) | n/a | n/a |
| 2 - Smart Routing | agreement >= 95%, p10 >= 0.85 | judge score >= 4.0 | numeric_fidelity >= 99% |
| 3 - Cheap Scorer | agreement >= 95%, Pareto non-empty | cross-judge score >= 3.8 | n/a |
| 4 - Structured | field_identity >= 98% | n/a | retry_rate >= 3% (else moot) |
| 5 - Retrieval | recall@5 >= 0.85, MRR >= 0.7 | similarity >= 0.90 of baseline | n/a |

---

## How to Run

### Prerequisites
1. impl-1's SQL pipeline deployed (sql/01-16 executed on `aws_spcs`).
2. PDF corpus uploaded to `@PDF_STAGE`.
3. Baseline results populated in `BASELINE_RESULTS`.

### Execution Order
```
-- 1. Create eval tables
snow sql -f eval/30_eval_setup.sql -c aws_spcs

-- 2. Load Q&A pairs (after spot-check approval)
-- Insert from eval/corpus/question_answer_pairs.yaml into EVAL_QA_PAIRS

-- 3. Run lever evals (order doesn't matter, but 31 is fastest)
snow sql -f eval/31_lever1_cache_identity.sql -c aws_spcs
snow sql -f eval/32_lever2_routing_agreement.sql -c aws_spcs
snow sql -f eval/33_lever3_model_matrix.sql -c aws_spcs
snow sql -f eval/34_lever4_structured_fielddiff.sql -c aws_spcs
snow sql -f eval/35_lever5_retrieval_quality.sql -c aws_spcs

-- 4. Compute Pareto frontier
snow sql -f eval/40_pareto_frontier.sql -c aws_spcs

-- 5. Summary pass/fail
snow sql -f eval/50_eval_summary.sql -c aws_spcs
```

### Interpreting Results
Query `EVAL_SUMMARY_V` (created by 50_eval_summary.sql) for the top-level pass/fail per lever.
Query `EVAL_PER_DOC` for per-document drill-down.
Query `EVAL_QA_RESULTS` for retrieval quality details.
Query `PARETO_FRONTIER_V` for the cost-quality tradeoff visualization data.

---

## Q&A Corpus

30 hand-built question/answer pairs in `corpus/question_answer_pairs.yaml`.

**Status:** All pairs marked `confidence: needs_spotcheck`. John must verify 10-20 pairs against source PDFs before treating as ground truth. Use `corpus/ground_truth_spotchecks.md` for the review workflow.

**Sources:**
- Corporate Bylaws (governance, board, subject representation)
- IRC Regulatory Charter (Regulatory Movement, eligibility, host city)
- Compliance Code (compliance, sanctions, TUEs, ABP)
- Federal Federal Regulatory Act (federal authority)
- Safety Code (mandatory reporting, prohibited conduct)

---

## Cross-Family Judge Rule

This is critical for Layer 2 integrity:

```
IF model_being_scored IN ('claude-4-sonnet', 'claude-haiku-4-5', 'claude-3-5-sonnet')
THEN judge_model = 'mistral-large2'

IF model_being_scored IN ('mistral-large2')
THEN judge_model = 'claude-haiku-4-5'

IF model_being_scored IN ('llama3.3-70b', 'openai-gpt-5-mini')
THEN judge_model = 'claude-haiku-4-5'  -- cheapest cross-family option
```

Rationale: LLM self-preference bias inflates scores by 0.3-0.8 points on 5-point scales (per Zheng et al. 2023, "Judging LLM-as-a-Judge"). Cross-family judging eliminates this confound.
