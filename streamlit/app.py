"""
Legal Doc AI — Cost & Quality Optimization Demo
================================================
Streamlit-on-Snowflake app (Container Runtime) demonstrating 10 cost optimization
levers for AI_PARSE_DOCUMENT + AI_COMPLETE pipelines.

Tabs:
  1. Upload & Compare — side-by-side baseline vs optimized
  2. Lever-by-Lever — waterfall chart of incremental savings
  3. Cost Dashboard — daily/model/cumulative credit usage
  4. Ask the Corpus — Cortex Agent chat over chunked legal docs
  5. Quality vs Cost — Pareto frontier scatter + eval pass/fail cards
  6. Operations & Projections — savings calculator, drift, spend tags, guardrails
"""

import difflib
import html
import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from snowflake.snowpark.context import get_active_session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Legal Doc AI — Cost & Quality", layout="wide")

# Approximate credits-per-million-tokens by model (Snowflake pricing, approximate).
# Mark as estimates — actual billing uses CORTEX_FUNCTIONS_USAGE_HISTORY.
MODEL_CREDIT_RATES: dict[str, float] = {
    "claude-4-sonnet": 12.0,  # 12 credits per 1M tokens
    "claude-haiku-4-5": 1.0,
    "claude-3-5-sonnet": 8.0,
    "mistral-large2": 5.0,
    "llama3.3-70b": 3.0,
}

DATABASE = "SNOWFLAKE_EXAMPLE"
SCHEMA = "LEGAL_DOC_AI_DEMO"
FQ = f"{DATABASE}.{SCHEMA}"


# ---------------------------------------------------------------------------
# Session + helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_session():
    return get_active_session()


def run_sql(query: str) -> pd.DataFrame:
    """Execute SQL and return pandas DataFrame. Caches nothing — callers decide."""
    session = get_session()
    return session.sql(query).to_pandas()


@st.cache_data(ttl=300)
def fetch_cached(query: str) -> pd.DataFrame:
    """Execute SQL with 5-min cache for expensive/stable queries."""
    session = get_session()
    return session.sql(query).to_pandas()


def estimate_credits(tokens: int, model: str) -> float:
    """Approximate credit cost from token count + model."""
    rate = MODEL_CREDIT_RATES.get(model, 10.0)
    return tokens * rate / 1_000_000


def _strip_md_fence(s: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` code-fence wrappers some models add."""
    if not s:
        return s
    s = s.strip()
    if s.startswith("```"):
        # Remove opening fence + optional language tag
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
    if s.endswith("```"):
        s = s.rsplit("```", 1)[0].rstrip()
    return s


# ---------------------------------------------------------------------------
# Tab 1: Upload & Compare
# ---------------------------------------------------------------------------
def tab_upload_compare():
    st.header("Compare Results — Side-by-Side")
    st.caption(
        "Pick a PDF that's already been through both pipelines. See the source document, "
        "the actual extracted text from each method, the claude-4-sonnet scoring verdict, "
        "and the real cost numbers — all from the existing run."
    )

    session = get_session()

    # Discover processed PDFs
    try:
        rows = session.sql(f"SELECT DISTINCT filename FROM {FQ}.BASELINE_RESULTS ORDER BY filename").collect()
        available = [r["FILENAME"] for r in rows]
    except Exception as e:
        st.error(f"Could not list processed PDFs: {e}")
        return

    if not available:
        st.warning("No processed PDFs yet. Run the baseline + optimized pipelines first.")
        return

    selected = st.selectbox(
        "Choose a PDF that's already been processed",
        available,
        help="These are the 5 docs the run already executed against. No new credits burned to view.",
    )

    if not selected:
        return

    # ---- Fetch all stored results for this PDF ----
    try:
        baseline_row = session.sql(f"SELECT * FROM {FQ}.BASELINE_RESULTS WHERE filename = '{selected}' LIMIT 1").collect()
        baseline = dict(baseline_row[0].as_dict()) if baseline_row else {}

        routing_row = session.sql(f"SELECT * FROM {FQ}.ROUTING_LOG WHERE filename = '{selected}' ORDER BY routed_at DESC LIMIT 1").collect()
        routing = dict(routing_row[0].as_dict()) if routing_row else {}

        struct_rows = session.sql(f"SELECT * FROM {FQ}.STRUCTURED_AB WHERE filename = '{selected}' ORDER BY tested_at DESC").collect()
        structured = next(
            (dict(r.as_dict()) for r in struct_rows if r["OUTPUT_MODE"] == "structured"),
            {},
        )

        chunk_count_row = session.sql(f"SELECT COUNT(*) AS C FROM {FQ}.LEGAL_CHUNKS WHERE doc_name = '{selected}'").collect()
        chunk_count = int(chunk_count_row[0]["C"]) if chunk_count_row else 0
    except Exception as e:
        st.error(f"Could not load results: {e}")
        return

    # ---- Top section: PDF preview + scoring verdict ----
    pdf_col, verdict_col = st.columns([1, 1])

    with pdf_col:
        st.subheader("Source PDF")
        st.caption(f"Page-by-page render of `{selected}` from `@PDF_STAGE`.")
        try:
            import pypdfium2 as pdfium

            with tempfile.TemporaryDirectory() as tmpdir:
                session.file.get(f"@{FQ}.PDF_STAGE/{selected}", tmpdir)
                local_path = os.path.join(tmpdir, selected)
                if not os.path.exists(local_path):
                    st.warning("PDF not found on stage.")
                else:
                    pdf = pdfium.PdfDocument(local_path)
                    n_pages = len(pdf)
                    st.info(f"Document has {n_pages} pages. Showing first 3.")
                    for page_idx in range(min(3, n_pages)):
                        page = pdf[page_idx]
                        bitmap = page.render(scale=1.5)
                        pil_image = bitmap.to_pil()
                        st.image(
                            pil_image,
                            caption=f"Page {page_idx + 1} of {n_pages}",
                            use_container_width=True,
                        )
                    pdf.close()
        except ImportError:
            st.error("pypdfium2 not installed. Add to pyproject.toml dependencies.")
        except Exception as e:
            st.error(f"Could not render PDF: {e}")

    with verdict_col:
        st.subheader("Sonnet vs Haiku — full diff")
        st.caption("Same prompt, same input text. Two models. Every field they returned, side-by-side, with deltas and a real semantic similarity score.")

        # Parse both verdicts up-front
        scoring_json_str = baseline.get("SCORING_RESULT_JSON", "") or ""
        haiku_json_str = (structured.get("OUTPUT_TEXT", "") or "") if structured else ""

        sonnet_obj: dict = {}
        haiku_obj: dict = {}
        try:
            cleaned = _strip_md_fence(scoring_json_str)
            if cleaned and cleaned.lstrip().startswith("{"):
                sonnet_obj = json.loads(cleaned)
        except Exception:
            sonnet_obj = {}
        try:
            cleaned_h = _strip_md_fence(haiku_json_str)
            parsed_h = json.loads(cleaned_h) if cleaned_h and cleaned_h.lstrip().startswith(("{", "[")) else None
            if isinstance(parsed_h, list) and parsed_h:
                parsed_h = parsed_h[0]
            if isinstance(parsed_h, dict):
                haiku_obj = parsed_h
        except Exception:
            haiku_obj = {}

        sonnet_mode = sonnet_obj.get("best_mode") or "—"
        sonnet_conf = sonnet_obj.get("confidence")
        sonnet_reason = sonnet_obj.get("reasoning") or ""
        haiku_mode = haiku_obj.get("best_mode") or "—"
        haiku_conf = haiku_obj.get("confidence")
        haiku_reason = haiku_obj.get("reasoning") or ""

        # Cost numbers (already computed below in the cost section, recompute here for context)
        st_score_tokens = baseline.get("SCORE_TOKENS") or 0
        ht_score_tokens = (structured.get("OUTPUT_TOKENS") or 0) if structured else 0

        # Field-by-field comparison table
        agreement_emoji = "✅" if (sonnet_mode == haiku_mode and sonnet_mode != "—") else "❌"
        conf_delta = (haiku_conf - sonnet_conf) if (isinstance(sonnet_conf, (int, float)) and isinstance(haiku_conf, (int, float))) else None
        reason_len_delta = len(haiku_reason) - len(sonnet_reason)

        diff_rows = [
            {
                "Field": "Best mode (the verdict)",
                "claude-4-sonnet": sonnet_mode,
                "claude-haiku-4-5": haiku_mode,
                "Match?": agreement_emoji,
            },
            {
                "Field": "Confidence",
                "claude-4-sonnet": f"{sonnet_conf:.2f}" if isinstance(sonnet_conf, (int, float)) else "—",
                "claude-haiku-4-5": f"{haiku_conf:.2f}" if isinstance(haiku_conf, (int, float)) else "—",
                "Match?": (f"Δ {conf_delta:+.2f}" if conf_delta is not None else "—"),
            },
            {
                "Field": "Reasoning length (chars)",
                "claude-4-sonnet": f"{len(sonnet_reason):,}",
                "claude-haiku-4-5": f"{len(haiku_reason):,}",
                "Match?": f"Δ {reason_len_delta:+,}",
            },
            {
                "Field": "Score tokens",
                "claude-4-sonnet": f"{st_score_tokens:,}",
                "claude-haiku-4-5": f"{ht_score_tokens:,}",
                "Match?": "—",
            },
            {
                "Field": "Score credits (this call)",
                "claude-4-sonnet": f"{(st_score_tokens or 0) * 0.000012:.6f}",
                "claude-haiku-4-5": f"{(ht_score_tokens or 0) * 0.000001:.6f}",
                "Match?": (f"~{((st_score_tokens or 0) * 0.000012) / max((ht_score_tokens or 1) * 0.000001, 1e-9):.0f}× cheaper" if ht_score_tokens else "—"),
            },
        ]
        st.dataframe(pd.DataFrame(diff_rows), hide_index=True, use_container_width=True)

        # Live semantic similarity between the two reasoning paragraphs
        if sonnet_reason and haiku_reason:
            try:
                sim_df = run_sql(f"SELECT AI_SIMILARITY($${sonnet_reason.replace('$', '')}$$, $${haiku_reason.replace('$', '')}$$) AS sim")
                if not sim_df.empty:
                    sim_score = float(sim_df.iloc[0]["SIM"])
                    if sim_score >= 0.85:
                        st.success(
                            f"**AI_SIMILARITY(sonnet_reasoning, haiku_reasoning) = {sim_score:.3f}** "
                            f"— the two reasonings are semantically very close. Haiku didn't just match the verdict; "
                            f"it matched the WHY. This is the metric the eval framework's Lever 3 gate uses."
                        )
                    elif sim_score >= 0.65:
                        st.info(
                            f"**AI_SIMILARITY = {sim_score:.3f}** — moderate overlap. Both arrived at the same verdict "
                            f"but emphasized different evidence. Worth reading both."
                        )
                    else:
                        st.warning(
                            f"**AI_SIMILARITY = {sim_score:.3f}** — verdicts may match but reasoning diverges. "
                            f"Inspect carefully; haiku may be right by coincidence rather than understanding."
                        )
            except Exception as e:
                st.caption(f"(Could not compute AI_SIMILARITY live: {e})")

        # The actual reasoning text — side by side, full
        st.markdown("##### Reasoning text — read both")
        rc1, rc2 = st.columns(2)
        rc1.markdown("**claude-4-sonnet** · `~12 credits / 1M tokens`")
        rc1.markdown(f"**Verdict:** {sonnet_mode}  ·  **Confidence:** {sonnet_conf if sonnet_conf is not None else '—'}")
        rc1.text_area(
            "sonnet_reasoning",
            value=sonnet_reason or "(no reasoning stored)",
            height=300,
            label_visibility="collapsed",
            key=f"sonnet_reasoning_{selected}",
        )
        rc2.markdown("**claude-haiku-4-5** · `~1 credit / 1M tokens` (~12× cheaper)")
        rc2.markdown(f"**Verdict:** {haiku_mode}  ·  **Confidence:** {haiku_conf if haiku_conf is not None else '—'}")
        rc2.text_area(
            "haiku_reasoning",
            value=haiku_reason or "(no reasoning stored)",
            height=300,
            label_visibility="collapsed",
            key=f"haiku_reasoning_{selected}",
        )

        # What you can and can't conclude
        if sonnet_mode != "—" and haiku_mode != "—":
            st.divider()
            st.subheader("What this comparison proves (and what it doesn't)")
            if sonnet_mode == haiku_mode:
                st.info(
                    f"**Verdict alignment on this doc:** both picked **{sonnet_mode}**. "
                    f"That's evidence haiku reached the **same scoring decision** as the gold-reference "
                    f"model on this one document — NOT proof that haiku is a better model. Only that "
                    f"haiku is **sufficient for THIS scoring task at ~12× lower cost** *on this kind of document*."
                )
            else:
                st.warning(
                    f"**Disagreement on this doc:** sonnet picked **{sonnet_mode}**, haiku picked **{haiku_mode}**. "
                    f"Read both reasoning fields above. If sonnet's reasoning is more defensible, haiku is "
                    f"NOT safe to substitute for THIS document type."
                )

            concl_a, concl_b = st.columns(2)
            with concl_a:
                st.markdown("**You CAN conclude:**")
                st.markdown(
                    "- For digital legal PDFs of this size, haiku reaches the same scoring decision as sonnet at ~1/12 the price.\n"
                    "- Haiku's reasoning cites specific evidence (section numbers, quotes), comparable to sonnet's.\n"
                    "- Structured output (`response_format=TYPE OBJECT`) eliminated retry loops — haiku returned valid JSON every time.\n"
                    "- Smart routing correctly classified all 5 docs as digital and skipped OCR."
                )
            with concl_b:
                st.markdown("**You CANNOT yet conclude:**")
                st.markdown(
                    "- That haiku is safe for **scanned / image-only PDFs** — the test set has zero. Need 5+ scanned docs.\n"
                    "- That haiku is safe for **non-legal domains** — biomedical, financial, code-heavy PDFs may behave differently.\n"
                    "- That this **scales** — borderline (mixed digital+scanned, multilingual) docs may break.\n"
                    "- Anything statistical with **N=5** — need 30+ docs for the Lever 3 matrix to give a real recommendation."
                )

            st.markdown("##### The actual recommendation logic for the customer")
            st.markdown(
                "Run `eval/33_lever3_model_matrix.sql` across **30+ documents** including digital + scanned + "
                "multilingual. Score each `(doc, model)` pair on:\n"
                "1. **Agreement-with-sonnet** — did the cheaper model pick the same extraction?\n"
                "2. **Reasoning fidelity** — `AI_SIMILARITY(cheap_reasoning, sonnet_reasoning)` ≥ 0.85\n"
                "3. **Cross-judge bias check** — claude judges mistral, mistral judges claude. Never self-judge.\n\n"
                "A model only earns the recommendation if **(a)** it sits on the Pareto frontier (cheaper than "
                "sonnet AND quality-equivalent), **(b)** disagreement-rate <5% on holdout, AND **(c)** the "
                "disagreements concentrate on doc types we can route around (e.g., 'haiku struggles with scanned' "
                "→ use sonnet for scanned, haiku for digital)."
            )

    st.divider()

    # ---- Three-column extraction comparison ----
    st.subheader("Three pipelines, side-by-side")
    st.caption("Same PDF, three extraction paths. See the actual text each produced, with token counts and credit cost.")

    col_ocr, col_layout, col_opt = st.columns(3)

    ocr_text = baseline.get("OCR_TEXT", "") or ""
    layout_text = baseline.get("LAYOUT_TEXT", "") or ""
    opt_mode = routing.get("CHOSEN_MODE", "?")
    opt_text = layout_text if opt_mode == "LAYOUT" else ocr_text  # the routed text

    ocr_tokens = baseline.get("OCR_TOKENS") or 0
    layout_tokens = baseline.get("LAYOUT_TOKENS") or 0
    score_tokens = baseline.get("SCORE_TOKENS") or 0
    haiku_tokens = (structured.get("OUTPUT_TOKENS") or 0) if structured else 0

    ocr_credits = ocr_tokens * 0.000003
    layout_credits = layout_tokens * 0.000003
    sonnet_score_credits = score_tokens * 0.000012
    haiku_score_credits = haiku_tokens * 0.000001
    baseline_total = ocr_credits + layout_credits + sonnet_score_credits
    optimized_total = (layout_credits if opt_mode == "LAYOUT" else ocr_credits) + haiku_score_credits

    with col_ocr:
        st.markdown("##### Baseline · OCR mode")
        st.metric("Tokens", f"{ocr_tokens:,}")
        st.metric("Credits", f"{ocr_credits:.4f}")
        st.text_area(
            "Extracted text (first 4 KB)",
            value=ocr_text[:4000] if ocr_text else "(no OCR text stored)",
            height=400,
            key=f"ocr_text_{selected}",
            label_visibility="collapsed",
        )

    with col_layout:
        st.markdown("##### Baseline · LAYOUT mode")
        st.metric("Tokens", f"{layout_tokens:,}")
        st.metric("Credits", f"{layout_credits:.4f}")
        st.text_area(
            "Extracted text (first 4 KB)",
            value=layout_text[:4000] if layout_text else "(no LAYOUT text stored)",
            height=400,
            key=f"layout_text_{selected}",
            label_visibility="collapsed",
        )

    with col_opt:
        st.markdown(f"##### Optimized · routed → {opt_mode}")
        if routing:
            st.caption(
                f"Smart router classified as **{routing.get('CLASSIFIED_AS', '?')}** "
                f"(confidence {routing.get('CONFIDENCE', 0):.2f}, method {routing.get('ROUTING_METHOD', '?')})"
            )
        st.metric("Tokens", f"{(layout_tokens if opt_mode == 'LAYOUT' else ocr_tokens):,}")
        st.metric("Credits (parse only)", f"{(layout_credits if opt_mode == 'LAYOUT' else ocr_credits):.4f}")
        st.text_area(
            "Extracted text (first 4 KB)",
            value=opt_text[:4000] if opt_text else "(no routed text stored)",
            height=400,
            key=f"opt_text_{selected}",
            label_visibility="collapsed",
        )

    st.divider()

    # ---- Content-level diff: where do OCR and LAYOUT actually differ? ----
    st.subheader("Major content differences — OCR vs LAYOUT")
    st.caption(
        "This is the part you can SEE: a line-by-line semantic diff of what each "
        "extractor produced. Red = OCR-only lines (LAYOUT dropped them or rendered "
        "differently). Green = LAYOUT-only lines (OCR missed them or formatted them "
        "differently). Lines that match are collapsed. This is where the routing "
        "decision actually has impact."
    )

    diff_lim = st.slider(
        "Diff window (chars from start of each text)",
        min_value=2000,
        max_value=20000,
        value=8000,
        step=1000,
        help="Larger window = more diff but slower render.",
        key=f"diff_window_{selected}",
    )

    def _normalize_for_diff(text: str) -> list[str]:
        # Collapse whitespace, drop empty lines, return non-empty lines
        if not text:
            return []
        text = re.sub(r"[ \t]+", " ", text)
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    ocr_lines = _normalize_for_diff(ocr_text[:diff_lim])
    layout_lines = _normalize_for_diff(layout_text[:diff_lim])

    sm = difflib.SequenceMatcher(None, ocr_lines, layout_lines)
    only_ocr: list[str] = []
    only_layout: list[str] = []
    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
        elif tag == "delete":
            only_ocr.extend(ocr_lines[i1:i2])
        elif tag == "insert":
            only_layout.extend(layout_lines[j1:j2])
        elif tag == "replace":
            only_ocr.extend(ocr_lines[i1:i2])
            only_layout.extend(layout_lines[j1:j2])

    diff_metric_col1, diff_metric_col2, diff_metric_col3, diff_metric_col4 = st.columns(4)
    diff_metric_col1.metric(
        "Lines matched (both)",
        f"{matched:,}",
        help="Lines OCR and LAYOUT extracted identically.",
    )
    diff_metric_col2.metric(
        "OCR-only lines",
        f"{len(only_ocr):,}",
        help="Lines OCR captured that LAYOUT missed (or rendered differently).",
    )
    diff_metric_col3.metric(
        "LAYOUT-only lines",
        f"{len(only_layout):,}",
        help="Lines LAYOUT captured that OCR missed (often: tables, headers, structured content).",
    )
    overlap_pct = matched / max(matched + max(len(only_ocr), len(only_layout)), 1) * 100
    diff_metric_col4.metric(
        "Line-level overlap",
        f"{overlap_pct:.1f}%",
        help="Higher = the two extractors are saying the same thing. Lower = real divergence.",
    )

    diff_left, diff_right = st.columns(2)
    with diff_left:
        st.markdown(f"**OCR-only lines ({len(only_ocr)})** — these may be noise or signal LAYOUT dropped")
        if only_ocr:
            st.text_area(
                "ocr_only",
                value="\n".join(only_ocr[:200]),
                height=300,
                label_visibility="collapsed",
                key=f"ocr_only_{selected}",
            )
        else:
            st.success("LAYOUT captured everything OCR did. (This is the digital-PDF success case.)")
    with diff_right:
        st.markdown(f"**LAYOUT-only lines ({len(only_layout)})** — structure OCR couldn't see")
        if only_layout:
            st.text_area(
                "layout_only",
                value="\n".join(only_layout[:200]),
                height=300,
                label_visibility="collapsed",
                key=f"layout_only_{selected}",
            )
        else:
            st.info("OCR captured everything LAYOUT did. Routing to OCR-only is safe for this doc.")

    # Numeric/structural fidelity check — what numbers/dates/dollar amounts appear in each?
    def _extract_numerics(text: str) -> set[str]:
        if not text:
            return set()
        pattern = r"\$[0-9,]+(?:\.[0-9]+)?|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d+%|\b\d{4}\b"
        return set(re.findall(pattern, text[:diff_lim]))

    ocr_nums = _extract_numerics(ocr_text)
    layout_nums = _extract_numerics(layout_text)
    only_in_ocr = ocr_nums - layout_nums
    only_in_layout = layout_nums - ocr_nums
    in_both = ocr_nums & layout_nums

    st.markdown("##### Numeric / date / dollar fidelity")
    st.caption("Real legal docs hinge on numbers (dates, dollar amounts, percentages, years). If one extractor misses these, that's a quality red flag.")
    n_col1, n_col2, n_col3 = st.columns(3)
    n_col1.metric("In both", f"{len(in_both):,}")
    n_col2.metric("Only in OCR", f"{len(only_in_ocr):,}", delta=None if not only_in_ocr else f"{len(only_in_ocr)} potential drops")
    n_col3.metric("Only in LAYOUT", f"{len(only_in_layout):,}", delta=None if not only_in_layout else f"{len(only_in_layout)} potential drops")
    if only_in_ocr or only_in_layout:
        with st.expander("See specific numbers each extractor found exclusively"):
            ec1, ec2 = st.columns(2)
            ec1.markdown("**OCR-only numerics:**")
            ec1.code(", ".join(sorted(only_in_ocr)) or "(none)")
            ec2.markdown("**LAYOUT-only numerics:**")
            ec2.code(", ".join(sorted(only_in_layout)) or "(none)")

    st.divider()

    # ---- Per-model verdict comparison ----
    st.subheader("Compare any two scoring models on this doc")
    st.caption(
        "Pick any cheap candidate model — see how its scoring decision compares to claude-4-sonnet "
        "(the gold reference). The actual verdict text, agreement flag, token cost, and live "
        "AI_SIMILARITY between the two reasonings are pulled from `SCORER_AB`."
    )

    try:
        scorer_models_df = run_sql(
            f"SELECT DISTINCT scorer_model FROM {FQ}.SCORER_AB WHERE filename = '{selected}' AND scorer_model != 'claude-4-sonnet' ORDER BY scorer_model"
        )
        scorer_models = scorer_models_df["SCORER_MODEL"].tolist() if not scorer_models_df.empty else []
    except Exception:
        scorer_models = []

    if not scorer_models:
        st.info(f"No SCORER_AB rows yet for this doc — run `CALL RUN_SCORER_MATRIX(ARRAY_CONSTRUCT('{selected}'));` to populate the 5-model comparison.")
    else:
        chosen_model = st.selectbox(
            "Cheap candidate model (vs gold = claude-4-sonnet)",
            scorer_models,
            index=scorer_models.index("claude-haiku-4-5") if "claude-haiku-4-5" in scorer_models else 0,
            key=f"scorer_model_pick_{selected}",
        )

        try:
            gold_row = run_sql(
                f"SELECT scoring_result, score_tokens, score_credits_est, agreement_with_gold "
                f"FROM {FQ}.SCORER_AB WHERE filename = '{selected}' AND scorer_model = 'claude-4-sonnet' LIMIT 1"
            )
            cand_row = run_sql(
                f"SELECT scoring_result, score_tokens, score_credits_est, agreement_with_gold "
                f"FROM {FQ}.SCORER_AB WHERE filename = '{selected}' AND scorer_model = '{chosen_model}' LIMIT 1"
            )
        except Exception as e:
            gold_row = pd.DataFrame()
            cand_row = pd.DataFrame()
            st.warning(f"Could not load scorer rows: {e}")

        if not gold_row.empty and not cand_row.empty:
            gold_text = gold_row.iloc[0]["SCORING_RESULT"] or ""
            cand_text = cand_row.iloc[0]["SCORING_RESULT"] or ""
            gold_tokens = int(gold_row.iloc[0]["SCORE_TOKENS"] or 0)
            cand_tokens = int(cand_row.iloc[0]["SCORE_TOKENS"] or 0)
            gold_credits = float(gold_row.iloc[0]["SCORE_CREDITS_EST"] or 0)
            cand_credits = float(cand_row.iloc[0]["SCORE_CREDITS_EST"] or 0)
            cand_agrees = bool(cand_row.iloc[0]["AGREEMENT_WITH_GOLD"]) if cand_row.iloc[0]["AGREEMENT_WITH_GOLD"] is not None else False

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Tokens (gold)", f"{gold_tokens:,}")
            mc2.metric(f"Tokens ({chosen_model})", f"{cand_tokens:,}")
            cost_ratio = gold_credits / max(cand_credits, 1e-9) if cand_credits else 0
            mc3.metric("Cost ratio (gold ÷ cand)", f"{cost_ratio:.1f}×")
            mc4.metric("Verdict matches gold?", "✅ Yes" if cand_agrees else "❌ No")

            # Render a unified diff of the two scoring results, with HTML coloring
            def _ratio(a: str, b: str) -> float:
                if not a or not b:
                    return 0.0
                return difflib.SequenceMatcher(None, a, b).ratio()

            txt_ratio = _ratio(gold_text, cand_text)
            st.metric("Text-level similarity (Levenshtein-ish)", f"{txt_ratio:.3f}")

            # Live AI_SIMILARITY between the two
            if gold_text and cand_text:
                try:
                    g = gold_text.replace("$", "").replace("'", "''")[:4000]
                    c = cand_text.replace("$", "").replace("'", "''")[:4000]
                    sim_df = run_sql(f"SELECT AI_SIMILARITY('{g}', '{c}') AS S")
                    if not sim_df.empty:
                        ai_sim = float(sim_df.iloc[0]["S"])
                        if ai_sim >= 0.85:
                            st.success(f"AI_SIMILARITY = **{ai_sim:.3f}** — the cheap model's verdict text is semantically interchangeable with gold.")
                        elif ai_sim >= 0.65:
                            st.info(f"AI_SIMILARITY = **{ai_sim:.3f}** — moderate alignment. Verdict matches but evidence cited differs.")
                        else:
                            st.warning(f"AI_SIMILARITY = **{ai_sim:.3f}** — low semantic overlap. Investigate before deploying this model.")
                except Exception as e:
                    st.caption(f"(AI_SIMILARITY skipped: {e})")

            # Side-by-side raw output with diff highlighting
            st.markdown("##### Verdict text — actual model output")
            cmpl, cmpr = st.columns(2)
            cmpl.markdown("**claude-4-sonnet** (gold)")
            cmpl.code(gold_text[:2000] or "(empty)", language="json")
            cmpr.markdown(f"**{chosen_model}**")
            cmpr.code(cand_text[:2000] or "(empty)", language="json")

            # Unified diff view
            with st.expander(f"Unified diff: gold vs {chosen_model}"):
                diff_html = []
                udiff = difflib.unified_diff(
                    (gold_text or "")[:3000].splitlines(),
                    (cand_text or "")[:3000].splitlines(),
                    fromfile="claude-4-sonnet",
                    tofile=chosen_model,
                    lineterm="",
                )
                for line in udiff:
                    safe = html.escape(line)
                    if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                        diff_html.append(f'<div style="color:#888;font-family:monospace;">{safe}</div>')
                    elif line.startswith("+"):
                        diff_html.append(f'<div style="background:#1e3a1e;color:#a3e6a3;font-family:monospace;padding:2px 6px;">{safe}</div>')
                    elif line.startswith("-"):
                        diff_html.append(f'<div style="background:#3a1e1e;color:#e6a3a3;font-family:monospace;padding:2px 6px;">{safe}</div>')
                    else:
                        diff_html.append(f'<div style="font-family:monospace;padding:2px 6px;">{safe}</div>')
                st.markdown("".join(diff_html), unsafe_allow_html=True)

    st.divider()

    # ============================================================
    # Quality probes — 6 ways to compare extraction methods
    # ============================================================
    st.subheader("Extraction quality probes")
    st.caption(
        "Six lenses for checking whether OCR vs LAYOUT (and the cheaper scoring "
        "models) actually preserve content fidelity. Each is an independent test."
    )

    # ---- Probe 1: Search-and-locate ----
    with st.expander("🔎 Search-and-locate — does each method preserve a specific phrase?"):
        st.caption(
            "Type any phrase from the source PDF. See hits per extraction method "
            "with surrounding context. The 'did the dollar amount survive?' check."
        )
        search_q = st.text_input(
            "Phrase to find",
            value="",
            placeholder='e.g. "the organization" or "$5,000,000"',
            key=f"sl_q_{selected}",
        )
        if search_q:
            def _search_with_context(text: str, query: str, context_chars: int = 80):
                if not text or not query:
                    return 0, []
                hits = []
                low = text.lower()
                q = query.lower()
                start = 0
                while True:
                    idx = low.find(q, start)
                    if idx < 0:
                        break
                    s = max(0, idx - context_chars)
                    e = min(len(text), idx + len(query) + context_chars)
                    hits.append(("..." if s > 0 else "") + text[s:e] + ("..." if e < len(text) else ""))
                    start = idx + len(query)
                    if len(hits) >= 5:
                        break
                return low.count(q), hits

            ocr_n, ocr_hits = _search_with_context(ocr_text, search_q)
            layout_n, layout_hits = _search_with_context(layout_text, search_q)
            opt_n, opt_hits = _search_with_context(opt_text, search_q)

            sm1, sm2, sm3 = st.columns(3)
            sm1.metric("OCR matches", ocr_n)
            sm2.metric("LAYOUT matches", layout_n)
            sm3.metric(f"Routed ({opt_mode}) matches", opt_n)

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.markdown("**OCR context**")
                if ocr_hits:
                    for h in ocr_hits:
                        st.code(h, language=None)
                else:
                    st.caption("No matches")
            with sc2:
                st.markdown("**LAYOUT context**")
                if layout_hits:
                    for h in layout_hits:
                        st.code(h, language=None)
                else:
                    st.caption("No matches")
            with sc3:
                st.markdown(f"**Routed ({opt_mode}) context**")
                if opt_hits:
                    for h in opt_hits:
                        st.code(h, language=None)
                else:
                    st.caption("No matches")

            if ocr_n != layout_n:
                st.warning(
                    f"Mismatch: OCR found {ocr_n}, LAYOUT found {layout_n}. "
                    "One method is dropping or duplicating this content."
                )

    # ---- Probe 2: Structural quality scorecard ----
    with st.expander("📐 Structural quality scorecard — what does each method preserve?"):
        st.caption(
            "Auto-computed counts of structural elements per extraction. "
            "Higher numbers don't always mean better — but big mismatches signal real divergence."
        )

        def _structure_counts(text: str) -> dict:
            if not text:
                return {k: 0 for k in [
                    "Heading lines (ALL CAPS or #)", "Numbered list items",
                    "Bulleted list items", "Table-row separators (|)",
                    "URLs", "Footnote/citation [N]", "Page-break markers",
                    "Lines", "Words"
                ]}
            heading_re = re.compile(r"^(#{1,6}\s|[A-Z][A-Z0-9 \-:.,()]{4,}$)", re.MULTILINE)
            numbered_re = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
            bullet_re = re.compile(r"^\s*[•\-\*]\s+\S", re.MULTILINE)
            url_re = re.compile(r"https?://\S+")
            footnote_re = re.compile(r"\[\d+\]")
            return {
                "Heading lines (ALL CAPS or #)": len(heading_re.findall(text)),
                "Numbered list items": len(numbered_re.findall(text)),
                "Bulleted list items": len(bullet_re.findall(text)),
                "Table-row separators (|)": text.count("|"),
                "URLs": len(url_re.findall(text)),
                "Footnote/citation [N]": len(footnote_re.findall(text)),
                "Page-break markers": text.count("\f") + text.count("--- PAGE"),
                "Lines": text.count("\n") + 1,
                "Words": len(text.split()),
            }

        ocr_struct = _structure_counts(ocr_text)
        layout_struct = _structure_counts(layout_text)
        struct_df = pd.DataFrame(
            {
                "Indicator": list(ocr_struct.keys()),
                "OCR": list(ocr_struct.values()),
                "LAYOUT": list(layout_struct.values()),
                "Δ (LAYOUT − OCR)": [
                    layout_struct[k] - ocr_struct[k] for k in ocr_struct
                ],
            }
        )
        st.dataframe(struct_df, hide_index=True, use_container_width=True)

        big_deltas = [
            row for _, row in struct_df.iterrows()
            if abs(row["Δ (LAYOUT − OCR)"]) > max(5, 0.2 * max(row["OCR"], row["LAYOUT"], 1))
        ]
        if big_deltas:
            st.markdown("**Notable divergences** (>20% difference):")
            for row in big_deltas:
                higher = "LAYOUT" if row["Δ (LAYOUT − OCR)"] > 0 else "OCR"
                st.markdown(
                    f"- **{row['Indicator']}**: {higher} captures "
                    f"{abs(row['Δ (LAYOUT − OCR)']):,} more than the other"
                )

    # ---- Probe 3: Live AI judge ----
    with st.expander("⚖️ Live AI judge — let claude grade both extractions on a rubric"):
        st.caption(
            "Calls AI_COMPLETE with both extractions and a legal-domain rubric. "
            "Returns per-criterion scores (faithfulness, structural integrity, "
            "numeric accuracy, headings preserved) plus a verdict. ~3 credits per judgment."
        )
        judge_model = st.selectbox(
            "Judge model",
            ["claude-haiku-4-5", "claude-4-sonnet", "claude-sonnet-4-6", "mistral-large2"],
            help="Cross-family rule: don't have a model judge its own family. "
                 "If the contestant is claude, use mistral; if mistral, use claude.",
            key=f"judge_model_{selected}",
        )
        if st.button("Run AI judge now", key=f"run_judge_{selected}"):
            with st.spinner(f"{judge_model} judging extractions..."):
                rubric = (
                    "You are a legal-document-extraction judge. Score TWO extractions "
                    "of the same legal PDF on a 1-5 scale per criterion:\n"
                    "1. Faithfulness — does the text match what a human reading the PDF "
                    "would write down?\n"
                    "2. Structural integrity — preserved headings, numbered sections, "
                    "tables, lists?\n"
                    "3. Numeric accuracy — dates, dollar amounts, percentages, statute "
                    "numbers preserved?\n"
                    "4. Reading order — does the text flow as the document is read top-"
                    "to-bottom, left-to-right?\n\n"
                    "Return JSON: {\"ocr\":{\"faithfulness\":N,\"structural\":N,\"numeric\":N,"
                    "\"reading_order\":N,\"notes\":\"...\"},\"layout\":{...same...},"
                    "\"winner\":\"OCR|LAYOUT|TIE\",\"reasoning\":\"...\"}"
                )
                ocr_sample = (ocr_text or "")[:6000].replace("'", "''").replace("$", "")
                layout_sample = (layout_text or "")[:6000].replace("'", "''").replace("$", "")
                prompt = (
                    rubric + "\n\n--- OCR EXTRACTION ---\n" + ocr_sample +
                    "\n\n--- LAYOUT EXTRACTION ---\n" + layout_sample
                )
                try:
                    judge_df = run_sql(
                        f"SELECT SNOWFLAKE.CORTEX.AI_COMPLETE('{judge_model}', "
                        f"$${prompt}$$) AS J"
                    )
                    if not judge_df.empty:
                        raw = str(judge_df.iloc[0]["J"])
                        cleaned = _strip_md_fence(raw)
                        try:
                            parsed = json.loads(cleaned)
                            jc1, jc2 = st.columns(2)
                            with jc1:
                                st.markdown("**OCR scores**")
                                ocr_scores = parsed.get("ocr", {})
                                for k in ["faithfulness", "structural", "numeric", "reading_order"]:
                                    st.metric(k.replace("_", " ").title(),
                                              f"{ocr_scores.get(k, '—')}/5")
                                st.caption(ocr_scores.get("notes", ""))
                            with jc2:
                                st.markdown("**LAYOUT scores**")
                                layout_scores = parsed.get("layout", {})
                                for k in ["faithfulness", "structural", "numeric", "reading_order"]:
                                    st.metric(k.replace("_", " ").title(),
                                              f"{layout_scores.get(k, '—')}/5")
                                st.caption(layout_scores.get("notes", ""))
                            winner = parsed.get("winner", "—")
                            st.success(f"**Verdict:** {winner}")
                            st.markdown(f"**Reasoning:** {parsed.get('reasoning', '')}")
                        except json.JSONDecodeError:
                            st.warning("Judge returned non-JSON; showing raw output:")
                            st.code(raw)
                except Exception as e:
                    st.error(f"Judge call failed: {e}")

    # ---- Probe 4: Same-question Q&A test ----
    with st.expander("❓ Same-question Q&A test — do the answers diverge?"):
        st.caption(
            "Ask the same question against each extraction. If the cheap method's "
            "answer matches gold, you can trust it. If they diverge, investigate."
        )
        qa_question = st.text_input(
            "Question to ask both extractions",
            value="What entity does this document establish or regulate?",
            key=f"qa_q_{selected}",
        )
        if st.button("Run Q&A test", key=f"run_qa_{selected}"):
            with st.spinner("Asking each extraction..."):
                qa_prompt_template = (
                    "Based ONLY on the following document text, answer this question "
                    "in 2-3 sentences: '" + qa_question.replace("'", "''") + "'\n\n"
                    "If the answer isn't in the text, say 'Not in extracted text.'\n\n"
                    "DOCUMENT TEXT:\n"
                )
                ocr_clip = (ocr_text or "")[:6000].replace("$", "")
                layout_clip = (layout_text or "")[:6000].replace("$", "")
                try:
                    res_df = run_sql(
                        "SELECT "
                        f"SNOWFLAKE.CORTEX.AI_COMPLETE('claude-haiku-4-5', $${qa_prompt_template}{ocr_clip}$$) AS OCR_ANS, "
                        f"SNOWFLAKE.CORTEX.AI_COMPLETE('claude-haiku-4-5', $${qa_prompt_template}{layout_clip}$$) AS LAYOUT_ANS"
                    )
                    if not res_df.empty:
                        ocr_ans = str(res_df.iloc[0]["OCR_ANS"]).strip()
                        layout_ans = str(res_df.iloc[0]["LAYOUT_ANS"]).strip()
                        qc1, qc2 = st.columns(2)
                        qc1.markdown("**Answer from OCR text**")
                        qc1.info(ocr_ans)
                        qc2.markdown("**Answer from LAYOUT text**")
                        qc2.info(layout_ans)
                        # Quick AI_SIMILARITY between answers
                        try:
                            a = ocr_ans.replace("'", "''").replace("$", "")[:2000]
                            b = layout_ans.replace("'", "''").replace("$", "")[:2000]
                            sim = run_sql(f"SELECT AI_SIMILARITY('{a}', '{b}') AS S")
                            if not sim.empty:
                                ai_s = float(sim.iloc[0]["S"])
                                if ai_s >= 0.85:
                                    st.success(f"Answers semantically agree (AI_SIMILARITY = {ai_s:.3f}).")
                                elif ai_s >= 0.65:
                                    st.info(f"Partial agreement (AI_SIMILARITY = {ai_s:.3f}).")
                                else:
                                    st.warning(f"Answers diverge (AI_SIMILARITY = {ai_s:.3f}). Read both.")
                        except Exception:
                            pass
                except Exception as e:
                    st.error(f"Q&A call failed: {e}")

    # ---- Probe 5: Vocabulary diff ----
    with st.expander("📚 Vocabulary diff — what words does each method capture uniquely?"):
        st.caption(
            "Top frequency-weighted words unique to each method. Reveals OCR noise "
            "(URLs, page numbers) and LAYOUT vocabulary OCR drops."
        )

        def _word_freq(text: str, top_n: int = 50) -> dict:
            if not text:
                return {}
            stopwords = set([
                "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "at",
                "is", "are", "was", "were", "be", "been", "with", "by", "as", "this",
                "that", "it", "from", "which", "any", "all", "such", "shall", "may"
            ])
            words = re.findall(r"\b[A-Za-z]{3,}\b", text.lower())
            freq: dict[str, int] = {}
            for w in words:
                if w in stopwords:
                    continue
                freq[w] = freq.get(w, 0) + 1
            return dict(sorted(freq.items(), key=lambda x: -x[1])[:top_n])

        ocr_vocab = _word_freq(ocr_text, 80)
        layout_vocab = _word_freq(layout_text, 80)
        only_ocr_vocab = sorted(
            ((w, ocr_vocab[w]) for w in ocr_vocab if w not in layout_vocab),
            key=lambda x: -x[1],
        )[:30]
        only_layout_vocab = sorted(
            ((w, layout_vocab[w]) for w in layout_vocab if w not in ocr_vocab),
            key=lambda x: -x[1],
        )[:30]

        vc1, vc2 = st.columns(2)
        with vc1:
            st.markdown("**Top words only in OCR**")
            if only_ocr_vocab:
                vdf = pd.DataFrame(only_ocr_vocab, columns=["word", "count"])
                st.dataframe(vdf, hide_index=True, use_container_width=True)
            else:
                st.caption("No vocabulary unique to OCR.")
        with vc2:
            st.markdown("**Top words only in LAYOUT**")
            if only_layout_vocab:
                vdf = pd.DataFrame(only_layout_vocab, columns=["word", "count"])
                st.dataframe(vdf, hide_index=True, use_container_width=True)
            else:
                st.caption("No vocabulary unique to LAYOUT.")

        st.caption(
            f"OCR: {sum(ocr_vocab.values()):,} content words · "
            f"LAYOUT: {sum(layout_vocab.values()):,} content words · "
            f"shared vocabulary size: {len(set(ocr_vocab) & set(layout_vocab))}"
        )

    # ---- Probe 6: Per-page side-by-side ----
    with st.expander("📄 Per-page side-by-side — pick a page, see all 4 views"):
        st.caption(
            "Page selector. Shows the rendered PDF page next to OCR / LAYOUT / "
            "routed text for the same page (page boundaries detected via heuristic)."
        )

        def _split_pages(text: str) -> list[str]:
            if not text:
                return []
            # Try form-feed first, then explicit page markers, fall back to length-based
            if "\f" in text:
                return [p for p in text.split("\f") if p.strip()]
            page_marker_re = re.compile(r"\n*[-=]{3,}\s*PAGE\s+\d+", re.IGNORECASE)
            if page_marker_re.search(text):
                return [p for p in page_marker_re.split(text) if p.strip()]
            # Heuristic: split every ~3000 chars at paragraph boundary
            pages = []
            chunk = 3000
            i = 0
            while i < len(text):
                end = min(i + chunk, len(text))
                if end < len(text):
                    nxt = text.find("\n\n", end)
                    if nxt > 0 and nxt - end < 500:
                        end = nxt
                pages.append(text[i:end])
                i = end
            return pages

        ocr_pages = _split_pages(ocr_text)
        layout_pages = _split_pages(layout_text)
        opt_pages = _split_pages(opt_text)
        n_pages = max(len(ocr_pages), len(layout_pages), len(opt_pages))
        if n_pages == 0:
            st.info("No text pages available.")
        else:
            page_idx = st.slider(
                f"Page (1 to {n_pages})",
                1, n_pages, 1,
                key=f"page_picker_{selected}",
            )
            i = page_idx - 1
            try:
                import pypdfium2 as pdfium
                pdf_col, ocr_col, layout_col, opt_col = st.columns([1.2, 1, 1, 1])
                with pdf_col:
                    st.markdown(f"**PDF page {page_idx}**")
                    with tempfile.TemporaryDirectory() as tmpdir:
                        session.file.get(f"@{FQ}.PDF_STAGE/{selected}", tmpdir)
                        local_path = os.path.join(tmpdir, selected)
                        if os.path.exists(local_path):
                            pdf = pdfium.PdfDocument(local_path)
                            if i < len(pdf):
                                page = pdf[i]
                                bitmap = page.render(scale=1.5)
                                st.image(bitmap.to_pil(), use_container_width=True)
                            pdf.close()
                with ocr_col:
                    st.markdown("**OCR text**")
                    st.text_area(
                        "ocr_p", value=ocr_pages[i] if i < len(ocr_pages) else "(no text)",
                        height=400, label_visibility="collapsed",
                        key=f"ocr_p_{selected}_{page_idx}"
                    )
                with layout_col:
                    st.markdown("**LAYOUT text**")
                    st.text_area(
                        "layout_p", value=layout_pages[i] if i < len(layout_pages) else "(no text)",
                        height=400, label_visibility="collapsed",
                        key=f"layout_p_{selected}_{page_idx}"
                    )
                with opt_col:
                    st.markdown(f"**Routed ({opt_mode})**")
                    st.text_area(
                        "opt_p", value=opt_pages[i] if i < len(opt_pages) else "(no text)",
                        height=400, label_visibility="collapsed",
                        key=f"opt_p_{selected}_{page_idx}"
                    )
            except Exception as e:
                st.warning(f"Per-page render failed: {e}. Showing text only.")

    st.divider()
    st.subheader("Cost comparison for this single PDF")

    cost_col1, cost_col2, cost_col3, cost_col4 = st.columns(4)

    cost_col1.metric(
        "Baseline total",
        f"{baseline_total:.4f} cr",
        help="OCR parse + LAYOUT parse + claude-4-sonnet score",
    )
    cost_col2.metric(
        "Optimized total",
        f"{optimized_total:.4f} cr",
        help=f"{opt_mode} parse only + claude-haiku-4-5 score (structured)",
    )
    if baseline_total > 0:
        savings_pct = (1 - optimized_total / baseline_total) * 100
        cost_col3.metric("Savings", f"{savings_pct:.1f}%")
    cost_col4.metric("Chunks indexed (Lever 5)", f"{chunk_count:,}")

    # Stacked bar showing where the money goes
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="OCR parse",
            x=["Baseline", "Optimized"],
            y=[ocr_credits, ocr_credits if opt_mode == "OCR" else 0],
            marker_color="#FFB3B3",
        )
    )
    fig.add_trace(
        go.Bar(
            name="LAYOUT parse",
            x=["Baseline", "Optimized"],
            y=[layout_credits, layout_credits if opt_mode == "LAYOUT" else 0],
            marker_color="#FFD8B3",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Score (sonnet)",
            x=["Baseline", "Optimized"],
            y=[sonnet_score_credits, 0],
            marker_color="#FF6B6B",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Score (haiku)",
            x=["Baseline", "Optimized"],
            y=[0, haiku_score_credits],
            marker_color="#4ECDC4",
        )
    )
    fig.update_layout(
        barmode="stack",
        title=f"Credit cost breakdown: {selected}",
        yaxis_title="Credits",
        height=380,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---- Quality scoring (manual rating) ----
    st.divider()
    st.subheader("Manual quality check")
    st.caption("Read the extracted text columns above against the source PDF. Score each method 1-5. This is what you'd walk a customer through.")

    rate_col1, rate_col2, rate_col3 = st.columns(3)
    with rate_col1:
        st.markdown("**Baseline · OCR**")
        ocr_rating = st.slider(
            "OCR quality",
            1,
            5,
            3,
            key=f"ocr_q_{selected}",
            label_visibility="collapsed",
        )
    with rate_col2:
        st.markdown("**Baseline · LAYOUT**")
        layout_rating = st.slider(
            "LAYOUT quality",
            1,
            5,
            4,
            key=f"layout_q_{selected}",
            label_visibility="collapsed",
        )
    with rate_col3:
        st.markdown(f"**Optimized · {opt_mode}**")
        opt_rating = st.slider(
            "Optimized quality",
            1,
            5,
            4,
            key=f"opt_q_{selected}",
            label_visibility="collapsed",
        )

    st.markdown("##### Quality / cost ratio (higher = better)")
    qc_col1, qc_col2, qc_col3 = st.columns(3)
    qc_col1.metric(
        "OCR (baseline)",
        f"{(ocr_rating / max(ocr_credits, 0.0001)):.0f}",
        help=f"Quality {ocr_rating} ÷ cost {ocr_credits:.4f} cr",
    )
    qc_col2.metric(
        "LAYOUT (baseline)",
        f"{(layout_rating / max(layout_credits, 0.0001)):.0f}",
        help=f"Quality {layout_rating} ÷ cost {layout_credits:.4f} cr",
    )
    qc_col3.metric(
        f"Optimized ({opt_mode})",
        f"{(opt_rating / max(optimized_total, 0.0001)):.0f}",
        help=f"Quality {opt_rating} ÷ cost {optimized_total:.4f} cr (full optimized total)",
    )

    st.info(
        "**How to use this:** open the source PDF (left column) in your viewer, scroll the "
        "extracted text on the right. Score each method honestly — does it preserve "
        "headings? numbers? signatures? Then look at the quality/cost ratio. The method "
        "with the highest ratio is the dominant choice for this document type. Repeat for "
        "5-10 PDFs to build a defensible recommendation."
    )

    # ---- Optional: fall back to upload-and-run for new PDFs ----
    with st.expander("Process a NEW PDF (burns real credits)"):
        uploaded = st.file_uploader(
            "Upload a fresh PDF to put through both pipelines",
            type=["pdf"],
            key="pdf_upload_new",
        )
        if uploaded and st.button("Run baseline + optimized on this new PDF", type="primary"):
            filename = uploaded.name
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            with st.spinner("Uploading to PDF_STAGE..."):
                session.file.put(
                    tmp_path,
                    f"@{FQ}.PDF_STAGE",
                    auto_compress=False,
                    overwrite=True,
                )
            Path(tmp_path).unlink(missing_ok=True)
            with st.spinner("Running baseline (slow — claude-4-sonnet)..."):
                session.sql(f"CALL {FQ}.BASELINE_PROCESS_DOC('{filename}')").collect()
            with st.spinner("Running optimized (smart route + haiku + embed)..."):
                session.sql(f"CALL {FQ}.SMART_PARSE('{filename}')").collect()
                session.sql(f"CALL {FQ}.SCORE_STRUCTURED('{filename}')").collect()
                session.sql(f"CALL {FQ}.CHUNK_AND_EMBED('{filename}')").collect()
            st.success(f"`{filename}` processed. Reload the page and select it from the dropdown.")


# ---------------------------------------------------------------------------
# Tab 2: Lever-by-Lever
# ---------------------------------------------------------------------------
def tab_lever_by_lever():
    st.header("Lever-by-Lever Savings")
    st.markdown("Toggle levers on/off to see incremental cost impact. Waterfall shows cumulative savings.")

    # Get baseline average from BASELINE_RESULTS
    try:
        baseline_df = fetch_cached(f"""
            SELECT
                AVG((ocr_tokens + layout_tokens) * 0.000003 + score_credits_est) AS avg_baseline_credits,
                COUNT(*) AS doc_count
            FROM {FQ}.BASELINE_RESULTS
        """)
        if baseline_df.empty or baseline_df.iloc[0]["AVG_BASELINE_CREDITS"] is None:
            st.warning("No baseline data yet. Run `BASELINE_PROCESS_DOC` on some PDFs first.")
            return
        avg_baseline = float(baseline_df.iloc[0]["AVG_BASELINE_CREDITS"])
        doc_count = int(baseline_df.iloc[0]["DOC_COUNT"])
    except Exception as e:
        st.error(f"Could not load baseline data: {e}")
        return

    st.metric("Average baseline credits/doc", f"{avg_baseline:.6f}", help=f"Based on {doc_count} docs")

    # Lever definitions with estimated savings percentages
    levers = {
        "1. Parse Cache (hash dedup)": {
            "key": "cache",
            "savings_pct": 1.0,
            "desc": "100% on repeat/reload",
        },
        "2. Smart Routing (digital→LAYOUT, scanned→OCR)": {
            "key": "routing",
            "savings_pct": 0.50,
            "desc": "~50% parse savings",
        },
        "3. Cheaper Scorer Model": {
            "key": "scorer",
            "savings_pct": 0.90,
            "desc": "85-95% scorer savings",
        },
        "4. Structured Outputs": {
            "key": "structured",
            "savings_pct": 0.15,
            "desc": "10-20% output token savings",
        },
        "5. Embed + Cortex Search (downstream)": {
            "key": "search",
            "savings_pct": 0.90,
            "desc": "90%+ Q&A savings",
        },
        "6. Cost Telemetry": {
            "key": "telemetry",
            "savings_pct": 0.0,
            "desc": "Visibility — no direct savings",
        },
    }

    # Model selector for lever 3
    try:
        models_df = fetch_cached(f"SELECT DISTINCT SCORER_MODEL FROM {FQ}.SCORER_AB ORDER BY 1")
        available_models = models_df["SCORER_MODEL"].tolist() if not models_df.empty else list(MODEL_CREDIT_RATES.keys())
    except Exception:
        available_models = list(MODEL_CREDIT_RATES.keys())

    selected_model = st.selectbox("Scorer model (Lever 3)", available_models, index=0)

    st.divider()

    # Toggles
    enabled = {}
    cols = st.columns(3)
    for i, (label, info) in enumerate(levers.items()):
        with cols[i % 3]:
            enabled[info["key"]] = st.toggle(label, value=True, help=info["desc"])

    # Build waterfall data
    # Cost breakdown: parse (~40%), score (~50%), downstream Q&A (~10%)
    parse_share = 0.40
    score_share = 0.50
    downstream_share = 0.10

    running_cost = avg_baseline
    waterfall_labels = ["Baseline"]
    waterfall_values = [avg_baseline]
    waterfall_measures = ["absolute"]

    if enabled["cache"]:
        # Cache only helps on repeats — estimate 30% of workload is repeat
        savings = avg_baseline * 0.30
        running_cost -= savings
        waterfall_labels.append("- Cache (repeats)")
        waterfall_values.append(-savings)
        waterfall_measures.append("relative")

    if enabled["routing"]:
        savings = avg_baseline * parse_share * 0.50
        running_cost -= savings
        waterfall_labels.append("- Smart Routing")
        waterfall_values.append(-savings)
        waterfall_measures.append("relative")

    if enabled["scorer"]:
        # Savings depends on selected model vs claude-4-sonnet
        model_rate = MODEL_CREDIT_RATES.get(selected_model, 10.0)
        gold_rate = MODEL_CREDIT_RATES["claude-4-sonnet"]
        model_savings_pct = max(0, 1 - model_rate / gold_rate)
        savings = avg_baseline * score_share * model_savings_pct
        running_cost -= savings
        waterfall_labels.append(f"- Cheap Scorer ({selected_model})")
        waterfall_values.append(-savings)
        waterfall_measures.append("relative")

    if enabled["structured"]:
        savings = avg_baseline * score_share * 0.15
        running_cost -= savings
        waterfall_labels.append("- Structured Outputs")
        waterfall_values.append(-savings)
        waterfall_measures.append("relative")

    if enabled["search"]:
        savings = avg_baseline * downstream_share * 0.90
        running_cost -= savings
        waterfall_labels.append("- Embed + Search")
        waterfall_values.append(-savings)
        waterfall_measures.append("relative")

    waterfall_labels.append("Optimized Total")
    waterfall_values.append(max(running_cost, 0))
    waterfall_measures.append("total")

    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=waterfall_measures,
            x=waterfall_labels,
            y=waterfall_values,
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            increasing={"marker": {"color": "#FF6B6B"}},
            decreasing={"marker": {"color": "#4ECDC4"}},
            totals={"marker": {"color": "#29B5E8"}},
        )
    )
    fig.update_layout(
        title="Cost Waterfall: Baseline → Optimized (credits per doc)",
        yaxis_title="Credits",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    total_pct_saved = max(0, (1 - running_cost / avg_baseline) * 100) if avg_baseline > 0 else 0
    st.success(f"**Combined savings: {total_pct_saved:.1f}%** (from {avg_baseline:.6f} to {running_cost:.6f} credits/doc)")


# ---------------------------------------------------------------------------
# Tab 3: Cost Dashboard
# ---------------------------------------------------------------------------
def tab_cost_dashboard():
    st.header("Cost Dashboard")
    st.markdown(
        "Two cost views: **(A) live local cost** from this demo's own result tables "
        "(BASELINE_RESULTS / SCORER_AB / STRUCTURED_AB), available immediately. "
        "**(B) account-wide spend** from `CORTEX_FUNCTIONS_USAGE_HISTORY` "
        "(SNOWFLAKE.ACCOUNT_USAGE has up to 3-hour lag — newer runs land later)."
    )

    # ============================================================
    # PART A: Live local cost — instant, no lag
    # ============================================================
    st.subheader("A. Live demo cost (this project's tables — no lag)")
    st.caption(
        "Direct credit estimates from token counts captured during the run. "
        "These are the numbers driving Tab 1's per-doc cost comparison."
    )

    try:
        baseline_cost = run_sql(f"""
            SELECT
                'baseline'              AS pipeline,
                'AI_PARSE_DOCUMENT'     AS function_name,
                'OCR'                   AS model_name,
                COUNT(*)                AS call_count,
                SUM(ocr_tokens)         AS total_tokens,
                SUM(ocr_tokens * 0.000003) AS total_credits
            FROM {FQ}.BASELINE_RESULTS
            UNION ALL
            SELECT 'baseline', 'AI_PARSE_DOCUMENT', 'LAYOUT',
                COUNT(*), SUM(layout_tokens), SUM(layout_tokens * 0.000003)
            FROM {FQ}.BASELINE_RESULTS
            UNION ALL
            SELECT 'baseline', 'AI_COMPLETE', 'claude-4-sonnet',
                COUNT(*), COALESCE(SUM(score_tokens), COUNT(*) * 3500),
                COALESCE(SUM(score_credits_est), COUNT(*) * 0.042)
            FROM {FQ}.BASELINE_RESULTS
            UNION ALL
            SELECT 'optimized', 'AI_PARSE_DOCUMENT (cached/routed)',
                COALESCE(rl.chosen_mode, 'LAYOUT'),
                COUNT(*), SUM(parse_tokens), SUM(parse_tokens * 0.000003)
            FROM {FQ}.PARSED_CACHE pc
            LEFT JOIN {FQ}.ROUTING_LOG rl ON pc.filename = rl.filename
            GROUP BY rl.chosen_mode
            UNION ALL
            SELECT 'optimized', 'AI_COMPLETE', scorer_model,
                COUNT(*), SUM(score_tokens), SUM(score_credits_est)
            FROM {FQ}.SCORER_AB
            GROUP BY scorer_model
            UNION ALL
            SELECT 'optimized', 'AI_EMBED', 'snowflake-arctic-embed-l-v2.0-8k',
                COUNT(*), COUNT(*) * 200, COUNT(*) * 0.0000005
            FROM {FQ}.LEGAL_CHUNKS
        """)
    except Exception as e:
        st.warning(f"Could not load local cost data: {e}")
        baseline_cost = pd.DataFrame()

    if not baseline_cost.empty:
        baseline_total = float(baseline_cost[baseline_cost["PIPELINE"] == "baseline"]["TOTAL_CREDITS"].sum())
        optimized_total = float(baseline_cost[baseline_cost["PIPELINE"] == "optimized"]["TOTAL_CREDITS"].sum())
        savings = (1 - optimized_total / baseline_total) * 100 if baseline_total > 0 else 0

        kpi_a1, kpi_a2, kpi_a3, kpi_a4 = st.columns(4)
        kpi_a1.metric("Baseline pipeline", f"{baseline_total:.4f} cr")
        kpi_a2.metric("Optimized pipeline", f"{optimized_total:.4f} cr")
        kpi_a3.metric("Savings", f"{savings:.1f}%" if baseline_total else "—")
        kpi_a4.metric("Total tokens", f"{int(baseline_cost['TOTAL_TOKENS'].sum()):,}")

        # Stacked bar: baseline vs optimized by function
        fig_local = px.bar(
            baseline_cost,
            x="PIPELINE",
            y="TOTAL_CREDITS",
            color="FUNCTION_NAME",
            title="Demo cost by pipeline (live, no lag)",
            labels={"TOTAL_CREDITS": "Credits", "PIPELINE": "Pipeline"},
            hover_data=["MODEL_NAME", "CALL_COUNT", "TOTAL_TOKENS"],
        )
        st.plotly_chart(fig_local, use_container_width=True)

        # Per-model breakdown table
        st.markdown("**Per-call breakdown (every AI function call this demo made)**")
        st.dataframe(
            baseline_cost.sort_values(["PIPELINE", "TOTAL_CREDITS"], ascending=[True, False]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info(
            "No local cost data yet. Run the baseline + optimized pipelines first "
            "(see Tab 1 'Process a NEW PDF' or call `BASELINE_PROCESS_DOC` directly)."
        )

    st.divider()

    # ============================================================
    # PART B: Account-Usage view (3-hr lag, fuller context)
    # ============================================================
    st.subheader("B. Account-wide Cortex spend (CORTEX_FUNCTIONS_USAGE_HISTORY — up to 3-hr lag)")

    days_back = st.slider("Days to look back", min_value=7, max_value=30, value=30)

    try:
        cost_df = fetch_cached(f"""
            SELECT
                USAGE_DATE,
                FUNCTION_NAME,
                MODEL_NAME,
                CALL_COUNT,
                TOTAL_TOKENS,
                TOTAL_CREDITS
            FROM {FQ}.DAILY_AI_COST
            WHERE USAGE_DATE >= DATEADD('day', -{days_back}, CURRENT_DATE())
            ORDER BY USAGE_DATE DESC
        """)
    except Exception as e:
        st.warning(f"Account-usage view query failed: {e}")
        st.caption("Falling back to local cost only (Part A above).")
        return

    if cost_df.empty:
        st.info(
            f"`CORTEX_FUNCTIONS_USAGE_HISTORY` has no rows for the last {days_back} days. "
            "Either: (1) the demo runs are still propagating (3-hr lag), or "
            "(2) the demo role lacks USAGE on SNOWFLAKE.ACCOUNT_USAGE. "
            "Use Part A above for live numbers."
        )
        return

    # KPIs
    l30 = cost_df["TOTAL_CREDITS"].sum()
    l7 = cost_df[cost_df["USAGE_DATE"] >= (pd.Timestamp.now() - pd.Timedelta(days=7)).date()]["TOTAL_CREDITS"].sum()

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(f"L{days_back} Credits", f"{l30:.4f}")
    kpi2.metric("L7 Credits", f"{l7:.4f}")
    kpi3.metric("Total Calls", f"{cost_df['CALL_COUNT'].sum():,}")

    st.divider()

    # Daily stacked bar by function
    daily_func = cost_df.groupby(["USAGE_DATE", "FUNCTION_NAME"])["TOTAL_CREDITS"].sum().reset_index()
    fig1 = px.bar(
        daily_func,
        x="USAGE_DATE",
        y="TOTAL_CREDITS",
        color="FUNCTION_NAME",
        title="Daily Credits by Function",
        labels={"TOTAL_CREDITS": "Credits", "USAGE_DATE": "Date"},
    )
    st.plotly_chart(fig1, use_container_width=True)

    # Pie by model
    col_pie, col_line = st.columns(2)
    with col_pie:
        model_agg = cost_df.groupby("MODEL_NAME")["TOTAL_CREDITS"].sum().reset_index()
        model_agg = model_agg[model_agg["TOTAL_CREDITS"] > 0]
        if not model_agg.empty:
            fig2 = px.pie(model_agg, names="MODEL_NAME", values="TOTAL_CREDITS", title="Credits by Model")
            st.plotly_chart(fig2, use_container_width=True)

    # Cumulative line
    with col_line:
        daily_total = cost_df.groupby("USAGE_DATE")["TOTAL_CREDITS"].sum().reset_index().sort_values("USAGE_DATE")
        daily_total["CUMULATIVE"] = daily_total["TOTAL_CREDITS"].cumsum()
        fig3 = px.line(daily_total, x="USAGE_DATE", y="CUMULATIVE", title="Cumulative Credits Over Time")
        st.plotly_chart(fig3, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 4: Ask the Corpus (Cortex Agent)
# ---------------------------------------------------------------------------
def tab_ask_corpus():
    st.header("Ask the Legal Corpus")
    st.markdown("Chat with the Legal Doc AI Agent — it searches chunked PDFs via Cortex Search and synthesizes answers with citations.")

    # Chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input
    user_input = st.chat_input("Ask a question about your legal documents...")
    if not user_input:
        return

    # Add user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Call Cortex Agent via SSE
    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        response_placeholder = st.empty()
        full_response = ""
        status_steps: list[str] = []

        try:
            # Read OAuth token (Container Runtime mounts this)
            token_path = "/snowflake/session/token"
            if os.path.exists(token_path):
                with open(token_path) as f:
                    token = f.read().strip()
            else:
                # Fallback for local dev: use session token
                st.warning("Running outside Container Runtime — agent chat unavailable.")
                st.session_state.messages.append({"role": "assistant", "content": "_Agent chat requires Container Runtime deployment._"})
                return

            # Build agent request — SNOWFLAKE_HOST is auto-set in Container Runtime;
            # the env var is the canonical way and there is no portable default.
            snowflake_host = os.environ.get("SNOWFLAKE_HOST")
            if not snowflake_host:
                st.error("SNOWFLAKE_HOST environment variable not set. The agent chat requires Container Runtime deployment where this is auto-injected.")
                return
            agent_url = f"https://{snowflake_host}/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/agents/LEGAL_DOC_AI_AGENT:run"

            messages = [
                {
                    "role": m["role"],
                    "content": [{"type": "text", "text": m["content"]}],
                }
                for m in st.session_state.messages
            ]
            payload = {"messages": messages}

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }

            response = requests.post(agent_url, json=payload, headers=headers, stream=True, timeout=120)
            response.raise_for_status()

            # Parse SSE stream
            event_type = None
            data_buffer = ""

            for line in response.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line_str = line if isinstance(line, str) else line.decode("utf-8")

                if line_str.startswith("event:"):
                    event_type = line_str[6:].strip()
                elif line_str.startswith("data:"):
                    data_buffer += line_str[5:].strip()
                elif line_str == "":
                    # Empty line = end of event
                    if event_type and data_buffer:
                        _process_agent_event(event_type, data_buffer, response_placeholder, status_placeholder, status_steps)
                        if event_type == "response.text.delta":
                            # Extract text from delta
                            text = _extract_delta_text(data_buffer)
                            if text:
                                full_response += text
                                response_placeholder.markdown(full_response + "▌")
                    data_buffer = ""
                    event_type = None

            # Final render without cursor
            if full_response:
                response_placeholder.markdown(full_response)
            else:
                response_placeholder.markdown("_No response received from agent._")
            status_placeholder.empty()

        except FileNotFoundError:
            full_response = "_OAuth token not found. Deploy to Container Runtime first._"
            response_placeholder.markdown(full_response)
        except requests.exceptions.RequestException as e:
            full_response = f"_Agent request failed: {e}_"
            response_placeholder.markdown(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})


def _extract_delta_text(data: str) -> str:
    """Extract text content from an SSE delta data payload."""
    try:
        obj = json.loads(data)
        # Multi-shape: could be {"text": "..."} or {"delta": {"text": "..."}} etc.
        if isinstance(obj, dict):
            if "text" in obj:
                return obj["text"]
            if "delta" in obj:
                d = obj["delta"]
                if isinstance(d, str):
                    return d
                if isinstance(d, dict) and "text" in d:
                    return d["text"]
                if isinstance(d, dict) and "value" in d:
                    return d["value"]
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _process_agent_event(
    event_type: str,
    data: str,
    response_ph,
    status_ph,
    status_steps: list[str],
):
    """Handle non-content SSE events for status display."""
    if event_type == "response.status":
        try:
            obj = json.loads(data)
            msg = obj.get("message", "") if isinstance(obj, dict) else str(obj)
            if msg:
                status_steps.append(msg)
                status_ph.caption(" → ".join(status_steps))
        except (json.JSONDecodeError, TypeError):
            pass
    elif event_type == "response.tool_use":
        try:
            obj = json.loads(data)
            tool_name = obj.get("name", "tool") if isinstance(obj, dict) else "tool"
            status_steps.append(f"Using {tool_name}...")
            status_ph.caption(" → ".join(status_steps))
        except (json.JSONDecodeError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Tab 5: Quality vs Cost (Pareto + Eval Summary)
# ---------------------------------------------------------------------------
def tab_quality_cost():
    st.header("Quality vs Cost — Did we hurt quality to save money?")
    st.caption(
        "Three questions, in order: (1) Did the optimizations preserve quality? "
        "(2) Which model is the best deal? (3) Where are we exposed?"
    )

    # Check if eval data exists
    try:
        pareto_df = fetch_cached(f"SELECT * FROM {FQ}.PARETO_FRONTIER_V")
    except Exception:
        pareto_df = pd.DataFrame()

    try:
        eval_df = fetch_cached(f"SELECT * FROM {FQ}.EVAL_SUMMARY_V")
    except Exception:
        eval_df = pd.DataFrame()

    if pareto_df.empty and eval_df.empty:
        st.info(
            "Evaluation results not yet available. Run the eval pipeline first:\n\n"
            "```sql\n"
            "@eval/30_eval_setup.sql\n"
            "@eval/31_lever1_cache_identity.sql\n"
            "@eval/32_lever2_routing_agreement.sql\n"
            "@eval/33_lever3_model_matrix.sql\n"
            "@eval/34_lever4_structured_fielddiff.sql\n"
            "@eval/35_lever5_retrieval_quality.sql\n"
            "@eval/40_pareto_frontier.sql\n"
            "@eval/50_eval_summary.sql\n"
            "```"
        )
        return

    # ===== TL;DR strip =====
    st.subheader("TL;DR")

    # Compute headline numbers
    n_pass = int((eval_df["VERDICT"] == "PASS").sum()) if not eval_df.empty and "VERDICT" in eval_df.columns else 0
    n_fail = int((eval_df["VERDICT"] == "FAIL").sum()) if not eval_df.empty and "VERDICT" in eval_df.columns else 0
    n_moot = int((eval_df["VERDICT"] == "MOOT").sum()) if not eval_df.empty and "VERDICT" in eval_df.columns else 0
    n_total_gates = len(eval_df) if not eval_df.empty else 0

    # Risky doc count
    try:
        risky_count_df = fetch_cached(f"""
            SELECT COUNT(*) AS N FROM {FQ}.EVAL_PER_DOC
            WHERE SIMILARITY_TO_GOLD < 0.90
              AND RUN_ID = (SELECT MAX(RUN_ID) FROM {FQ}.EVAL_RUNS)
        """)
        n_risky = int(risky_count_df.iloc[0]["N"]) if not risky_count_df.empty else 0
    except Exception:
        n_risky = 0

    # Cost reduction headline (best non-gold model on frontier vs gold)
    cost_reduction_pct = None
    recommended_model = None
    if not pareto_df.empty and "SAVINGS_VS_GOLD_PCT" in pareto_df.columns:
        frontier_only = pareto_df[pareto_df["ON_PARETO_FRONTIER"] & (pareto_df["SAVINGS_VS_GOLD_PCT"] > 0)]
        if not frontier_only.empty:
            best = frontier_only.sort_values("SAVINGS_VS_GOLD_PCT", ascending=False).iloc[0]
            cost_reduction_pct = float(best["SAVINGS_VS_GOLD_PCT"])
            recommended_model = str(best["MODEL_NAME"])

    tl1, tl2, tl3 = st.columns(3)
    with tl1:
        if cost_reduction_pct is not None:
            st.metric("Cost reduction (vs claude-4-sonnet)", f"{cost_reduction_pct:.0f}%",
                      help=f"Best Pareto-frontier model: {recommended_model}")
        else:
            st.metric("Cost reduction", "—")

    with tl2:
        verdict_text = f"{n_pass} of {n_total_gates}"
        delta_text = "passing" if n_fail == 0 else f"{n_fail} failing"
        st.metric("Quality gates", verdict_text, delta=delta_text,
                  delta_color="normal" if n_fail == 0 else "inverse",
                  help="Each lever has a quality gate that must pass before we recommend it. MOOT = lever doesn't apply to this workload.")

    with tl3:
        st.metric("Risky documents", f"{n_risky}",
                  delta="below 0.90 similarity" if n_risky > 0 else "all docs ≥ 0.90",
                  delta_color="inverse" if n_risky > 0 else "normal",
                  help="Docs where the optimized pipeline diverges from gold by >10%. Worth a human review.")

    # Headline takeaway
    if n_fail == 0 and n_risky == 0 and cost_reduction_pct is not None:
        st.success(
            f"**Bottom line:** {cost_reduction_pct:.0f}% cheaper than baseline, "
            f"every quality gate passes, no documents flagged for review. "
            f"Recommended scoring model: **{recommended_model}**."
        )
    elif n_fail > 0:
        st.error(
            f"**Bottom line:** {n_fail} quality gate(s) failed — review before recommending."
        )
    elif n_risky > 0:
        st.warning(
            f"**Bottom line:** {n_risky} document(s) flagged for human review. "
            f"Cost savings still valid, but spot-check before going to production."
        )

    st.divider()

    # ===== Q1: Did we hurt quality? =====
    st.subheader("Question 1 — Did we hurt quality?")
    st.caption(
        "Each optimization lever is gated by a quality test. The lever ships only if its test passes."
    )

    if not eval_df.empty:
        for _, row in eval_df.iterrows():
            verdict = str(row.get("VERDICT", "?"))
            lever_name = str(row.get("LEVER_NAME", row.get("LEVER", "?")))
            gate = str(row.get("GATE_DESCRIPTION", "n/a"))
            passed = row.get("PASSED_DOCS", "?")
            total = row.get("TOTAL_DOCS", "?")
            min_sim_raw = row.get("MIN_SIMILARITY", None)

            try:
                min_sim_str = f"{float(min_sim_raw):.3f}" if min_sim_raw is not None else "n/a"
            except (ValueError, TypeError):
                min_sim_str = "n/a"

            # Lever 3's "TOTAL_DOCS" actually counts models tested on the Pareto frontier,
            # not docs. Surface the right noun so the verdict line reads honestly.
            unit = "models" if lever_name.startswith("3 -") else "docs"

            # Plain-English explanation per verdict
            if verdict == "PASS":
                icon, color, plain = "✅", "#4ECDC4", (
                    f"**Recommended.** Tested on {total} {unit}, {passed} met the quality bar. "
                    f"Worst-case similarity to gold: {min_sim_str} (1.000 = identical, 0.900+ = same meaning)."
                )
            elif verdict == "FAIL":
                icon, color, plain = "❌", "#FF6B6B", (
                    f"**Do not recommend yet.** {total - passed if isinstance(total, (int, float)) and isinstance(passed, (int, float)) else '?'} of {total} {unit} failed the gate. "
                    f"Worst-case similarity: {min_sim_str}. Investigate before shipping."
                )
            elif verdict == "MOOT":
                icon, color, plain = "⚪", "#94A3B8", (
                    "**Lever doesn't apply.** The problem this lever solves doesn't show up "
                    "on the customer's workload — e.g., free-text retry rates are already <3%, so "
                    "structured outputs aren't worth the migration cost. Skip it."
                )
            else:
                icon, color, plain = "⚠️", "#F59E0B", f"Verdict: {verdict}. Investigate."

            with st.container():
                left, right = st.columns([1, 4])
                with left:
                    st.markdown(
                        f"<div style='border-left:6px solid {color};padding-left:12px;'>"
                        f"<h3 style='margin:0'>{icon} {verdict}</h3>"
                        f"<p style='margin:4px 0;color:#666'><strong>{lever_name}</strong></p>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with right:
                    st.markdown(f"**Quality gate:** {gate}")
                    st.markdown(plain)
                st.markdown("")  # spacing

    with st.expander("ℹ️ How to read these verdicts"):
        st.markdown(
            "- **PASS** — the lever's quality test passed on every doc in the eval corpus. Safe to recommend.\n"
            "- **FAIL** — the lever's output differs enough from gold that we'd hurt quality. Do not ship as-is.\n"
            "- **MOOT** — the lever solves a problem that doesn't exist on this workload. Skipping it isn't a loss.\n"
            "- **Similarity to gold** — cosine similarity between the optimized output's embedding and "
            "the claude-4-sonnet baseline's embedding. 1.000 = identical text, 0.95+ = same meaning, "
            "0.90 = noticeably different but topically aligned, <0.90 = needs human review."
        )

    st.divider()

    # ===== Q2: Which model is the best deal? =====
    st.subheader("Question 2 — Which scorer model is the best deal?")
    st.caption(
        "We tested 5 scorer models against the same 5-doc corpus. "
        "The 'recommended' model gives ~equivalent verdicts to claude-4-sonnet at a fraction of the cost."
    )

    if not pareto_df.empty:
        # Build a clean comparison table
        df = pareto_df.copy()
        df["CREDITS_PER_DOC"] = df["TOTAL_CREDITS"] / df["DOC_COUNT"].clip(lower=1)
        df = df.sort_values("CREDITS_PER_DOC")

        # Plain-English columns
        display_cols = []
        for _, row in df.iterrows():
            is_gold = row["MODEL_NAME"] == "claude-4-sonnet"
            is_frontier = bool(row.get("ON_PARETO_FRONTIER", False))
            mean_q = float(row["MEAN_QUALITY"]) if pd.notna(row["MEAN_QUALITY"]) else None
            cred = float(row["CREDITS_PER_DOC"])
            sav = float(row.get("SAVINGS_VS_GOLD_PCT", 0))

            if is_gold:
                tag = "🥇 Gold (baseline)"
                why = "The reference everyone else is measured against."
            elif is_frontier and sav > 50:
                tag = "✅ Recommended"
                why = f"Matches gold's quality at {sav:.0f}% lower cost. This is the lever 3 winner."
            elif is_frontier:
                tag = "👍 On the frontier"
                why = "Reasonable quality/cost tradeoff but a better option exists below."
            else:
                tag = "❌ Dominated"
                why = "Another model is both cheaper AND higher quality. Don't pick this."

            display_cols.append({
                "Status": tag,
                "Model": row["MODEL_NAME"],
                "Credits/doc": f"{cred:.6f}",
                "Quality (vs gold)": f"{mean_q:.3f}" if mean_q is not None else "—",
                "Cost vs gold": "—" if is_gold else f"{sav:.0f}% cheaper" if sav > 0 else f"{abs(sav):.0f}% more expensive",
                "Why": why,
            })

        st.dataframe(pd.DataFrame(display_cols), use_container_width=True, hide_index=True)

        with st.expander("📊 Show the cost-vs-quality scatter chart (advanced)"):
            st.caption(
                "Each dot is a model. **Up = higher quality**, **left = cheaper**. "
                "The dashed line is the Pareto frontier — models on the line are 'best in their price tier'. "
                "Models below the line are dominated (something is both cheaper AND better)."
            )
            fig = px.scatter(
                df,
                x="CREDITS_PER_DOC",
                y="MEAN_QUALITY",
                color="ON_PARETO_FRONTIER",
                text="MODEL_NAME",
                hover_data=["P10_QUALITY", "MEAN_JUDGE_SCORE", "SAVINGS_VS_GOLD_PCT"],
                title="Cost vs Quality — Pareto Frontier",
                labels={
                    "CREDITS_PER_DOC": "Credits per doc (lower = cheaper →)",
                    "MEAN_QUALITY": "Mean quality (higher = closer to gold →)",
                    "ON_PARETO_FRONTIER": "On Pareto frontier",
                },
                color_discrete_map={True: "#29B5E8", False: "#94A3B8"},
            )
            fig.update_traces(textposition="top center")
            frontier_pts = df[df["ON_PARETO_FRONTIER"]].sort_values("CREDITS_PER_DOC")
            if len(frontier_pts) > 1:
                fig.add_trace(
                    go.Scatter(
                        x=frontier_pts["CREDITS_PER_DOC"],
                        y=frontier_pts["MEAN_QUALITY"],
                        mode="lines",
                        line={"dash": "dash", "color": "#29B5E8", "width": 2},
                        name="Pareto Frontier",
                        showlegend=True,
                    )
                )
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("🔍 Raw model details (P10 quality, judge scores, agreement %)"):
            st.markdown(
                "- **Mean quality** — average cosine similarity to gold across all docs.\n"
                "- **P10 quality** — the 10th-percentile (worst-case) similarity. Catches outliers that mean-averaging would hide.\n"
                "- **Agreement %** — how often this model's verdict (OCR vs LAYOUT) matched gold's verdict.\n"
                "- **Mean judge score** — LLM-as-judge quality score from cross-family judges (claude judges mistral, mistral judges claude) to control for self-preference bias."
            )
            st.dataframe(
                pareto_df[
                    [
                        "MODEL_NAME",
                        "MEAN_QUALITY",
                        "P10_QUALITY",
                        "AGREEMENT_PCT",
                        "MEAN_JUDGE_SCORE",
                        "TOTAL_CREDITS",
                        "DOC_COUNT",
                        "ON_PARETO_FRONTIER",
                        "SAVINGS_VS_GOLD_PCT",
                    ]
                ].sort_values("TOTAL_CREDITS"),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    # ===== Q3: Where are we exposed? =====
    st.subheader("Question 3 — Where are we exposed?")
    st.caption(
        "Documents where the optimized pipeline diverges from gold by more than 10% "
        "(similarity < 0.90). These are the docs to spot-check before going to production."
    )

    try:
        risky_df = fetch_cached(f"""
            SELECT
                FILENAME,
                ROUND(SIMILARITY_TO_GOLD, 4) AS SIMILARITY,
                LEVER,
                NOTES
            FROM {FQ}.EVAL_PER_DOC
            WHERE SIMILARITY_TO_GOLD < 0.90
              AND RUN_ID = (SELECT MAX(RUN_ID) FROM {FQ}.EVAL_RUNS)
            ORDER BY SIMILARITY_TO_GOLD ASC
            LIMIT 5
        """)
        if not risky_df.empty:
            st.dataframe(risky_df, use_container_width=True, hide_index=True)
            st.caption(
                "**What 'risky' means here:** the optimized output's text diverges enough from "
                "the gold (claude-4-sonnet) output that a human compliance reviewer should look "
                "before this answer goes to a paralegal or external counsel. It does NOT mean "
                "the answer is wrong — it means we can't auto-certify it."
            )
        else:
            st.success(
                "✅ No documents below the 0.90 similarity threshold. The optimized pipeline "
                "produces output that's semantically equivalent to the gold baseline on every "
                "doc in the eval corpus."
            )
    except Exception:
        st.info("Risky-docs analysis requires eval results in `EVAL_PER_DOC` table.")

    with st.expander("ℹ️ Why 0.90 is the threshold"):
        st.markdown(
            "- **0.95–1.000** — semantic match. Same meaning, possibly different phrasing.\n"
            "- **0.90–0.95** — drift but topically aligned. Worth a glance, not alarming.\n"
            "- **0.80–0.90** — noticeable divergence. Spot-check before approving.\n"
            "- **<0.80** — the optimized pipeline is producing meaningfully different content. Investigate.\n\n"
            "0.90 is a conservative gate — most enterprise eval pipelines flag at 0.85. We picked "
            "0.90 because legal documents have low tolerance for subtle wording shifts."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# Tab 6: Operations & Projections
# ---------------------------------------------------------------------------
def tab_operations():
    st.header("Operations & Projections")
    st.caption(
        "Annual savings calculator, drift monitor status, spend attribution, "
        "and resource monitor configuration."
    )

    # ---- Section A: Annual Savings Calculator ----
    st.subheader("A. Annual Savings Calculator")
    docs_per_year = st.slider(
        "Projected documents per year",
        min_value=100,
        max_value=10000,
        value=1825,
        step=25,
        help="Default: 5 docs/day × 365 = 1,825",
    )

    try:
        savings_df = fetch_cached(f"""
            SELECT
                FILENAME,
                TOTAL_BASELINE_CREDITS,
                CAST(TOTAL_OPTIMIZED_CREDITS AS FLOAT) AS OPTIMIZED_CREDITS,
                CREDITS_SAVED,
                PCT_SAVINGS
            FROM {FQ}.LEVER_SAVINGS
        """)
        if not savings_df.empty:
            n_docs = len(savings_df["FILENAME"].unique())
            total_baseline_per_corpus = savings_df["TOTAL_BASELINE_CREDITS"].sum()
            total_optimized_per_corpus = savings_df["OPTIMIZED_CREDITS"].sum()
            baseline_per_doc = total_baseline_per_corpus / n_docs
            optimized_per_doc = total_optimized_per_corpus / n_docs

            annual_baseline = baseline_per_doc * docs_per_year
            annual_optimized = optimized_per_doc * docs_per_year
            annual_saved = annual_baseline - annual_optimized

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Annual Baseline", f"{annual_baseline:,.0f} cr")
            col2.metric("Annual Optimized", f"{annual_optimized:,.1f} cr")
            col3.metric("Credits Saved", f"{annual_saved:,.0f} cr")
            col4.metric("% Reduction", f"{(annual_saved/annual_baseline*100 if annual_baseline else 0):.1f}%")

            st.caption(
                f"Based on {n_docs}-doc benchmark: {baseline_per_doc:.4f} cr/doc baseline, "
                f"{optimized_per_doc:.6f} cr/doc optimized ({savings_df['PCT_SAVINGS'].mean():.1f}% reduction). "
                "Credits only — dollar conversion omitted (depends on contracted credit rate)."
            )
        else:
            st.info("No data in LEVER_SAVINGS — run the baseline pipeline first.")
    except Exception as e:
        st.warning(f"Could not load savings data: {e}")

    st.divider()

    # ---- Section B: Drift Monitor Status ----
    st.subheader("B. Drift Monitor Status")
    try:
        drift_df = fetch_cached(f"SELECT * FROM {FQ}.EVAL_DRIFT_LATEST ORDER BY LEVER_NUM")
        if not drift_df.empty:
            def color_status(val):
                if val == "OK":
                    return "background-color: #d4edda"
                elif val == "WARN":
                    return "background-color: #fff3cd"
                else:
                    return "background-color: #f8d7da"

            styled = drift_df[["LEVER_NUM", "LEVER", "BASELINE_VALUE", "CURRENT_VALUE", "DRIFT_PCT", "ALERT_STATUS"]].style.map(
                color_status, subset=["ALERT_STATUS"]
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.caption("Green = OK (drift < 5%), Yellow = WARN (5-10%), Red = BREACH (>10%)")
        else:
            st.info("No drift data — run eval/10_drift_monitor.sql to establish baselines.")
    except Exception as e:
        st.warning(f"Could not load drift data: {e}")

    st.divider()

    # ---- Section C: Spend by Tag ----
    st.subheader("C. Spend by Query Tag")
    try:
        tag_df = fetch_cached(f"SELECT * FROM {FQ}.SPEND_BY_TAG")
        if not tag_df.empty and len(tag_df) > 0:
            fig = px.bar(
                tag_df,
                x=tag_df.columns[0],
                y=tag_df.columns[1] if len(tag_df.columns) > 1 else tag_df.columns[0],
                title="Credit Spend by Query Tag",
                color_discrete_sequence=["#29B5E8"],
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(
                "No spend-by-tag data yet. Query tags are logged to QUERY_TAG_LOG — "
                "the SPEND_BY_TAG view aggregates once enough tagged queries accumulate."
            )
    except Exception as e:
        st.warning(f"Could not load tag spend: {e}")

    st.divider()

    # ---- Section D: Resource Monitor Preview ----
    st.subheader("D. Resource Monitor Configuration")
    try:
        guardrail_df = fetch_cached(f"SELECT * FROM {FQ}.BUDGET_GUARDRAIL_DOCS ORDER BY THRESHOLD_PCT")
        if not guardrail_df.empty:
            st.dataframe(guardrail_df, use_container_width=True, hide_index=True)

            # Visual timeline
            fig = go.Figure()
            colors = {"NOTIFY": "#ffc107", "SUSPEND": "#fd7e14", "SUSPEND_IMMEDIATE": "#dc3545"}
            for _, row in guardrail_df.iterrows():
                fig.add_trace(go.Bar(
                    x=[row["THRESHOLD_PCT"]],
                    y=[row["GUARDRAIL_NAME"]],
                    orientation="h",
                    marker_color=colors.get(row["ACTION_TYPE"], "#6c757d"),
                    name=f"{row['THRESHOLD_PCT']}% — {row['ACTION_TYPE']}",
                    hovertext=row["RATIONALE"],
                ))
            fig.update_layout(
                title="Budget Guardrail Escalation",
                xaxis_title="% of Monthly Budget",
                xaxis=dict(range=[0, 110]),
                showlegend=False,
                height=250,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No guardrail configuration — run sql/30_resource_monitor.sql.")
    except Exception as e:
        st.warning(f"Could not load guardrail data: {e}")


# ---------------------------------------------------------------------------
# Tab 0: Overview (architecture + Snowflake feature inventory)
# ---------------------------------------------------------------------------
def tab_overview():
    st.header("Architecture & Snowflake Features")
    st.caption("How the pipeline works, what Snowflake products power it, and where the savings come from.")

    # =========================================================================
    # DIAGNOSTIC HEADLINE — generic pattern shown to any legal-document customer
    # =========================================================================
    st.subheader("📍 Where most legal-document customers typically are today")

    tcol1, tcol2, tcol3, tcol4 = st.columns(4)
    tcol1.metric(
        "L30 AI credits",
        "your number",
        delta="AI_ML + AI",
        delta_color="off",
        help="Pull this from CORTEX_AI_FUNCTIONS_USAGE_HISTORY for the customer's account. AI_ML covers AI_PARSE_DOCUMENT; AI covers AI_COMPLETE / AI_EMBED.",
    )
    tcol2.metric(
        "Annualized AI credits",
        "L30 × 12",
        delta="run rate",
        delta_color="off",
        help="Simple 12× extrapolation of L30 — credits only, dollar conversion depends on contracted rate.",
    )
    tcol3.metric(
        "Cortex Search credits",
        "often 0",
        delta="not deployed",
        delta_color="inverse",
        help="If SNOWFLAKE_INTELLIGENCE feature credits = 0, no Cortex Search Service exists. This is the single highest-impact gap.",
    )
    tcol4.metric(
        "Cortex Agent credits",
        "often 0",
        delta="not deployed",
        delta_color="inverse",
        help="No agents created → all Q&A is going through full-document AI_COMPLETE.",
    )

    st.info(
        "**The diagnostic pattern:** when a customer's L30 AI credits are concentrated in "
        "`AI_PARSE_DOCUMENT` + `AI_COMPLETE` with zero `SNOWFLAKE_INTELLIGENCE` consumption, "
        "every question against a long PDF is re-tokenizing the whole document. "
        "That's typically the largest credit driver — and the largest fix — for legal-document "
        "AI workloads. Lever 5 (chunk + Cortex Search) addresses it directly."
    )

    st.divider()

    # =========================================================================
    # TOP RECOMMENDATIONS
    # =========================================================================
    st.subheader("🎯 Top recommendations for the customer team")
    st.caption(
        "Sorted by impact × confidence. Each recommendation has a measured savings "
        "claim from the demo and a quality gate that already passed."
    )

    rec_df = pd.DataFrame([
        {
            "Rank": "#1",
            "Lever": "Lever 5 — AI_EMBED + Cortex Search",
            "Where it helps": "Q&A token cost",
            "Estimated impact": "Material reduction (varies with question volume)",
            "Risk": "Low",
            "Effort": "~1 week",
            "Why it matters most for the customer": (
                "The customer has no retrieval infrastructure today — verified zero "
                "Snowflake Intelligence credits L30. Every paralegal question re-feeds "
                "the entire PDF into AI_COMPLETE. Largest unlocked savings in the portfolio. "
                "Pay once at ingest, retrieve cents-per-question after."
            ),
        },
        {
            "Rank": "#2",
            "Lever": "Lever 3 — Cheaper Scorer (claude-haiku-4-5)",
            "Where it helps": "Scoring step cost",
            "Estimated impact": "~10× cheaper per scoring call (eval shows ≥95% verdict agreement on demo corpus)",
            "Risk": "Low",
            "Effort": "~1 day",
            "Why it matters most for the customer": (
                "claude-4-sonnet is the most expensive model in the matrix. The scoring "
                "task is binary classification — frontier reasoning is overkill. "
                "Drift monitor (Lever 11) catches any future regression. One model name change."
            ),
        },
        {
            "Rank": "#3",
            "Lever": "Lever 2 — Smart Routing (digital→LAYOUT, scanned→OCR)",
            "Where it helps": "Parse step cost",
            "Estimated impact": "Up to ~50% on parse step (depends on digital/scanned mix)",
            "Risk": "Low–medium",
            "Effort": "~3 days",
            "Why it matters most for the customer": (
                "Today both parse modes run on every doc. Most modern legal PDFs are digital "
                "and only need LAYOUT. Heuristic threshold cuts parse spend on those, with a "
                "fallback path for anything ambiguous."
            ),
        },
        {
            "Rank": "#4",
            "Lever": "Lever 1 — Parse Cache",
            "Where it helps": "Dev reload cost",
            "Estimated impact": "100% on cache hits (only re-runs of unchanged files)",
            "Risk": "Zero",
            "Effort": "~1 day",
            "Why it matters most for the customer": (
                "Dev reloads currently re-parse the same documents from scratch. File-hash "
                "dedup is provably byte-identical and a no-brainer first ship. Day 1 deploy."
            ),
        },
        {
            "Rank": "#5",
            "Lever": "Lever 10 — Resource Monitor",
            "Where it helps": "Bill-shock prevention",
            "Estimated impact": "Caps blast radius (not a savings lever)",
            "Risk": "Zero",
            "Effort": "~1 hour",
            "Why it matters most for the customer": (
                "Operational guardrail. One CREATE RESOURCE MONITOR statement caps "
                "monthly spend with NOTIFY/SUSPEND thresholds. Ship Day 1 alongside the cache."
            ),
        },
    ])

    st.dataframe(
        rec_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.TextColumn(width="small"),
            "Lever": st.column_config.TextColumn(width="medium"),
            "Where it helps": st.column_config.TextColumn(width="small"),
            "Estimated impact": st.column_config.TextColumn(width="medium"),
            "Risk": st.column_config.TextColumn(width="small"),
            "Effort": st.column_config.TextColumn(width="small"),
            "Why it matters most for the customer": st.column_config.TextColumn(width="large"),
        },
    )

    st.markdown("")
    st.caption(
        "**Levers 4, 6, 7, 8, 9, 11 are operational hygiene** — query tag attribution, "
        "completion cache, batch demo, token preflight, drift monitor, batch search. "
        "Worth deploying after the top 5 are stable. None are in the critical path "
        "for the credit-savings story."
    )

    st.divider()

    # =========================================================================
    # WHY CORTEX SEARCH — the big WHY
    # =========================================================================
    st.subheader("🔥 Why you should use Cortex Search (the big WHY)")
    st.caption("This is the single highest-impact recommendation. Here's why it's not optional.")

    why_col1, why_col2 = st.columns(2)

    with why_col1:
        st.markdown(
            "### ❌ Today: Full-document AI_COMPLETE per question\n\n"
            "```sql\n"
            "-- Every paralegal question:\n"
            "SELECT AI_COMPLETE(\n"
            "  'claude-4-sonnet',\n"
            "  'Read this 200-page contract: ' \n"
            "    || ENTIRE_PDF_TEXT  -- 50K+ tokens\n"
            "    || ' Question: ' || ?\n"
            ");\n"
            "```\n\n"
            "**Cost shape:**\n"
            "- Pay full document tokens × every question\n"
            "- 10 questions on a 200-page PDF = 10 × 50K = **500K tokens billed**\n"
            "- Latency 8-15 seconds per question\n"
            "- No citations — model can hallucinate\n"
            "- No reuse — same doc re-tokenized for every user\n\n"
            "**This is the dominant credit consumer in the L30 AI bill.**"
        )

    with why_col2:
        st.markdown(
            "### ✅ With Cortex Search: chunked retrieval\n\n"
            "```sql\n"
            "-- One-time at ingest:\n"
            "CREATE CORTEX SEARCH SERVICE legal_search\n"
            "ON chunk_text\n"
            "WAREHOUSE = SMALL\n"
            "TARGET_LAG = '1 hour'\n"
            "AS SELECT chunk_text FROM legal_chunks;\n\n"
            "-- Every question:\n"
            "SEARCH_PREVIEW('legal_search', ?)\n"
            "  → top-5 relevant chunks\n"
            "  → AI_COMPLETE(model, chunks + question)\n"
            "```\n\n"
            "**Cost shape:**\n"
            "- Pay embedding credits ONCE at ingest (small, one-time per chunk)\n"
            "- Per question: ~5K tokens of chunks instead of 50K of full doc\n"
            "- Same 10 questions = **~50K tokens billed** instead of 500K\n"
            "- Sub-second retrieval, citations preserved\n\n"
            "**Order of magnitude fewer billed tokens, faster, more accurate.**"
        )

    st.divider()

    st.markdown("### Five reasons this is the #1 recommendation, in order")

    st.markdown(
        "**1. The math is uncontested.** A 200-page PDF asked 10 questions today consumes "
        "~500K billed tokens. The same 10 questions through Cortex Search consume "
        "~50K billed tokens. An order of magnitude fewer. The gap doesn't shrink — it grows as your "
        "corpus grows.\n\n"

        "**2. Quality goes UP, not down.** Full-doc Q&A loses precision because the "
        "model has to hold 200 pages of context. Retrieval narrows to the 5 most "
        "relevant chunks, which is closer to how your paralegals actually think. "
        "And every answer comes with **citations** to the exact source paragraphs — "
        "auditable, defensible, court-grade.\n\n"

        "**3. Latency drops 10×.** Today: 8–15 seconds per question (large prompts "
        "tokenize slowly). With retrieval: sub-second retrieval + 1–2 second "
        "generation. The difference between 'tool I'll use' and 'tool that gathers dust'.\n\n"

        "**4. Snowflake Intelligence + Cortex Agent is then trivial.** Once you have "
        "a Cortex Search Service, wiring it into a Cortex Agent for natural-language "
        "Q&A is one DDL statement. Your paralegals get a chat UI in Snowsight that "
        "answers questions with citations across the whole corpus. **Today: zero "
        "Intelligence usage in your account.** Tomorrow: a self-serve research tool.\n\n"

        "**5. Costs scale linearly with QUESTIONS, not DOCUMENTS.** Today's pattern "
        "punishes you for adding documents AND for asking questions. Cortex Search "
        "decouples them: ingest cost is one-time, query cost is question-scaled. As "
        "the corpus grows from 5 docs/day to 50 docs/day, your savings multiplier grows."
    )

    with st.expander("⚠️ What Cortex Search is NOT a fit for"):
        st.markdown(
            "- **Numerical aggregation** — 'sum revenue across all contracts' is a "
            "Cortex Analyst (text-to-SQL) job, not a Cortex Search job\n"
            "- **Tables/structured data** — Cortex Search is for unstructured text\n"
            "- **Real-time knowledge** — TARGET_LAG min is 1 minute; not for sub-second freshness\n"
            "- **Workloads >2,000 queries per job** — that's Lever 11 (Batch Cortex Search) territory\n"
            "- **Non-English at scale** — supported but quality varies; eval before commitment"
        )

    with st.expander("📊 Show me the projected customer savings from just Lever 5"):
        st.markdown(
            "**Assumptions:** 5 paralegals × 8 questions/day × 250 working days = 10,000 Q&A/year. "
            "Average doc size 50 pages.\n\n"
            "| Pattern | Tokens per question | Annual tokens billed |\n"
            "|---|---|---|\n"
            "| **Today (full-doc AI_COMPLETE)** | ~25,000 | **~250M tokens** |\n"
            "| **With Cortex Search** | ~3,000 | **~30M tokens** |\n"
            "| **Reduction** | ~88% | ~220M tokens avoided |\n\n"
            "**At enterprise volume** (50 paralegals × full corpus = ~100K Q&A/year): "
            "the same ratio holds — tokens billed scale linearly with question count, so "
            "the absolute savings grow proportionally.\n\n"
            "Plus the latency win, plus the citations, plus the agent unlock. "
            "The token reduction is the smallest part of the value.\n\n"
            "*Note: dollar conversion intentionally omitted — actual savings depend on "
            "the customer's contracted credit rate, which we don't quote without the AE in the conversation.*"
        )

    st.divider()

    st.subheader("Data flow — baseline vs optimized")

    # Fetch rendered Mermaid diagrams from stage and display as images
    # (Per memo 8544760f / streamlit-container-runtime-uv Pitfall 12: presigned URLs
    # blocked by S3 X-Frame-Options; data: URIs blocked by corporate proxies; only
    # session.file.get + st.image works reliably in Container Runtime.)
    import os
    import tempfile

    session = get_session()
    col_a, col_b = st.columns(2)

    with tempfile.TemporaryDirectory() as tmpdir:
        for col, fname, caption in [
            (col_a, "architecture-baseline.png", "Baseline — claude-4-sonnet, OCR + LAYOUT both"),
            (col_b, "architecture-optimized.png", "Optimized — 6 cost-savings levers stacked (10 total levers in demo)"),
        ]:
            try:
                session.file.get(
                    f"@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE/img/{fname}",
                    tmpdir,
                )
                local_path = os.path.join(tmpdir, fname)
                if os.path.exists(local_path):
                    col.image(local_path, caption=caption, use_container_width=True)
                else:
                    col.warning(f"Diagram {fname} not found on stage.")
            except Exception as e:
                col.error(f"Could not load {fname}: {e}")

    st.subheader("Step-by-step walkthrough")
    st.caption("Click any step to see exactly what happens, what gets called, what's stored, and why.")

    # ---- BASELINE explanations ----
    st.markdown("### Baseline pipeline (the customer's current pattern)")

    with st.expander("**Step 1 — PDF Document arrives in @PDF_STAGE**", expanded=False):
        st.markdown(
            """
A PDF is uploaded to the SSE-encrypted internal stage `@PDF_STAGE`.
SSE encryption is a hard requirement for `AI_PARSE_DOCUMENT` — it won't run on
client-side encrypted stages or user/table stages.

The stage has `DIRECTORY = (ENABLE = TRUE)` so we can `LIST @PDF_STAGE` and
walk the file inventory programmatically.

**SQL that defines the stage:**
```sql
CREATE STAGE PDF_STAGE
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
    DIRECTORY = (ENABLE = TRUE);
```
            """
        )

    with st.expander("**Step 2 — AI_PARSE_DOCUMENT (OCR mode)**"):
        st.markdown(
            """
Snowflake's Cortex `AI_PARSE_DOCUMENT` function reads the PDF as a `FILE` object
and returns extracted text. **OCR mode** is image-based: every page gets
optically-recognized regardless of whether the PDF has embedded text. It's the
fallback for scanned documents.

the customer's current pattern always runs OCR mode, even on digital-text PDFs — that's
the wasteful part. Cost: **~0.21 credits per doc** on this 9-doc corpus (range 0.004–0.49 depending on page count).

**SQL inside the SPROC:**
```sql
SELECT AI_PARSE_DOCUMENT(
    TO_FILE('@PDF_STAGE', :filename),
    {'mode': 'OCR'}
):content::VARCHAR INTO :ocr_result;
```
            """
        )

    with st.expander("**Step 3 — AI_PARSE_DOCUMENT (LAYOUT mode)**"):
        st.markdown(
            """
Same function, different mode. **LAYOUT mode** preserves the document's
structural elements: headings, tables, paragraph order, lists. The output is
markdown-flavored text that round-trips well into chunkers and downstream LLMs.

For a digital-text PDF, LAYOUT alone produces ~the same content as OCR, often
with cleaner structure. Cost: **~1.36 credits per doc** on this 9-doc corpus (range 0.03–3.24) — typically ~6× more than OCR mode per page.

**SQL:**
```sql
SELECT AI_PARSE_DOCUMENT(
    TO_FILE('@PDF_STAGE', :filename),
    {'mode': 'LAYOUT'}
):content::VARCHAR INTO :layout_result;
```
            """
        )

    with st.expander("**Step 4 — AI_COMPLETE (claude-4-sonnet) compares + scores**"):
        st.markdown(
            """
The two extractions are concatenated into a single prompt and `claude-4-sonnet`
is asked to pick the better one. The prompt looks roughly like:

> Compare these two PDF extractions. Which is better quality? Return JSON:
> `{"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}`
>
> --- OCR ---
> {first 6KB of OCR text}
>
> --- LAYOUT ---
> {first 6KB of LAYOUT text}

claude-4-sonnet is the most expensive model on Snowflake's Cortex roster —
**12 credits per million tokens**. For typical legal
PDFs the prompt + completion runs ~3,000-5,000 tokens, so each call costs
**~0.04-0.06 credits**.

The result is a JSON blob saved to `BASELINE_RESULTS.scoring_result_json` along
with token counts for cost tracking.
            """
        )

    with st.expander("**Step 5 — Best extraction + score row written**"):
        st.markdown(
            """
The full row lands in the `BASELINE_RESULTS` table with all three calls
captured side by side. This is the audit trail — you can always go back and
ask "why did the model pick OCR for this doc?" by reading
`scoring_result_json:reasoning`.

**Schema:**
```sql
BASELINE_RESULTS (
  filename             VARCHAR,
  ocr_text             VARCHAR,        -- full OCR extraction
  layout_text          VARCHAR,        -- full LAYOUT extraction
  scoring_result_json  VARCHAR,        -- claude-4-sonnet's verdict + reasoning
  ocr_tokens           NUMBER,         -- cost telemetry
  layout_tokens        NUMBER,
  score_tokens         NUMBER,
  score_credits_est    FLOAT,
  processed_at         TIMESTAMP_NTZ
)
```
            """
        )

    with st.expander("**Step 6 — Q&A: AI_COMPLETE re-reads the full document per question**"):
        st.markdown(
            """
This is the **second expensive pattern** in the customer's current flow. When someone
asks a question about the document ("what's the breach clause?"), the app
sends the **entire extracted text** plus the question to `claude-4-sonnet`
again.

That works, but every question pays for re-reading the whole doc. For a
50-page contract, that's ~30,000 tokens of context per question. At
claude-4-sonnet rates that's roughly **0.06 credits per Q&A** — and it scales
linearly with document size and question volume.

This is what Lever 5 (AI_EMBED + Cortex Search) eliminates: pay once at ingest
to chunk + embed, then retrieval per question is cents instead of dollars.
            """
        )

    st.divider()

    # ---- OPTIMIZED explanations ----
    st.markdown("### Optimized pipeline (6 cost-savings levers stacked)")
    st.caption("Levers 1–6 stack to produce the savings narrative below. Levers 7–10 (preflight, completion cache, batch inference, resource monitor) are operational guardrails — see sidebar for details.")

    with st.expander("**Step 1 — PDF arrives in @PDF_STAGE** (same as baseline)"):
        st.markdown("Identical entry point — only the processing differs. SSE-encrypted stage with directory enabled, same file inventory.")

    with st.expander("**Step 2 — Lever 1: PARSE_WITH_CACHE (file-hash dedup)**"):
        st.markdown(
            """
Before we burn any AI tokens, we check whether we've already parsed this exact
file. The `PARSED_CACHE` table is keyed by `FILE_HASH = MD5(relative_path || size || last_modified)`.

If the hash matches a cached row, we **return the stored text immediately** —
zero AI cost. This is the **100% savings on re-runs** lever, which matters
massively for the customer's 260-doc development reloads.

**SQL flow inside the SPROC:**
```sql
-- Compute hash from stage directory metadata
SELECT MD5(RELATIVE_PATH || '|' || SIZE::VARCHAR || '|' || LAST_MODIFIED::VARCHAR)
INTO :file_hash
FROM DIRECTORY(@PDF_STAGE)
WHERE RELATIVE_PATH = :filename;

-- Cache lookup
SELECT PARSED_TEXT INTO :cached_text
FROM PARSED_CACHE
WHERE FILE_HASH = :file_hash AND MODE = :mode;

IF (:cached_text IS NOT NULL) THEN
    RETURN cached_text;  -- HIT: zero credits
END IF;

-- MISS: actually call AI_PARSE_DOCUMENT and INSERT into PARSED_CACHE
```

Quality gate (Lever 1): the cached output is byte-identical to the original
parse by definition (same VARCHAR column read back), so similarity = 1.0.
            """
        )

    with st.expander("**Step 3 — Lever 2: SMART_PARSE routes by document type**"):
        st.markdown(
            """
Instead of always calling both OCR and LAYOUT, `SMART_PARSE` makes one cheap
LAYOUT call as a probe, then decides:

- **If LAYOUT returned > 500 characters** → the doc is digital (text-native PDF).
  Use the LAYOUT result we just computed. **Skip OCR entirely** → ~50% parse savings.
- **If LAYOUT returned ≤ 500 characters** → the doc is image-only / scanned.
  Fall back to a second `AI_PARSE_DOCUMENT(..., {'mode':'OCR'})` call.

In our 5-PDF run, all 5 government documents classified as `digital`, so OCR
was skipped on every one.

**SQL:**
```sql
-- Probe with LAYOUT
SELECT AI_PARSE_DOCUMENT(TO_FILE('@PDF_STAGE', :filename), {'mode':'LAYOUT'})
       :content::VARCHAR INTO :sample_text;

IF (LENGTH(:sample_text) > 500) THEN
    chosen_mode := 'LAYOUT';
    parse_result := :sample_text;     -- already have it, no second call
ELSE
    chosen_mode := 'OCR';
    SELECT AI_PARSE_DOCUMENT(TO_FILE('@PDF_STAGE', :filename), {'mode':'OCR'})
           :content::VARCHAR INTO :parse_result;
END IF;

-- Log decision into ROUTING_LOG (so eval can score the routing accuracy)
INSERT INTO ROUTING_LOG (filename, classified_as, chosen_mode, ...) VALUES (...);

-- Also write into PARSED_CACHE so Lever 1 picks up next time
MERGE INTO PARSED_CACHE ...;
```

Quality gate (Lever 2): on the 5-doc set, routing decisions had to match the
"always-both-and-pick" baseline ≥ 95% of the time and similarity-to-gold ≥ 0.85
at the 10th percentile.
            """
        )

    with st.expander("**Step 4 — Levers 3 + 4: SCORE_STRUCTURED with claude-haiku-4-5**"):
        st.markdown(
            """
Two levers compose into one SPROC call:

**Lever 3 — cheaper model.** Same scoring prompt, but routed to
`claude-haiku-4-5` (~1 credit per million tokens) instead of `claude-4-sonnet`
(~12 credits per million tokens). That's a **~12× cost reduction** on the score step.
The eval framework's Lever 3 matrix runs the same prompt across 6 models
(claude-4-sonnet, claude-haiku-4-5, claude-3-5-sonnet, mistral-large2,
llama3.3-70b, openai-gpt-5-mini) and only recommends a model if it agrees
with claude-4-sonnet's verdict ≥ 95% of the time.

**Lever 4 — structured outputs.** Instead of asking the model to "return JSON"
and hoping the JSON is well-formed, we use `response_format => TYPE OBJECT(...)`
which **guarantees** the LLM emits a valid object matching the schema. No
retry loop, no regex fallback parsing.

**SQL:**
```sql
SELECT PARSE_JSON(AI_COMPLETE(
    'claude-haiku-4-5',
    :scoring_prompt,
    response_format => TYPE OBJECT(
        best_mode STRING,
        confidence FLOAT,
        reasoning STRING
    ),
    show_details => TRUE      -- returns token usage too
)) INTO :result;
```

The output lands in `STRUCTURED_AB` with `output_mode='structured'` and
`retries=0`. The free-text version (Lever 4 negative control) lands in the
same table with `output_mode='freetext'` and a retry counter — in our run,
haiku-4-5 returned valid JSON every time, so retries was 0.

Quality gate (Lever 3): agreement-with-claude-4-sonnet ≥ 95% on holdout.
Quality gate (Lever 4): field-level identity ≥ 98% AND free-text retry rate ≥ 3%.
            """
        )

    with st.expander("**Step 5 — Lever 5: CHUNK_AND_EMBED for semantic retrieval**"):
        st.markdown(
            """
Once we have the parsed text, we don't want to keep stuffing it into prompts
forever. Instead, we **chunk it once and embed it** — paying upfront for
permanent cheap retrieval.

**Chunking:** `SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER` with the
`'markdown'` separator hierarchy. The splitter respects markdown headings,
paragraphs, and sentences in that priority order, so chunks land at semantic
boundaries instead of arbitrary character counts. Chunk size = 1500 chars,
overlap = 200 chars.

**Embedding:** `AI_EMBED('snowflake-arctic-embed-l-v2.0-8k', chunk_text)`
returns a `VECTOR(FLOAT, 1024)`. The `-8k` suffix means the model accepts up
to 8,000 tokens of context per chunk — well above our 1,500-char chunks, so
no truncation.

The result lands in `LEGAL_CHUNKS`. For our 5 PDFs we got **8,576 chunks**.

**SQL inside CHUNK_AND_EMBED:**
```sql
INSERT INTO LEGAL_CHUNKS (chunk_text, doc_name, page_no, embedding)
SELECT
    c.value::VARCHAR AS chunk_text,
    :filename AS doc_name,
    NULL AS page_no,                      -- placeholder
    AI_EMBED('snowflake-arctic-embed-l-v2.0-8k', c.value::VARCHAR) AS embedding
FROM TABLE(FLATTEN(
    SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(
        :parsed_text, 'markdown', 1500, 200
    )
)) c;
```
            """
        )

    with st.expander("**Step 6 — Cortex Search Service indexes the chunks**"):
        st.markdown(
            """
With chunks + embeddings sitting in `LEGAL_CHUNKS`, we wrap them in a managed
Cortex Search Service:

```sql
CREATE OR REPLACE CORTEX SEARCH SERVICE LEGAL_DOC_AI_SEARCH
    ON chunk_text
    ATTRIBUTES doc_name, page_no
    WAREHOUSE = SFE_LEGAL_DOC_AI_WH
    TARGET_LAG = '1 hour'
    AS SELECT chunk_text, doc_name, page_no FROM LEGAL_CHUNKS;
```

The service builds a **hybrid retrieval index** (keyword + dense vector) over
`chunk_text`. `TARGET_LAG = '1 hour'` means the index auto-refreshes when
underlying data changes, with at most 1 hour of staleness. `ATTRIBUTES`
declares filterable metadata (so we can scope a search to one document).

This replaces what would otherwise be a self-hosted vector DB (Pinecone,
Weaviate, pgvector). The query plane is just SQL.
            """
        )

    with st.expander("**Step 7 — LEGAL_DOC_AI_AGENT does retrieval-augmented generation**"):
        st.markdown(
            """
The Cortex Agent ties it all together. When you ask a question in Tab 4, the
agent:

1. **Searches** `LEGAL_DOC_AI_SEARCH` for the top-5 most relevant chunks.
2. **Synthesizes** an answer using a cheap LLM (default settings — claude-haiku
   tier) over just those 5 chunks (~7,500 chars total) instead of the full
   document.
3. **Cites** the source `doc_name` and `page_no` for each chunk it used.

Cost per question: **~0.002 credits** (claude-haiku-4-5 over retrieved top-5 chunks) vs **~0.04 credits** for the full-document baseline (claude-4-sonnet over 50K-char context) — a **~20× reduction** on Q&A. Measured on this 9-doc corpus, last 7d via `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`.

**Agent spec:**
```sql
CREATE OR REPLACE AGENT LEGAL_DOC_AI_AGENT
  WITH PROFILE = '{"display_name":"Legal Doc AI Q and A Agent"}'
  FROM SPECIFICATION $$
  {
    "models": {"orchestration": "auto"},
    "tools": [{"tool_spec": {"type":"cortex_search","name":"legal_search",
               "description":"Searches legal documents..."}}],
    "tool_resources": {
      "legal_search": {
        "search_service": "SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH",
        "id_column": "DOC_NAME",
        "max_results": 5,
        "title_column": "DOC_NAME"
      }
    }
  }
  $$;
```

Quality gate (Lever 5): retrieval recall@5 ≥ 0.85, MRR ≥ 0.7, end-to-end
similarity-to-gold ≥ 0.90 of the full-doc baseline.
            """
        )

    with st.expander("**Step 8 — Answer + citations returned to the user**"):
        st.markdown(
            "The agent streams its response back via Server-Sent Events. The "
            "Streamlit Tab 4 chat handles the SSE parse loop and renders the answer "
            "with the underlying chunks listed as citations underneath."
        )

    with st.expander("**Sidecar — Lever 6: DAILY_AI_COST telemetry**"):
        st.markdown(
            """
Every Cortex AI call is recorded by Snowflake automatically in
`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY` (3-hour lag). We wrap
that in two views:

```sql
CREATE OR REPLACE VIEW DAILY_AI_COST AS
SELECT
    DATE_TRUNC('day', start_time) AS day,
    function_name,
    model_name,
    SUM(token_credits) AS credits,
    SUM(tokens) AS tokens
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY
WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3;
```

Tab 3 (Cost Dashboard) reads this view to show daily spend by function and
model, plus cumulative spend over time. **Lever 6 doesn't reduce cost
directly — it just makes spend visible** so the customer can monitor going
forward.

No third-party APM tool needed; the telemetry lives inside Snowflake.
            """
        )

    st.subheader("What this demo proves — Snowflake feature inventory")

    feature_rows = [
        {
            "Snowflake product": "AI_PARSE_DOCUMENT (Cortex AI)",
            "Status": "GA",
            "What it does here": "Extracts text from PDFs in OCR or LAYOUT mode; LAYOUT preserves headings/tables/reading order",
            "Why it matters": "Replaces a custom OCR + layout pipeline (Textract + Rekognition + glue code)",
        },
        {
            "Snowflake product": "AI_COMPLETE (Cortex AI)",
            "Status": "GA",
            "What it does here": "Scores OCR vs LAYOUT extractions; structured outputs via response_format=TYPE OBJECT(...)",
            "Why it matters": "Same prompt across 6 model families; A/B without changing infra; structured outputs eliminate JSON-parse retries",
        },
        {
            "Snowflake product": "AI_EMBED (Cortex AI)",
            "Status": "GA",
            "What it does here": "Embeds 8,576 chunks via snowflake-arctic-embed-l-v2.0-8k (1024-dim, long-context)",
            "Why it matters": "Unified embedding API; multilingual + long-context options",
        },
        {
            "Snowflake product": "Cortex Search Service",
            "Status": "GA",
            "What it does here": "Indexes LEGAL_CHUNKS with TARGET_LAG '1 hour'; powers Tab 4 retrieval over the corpus",
            "Why it matters": "Replaces a self-hosted vector DB (Pinecone, Weaviate) — query plane is just SQL",
        },
        {
            "Snowflake product": "Cortex Agent",
            "Status": "GA",
            "What it does here": "Answers Q&A with retrieval-augmented generation; tool=cortex_search, agent=LEGAL_DOC_AI_AGENT",
            "Why it matters": "Replaces full-document re-parsing per question — pay once at ingest, retrieve cheaply forever",
        },
        {
            "Snowflake product": "Streamlit-on-Snowflake (Container Runtime)",
            "Status": "GA",
            "What it does here": "Hosts this app on SFE_LEGAL_DOC_AI_POOL with PYPI_ACCESS_INTEGRATION; uv pyproject.toml deps",
            "Why it matters": "No Docker, no Kubernetes, no CI/CD — code lives in a stage, container restarts on ADD LIVE VERSION",
        },
        {
            "Snowflake product": "ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY",
            "Status": "GA",
            "What it does here": "Tab 3 cost dashboard reads per-function/per-model spend from this view (3-hr lag)",
            "Why it matters": "First-party telemetry — no third-party APM tool needed to see Cortex AI spend",
        },
    ]

    df = pd.DataFrame(feature_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Honest cost story (real numbers from the run)")

    cost_rows = [
        {
            "Pipeline": "Baseline (claude-4-sonnet, OCR + LAYOUT both, free-text)",
            "Calls per doc": "3 (parse OCR + parse LAYOUT + score)",
            "Avg credits / doc (5 PDFs)": "≈ 2.80",
            "Bottleneck": "OCR cost is paid even on digital PDFs; claude-4-sonnet scoring is ~10× haiku",
        },
        {
            "Pipeline": "Optimized (smart-route LAYOUT-only + claude-haiku-4-5 + structured)",
            "Calls per doc": "2-3 (route + score, embed once)",
            "Avg credits / doc (5 PDFs)": "≈ 0.84 (parse) + 0.0017 (score)",
            "Bottleneck": "Parse is still the dominant cost; embedding is one-time",
        },
        {
            "Pipeline": "Optimized + cache (2nd run)",
            "Calls per doc": "0 (cache hit)",
            "Avg credits / doc (5 PDFs)": "≈ 0",
            "Bottleneck": "None — entire pipeline returns from PARSED_CACHE",
        },
    ]
    cdf = pd.DataFrame(cost_rows)
    st.dataframe(cdf, use_container_width=True, hide_index=True)

    st.info(
        "**Note on score telemetry:** The current run captured token counts for parse but not for the "
        "claude-4-sonnet scoring step (a JSON-path bug in `BASELINE_PROCESS_DOC` returned NULL for "
        "`:score_details:usage:total_tokens`). Score credits are estimated at 3,500 tokens per call "
        "(typical for the comparison prompt with 6KB OCR + 6KB LAYOUT + system prompt). Real spend will "
        "be visible in Tab 3 once `CORTEX_FUNCTIONS_USAGE_HISTORY` populates (~3-hour lag from the run)."
    )


# ---------------------------------------------------------------------------
def main():
    st.title("Legal Doc AI — Cost & Quality Optimization")
    st.caption("11 levers to reduce Cortex AI costs while maintaining extraction quality")

    # Persistent sidebar — every tab gets this lever cheat sheet
    with st.sidebar:
        st.markdown("### The 11 Levers")
        st.caption("Click any lever to see what it does, the cost claim, and the quality gate that must pass before recommending it.")

        with st.expander("**1 — Parse Cache** · 100% savings on re-runs"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "Every time the dev pipeline runs, `AI_PARSE_DOCUMENT` is called from "
                "scratch on every PDF. Even if the PDF hasn't changed since yesterday. "
                "Even if you're doing your third dev reload of the same 260-doc batch "
                "this hour. Each call costs full token rate.\n\n"
                "### What 'parse cache' means here\n\n"
                "Compute a content hash of each PDF (md5 of the staged file). On every "
                "parse request, look up `(file_hash, mode)` in the `PARSED_CACHE` "
                "table. If a row exists → return the cached text, skip the AI call "
                "entirely. If not → call `AI_PARSE_DOCUMENT`, then INSERT the result.\n\n"
                "### Why current approach is wasteful\n\n"
                "Re-parsing identical content burns 100% of the parse cost for 0% of "
                "the value. The 260-doc dev reload the customer mentioned costs 260 × full-"
                "parse on every iteration. With caching, only the FIRST run touches "
                "AI_PARSE_DOCUMENT. Reloads 2, 3, 4… are free.\n\n"
                "### What the demo shows\n\n"
                "5 PDFs × 2 modes = 10 entries in `PARSED_CACHE`. Tab 1 'Manual quality "
                "check' lets you compare cached vs fresh — they're byte-identical "
                "(AI_SIMILARITY = 1.000).\n\n"
                "### What 'parse cache' does NOT mean\n\n"
                "- It does NOT cache LLM completion responses (only AI_PARSE_DOCUMENT output).\n"
                "- It does NOT detect content-equivalent PDFs (re-saved/re-OCR'd same "
                "doc gets a different hash → cache miss). That's by design.\n"
                "- It is NOT a TTL cache; entries persist until manually purged.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/11_cache_layer.sql` — `PARSED_CACHE` table + `PARSE_WITH_CACHE` SPROC\n"
                "- **Quality gate**: AI_SIMILARITY = 1.000 between cached and fresh on every doc\n"
                "- **Tab 2** 'Lever-by-Lever': cumulative savings curve\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"You're paying full price every dev reload. A hash + cache table "
                "makes the second reload free. Zero quality risk because the cache "
                "stores the exact bytes the AI returned the first time.\"*"
            )

        with st.expander("**2 — Smart Routing** · ~50% savings on parse"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "Every PDF gets parsed BOTH ways — `AI_PARSE_DOCUMENT(mode='OCR')` AND "
                "`AI_PARSE_DOCUMENT(mode='LAYOUT')` — because they don't know in advance "
                "which mode will produce better text. Then they ask claude-4-sonnet to "
                "pick. That's 2× parse cost on every document, every run.\n\n"
                "### What 'smart routing' means here\n\n"
                "Cheaply pre-classify the PDF as **digital** (text-native) or **scanned** "
                "(image-only) BEFORE deciding which parse mode to call. The heuristic: "
                "try `LAYOUT` first; if it returns >500 chars of meaningful text, the "
                "PDF is digital → use LAYOUT only, skip OCR. If LAYOUT returns near-"
                "empty output, the PDF is scanned → fall back to OCR.\n\n"
                "### Why current approach is wasteful\n\n"
                "Most legal PDFs are digital (born-digital from Word/legal authoring "
                "tools). Running OCR on a digital PDF is pure waste — OCR is for image "
                "content, and digital PDFs already have selectable text. Running LAYOUT "
                "on a scanned PDF is also wasteful — LAYOUT can't help when there's no "
                "structural metadata to preserve.\n\n"
                "### What the demo shows\n\n"
                "All 5 corpus PDFs were classified `digital` and routed to LAYOUT-only. "
                "Routing decisions logged in `ROUTING_LOG`. Tab 1 'Major content "
                "differences' shows the OCR-vs-LAYOUT diff per doc — for these federal "
                "PDFs, the layout output is consistently richer (preserves headings, "
                "section numbers, tables). OCR drops most of that structure.\n\n"
                "### What 'smart routing' does NOT mean\n\n"
                "- It does NOT route between LLM models (that's Lever 3).\n"
                "- It does NOT permanently classify a doc — re-running can re-classify "
                "if the heuristic threshold changes.\n"
                "- It is NOT 100% accurate; image-heavy digital PDFs (lots of figures) "
                "may still need OCR fallback. Quality gate measures this.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/12_smart_routing.sql` — `ROUTING_LOG` table + `SMART_PARSE` SPROC\n"
                "- **Quality gate**: routing agreement with always-both ≥ 95%; AI_SIMILARITY p10 ≥ 0.85; numeric fidelity ≥ 99%\n"
                "- **Tab 1** 'Major content differences' + 'Numeric / date / dollar fidelity'\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Stop running both parse modes blind. Pick one based on a 1-line "
                "heuristic. Skip OCR for digital docs (most of yours). Cuts parse cost "
                "in half with no quality drop on the modes you actually need.\"*"
            )

        with st.expander("**3 — Cheaper Scorer Model** · 10× cheaper"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "After parsing a PDF in both OCR and LAYOUT, you have two versions of "
                "the same text. They differ. To pick the better one, the customer asks "
                "`claude-4-sonnet` (the most expensive Anthropic model in the catalog) "
                "to look at both and decide.\n\n"
                "### What 'scoring' means here\n\n"
                "The scorer model reads OCR text + LAYOUT text and answers a small "
                "JSON question:\n\n"
                "```json\n{\n  \"best_mode\": \"LAYOUT\",\n  \"confidence\": 0.95,\n  \"reasoning\": \"LAYOUT preserved table structure\"\n}\n```\n\n"
                "Three fields out, ~1.6K tokens. It's not generating content. It's not "
                "extracting entities. It's judging which extraction is higher fidelity "
                "and giving a one-sentence reason.\n\n"
                "### Why current approach is wasteful\n\n"
                "claude-4-sonnet is built for hard reasoning — multi-step legal analysis, "
                "code generation, complex synthesis. The OCR-vs-LAYOUT pick is trivial "
                "by comparison. **Paying claude-4-sonnet rates to do a task a much "
                "cheaper model handles is the central waste.**\n\n"
                "### What the demo shows — measured numbers (credits per doc)\n\n"
                "Same 5 docs × 5 models:\n"
                "- claude-4-sonnet (gold reference): **0.0175 cr/doc**\n"
                "- claude-sonnet-4-6: 0.014 cr/doc\n"
                "- mistral-large2: 0.0054 cr/doc\n"
                "- llama3.3-70b: 0.0026 cr/doc\n"
                "- **claude-haiku-4-5: 0.0017 cr/doc** ← recommended (~10× cheaper than gold)\n\n"
                "Agreement with claude-4-sonnet: ~95% across all 4 cheap candidates. "
                "On the Pareto frontier, claude-haiku-4-5 dominates.\n\n"
                "### What 'cheaper scorer' does NOT mean\n\n"
                "- It does NOT mean the cheap model does the parsing — `AI_PARSE_DOCUMENT` "
                "still runs the same way. The scorer judges the parse OUTPUTS.\n"
                "- It does NOT mean evaluating model quality (that's the eval framework).\n"
                "- It does NOT rank documents — it ranks two extractions of one document.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/13_cheap_scorer.sql` — `SCORER_AB` table + `RUN_SCORER_MATRIX` SPROC\n"
                "- **Quality gate**: Pareto frontier non-empty AND ≥1 cheaper-than-gold model on it; cross-family judge rule (claude judges mistral, mistral judges claude)\n"
                "- **Tab 1** 'Compare any two scoring models' — verdict diff for any cheap candidate\n"
                "- **Tab 5** 'Quality vs Cost' — Pareto frontier scatter\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"You're using a sledgehammer (claude-4-sonnet) to crack a nut "
                "(binary OCR-vs-LAYOUT pick). A pocket knife (claude-haiku-4-5) does "
                "the same job, gets the same answer 95%+ of the time, costs 10× less. "
                "We measured it across 5 docs × 5 models on the Pareto frontier.\"*"
            )

        with st.expander("**4 — Structured Outputs** · eliminates retries (often MOOT)"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today — likely)\n\n"
                "When asking an LLM for structured data (\"return JSON with these "
                "fields…\"), the model returns a free-text string that LOOKS like JSON. "
                "Sometimes it's malformed — extra prose, missing brace, code-fence "
                "wrapping. Code that consumes it has to `try: json.loads()`, catch the "
                "exception, retry the LLM call, and burn tokens again.\n\n"
                "### What 'structured outputs' means here\n\n"
                "Pass `response_format => TYPE OBJECT(best_mode STRING, confidence "
                "FLOAT, reasoning STRING)` to `AI_COMPLETE`. Snowflake constrains the "
                "model's output at decode time so the response is GUARANTEED to match "
                "the schema. Zero retries. Zero parse failures.\n\n"
                "### Why current approach is wasteful (when it is)\n\n"
                "Each retry = another full LLM call = duplicate token cost. If your "
                "free-text JSON parse rate is 95%, that's 1 in 20 docs eating 2× cost. "
                "If it's 90%, you're paying ~10% extra on every batch.\n\n"
                "### What the demo shows\n\n"
                "We ran both `SCORE_STRUCTURED` (uses TYPE OBJECT) and `SCORE_FREETEXT` "
                "(no schema constraint) on the same 5 docs with claude-haiku-4-5. "
                "Result: **0% retry rate on free-text** with this model on this prompt. "
                "Lever 4 verdict in Tab 5: **MOOT** — there's nothing to save because "
                "haiku already returns valid JSON every time on this task.\n\n"
                "### Why MOOT is honest, not failure\n\n"
                "If the cheap-model + simple-prompt combo doesn't actually have a JSON-"
                "validity problem, structured outputs aren't a real saving. We could "
                "have manufactured a savings number; we showed the MOOT instead. That's "
                "the methodology customers can trust.\n\n"
                "### What 'structured outputs' does NOT mean\n\n"
                "- It does NOT enforce semantic correctness — the JSON parses but its "
                "values may still be wrong (a different problem, addressed by Lever 3 quality gate).\n"
                "- It does NOT work with `PROMPT()`-style multimodal inputs (text-only AI_COMPLETE).\n"
                "- It is NOT free — there's a small overhead vs unconstrained generation, "
                "though typically <5% on output tokens.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/14_structured_outputs.sql` — `STRUCTURED_AB` table + `SCORE_STRUCTURED` / `SCORE_FREETEXT` SPROCs\n"
                "- **Quality gate**: field identity ≥98% AND free-text retry rate ≥3% (else MOOT)\n"
                "- **Tab 5** 'Quality vs Cost' — Lever 4 row shows MOOT verdict for this corpus\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"If your free-text JSON parse rate is shaky, structured outputs "
                "kill retry costs. With claude-haiku-4-5 on this task it's 0% retries "
                "either way — so this lever is MOOT here. Worth measuring on YOUR "
                "prompts before deciding.\"*"
            )

        with st.expander("**5 — AI_EMBED + Cortex Search** · 90%+ savings on Q&A"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today — likely)\n\n"
                "After extracting text from a PDF, downstream consumers ask questions: "
                "\"What's the sanction for a first-time violation?\" \"Who can appeal?\" "
                "Each question typically gets answered by stuffing the FULL document "
                "(potentially hundreds of thousands of tokens) into `claude-4-sonnet` "
                "with the question. Every question pays full-doc-token cost.\n\n"
                "### What 'AI_EMBED + Cortex Search' means here\n\n"
                "1. **At ingest (one time)**: chunk the parsed text (`SPLIT_TEXT_RECURSIVE_CHARACTER`), "
                "embed each chunk with `AI_EMBED('snowflake-arctic-embed-l-v2.0-8k', "
                "chunk_text)`, register chunks in a Cortex Search Service.\n"
                "2. **At question time**: the search service returns the top-k most "
                "relevant chunks (typically 3-10) for any natural-language query. Pass "
                "ONLY those chunks + the question to a cheap LLM. ~5K tokens per "
                "question, not 500K.\n\n"
                "### Why current approach is wasteful\n\n"
                "Repeated full-doc Q&A is paying ingest cost on every question. The "
                "expensive LLM has to re-read the whole document to find one answer. "
                "Embeddings + retrieval pay the ingest cost ONCE; every question after "
                "is cheap. With 100+ questions per doc, the savings are dramatic.\n\n"
                "### What the demo shows — measured numbers\n\n"
                "- 5 PDFs chunked + embedded: 8,576 chunks indexed in `LEGAL_DOC_AI_SEARCH`\n"
                "- 5 hand-built Q&A pairs run through retrieval: recall@5 = 1.0, MRR = 1.0\n"
                "- AI_SIMILARITY of retrieval-augmented answer vs gold = 0.90\n"
                "- vs full-doc-stuff baseline AI_SIMILARITY = 0.94 (slight drop)\n"
                "- Cost: cheap retrieval pipeline ≈ 1/10 the price of full-doc stuffing\n\n"
                "### What it enables — the Cortex Agent\n\n"
                "Tab 4 'Ask the Corpus' is a Cortex Agent (`LEGAL_DOC_AI_AGENT`) wired "
                "to the search service. Type a question; it retrieves chunks; it "
                "answers with citations. This is the interface the customer's downstream "
                "consumers should use instead of full-doc Q&A.\n\n"
                "### What 'AI_EMBED + Cortex Search' does NOT mean\n\n"
                "- It does NOT replace AI_PARSE_DOCUMENT — you still need the parsed text first.\n"
                "- It does NOT work for tasks that need full-document context (e.g., "
                "'summarize the whole doc'). For Q&A only.\n"
                "- It does NOT eliminate the LLM step — retrieval gives you context, "
                "you still call AI_COMPLETE on the retrieved chunks.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/15_embed_search.sql` (`LEGAL_CHUNKS` + `CHUNK_AND_EMBED` + `LEGAL_DOC_AI_SEARCH`), `sql/16_agent.sql` (the Cortex Agent)\n"
                "- **Quality gate**: recall@5 ≥ 0.85, MRR ≥ 0.7, end-to-end answer AI_SIMILARITY ≥ 90% of full-doc baseline\n"
                "- **Tab 4** 'Ask the Corpus' — live Cortex Agent chat\n"
                "- **Tab 5** Lever 5 verdict\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Pay parse + embedding cost once. Every question after retrieves "
                "the relevant chunks for a fraction of the cost of re-reading the whole "
                "doc. Same answer quality (within 5%). Scales linearly with question "
                "volume instead of exponentially.\"*"
            )

        with st.expander("**6 — Cost Telemetry** · visibility, not savings"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today — likely)\n\n"
                "Cortex AI spend shows up at the end of the month on the bill. There's "
                "no per-function, per-model, per-pipeline breakdown unless you build "
                "one. A regression in cost (someone deploys a flow that calls "
                "claude-4-sonnet 10× more than expected) goes undetected for weeks.\n\n"
                "### What 'cost telemetry' means here\n\n"
                "Two views over `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY`:\n"
                "- `DAILY_AI_COST` — daily roll-up (function × model × day, "
                "credits + tokens + call count)\n"
                "- `LEVER_SAVINGS` — joins local result tables for baseline-vs-"
                "optimized comparison on the same docs\n\n"
                "Plus a Tab 3 dashboard that surfaces both views with charts.\n\n"
                "### Why visibility matters\n\n"
                "You can't optimize what you can't measure. Without per-model breakdown, "
                "you can't tell if a Lever 3 deploy actually moved the needle. Without "
                "per-day breakdown, you can't catch a runaway cost regression.\n\n"
                "### What the demo shows\n\n"
                "Tab 3 has two parts:\n"
                "- **Part A — Live demo cost** (no lag): pulls from this project's local tables (BASELINE_RESULTS, SCORER_AB, etc.) for instant numbers.\n"
                "- **Part B — Account-wide spend** (1-hr SLA): pulls from `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`. Today's headline: AI_PARSE_DOCUMENT layout = 15.29 credits, AI_COMPLETE haiku = 0.025 credits — exactly the cost shape the customer needs to see.\n\n"
                "### Important caveat — view migration\n\n"
                "The OLD `CORTEX_FUNCTIONS_USAGE_HISTORY` view is deprecated (last "
                "updated Oct 2025 on demo accounts). The NEW view is "
                "`CORTEX_AI_FUNCTIONS_USAGE_HISTORY` — different schema (CREDITS column "
                "not TOKEN_CREDITS, METRICS array not TOKENS scalar). the customer's dashboards "
                "may still reference the old view.\n\n"
                "### What 'cost telemetry' does NOT mean\n\n"
                "- It does NOT save money — it's read-only views on usage data.\n"
                "- It is NOT real-time — there's up to 1-hour SLA on the new view, "
                "3+ hours on the old one.\n"
                "- It does NOT track warehouse compute (only Cortex AI function billing).\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/20_cost_telemetry.sql` — both views\n"
                "- **Tab 3** 'Cost Dashboard' — Part A + Part B\n"
                "- **Quality gate**: none (read-only views)\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"You can't optimize what you can't measure. Two views + a dashboard "
                "give you per-function, per-model, per-day breakdown. Heads-up: the "
                "old usage view is deprecated as of 2026 — make sure you're querying "
                "CORTEX_AI_FUNCTIONS_USAGE_HISTORY, not the old name.\"*"
            )

        with st.expander("**7 — Token Preflight** · blocks oversized calls"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "Documents go straight to `AI_COMPLETE` without checking how many tokens "
                "they'll consume. A 920-page PDF (Federal Regulatory Act) burns 2.06 credits on "
                "a single call. Nobody knows it was going to be expensive until the bill "
                "arrives.\n\n"
                "### What 'token preflight' means here\n\n"
                "Before calling any expensive AI function, estimate the input token count "
                "using `AI_COUNT_TOKENS` (near-free) or `LENGTH(text)/4` heuristic. Compare "
                "against configurable thresholds: ALLOW (<0.8 cr), WARN (0.8-2.5 cr), "
                "BLOCK (>2.5 cr). Log every decision to `PREFLIGHT_LOG`.\n\n"
                "### Why current approach is wasteful\n\n"
                "Without a cost check upfront, every document — regardless of size — "
                "gets the same full-context treatment. A 31-page US Code costs 0.13 credits; "
                "a 527-page Federal Register costs 2.64 credits. The 20× cost difference "
                "is invisible until the monthly bill.\n\n"
                "### What the demo shows\n\n"
                "5 PDFs through preflight (illustrative thresholds):\n"
                "- `cfr_title12_part1_banking.pdf` (40K tokens) → **allow** (0.13 cr)\n"
                "- `plaw_107publ204_sarbanes_oxley.pdf` (75K tokens) → **allow** (0.45 cr)\n"
                "- `plaw_104publ191_hipaa.pdf` (190K tokens) → **warn** (1.14 cr)\n"
                "- `plaw_111publ148_aca.pdf` (655K tokens) → **block** (1.96 cr)\n"
                "- `plaw_111publ203_dodd_frank.pdf` (587K tokens) → **block** (1.76 cr)\n\n"
                "Two documents blocked before incurring cost.\n\n"
                "### What 'token preflight' does NOT mean\n\n"
                "- It does NOT prevent the document from being processed — blocked docs "
                "can use the chunked retrieval path (Lever 5) instead of full-doc calls.\n"
                "- It does NOT replace the resource monitor (Lever 10) — preflight is per-"
                "call; resource monitor is per-warehouse/budget.\n"
                "- It is NOT a hard gate by default — 'warn' decisions still proceed; "
                "only 'block' prevents execution.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/17_token_preflight.sql` — `PREFLIGHT_LOG` table + `TOKEN_PREFLIGHT` SPROC\n"
                "- **Table**: `PREFLIGHT_LOG` (file_name, est_input_tokens, est_credits, decision, run_at)\n"
                "- **Quality gate**: no false positives (legitimate small docs never blocked)\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Check the price tag before you buy. A near-free token count estimate "
                "catches the 920-page monster before it eats 2 credits. Block or reroute "
                "to chunked retrieval — same answer, 1/20th the cost.\"*"
            )

        with st.expander("**8 — Completion Cache** · deduplicates identical prompts"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "Multiple downstream consumers ask the same question about the same "
                "document. Each call to `AI_COMPLETE` with an identical prompt+context "
                "pays full token cost again. The LLM is deterministic on identical inputs "
                "(temperature=0), so the response is the same every time.\n\n"
                "### What 'completion cache' means here\n\n"
                "Hash the full prompt (system + user + context). Before calling "
                "`AI_COMPLETE`, check `COMPLETION_CACHE` for that hash. Hit → return "
                "cached response (0 credits). Miss → call the model, store the response.\n\n"
                "### Why current approach is wasteful\n\n"
                "If 5 users ask the same compliance question about the same document in "
                "the same day, that's 5× the AI_COMPLETE cost for 1× the information. "
                "With temperature=0, every response is identical.\n\n"
                "### What the demo shows\n\n"
                "The `COMPLETION_CACHE` table stores prompt_hash → response pairs. On "
                "any exact-match prompt, the pipeline returns cached results at zero "
                "marginal cost. Combined with Lever 1 (parse cache), re-runs of the "
                "entire pipeline on unchanged documents cost exactly 0 credits.\n\n"
                "### What 'completion cache' does NOT mean\n\n"
                "- It does NOT cache semantically-similar prompts — only exact hash "
                "matches. 'What is the penalty?' and 'What's the penalty?' are different.\n"
                "- It does NOT apply when temperature > 0 (non-deterministic outputs).\n"
                "- It does NOT have a TTL by default — entries persist until manually "
                "purged or until the underlying document changes.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/18_completion_cache.sql` — `COMPLETION_CACHE` table + lookup logic\n"
                "- **Quality gate**: cached response byte-identical to fresh call\n"
                "- **Tab 3**: savings shown in cumulative credit curve\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Same question, same doc, same answer — don't pay twice. A hash-"
                "keyed cache makes repeated queries free. Combined with parse cache, "
                "the second run of the entire pipeline costs zero.\"*"
            )

        with st.expander("**9 — Batch Inference** · 3.76× faster, same cost"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "Documents are processed one at a time in a Python loop: parse doc 1, "
                "wait, score doc 1, wait, parse doc 2, wait… Each AI call blocks until "
                "completion before the next starts. Network round-trips and cold-start "
                "latency compound.\n\n"
                "### What 'batch inference' means here\n\n"
                "Replace sequential `FOR doc IN docs` loops with SET-based SQL that "
                "processes all documents in a single statement. Snowflake parallelizes "
                "the AI calls server-side — no client-side orchestration needed.\n\n"
                "### Why current approach is wasteful\n\n"
                "Sequential processing adds N × (network_latency + cold_start) overhead. "
                "For 5 documents, that's 14 seconds elapsed vs 3.7 seconds in batch mode. "
                "Credits are identical — you're paying for the same tokens — but wall-clock "
                "time matters for user experience and pipeline SLAs.\n\n"
                "### What the demo shows\n\n"
                "- **Loop mode**: 5 docs in 14.0 seconds, 0.00275 credits\n"
                "- **Batch mode**: 5 docs in 3.7 seconds, 0.00275 credits\n"
                "- Speedup: **3.76×** with zero additional cost\n\n"
                "Both modes logged to `BATCH_DEMO_LOG` with elapsed_seconds and est_credits.\n\n"
                "### What 'batch inference' does NOT mean\n\n"
                "- It does NOT reduce credit cost — same tokens, same model, same rate.\n"
                "- It does NOT work for streaming use cases where you need partial results.\n"
                "- It is NOT unlimited — very large batches may hit concurrency limits.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/19_batch_demo.sql` — `BATCH_DEMO_LOG` table + loop vs batch SPROCs\n"
                "- **Table**: `BATCH_DEMO_LOG` (run_id, mode, doc_count, elapsed_seconds, est_credits)\n"
                "- **Quality gate**: same credits ± 1%; batch elapsed < loop elapsed\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Same cost, 4× faster. Stop processing one-at-a-time in a Python loop. "
                "A single SET-based SQL statement lets Snowflake parallelize across documents "
                "server-side. Your pipeline SLA drops from minutes to seconds.\"*"
            )

        with st.expander("**10 — Resource Monitor** · budget guardrails"):
            st.markdown(
                "### The setup (what a typical legal-document customer does today)\n\n"
                "No spending limits on the AI pipeline warehouse. If a bug in the pipeline "
                "enters an infinite loop calling `AI_COMPLETE`, or someone accidentally runs "
                "a 10,000-doc batch, there's no automatic shutoff. The bill just grows.\n\n"
                "### What 'resource monitor' means here\n\n"
                "A Snowflake RESOURCE MONITOR attached to `SFE_LEGAL_DOC_AI_WH` with 4 "
                "escalating thresholds:\n"
                "- **50%** → NOTIFY (email alert: 'halfway through budget')\n"
                "- **75%** → NOTIFY (finance review trigger)\n"
                "- **90%** → SUSPEND (warehouse suspends after in-flight queries complete)\n"
                "- **100%** → SUSPEND_IMMEDIATE (all queries cancelled, zero overage)\n\n"
                "### Why this matters\n\n"
                "AI credit spend is effectively unbounded without guardrails. A single "
                "misconfigured flow can consume an entire month's budget in hours. Resource "
                "monitors provide the safety net that prevents bill shock.\n\n"
                "### What the demo shows\n\n"
                "The `BUDGET_GUARDRAIL_DOCS` table documents the 4-tier escalation "
                "strategy. The resource monitor is configured on the demo warehouse with "
                "a monthly credit quota. The pipeline respects soft-suspend (finishes "
                "in-flight work) at 90% and hard-stops at 100%.\n\n"
                "### What 'resource monitor' does NOT mean\n\n"
                "- It does NOT prevent cost — it caps cost at the budget.\n"
                "- It does NOT distinguish 'good' spend from 'bad' spend — all warehouse "
                "credits count equally against the quota.\n"
                "- It does NOT reset automatically — monitor resets on the configured "
                "schedule (monthly by default).\n"
                "- It is NOT per-query — it's per-warehouse cumulative.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL**: `sql/30_resource_monitor.sql` — monitor DDL + threshold config\n"
                "- **Table**: `BUDGET_GUARDRAIL_DOCS` (guardrail_name, threshold_pct, action_type, rationale)\n"
                "- **Tab 6** 'Operations & Projections': Resource Monitor Preview section\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Set a budget, get alerted at 50%, auto-pause at 90%. One CREATE "
                "RESOURCE MONITOR statement prevents bill shock. If something goes wrong, "
                "the worst case is 'pipeline paused' — not 'surprise overage on month-end invoice'.\"*"
            )

        with st.expander("⚠️ **11 — Batch Cortex Search** · offline scale only · NOT for Q&A"):
            st.markdown(
                "### ⚠️ STRONG WARNING — read first\n\n"
                "**Do NOT use this for live Q&A. Do NOT use this for our 5–15 doc demo.**\n\n"
                "Per Snowflake docs: *\"If you need to run fewer than 2,000 queries, you'll "
                "typically get faster results using the interactive Cortex Search API rather "
                "than batch search.\"* Below 2K queries, batch is **slower** (startup latency) "
                "and **more expensive** (you start paying for query embeddings that are FREE "
                "in interactive mode). This lever is documentation-only on this demo — we "
                "intentionally don't ship a measured-savings number because there are none "
                "at our corpus size.\n\n"
                "### The setup (what a customer will eventually need)\n\n"
                "Once the customer's legal corpus grows past ~2,000 queries-per-job — annual contract "
                "deduplication, monthly entity resolution against a canonical party-name list, "
                "or full-corpus eval re-runs across 1,825+ docs × multiple Q&A — the interactive "
                "Cortex Search API hits throughput ceilings and finishes too slowly to be "
                "operationally useful.\n\n"
                "### What 'batch Cortex Search' means here\n\n"
                "`CORTEX_SEARCH_BATCH` is a SQL **table function** invoked via `LATERAL`. "
                "Pattern:\n\n"
                "```sql\n"
                "SELECT q.query, r.*\n"
                "FROM query_table AS q,\n"
                "  LATERAL CORTEX_SEARCH_BATCH(\n"
                "    service_name => 'DB.SCHEMA.SVC',\n"
                "    query => q.query,\n"
                "    limit => 10\n"
                "  ) AS r;\n"
                "```\n\n"
                "It spins up dedicated compute to serve the job (separate from interactive "
                "queries — no degradation to live Q&A throughput) and trades startup latency "
                "for sustained high throughput.\n\n"
                "### Why current approach hits a ceiling\n\n"
                "Interactive Cortex Search is rate-limited per-service. At this scale "
                "(annual eval sweep × 1,825 docs × ~10 questions each = ~18K queries), "
                "interactive would take hours and tie up the live service. Batch finishes "
                "in minutes on isolated compute.\n\n"
                "### What the demo shows\n\n"
                "**Documentation-only.** We do NOT run a `CORTEX_SEARCH_BATCH` job on the "
                "demo's 8,576-chunk service because (a) the docs explicitly recommend "
                "interactive at this size, and (b) it would cost more than the equivalent "
                "interactive call. The SQL pattern is captured in `sql/32_batch_search.sql` "
                "as a reference for when the customer needs it. The 3 cost components are:\n"
                "- **Serving cost** — index size × job duration\n"
                "- **Query embedding cost** — per token (NOT free, unlike interactive)\n"
                "- **Warehouse compute** — for the SQL job\n\n"
                "### What 'batch Cortex Search' does NOT mean\n\n"
                "- It does NOT make small workloads cheaper. Below 2K queries it is "
                "**strictly worse** than interactive on cost AND latency.\n"
                "- It does NOT support reranking. If your `scoring_config` includes "
                "reranker settings, they are silently ignored.\n"
                "- It is NOT a drop-in replacement for the live Cortex Agent — agents "
                "use interactive search.\n"
                "- It does NOT give free query embedding (interactive does).\n"
                "- It is NOT magic — it just spins up dedicated, throughput-optimized "
                "compute that costs real money.\n\n"
                "### Where to find it in the demo\n\n"
                "- **SQL reference**: `sql/32_batch_search.sql` — `CORTEX_SEARCH_BATCH` "
                "syntax + cost-component documentation + the 2K-query threshold rule\n"
                "- **Usage view**: `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_BATCH_QUERY_USAGE_HISTORY` "
                "(only populates if you run a real batch job)\n"
                "- **Docs**: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/batch-cortex-search\n\n"
                "### TL;DR for the customer\n\n"
                "> *\"Save this for when your corpus is big enough that interactive Cortex "
                "Search can't keep up — 2,000+ queries per job. Use cases: annual entity "
                "resolution, contract deduplication, full-corpus eval re-runs. For everything "
                "else (live agent Q&A, ad-hoc retrieval), keep using interactive — it is "
                "literally cheaper and faster below the threshold.\"*"
            )

        st.divider()
        st.caption(
            "**The narrative:** baseline (claude-4-sonnet + OCR + LAYOUT on every doc) "
            "vs optimized (cache + LAYOUT-routed + claude-haiku-4-5 + AI_EMBED + "
            "preflight + completion cache + batch + resource monitor). "
            "Real measured savings on a 5-doc corpus: see Tab 1 cost summary."
        )

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Overview",
            "Upload & Compare",
            "Lever-by-Lever",
            "Cost Dashboard",
            "Ask the Corpus",
            "Quality vs Cost",
            "Operations & Projections",
        ]
    )

    with tab0:
        tab_overview()
    with tab1:
        tab_upload_compare()
    with tab2:
        tab_lever_by_lever()
    with tab3:
        tab_cost_dashboard()
    with tab4:
        tab_ask_corpus()
    with tab5:
        tab_quality_cost()
    with tab6:
        tab_operations()


if __name__ == "__main__":
    main()
