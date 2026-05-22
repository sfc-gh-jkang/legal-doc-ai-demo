# Legal Doc AI PDF Cost + Quality Optimization Demo

Demonstrates 11 cost-and-quality levers for Snowflake Cortex AI document processing, using a typical enterprise legal-PDF pipeline as context. The original 6 are stackable cost-savings optimizations; the additional 5 are operational guardrails (preflight, completion cache, batching, resource monitor, batch search).

## Pain Statement

A typical legal-document AI pipeline runs **both** `AI_PARSE_DOCUMENT(OCR)` and `AI_PARSE_DOCUMENT(LAYOUT)` on every PDF, then uses `AI_COMPLETE('claude-4-sonnet')` to score and pick the better extraction. This double-parse + expensive-scorer pattern costs several times more than necessary. Q&A on top is even worse: each question typically re-feeds the entire parsed document into another `AI_COMPLETE` call.

## The 6 Stackable Cost Levers

| # | Lever | Expected Reduction | How |
|---|-------|-----------------|-----|
| 1 | Parse cache (file-hash dedup) | 100% on cache hits | Hash-based lookup skips re-parsing identical files |
| 2 | Smart routing (digital→LAYOUT, scanned→OCR) | up to ~50% on parse step | Classify once, parse once |
| 3 | Cheaper scorer model | ~10× cheaper per scoring call | haiku/mistral/llama match claude-4-sonnet at fraction of cost |
| 4 | Structured outputs | varies by retry rate | `response_format => TYPE OBJECT(...)` eliminates retry overhead (often MOOT in practice) |
| 5 | AI_EMBED + Cortex Search | order-of-magnitude on Q&A token billing | Chunk + retrieve replaces full-doc re-reads |
| 6 | Cost telemetry views | visibility, not savings | CORTEX_AI_FUNCTIONS_USAGE_HISTORY dashboards |

## Operational Levers (7–11)

| # | Lever | Purpose |
|---|-------|---------|
| 7 | Token preflight | `AI_COUNT_TOKENS` blocks/warns oversized calls before they fire |
| 8 | Completion cache | Deduplicates identical scoring prompts on repeat runs |
| 9 | Batch inference | SET-based `SELECT AI_COMPLETE(...) FROM table` vs row-by-row Python loop (~3.7× faster, same credit cost) |
| 10 | Resource monitor | Budget guardrail with NOTIFY/SUSPEND thresholds |
| 11 | Batch Cortex Search | Offline-only — for entity resolution / dedup at >2K queries per job. **NOT for live Q&A** (worse than interactive at small scale) |

> **Dollar conversion is intentionally omitted throughout the demo.** All savings claims are in credits. Multiply by the customer's contracted credit rate for a dollar projection — list rate is not appropriate for customer-facing claims.

## Quick Start

```bash
# 1. Download public legal corpus
cd scripts && uv run fetch_corpus.py

# 2. Upload to Snowflake stage
uv run upload_pdfs.py

# 3. Deploy SQL pipeline (review first!)
snow sql -f deploy.sql -c aws_spcs

# 4. Run benchmark comparison
snow sql -f sql/99_compare_all.sql -c aws_spcs
```

## Project Structure

```
sql/            SQL pipeline (01-16 setup + cost levers, 17-19 ops levers, 20 telemetry,
                30-32 guardrails + batch search, 99 benchmark)
eval/           Quality evaluation framework (drift monitor, cross-judge bias, per-lever gates)
scripts/        Python helpers (fetch corpus, upload PDFs, pypdf fallback, preprocessing,
                grounded Q&A generation)
streamlit/      Streamlit-on-Snowflake demo app (Container Runtime, 7 tabs)
docs/           Customer narrative, annual savings, migration plan, risk register
slides/         Marp deck (12 slides)
tests/          pytest suite
```

## Snowflake Objects

- **Database:** `SNOWFLAKE_EXAMPLE`
- **Schema:** `LEGAL_DOC_AI_DEMO`
- **Warehouse:** `SFE_LEGAL_DOC_AI_WH` (X-Small)
- **Stage:** `@PDF_STAGE` (SSE-encrypted, directory enabled)
- **Search Service:** `LEGAL_DOC_AI_SEARCH`
- **Agent:** `LEGAL_DOC_AI_AGENT`
- **Streamlit:** `LEGAL_DOC_AI_APP` (Container Runtime, requires `PYPI_ACCESS_INTEGRATION`)

## Requirements

- Snowflake account with Cortex AI enabled
- `snow` CLI configured (connection: `aws_spcs`)
- Python 3.11+ with `uv`
- Public internet access for corpus download

## Repository Owner

- **Owner:** John Kang (john.kang@snowflake.com / [@sfc-gh-jkang](https://github.com/sfc-gh-jkang))
- **Access requests:** Open a CASEC Jira (Cloud and Application Security, Consultation type) for access changes
- **License:** Apache-2.0 (see [LICENSE](LICENSE))
- **Status:** Internal demo — not publicly released. Any decision to flip the repo public requires CASEC + ProdSec + manager + Compliance sign-off per Snowflake SCM policy.
