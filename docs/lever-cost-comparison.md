# Lever-by-Lever Cost Comparison

Per-lever savings measured on the public 9-PDF federal-regulatory corpus (Sarbanes-Oxley, Dodd-Frank, HIPAA, ACA, EESA, NDAA-2018/2024, CFR Banking, CFR FTC). Numbers are pulled from `BASELINE_RESULTS`, `SCORER_AB`, `EVAL_PER_DOC`, `EVAL_QA_RESULTS`, and `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` after running the full eval suite.

> **Caveat:** All numbers are measured on a 9-document held-out corpus. Customer corpora may show different ratios — re-run `eval/` against your own data to validate.

---

## How to Reproduce

```bash
cd legal-doc-ai-demo
# Deploy the full pipeline (one-time)
./deploy.sql  # see file header for ordering

# Run the eval suite (~0.15 cr total)
for f in eval/30_*.sql eval/31_*.sql eval/32_*.sql \
         eval/33_*.sql eval/34_*.sql eval/35_*.sql \
         eval/40_*.sql eval/41_*.sql; do
  snow sql -f "$f" -c <your-connection> --enable-templating NONE
done

# Snapshot results
./scripts/snapshot_demo_state.sh
```

Prerequisites:

1. SQL pipeline deployed (`sql/00_prereqs.sql` through `sql/30_resource_monitor.sql`)
2. PDF corpus uploaded to `@PDF_STAGE` (run `scripts/fetch_corpus.py` then `scripts/upload_pdfs.py`)
3. Baseline results populated by `sql/10_baseline.sql`

---

## Cost Table (per document, measured)

| Lever | Credits/doc | Quality Gate | Verdict |
|---|---|---|---|
| **Baseline** (always-both parse + sonnet scorer) | ~1.57 cr | n/a | reference |
| **+Cache** (Lever 1) | 0 cr on hit; 1.57 cr first-run | AI_SIMILARITY = 1.000 byte-identical | **PASS** |
| **+Smart Routing** (Lever 2) | ~1.36 cr (LAYOUT-only on digital docs) | routing agreement = 100%, p10 sim = 1.000 | **PASS** |
| **+Cheap Scorer** (Lever 3, claude-haiku-4-5) | ~0.0006 cr scorer step (was ~0.007) | mode agreement = 100%, on Pareto, sim = 0.86 | **PASS** |
| **+Structured Outputs** (Lever 4) | ~0 cr delta | field identity = 100%, retry rate = 0.5% | **MOOT** (corpus rarely fails free-text) |
| **+Retrieval** (Lever 5, search vs full-doc) | ~0.0015 cr/q (was ~0.04 cr/q full-doc) | recall@5 = 1.0, MRR = 1.0, e2e sim = 96.2% | **PASS** |
| **+Telemetry** (Lever 6) | +0 cr | visibility only | n/a |

**Per-doc end-to-end (all stackable levers applied):** ~1.36 cr (LAYOUT-only) + ~0.0006 cr (haiku scorer) + ~0.0015 cr/q (search) ≈ **1.36 cr first-parse + 0 cr cache-hits + ~0.002 cr/question downstream**.

---

## Cumulative Savings (illustrative — measured per-doc rates × volume)

| Scenario | Baseline (cr) | Optimized (cr) | Savings | % Reduction |
|---|---|---|---|---|
| Single new document, no questions | 1.57 | 1.36 | 0.21 | 13% (parse-step only) |
| 260-doc dev reload, 2nd run | 408 | 0 (all cache hits) | 408 | 100% |
| 1,825 docs/yr first-parse + 10 questions per doc | 2,866 + 730 = 3,596 | 2,482 + 27.4 = 2,509 | 1,087 | 30% |
| Annual production + 50 dev reloads + 10 q/doc | 23,996 | 2,509 | 21,487 | 90% |

The dominant savings come from (a) cache on dev-reloads and (b) retrieval replacing full-doc Q&A. The lever stack compounds: cache eliminates first-parse cost on warm runs, smart routing trims the cold first-parse, cheap scorer cuts the scoring micro-step, and retrieval cuts the per-question Q&A by ~25×.

---

## Per-Model Scorer Comparison (Lever 3 Detail)

Measured across 9 docs × 5 models × repeated trials (45 rows in `SCORER_AB`).

| Model | Avg credits/score | Mode agreement w/ gold | Cross-judge similarity | On Pareto frontier |
|---|---|---|---|---|
| `claude-4-sonnet` (gold) | ~0.0073 | 100% (reference) | 1.000 (self) | reference |
| `claude-sonnet-4-6` | ~0.0073 | 100% | 0.93 | yes |
| `claude-haiku-4-5` | ~0.0006 | 100% | 0.86 | **yes (recommended)** |
| `mistral-large2` | ~0.0030 | 89% | 0.74 | dominated |
| `llama3.3-70b` | ~0.0018 | 78% | 0.69 | dominated |

`claude-haiku-4-5` dominates: 92.1% scorer-step credit savings vs `claude-4-sonnet`, full mode agreement, and high reasoning-text similarity.

---

## Structured Output Detail (Lever 4)

| Mode | Avg output tokens | Retry rate | Parse success rate |
|---|---|---|---|
| Structured (`response_format`) | ~120 | 0% (by construction) | 100% |
| Free-text (prompt-only) | ~140 | 0.5% | 99.5% |

Free-text retry rate is well below the 3% threshold, so this lever is marked **MOOT** for this corpus. The implementation is correct and would shine on noisier corpora (e.g., low-quality OCR with messy formatting).

---

## Notes

- All credit estimates use Snowflake list rates pulled from `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` for the eval window, divided by document or question count. They are not customer-negotiated rates.
- Parse credits dominated by `AI_PARSE_DOCUMENT` LAYOUT mode (~1.36 cr/doc on the corpus); OCR mode (~0.21 cr/doc) is rarely needed when routing is enabled.
- Scorer credit rates approximated from `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`; precise per-token rates may shift with model price changes.
- "Credits/doc" for Lever 1 (cache) assumes a second-run cache hit. First-run cost is identical to baseline.
- Lever 5 savings apply only to downstream Q&A, not initial parse+score. The levers stack rather than overlap.
- Numbers above were measured on May 22, 2026 against the 9-doc public corpus. Re-run on your own corpus before quoting customer-facing percentages.
