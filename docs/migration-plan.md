# Migration Plan — Legal Doc AI AI Pipeline Optimization

## Overview

Phased 30-day rollout of 10 optimization levers, ordered by risk (lowest first). Each phase includes prerequisites, success criteria, and rollback procedures. All changes are deployed to `SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO` on warehouse `SFE_LEGAL_DOC_AI_WH`.

---

## Day 1–3: Resource Monitor + Parse Cache (Zero Risk)

### What Ships
- **Lever 10**: Resource monitor with 4-tier budget guardrails (50%/75%/90%/100%)
- **Lever 1**: Parse cache table (`PARSED_CACHE`) — deterministic SHA256 keyed, byte-identical retrieval

### Prerequisites
- `SFE_LEGAL_DOC_AI_WH` warehouse exists with ACCOUNTADMIN-level resource monitor permissions
- `PARSED_CACHE` table created via `sql/11_cache_layer.sql`

### Owner
Customer IT / Snowflake SE (John Kang)

### Success Criteria
- Resource monitor triggers test notification at 50% threshold
- Second parse of any cached document returns in <1s with 0 AI credits consumed
- Eval gate: cache similarity = 1.000 (byte-identical to fresh parse)

### Rollback
- `ALTER RESOURCE MONITOR LEGAL_DOC_AI_MONITOR SET CREDIT_QUOTA = NULL;` (disables guardrails)
- `TRUNCATE TABLE PARSED_CACHE;` (forces fresh parse on next run)

---

## Day 4–7: Smart Routing + Token Preflight (Low Risk)

### What Ships
- **Lever 2**: Heuristic routing classifier — digital PDFs → LAYOUT mode, scanned → OCR mode
- **Lever 7**: Token preflight estimator — blocks calls >2.5 credits, warns at >0.8 credits
- **Lever 6 (pypdf path)**: pypdf text extraction for digital-native PDFs (bypasses AI_PARSE_DOCUMENT entirely)

### Prerequisites
- Routing classifier logic deployed via `sql/12_smart_routing.sql`
- Preflight estimator deployed via `sql/17_token_preflight.sql`
- `scripts/pypdf_fallback.py` accessible from Snowflake stage or Snowpark

### Owner
Legal Doc AI Tech Lead + Snowflake SE

### Success Criteria
- 100% of digital-native PDFs routed to LAYOUT mode with confidence ≥ 0.95
- Preflight blocks documents estimated at >2.5 credits (confirmed: `fed_reg_2023_compliance_standards.pdf` at 2.64 credits → blocked)
- pypdf extraction succeeds on all 5 corpus documents (9.5M chars extracted, 16.646 credits saved)
- Zero false positives (no legitimate documents incorrectly blocked)

### Rollback
- Set routing to always use OCR mode: `UPDATE ROUTING_LOG SET CHOSEN_MODE = 'OCR';`
- Disable preflight: bypass the `PREFLIGHT_LOG` check in the pipeline entry point
- Revert to AI_PARSE_DOCUMENT: remove pypdf path from extraction logic

---

## Day 8–14: A/B Haiku Scorer in Shadow Mode (Medium Risk, Gated)

### What Ships
- **Lever 3**: claude-haiku-4-5 scorer running in shadow alongside claude-4-sonnet (gold)
- **Lever 9**: Batch inference mode for scorer calls (3.76x throughput improvement)
- **Query tags**: All lever calls tagged with `legal_doc_ai_demo:lever_N` for cost attribution

### Prerequisites
- Pareto frontier analysis complete showing haiku on frontier (confirmed: 90.1% savings vs gold)
- Cross-judge bias report reviewed (haiku bias delta: -0.18 — acceptable for shadow mode)
- Batch demo validates same-credit, faster-elapsed pattern (confirmed: 3.7s vs 14.0s)
- Drift monitor baseline set for all 5 eval dimensions

### Owner
Legal Doc AI Tech Lead (shadow mode decisions) + Snowflake SE (monitoring)

### Success Criteria
- Shadow mode: haiku scores logged alongside gold scores for 7 days
- Agreement rate ≥ 85% between haiku and gold on production documents
- No drift alerts triggered (all dimensions <5% drift from baseline)
- Query tag attribution confirms haiku shadow cost remains within 10% of projection (0.0017 credits/doc)

### Rollback
- Disable shadow scorer: remove haiku calls from scoring pipeline
- Gold model continues as sole scorer with zero disruption

---

## Day 15–21: Promote Haiku to Primary + Structured Outputs

### What Ships
- **Lever 3 promotion**: claude-haiku-4-5 becomes primary scorer; claude-4-sonnet reserved for escalation
- **Lever 4**: Structured JSON output mode (`response_format`) for scorer responses
- **Lever 8**: Completion cache for repeated identical prompts within sessions

### Prerequisites
- 7-day shadow mode data confirms agreement ≥ 85%
- Drift monitor shows 0% drift across all 5 dimensions (confirmed as of baseline set date)
- Structured output eval gate: retry rate <3% (currently MOOT — free-text retries negligible)
- Completion cache deployed via `sql/18_completion_cache.sql`

### Owner
Legal Doc AI Tech Lead (promotion decision) + Customer Compliance (quality sign-off)

### Success Criteria
- Haiku processes 100% of new document scores (gold only on explicit escalation)
- Structured outputs eliminate all JSON parsing failures (0% retry rate)
- Completion cache achieves >0% hit rate on repeated regulatory queries
- Combined cost per document ≤ 0.005 credits (currently measured at 0.0024)

### Rollback
- `UPDATE` scoring pipeline to route back to claude-4-sonnet
- Disable structured output mode (revert to free-text + parse)
- `TRUNCATE TABLE COMPLETION_CACHE;` if stale entries suspected

---

## Day 22–28: Cortex Search + Cortex Agent

### What Ships
- **Lever 5**: AI_EMBED + Cortex Search service for retrieval-augmented Q&A
- **Lever 6**: Cortex Agent orchestration layer for multi-turn legal research

### Prerequisites
- `LEGAL_CHUNKS` table populated with chunked document content
- Cortex Search service created on `LEGAL_CHUNKS`
- Eval QA pairs validated (30 grounded Q&A pairs, recall@5 ≥ 0.85, MRR ≥ 0.7)
- Agent configuration uses claude-4-sonnet (required model family for Cortex Agents)

### Owner
Legal Doc AI Tech Lead (user acceptance) + Snowflake SE (service configuration)

### Success Criteria
- Retrieval queries return relevant chunks without full-document re-read (>99% credit savings on Q&A)
- Agent correctly answers 30 grounded Q&A pairs from the eval corpus
- End-to-end similarity ≥ 90% of full-document baseline quality
- Agent response latency <10s for typical legal research queries

### Rollback
- `DROP CORTEX SEARCH SERVICE` if retrieval quality degrades
- Agent reverts to direct AI_COMPLETE calls with full document context
- Chunks table and embeddings preserved for re-enablement

---

## Day 29–30: Production Hardening + Ongoing Governance

### What Ships
- **Drift monitor**: Weekly scheduled task evaluating all 5 dimensions
- **Cost telemetry v2**: Daily cost attribution via `DAILY_TOTAL_COST` view
- **Cross-judge bias monitoring**: Quarterly refresh of bias report

### Prerequisites
- All 10 levers deployed and passing eval gates
- Resource monitor active with production budget
- Query tags applied to all pipeline stages

### Owner
Customer IT (operations) + Snowflake SE (quarterly reviews)

### Success Criteria
- Drift monitor task runs weekly without manual intervention
- Monthly cost review cadence established (first review at Day 60)
- All query costs attributable via `SPEND_BY_TAG` view
- No untagged AI_COMPLETE or AI_EMBED calls in production pipeline

### Rollback
- Individual levers can be toggled off independently without affecting others
- Worst-case full rollback: revert to baseline pipeline in <1 hour (single deployment)

---

## Phase Dependencies (Critical Path)

```
Day 1-3:  [Lever 10: Monitor] + [Lever 1: Cache]
             │
Day 4-7:  [Lever 2: Routing] + [Lever 7: Preflight] + [pypdf path]
             │
Day 8-14: [Lever 3: Shadow Scorer] + [Lever 9: Batch] + [Query Tags]
             │                                              │
             ├── 7 days shadow data required ──────────────►│
             │                                              │
Day 15-21:[Lever 3: Promote] + [Lever 4: Structured] + [Lever 8: Cache]
             │
Day 22-28:[Lever 5: Retrieval] + [Lever 6: Agent]
             │
Day 29-30:[Drift Monitor] + [Cost Telemetry] + [Governance]
```

---

## Risk Summary by Phase

| Phase | Risk Level | Gate | Abort Condition |
|-------|:----------:|------|-----------------|
| Day 1–3 | Zero | None (always safe) | N/A |
| Day 4–7 | Low | No false-positive blocks | >1 legitimate doc blocked |
| Day 8–14 | Medium | Drift <5%, agreement ≥85% | Any drift alert fires |
| Day 15–21 | Medium | Quality sign-off from Compliance | Compliance rejects haiku output |
| Day 22–28 | Medium | Recall@5 ≥0.85 on production queries | <80% recall on real queries |
| Day 29–30 | Low | Automation runs cleanly | Task failures >2 consecutive |
