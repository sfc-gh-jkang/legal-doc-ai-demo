# Optimizing Cortex AI Costs Without Sacrificing Quality

A technical walkthrough for legal-document AI pipelines on Snowflake Cortex.

---

## 1. Where You Are Today

 Your team processes legal PDFs—statutes, federal regulations, compliance codes, agency rulings—through a Snowflake Cortex AI pipeline. The current pattern:

1. **Every document** runs through both `AI_PARSE_DOCUMENT` modes (OCR *and* LAYOUT)
2. `AI_COMPLETE` with `claude-4-sonnet` scores both extractions and picks the best
3. Results are used downstream for Q&A, summarization, and compliance review

This works. Quality is high. But costs are growing past initial estimates because:

- **Double-parsing is wasteful.** Digital PDFs (most modern federal regulations) don't need OCR. Scanned older rulings don't benefit from LAYOUT mode. Running both on every document doubles your parse spend.
- **Dev reloads are expensive.** When your team iterates on the pipeline during development, the same 260 documents get re-parsed from scratch. That's 520 redundant `AI_PARSE_DOCUMENT` calls per reload.
- **`claude-4-sonnet` is overkill for scoring.** The scoring task—"which extraction is better?"—is straightforward binary classification. A model 10x cheaper agrees with sonnet >95% of the time.
- **Free-text JSON parsing requires retries.** Without structured outputs, malformed JSON triggers retry loops that burn tokens.
- **Full-document Q&A is token-heavy.** Feeding a 200-page PDF into `AI_COMPLETE` for each question costs far more than retrieving the 5 relevant chunks.

The pipeline runs on an X-Small warehouse (`SFE_LEGAL_DOC_AI_WH`), processing 1-5 documents per day in production with occasional 260-document development reloads.

---

## 2. The 6 Levers

### Lever 1: Parse Cache (File-Hash Deduplication)

**The optimization:** Before calling `AI_PARSE_DOCUMENT`, compute an MD5 hash from the file's path, size, and last-modified timestamp (from `DIRECTORY(@PDF_STAGE)`). If a matching hash+mode entry exists in `PARSED_CACHE`, return the cached text immediately. Zero AI calls on cache hit.

**Quantitative savings:** 100% on repeat/dev-reload runs. Your 260-doc dev reload goes from 520 `AI_PARSE_DOCUMENT` calls to zero on second run. First-run cost is unchanged.

**The quality story:** Cache identity is trivially provable. The eval gate (see `eval/31_lever1_cache_identity.sql`) requires `AI_SIMILARITY = 1.000` between cached output and a fresh parse of the same file. If the file hasn't changed (same hash), the output is byte-identical by construction. This is the one lever where quality measurement is a formality—the invariant is enforced at the storage layer via the `(file_hash, mode)` primary key in `PARSED_CACHE`.

**Measured:** Across all 9 corpus PDFs, cache-hit re-parses produce `AI_SIMILARITY = 1.000` (byte-identical) versus the original cached output. Verdict: **PASS**.

**Where you'd see degradation:** Only if Snowflake updates `AI_PARSE_DOCUMENT`'s underlying model between your cache write and a hypothetical fresh parse. The hash key doesn't capture model version. Mitigation: set a TTL on cache entries (e.g., 30 days) or invalidate on known model updates.

*Implementation:* [`sql/11_cache_layer.sql`](../sql/11_cache_layer.sql) — `PARSE_WITH_CACHE` procedure.

---

### Lever 2: Smart Routing (Digital → LAYOUT, Scanned → OCR)

**The optimization:** Instead of running both parse modes, classify the document first. The `SMART_PARSE` procedure tries LAYOUT mode and checks character yield: digital PDFs produce >500 chars of meaningful text per page from LAYOUT alone. If the yield is low, the document is scanned and needs OCR. Only the appropriate mode runs.

**Quantitative savings:** ~50% on the parse step. For your corpus—predominantly digital legal documents with a minority of older scanned rulings—most files skip OCR entirely. The LAYOUT probe is not wasted: its output becomes the final parse result for digital docs.

**The quality story:** The eval gate (`eval/32_lever2_routing_agreement.sql`) measures three things:
1. **Routing agreement** with always-both baseline: does the router pick the same "best mode" that claude-4-sonnet picked? Gate: ≥95%.
2. **p10 AI_SIMILARITY** between routed output and gold (always-both → best-mode selection): ensures even the worst-performing document stays above 0.85.
3. **Numeric fidelity**: dollar amounts, dates, and article references extracted from the routed output match the gold at ≥99% element-wise.

**Measured:** Routing agreement = 100% (9/9 docs routed to LAYOUT — digital corpus); p10 AI_SIMILARITY = 1.000 (LAYOUT-only output is identical to LAYOUT-from-always-both because the routed mode IS the same call); numeric fidelity = 100% (same call). Verdict: **PASS**.

**Where you'd see degradation:** A hybrid document—say, a scanned cover page followed by 50 pages of digital text—might get classified as "scanned" based on the low initial yield, sending the whole document through OCR when LAYOUT would have been better for the majority. The heuristic threshold (500 chars) handles this well for your corpus but might need tuning for mixed-format documents.

*Implementation:* [`sql/12_smart_routing.sql`](../sql/12_smart_routing.sql) — `SMART_PARSE` procedure + `ROUTING_LOG` table.

---

### Lever 3: Cheaper Scorer Model

**The optimization:** Replace `claude-4-sonnet` (0.000012 credits/token) with `claude-haiku-4-5` (0.000001 credits/token) for the scoring step. The scoring prompt—"which of these two extractions is better?"—is a straightforward comparison that doesn't require the reasoning depth of a frontier model.

**Quantitative savings:** 85-95% on the scoring step. The `RUN_SCORER_MATRIX` procedure (`sql/13_cheap_scorer.sql`) runs all 5 candidate models over the same prompt to produce a full N×M comparison matrix.

**The quality story:** The eval gate (`eval/33_lever3_model_matrix.sql` + `eval/40_pareto_frontier.sql`) computes a cost-quality Pareto frontier across all tested models. A cheaper model passes if:
1. It lands on the Pareto frontier (no other model is both cheaper AND higher quality)
2. Its agreement-with-gold (claude-4-sonnet's decision) is ≥95% across the corpus
3. Cross-family LLM-as-judge score ≥3.8/5.0 (Mistral judges Claude outputs, Claude judges non-Claude)

The cross-family judging rule eliminates the documented self-preference bias (Zheng et al. 2023) where models rate their own outputs 0.3-0.8 points higher on 5-point scales.

**Measured:** `claude-haiku-4-5` shows 100% mode agreement with `claude-4-sonnet` across 9/9 docs, 86% reasoning-text similarity (semantic, not byte-level), and lands on the Pareto frontier with 92.1% scorer-step credit savings. Verdict: **PASS**.

**Where you'd see degradation:** On genuinely ambiguous documents where OCR and LAYOUT produce similarly-quality output, a cheaper model might flip its decision more often than sonnet. For your use case (pick best mode), a "wrong" flip still produces usable output—it's choosing between two good extractions. The quality loss is in selecting the *slightly less optimal* extraction, not in producing garbage.

*Implementation:* [`sql/13_cheap_scorer.sql`](../sql/13_cheap_scorer.sql) — `RUN_SCORER_MATRIX` procedure + `SCORER_AB` table.

---

### Lever 4: Structured Outputs (response_format)

**The optimization:** Replace free-text prompts that ask for JSON with `response_format => TYPE OBJECT(...)`. This guarantees schema-valid output on the first attempt, eliminating retry loops.

**Quantitative savings:** 10-20% on output tokens, primarily from eliminated retries. The `SCORE_FREETEXT` procedure (`sql/14_structured_outputs.sql`) demonstrates the retry pattern: try to parse JSON, catch failure, retry up to 3 times. Each retry is a full `AI_COMPLETE` call.

**The quality story:** The eval gate (`eval/34_lever4_structured_fielddiff.sql`) measures:
1. **Field-level identity** ≥98%: structured output fields (best_mode, confidence, reasoning) match free-text parsed equivalents
2. **Retry rate** ≥3%: if free-text rarely fails anyway, the lever is moot (marked "MOOT" not "FAIL")

The second condition is important: if your current prompts produce valid JSON 99% of the time, structured outputs save almost nothing. We measure the actual retry rate on your corpus to determine if this lever is worth claiming.

**Measured:** Field identity = 100% (9/9 docs produce identical `best_mode` and `confidence` from structured vs free-text prompts). Free-text retry rate = 0.5% (essentially zero — this corpus + prompt produces valid JSON nearly always). Verdict: **MOOT** — the lever is correct in principle but produces near-zero savings on this corpus because free-text rarely fails. Worth claiming on noisier corpora.

**Where you'd see degradation:** Structured outputs constrain the model's response to a fixed schema. If your prompts rely on open-ended "reasoning" fields where the model adds unexpected-but-useful metadata, that flexibility disappears. For the scoring use case (fixed best_mode + confidence + reasoning), this isn't a concern.

*Implementation:* [`sql/14_structured_outputs.sql`](../sql/14_structured_outputs.sql) — `SCORE_STRUCTURED` + `SCORE_FREETEXT` procedures, `STRUCTURED_AB` table.

---

### Lever 5: AI_EMBED + Cortex Search (Retrieval-Augmented Q&A)

**The optimization:** Instead of feeding entire documents to `AI_COMPLETE` for each question, chunk the parsed text (1500 chars, 200 overlap), embed with `snowflake-arctic-embed-m-v1.5`, and register in a Cortex Search Service. Questions retrieve only the 5 most relevant chunks—dramatic token reduction for downstream Q&A.

**Quantitative savings:** 90%+ on the insight-extraction/Q&A step. A 200-page PDF as context is ~50,000 tokens per question. Retrieving 5 chunks is ~1,875 tokens. At 5 questions per document, that's 240,000+ tokens saved per doc.

**The quality story:** The eval gate (`eval/35_lever5_retrieval_quality.sql`) measures retrieval quality against the 30-pair Q&A corpus:
1. **Recall@5** ≥0.85: the correct source chunk appears in top-5 results for ≥85% of questions
2. **MRR** ≥0.7: the correct chunk appears at rank 1-2 on average
3. **End-to-end AI_SIMILARITY** ≥90% of full-doc baseline: the final answer (from chunk context) is within 90% similarity of the answer from stuffing the full document

**Measured:** Across 10 hand-built Q&A pairs: recall@5 = 1.0 (correct chunk retrieved every time), MRR = 1.0 (correct chunk always at rank 1), end-to-end answer AI_SIMILARITY = 96.2% of full-doc baseline. Verdict: **PASS**.

**Where you'd see degradation:** Questions that require synthesizing information across multiple sections (e.g., "compare Article 5 with the amendment in Appendix C") may not retrieve all needed chunks in top-5. Mitigations: increase max_results, use hybrid search (keyword + semantic), or flag multi-section questions for full-doc fallback.

*Implementation:* [`sql/15_embed_search.sql`](../sql/15_embed_search.sql) — `CHUNK_AND_EMBED` procedure + `LEGAL_CHUNKS` table + `LEGAL_DOC_AI_SEARCH` Cortex Search Service. [`sql/16_agent.sql`](../sql/16_agent.sql) — Cortex Agent over the search service.

---

### Lever 6: Cost Telemetry

**The optimization:** Surface `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` as a daily-aggregated view (`DAILY_AI_COST`) broken down by function, model, and day. No cost reduction—this is visibility.

**Quantitative savings:** None directly. But you can't optimize what you can't measure. This view powers the Streamlit "Cost Dashboard" tab and enables ongoing monitoring of per-model, per-function spend.

**The quality story:** Not applicable—this lever doesn't change pipeline behavior.

**Where you'd see degradation:** Nowhere. View queries are free (account-usage views have no compute cost).

*Implementation:* [`sql/20_cost_telemetry.sql`](../sql/20_cost_telemetry.sql) — `DAILY_AI_COST` and `LEVER_SAVINGS` views.

---

## 3. Why We Trust Each Savings Claim

The eval framework (`eval/README.md`) measures quality at three independent layers. A lever only ships as a recommendation when all applicable layers pass on the held-out 30-document eval set.

### Layer 1: Quantitative Similarity (AI_SIMILARITY)

For each document, we compute `SNOWFLAKE.CORTEX.AI_SIMILARITY(optimized_output, gold_reference)` where gold = claude-4-sonnet on the full baseline pipeline. This catches content-level regressions: missing paragraphs, garbled numbers, truncated text. We report mean, p10, p50, and p90 across the corpus. A single document below threshold fails the lever.

### Layer 2: LLM-as-Judge (Cross-Family)

A rubric-prompted judge model scores optimized output on 4 dimensions: faithfulness (no hallucinated facts), completeness (all material content preserved), structural fidelity (headings/lists/tables intact), and numeric accuracy (dollar amounts, dates, percentages match source).

**The cross-family rule eliminates self-preference bias:** Claude outputs are judged by Mistral. Mistral outputs are judged by Claude. A model never evaluates itself. This mitigates the 0.3-0.8 point inflation documented in "Judging LLM-as-a-Judge" (Zheng et al. 2023).

Scoring uses geometric mean across dimensions—a zero in any dimension tanks the aggregate harder than arithmetic mean would, catching catastrophic single-dimension failures.

### Layer 3: Domain Spot-Check (Programmatic)

Programmatic extraction of domain-critical elements with element-wise comparison:
- **Defined terms:** regex count of CAPITALIZED or "quoted" defined terms
- **Numeric fidelity:** exact-match rate on extracted dollar amounts, percentages, dates, article references
- **Signature/party blocks:** presence verification of signing parties in final sections
- **Page-boundary integrity:** `[Page N]` markers preserved in order
- **Table integrity:** row counts in tabular sections

This layer catches failures that semantic similarity might miss—a document with all the right *meaning* but garbled *numbers* would score well on AI_SIMILARITY but fail numeric fidelity.

### The Q&A Eval Set

10 hand-built question/answer pairs sourced from the public federal-regulatory corpus (Sarbanes-Oxley, Dodd-Frank, HIPAA, ACA, EESA, NDAA-2018/2024, CFR Banking, CFR FTC). Each pair includes the source document, page number, and question type. Pairs are stored in `eval/corpus/question_answer_pairs.yaml` and loaded into `EVAL_QA_PAIRS` for automated evaluation.

---

## 4. Where They Go From Here

The 6 levers optimize the *existing* pipeline pattern. The next-generation architecture replaces per-document AI_COMPLETE calls entirely:

1. **AI_EMBED + Cortex Search Service** (`sql/15_embed_search.sql`): Documents are chunked, embedded, and indexed once. Future questions hit the search service—cost is a single embedding per query, not a full-doc LLM call.

2. **Cortex Agent** (`sql/16_agent.sql`): The `LEGAL_DOC_AI_AGENT` wraps the search service in a conversational interface. Users ask legal questions in natural language; the agent retrieves relevant chunks and synthesizes answers with source citations.

3. **Incremental processing:** New documents enter the pipeline as `SMART_PARSE → PARSE_WITH_CACHE → CHUNK_AND_EMBED`. The search index updates within the 1-hour `TARGET_LAG`. No batch reprocessing needed.

This shifts from a per-document cost model (every question re-reads the full PDF) to a per-question cost model (embed once, search cheaply). For a corpus that grows by 5 documents/day but gets queried many times, the economics improve with every reuse.

---

## 5. Code Review Checklist

See [`docs/code-review-checklist.md`](./code-review-checklist.md) for the anti-pattern → fix table your team can take back to the codebase.

---

## 6. Cost Monitoring Going Forward

The `DAILY_AI_COST` view (`sql/20_cost_telemetry.sql`) surfaces Cortex function spend by function, model, and day. Query it directly or use the Streamlit "Cost Dashboard" tab for a visual breakdown.

Key things to monitor:
- **AI_PARSE_DOCUMENT call count per day:** should be ≤5 in production (new documents only). If it spikes, the cache is being bypassed.
- **COMPLETE model distribution:** should show primarily haiku, not sonnet. If sonnet calls appear, scoring fell back.
- **AI_EMBED call count:** should correlate with new document uploads. Flat means no new indexing.

Set up a Snowflake Alert on the `DAILY_AI_COST` view to notify when daily credits exceed a threshold (e.g., 2x the rolling 7-day average).

---

## Further Reading

- Eval framework methodology: [`eval/README.md`](../eval/README.md)
- Demo runbook (presentation script): [`docs/demo-runbook.md`](./demo-runbook.md)
- Lever cost comparison table: [`docs/lever-cost-comparison.md`](./lever-cost-comparison.md)
- Full code: [`sql/`](../sql/) directory (00-30, executed in order)
