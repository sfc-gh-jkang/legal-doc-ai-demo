# Customer Pushback Prep — Pre-Canned Answers

Anticipated customer questions during the Legal Doc AI demo, with defensible answers grounded in the data we ran.

---

## "How is 92% savings on the scorer real?"

**Short**: Same prompt, same docs, different model.

**Long**:
- Gold model: `claude-4-sonnet` at ~3 credits per million tokens (per Snowflake Cortex pricing).
- Challenger: `claude-haiku-4-5` at ~0.3 credits per million tokens — 10× cheaper per token.
- We ran both models against the same scoring prompt across 9 federal-regulatory PDFs.
- **Quality**: 100% mode-agreement with gold (every doc, both models picked LAYOUT). 86% AI_SIMILARITY on the reasoning text — same conclusion, slightly less verbose justification.
- **Cost**: Total 9-doc run was 0.063 credits with gold vs. 0.005 credits with haiku. That's the 92% number.

**If they push back**: "Show me the Pareto chart on Tab 5." Walk through: claude-haiku-4-5 sits on the frontier at (0.005 credits, 0.86 quality); claude-4-sonnet sits at (0.063 credits, 1.00 quality). The 3 challengers in between (sonnet-4-6, mistral-large2, llama3.3-70b) are dominated.

**Caveat to volunteer**: "This is on a 9-doc bench with truncated input (first 3,000 chars per mode). Customer-scale validation should re-run on a representative cross-section of their corpus before shipping."

---

## "What's the actual dollar value?"

**Short**: Credits × your contracted credit rate. We don't show dollars in the demo on purpose.

**Long**:
- Snowflake list rate (~$3/credit) is not what most enterprise customers pay. Effective contracted rates land closer to $1.50–$2.50/credit depending on commit size, multi-product bundling, and term length.
- Showing list-rate dollars would over-promise savings.
- The demo deliberately stops at credits. Take the numbers in Tab 6 (e.g., "4.4 credits saved per NDAA-2024 doc") and multiply by **your** rate from your AE.

**If they push for a number**: Punt to the AE. "Isaac/Jay/your AE has the contracted rate; I'd rather they put the dollar figure in writing than me guess from list."

**Internal rule** (do not say to customer): per memory rule `6cdd74ec`, never suggest customers "negotiate further discounts" off list. Volume tiers are the public mechanism; rate conversations belong to the AE.

---

## "Why is structured outputs MOOT? Aren't structured outputs important?"

**Short**: They are — but only when free-text responses fail often enough to retry.

**Long**:
- Lever 4 (structured outputs via `response_format => TYPE OBJECT(...)`) eliminates retry overhead caused by free-text JSON parse failures.
- We measured the free-text retry rate on this corpus: **0.5%** (1 retry per 200 attempts). The MOOT verdict gate is `< 3.0%`.
- At 0.5% retry rate, the cost of the lever (slightly higher per-call latency from constrained decoding) doesn't pay back the savings from eliminated retries.
- **Ship lever 4 only when free-text retry rate climbs above ~3%.** Different prompts and models will tip the balance differently.

**If they push back**: "I want it anyway for production stability." → Fair. Ship it for production paths where parse-correctness matters more than the marginal cost. The MOOT verdict is a cost-only judgment, not a quality-only one.

---

## "What's the LLM accuracy guarantee?"

**Short**: There is no provider-side guarantee. We measure quality empirically against a gold model.

**Long**:
- Snowflake Cortex doesn't guarantee LLM output correctness — that's true of every LLM provider (OpenAI, Anthropic, Google, etc.).
- The optimization framework here is built on a **gold-vs-challenger** measurement loop: pick a known-good model (claude-4-sonnet here), run challengers against the same input, score for similarity / agreement / Pareto position.
- This shifts the question from "is the model right?" to "does the cheaper model agree with the more-expensive one often enough for our use case?"
- For high-stakes outputs (legal interpretation, medical advice, financial recommendations), a human-in-the-loop step is still recommended on top of the LLM.

---

## "Can we run llama or mistral instead of claude?"

**Short**: Yes — and we tested both. Look at the Pareto chart.

**Long**:
- llama3.3-70b: 0.020 credits, 0.79 quality — **dominated** by claude-haiku-4-5 (which is cheaper and higher quality).
- mistral-large2: 0.029 credits, 0.85 quality — **also dominated** by haiku.
- Snowflake Cortex Agent currently restricts to claude models for the agent framework, but raw `AI_COMPLETE` accepts all of them.
- For batch scoring (Lever 3), claude-haiku-4-5 is the dominating choice on this corpus. Could shift on a different workload.

---

## "How does this scale to 1M PDFs?"

**Short**: Lever 11 (Batch Cortex Search) for offline jobs, Snowpipe Streaming for online ingest.

**Long**:
- Levers 1, 2, 3, 5 (cache, smart routing, cheap scorer, retrieval) all scale linearly per doc.
- At 1M docs, the parse step alone is ~6,000 credits at full LAYOUT (per the cost telemetry math). Lever 1 cache makes re-parses free, lever 2 smart routing cuts that ~50% on first parse.
- Lever 11 (Batch Cortex Search) is for one-time entity-resolution-style retrieval at >2,000 queries per job. For live Q&A, the interactive search service is correct.
- Real customer scale-up should pilot on 1,000 docs, measure observed cost, then decide.

---

## "What about non-English docs?"

**Short**: AI_PARSE_DOCUMENT and Cortex Search both support multilingual; embedding model is language-aware. Test on a sample first.

**Long**:
- AI_PARSE_DOCUMENT (OCR + LAYOUT modes) handles multilingual scripts; we haven't tested on this corpus (all docs are US federal regs in English).
- AI_EMBED with `e5-base-v2` or `voyage-multilingual-2` (if enabled) is the right choice for multilingual chunking.
- LLM scoring (Lever 3) — claude and mistral families are strong on European languages; weaker on CJK. Validate per-language before shipping.

---

## "Can I see the SQL?"

Open a side terminal and walk through:
- `eval/35_lever5_retrieval_quality.sql` — the retrieval quality eval (Cortex Search Preview API call shape)
- `sql/15_embed_search.sql` — chunking + AI_EMBED + Cortex Search service creation
- `sql/13_cheap_scorer.sql` — the scorer matrix DDL
- `streamlit/app.py` line 1810+ — how Tab 5 renders the verdicts from `EVAL_SUMMARY_V`

---

## "What if I want this on Azure / GCP?"

**Short**: All Cortex AI functions GA on AWS, AI_PARSE_DOCUMENT in PuPr on Azure (May 2026). GCP availability lags.

**Long**: Defer to current Snowflake docs / your AE — preview/GA matrix changes monthly. For this demo, we're on AWS US East 1.
