# Legal Doc AI Demo — Runbook (1-Pager)

**Audience**: John Kang (presenter) during the live customer call.
**Estimated runtime**: 30–45 min (single tab pass), 60 min with deep Q&A.

---

## Pre-demo checklist (T–10 min)

```bash
# 1. Pre-warm compute pool + warehouse (avoids 30–60s cold start on first AI_PARSE call)
snow sql -c aws_spcs -q "ALTER COMPUTE POOL SFE_LEGAL_DOC_AI_POOL RESUME IF SUSPENDED;
                          ALTER WAREHOUSE SFE_LEGAL_DOC_AI_WH RESUME IF SUSPENDED;
                          SELECT 1;"

# 2. Refresh Snowsight session token if stale (avoids browser-SSO popup mid-demo)
snow connection test -c aws_spcs

# 3. Open the Streamlit (URL is account-specific — get yours via SQL)
snow sql -c aws_spcs -q \
  "SELECT SYSTEM\$GENERATE_STREAMLIT_URL_FROM_NAME('SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP');"
# Then open the returned URL in your browser, or browse via Snowsight:
# Snowsight  →  Projects  →  Streamlit  →  LEGAL_DOC_AI_APP

# 4. Optional — take a snapshot of the demo state for rollback safety
bash scripts/snapshot_demo_state.sh
```

**Container Runtime caveat**: First page load is ~10s (container start). If you opened the URL pre-demo, navigate away then back to keep it warm.

---

## Click-through script

| # | Tab | Click / Action | What to say (1-liner) |
|---|-----|----------------|----------------------|
| 1 | **Tab 0 — Overview** | Land here | "Where customers like yours typically start. Both architecture diagrams render here — baseline vs. optimized. We'll walk both pipelines." |
| 2 | **Tab 0 — Architecture diagrams** | Scroll | "Baseline: every PDF runs OCR + LAYOUT + claude-4-sonnet scorer + full-doc Q&A. Optimized stacks 6 cost levers." |
| 3 | **Tab 1 — Live Pipeline** | Click "Run live demo" on a small PDF (`cfr_title16_part1_ftc.pdf`) | "Watch each stage tick over: parse → score → embed → ready for retrieval. The token preflight shows you what _would_ have been blocked." |
| 4 | **Tab 2 — Cost Telemetry** | Scroll | "This is real `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` from this account, last 7d. Credits per model, credits per function." |
| 5 | **Tab 3 — Per-Doc Cost** | Scroll | "Same data sliced by filename. The big legal docs (NDAA, ACA, Dodd-Frank) drive most of the cost." |
| 6 | **Tab 4 — Cortex Agent** | Type one of the 10 grounded Q&A questions (see below) | "The agent retrieves the relevant chunks and synthesizes — no full-doc re-feed. Citation comes back with the chunk source." |
| 7 | **Tab 5 — Quality vs Cost** | Scroll through 5 lever verdicts + Pareto chart | "Each lever is gated by a quality test. 4 PASS, 1 MOOT (structured outputs not needed at <3% retry rate). Pareto frontier shows claude-haiku-4-5 dominates at 92% cheaper, 86% reasoning similarity." |
| 8 | **Tab 6 — Lever Savings** | Scroll | "Per-doc savings calculator. Numbers in credits — multiply by your contracted credit rate for dollars." |
| 9 | **Sidebar** | Open a lever 6–11 panel (cost telemetry, completion cache, batch demo, resource monitor, batch search) | "Levers 6–11 are operational guardrails — visibility, batching, monitoring." |

---

## 10 grounded Q&A questions (for Tab 4)

Pick 2–3 based on customer's industry. All have been gold-evaluated; recall@5 = 1.0, MRR = 1.0.

| ID | Question | Source |
|---|---|---|
| qa_001 | What auditing standards must registered public accounting firms follow under Sarbanes-Oxley Section 103? | sarbanes_oxley.pdf |
| qa_002 | What is the primary purpose of the Health Insurance Portability and Accountability Act? | hipaa.pdf |
| qa_003 | What did the Emergency Economic Stabilization Act of 2008 establish? | eesa.pdf |
| qa_004 | What does the Dodd-Frank Wall Street Reform Act establish for consumer financial protection? | dodd_frank.pdf |
| qa_005 | What does CFR Title 16 Part 1 govern? | cfr_title16_ftc.pdf |
| qa_006 | What does the Volcker Rule under Dodd-Frank prohibit banks from doing? | dodd_frank.pdf |
| qa_007 | What does the NDAA fiscal year 2024 authorize for military pay? | ndaa_2024.pdf |
| qa_008 | What does CFR Title 12 Part 1 cover regarding national banks? | cfr_title12_banking.pdf |
| qa_009 | What does the NDAA fiscal year 2018 establish for cybersecurity? | ndaa_2018.pdf |
| qa_010 | What HIPAA provisions protect against improper disclosure of protected health information? | hipaa.pdf |

---

## Recovery plays (if something stalls)

| Symptom | Recovery |
|---|---|
| Tab loads blank / "Container starting" | Wait 10–20 s, re-click. If 30 s+, run `ALTER COMPUTE POOL ... RESUME` again. |
| Agent chat hangs > 30 s | The first call after compute-pool warmup is slow. Apologize, ask another question, the second one will stream fast. |
| Plotly chart shows error | Likely a column-derivation gotcha (see memory rule b5b7359d). Skip the chart, narrate the underlying numbers from the table. |
| "Token expired" or browser SSO popup | Snowsight ID_TOKEN aged out. Run `snow connection test -c aws_spcs` in a side terminal, refresh the tab. |
| Customer asks "show me the SQL" | Open `eval/35_lever5_retrieval_quality.sql` in another tab, walk the search service call. |
| Customer asks for $ figures | "We deliberately keep it in credits. Multiply by your contracted rate — list rate would mislead." |

---

## Open-source publish path (post-CASEC approval)

This repo is **local-only** today. To publish:

1. File CASEC Jira (Cloud and Application Security, Consultation type)
2. Get manager + ProdSec + compliance approvals (CC @Priya Pataskar @Arvind Iyer)
3. After approval:
   ```bash
   gh repo create sfc-gh-jkang/legal-doc-ai-demo --public --source=. --push
   ```
4. LICENSE (Apache-2.0), README owner section, and `.gitignore` secret patterns are already in place.

See `.snowflake/cortex/skills/open-source-repo/SKILL.md` for the full audit script (`audit_repos.sh`).

---

## Reference files

- **Customer pushback prep**: `docs/customer-pushback-prep.md` — pre-canned answers to anticipated questions
- **Backup script**: `scripts/snapshot_demo_state.sh` — DDL + row-count snapshot before/after demo
- **Architecture PNGs**: `docs/architecture-baseline.png`, `docs/architecture-optimized.png`
- **Slide deck outline**: `slides/legal-doc-ai-cost-optimization.md`
