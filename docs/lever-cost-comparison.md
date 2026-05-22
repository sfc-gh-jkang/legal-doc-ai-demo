# Lever-by-Lever Cost Comparison

Per-lever savings measured on the customer legal PDF corpus. Populated by `scripts/benchmark.py`.

---

## How to Populate

```bash
cd /Users/jkang/Documents/vscode/legal-doc-ai-demo
uv run python scripts/benchmark.py --connection aws_spcs --warehouse SFE_LEGAL_DOC_AI_WH
```

Prerequisites:
1. SQL pipeline deployed (`sql/01_setup.sql` through `sql/20_cost_telemetry.sql`)
2. PDF corpus uploaded to `@PDF_STAGE`
3. Baseline results populated (run `sql/99_compare_all.sql` or let benchmark.py handle it)

---

## Cost Table

| Lever | Credits/doc (1 doc) | Credits (260 docs, dev reload) | Credits (1,825 docs, 1 yr × 5/day) | Quality Gate | Status |
|---|---|---|---|---|---|
| **Baseline** (current) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | n/a | n/a |
| **+Cache** (Lever 1) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | AI_SIMILARITY = 1.000 | <!-- PASS/FAIL --> |
| **+Smart Routing** (Lever 2) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | routing agreement ≥ 95%, p10 ≥ 0.85 | <!-- PASS/FAIL --> |
| **+Cheap Scorer** (Lever 3) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | agreement ≥ 95%, Pareto frontier | <!-- PASS/FAIL --> |
| **+Structured Outputs** (Lever 4) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | field identity ≥ 98% | <!-- PASS/FAIL/MOOT --> |
| **+Retrieval** (Lever 5) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | recall@5 ≥ 0.85, MRR ≥ 0.7 | <!-- PASS/FAIL --> |
| **+Telemetry** (Lever 6) | +0.000 | +0.000 | +0.000 | visibility only | PASS |

---

## Cumulative Savings

| Scenario | Baseline | Optimized | Savings | % Reduction |
|---|---|---|---|---|
| Single new document | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |
| 260-doc dev reload (2nd run) | <!-- TODO: fill --> | 0.000 (cache hits) | <!-- TODO: fill --> | ~100% |
| Annual production (1,825 docs, first-parse) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |
| Annual production + 50 dev reloads | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |

---

## Per-Model Scorer Comparison (Lever 3 Detail)

| Model | Avg Credits/Score | Agreement with Gold | Cross-Judge Score | On Pareto Frontier |
|---|---|---|---|---|
| claude-4-sonnet (gold) | <!-- TODO: fill --> | 100% (reference) | <!-- TODO: fill --> | <!-- TODO: fill --> |
| claude-haiku-4-5 | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |
| claude-3-5-sonnet | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |
| mistral-large2 | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |
| llama3.3-70b | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |

---

## Structured Output Detail (Lever 4)

| Mode | Avg Tokens | Retry Rate | Parse Success Rate |
|---|---|---|---|
| Structured (`response_format`) | <!-- TODO: fill --> | 0% (by construction) | 100% |
| Free-text (prompt-only) | <!-- TODO: fill --> | <!-- TODO: fill --> | <!-- TODO: fill --> |

If free-text retry rate < 3%, this lever is marked **MOOT** (savings too small to claim).

---

## Notes

- All credit estimates use Snowflake list rates as of the benchmark run date.
- Parse token counts estimated as `LENGTH(text) / 4` (approximate tokenizer ratio).
- Scorer credit rates: claude-4-sonnet=0.000012/token, haiku-4-5=0.000001, claude-3-5-sonnet=0.000008, mistral-large2=0.000005, llama3.3-70b=0.000003.
- "Credits/doc" for Lever 1 (cache) assumes second-run (cache hit). First-run cost is identical to baseline.
- Lever 5 savings apply only to downstream Q&A, not initial parse+score. The levers compound.
