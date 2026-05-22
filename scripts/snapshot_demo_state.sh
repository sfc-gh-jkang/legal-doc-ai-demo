#!/usr/bin/env bash
# snapshot_demo_state.sh — Capture DDL + row counts for Legal Doc AI demo state
#
# Usage:
#   bash scripts/snapshot_demo_state.sh
#   bash scripts/snapshot_demo_state.sh --label pre-customer-x
#
# Output: data/snapshots/<timestamp>[-<label>]/
#   - ddl.sql            — CREATE statements for all schema objects
#   - counts.txt         — row counts for every table + view
#   - eval_summary.txt   — current EVAL_SUMMARY_V verdicts
#   - pareto.txt         — current PARETO_FRONTIER_V state
#   - lever_savings.txt  — Tab 6 numbers
#
# Use BEFORE a demo (rollback safety) and AFTER a demo (post-mortem).

set -euo pipefail

CONNECTION="${CONNECTION:-aws_spcs}"
DB="SNOWFLAKE_EXAMPLE"
SCHEMA="LEGAL_DOC_AI_DEMO"
LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="-$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS=$(date +%Y%m%d_%H%M%S)
OUTDIR="${REPO_ROOT}/data/snapshots/${TS}${LABEL}"

mkdir -p "$OUTDIR"
echo "Snapshot output: $OUTDIR"

# 1. Row counts for every table + view in the schema
snow sql -c "$CONNECTION" -q "
SELECT TABLE_NAME, ROW_COUNT
FROM ${DB}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '${SCHEMA}'
  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
ORDER BY TABLE_NAME;
" > "${OUTDIR}/counts.txt" 2>&1
echo "  - counts.txt"

# 2. DDL for every object via GET_DDL on the whole schema
snow sql -c "$CONNECTION" -q "SELECT GET_DDL('SCHEMA', '${DB}.${SCHEMA}', TRUE);" \
  > "${OUTDIR}/ddl.sql" 2>&1
echo "  - ddl.sql"

# 3. Eval summary current state
snow sql -c "$CONNECTION" -q "
SELECT LEVER_NAME, VERDICT, TOTAL_DOCS, PASSED_DOCS, MIN_SIMILARITY, GATE_DESCRIPTION
FROM ${DB}.${SCHEMA}.EVAL_SUMMARY_V;
" > "${OUTDIR}/eval_summary.txt" 2>&1
echo "  - eval_summary.txt"

# 4. Pareto frontier current state
snow sql -c "$CONNECTION" -q "
SELECT MODEL_NAME, ROUND(MEAN_QUALITY,4) AS Q, ROUND(TOTAL_CREDITS,6) AS CR,
       ON_PARETO_FRONTIER, ROUND(SAVINGS_VS_GOLD_PCT*100,1) AS SAV_PCT
FROM ${DB}.${SCHEMA}.PARETO_FRONTIER_V
ORDER BY TOTAL_CREDITS;
" > "${OUTDIR}/pareto.txt" 2>&1
echo "  - pareto.txt"

# 5. Lever savings
snow sql -c "$CONNECTION" -q "
SELECT FILENAME,
       ROUND(TOTAL_BASELINE_CREDITS, 6) AS BASELINE_CR,
       ROUND(TOTAL_OPTIMIZED_CREDITS, 6) AS OPT_CR,
       ROUND(CREDITS_SAVED, 6) AS SAVED,
       ROUND(PCT_SAVINGS, 1) AS PCT
FROM ${DB}.${SCHEMA}.LEVER_SAVINGS
ORDER BY CREDITS_SAVED DESC;
" > "${OUTDIR}/lever_savings.txt" 2>&1
echo "  - lever_savings.txt"

echo ""
echo "Snapshot complete: ${OUTDIR}"
echo "Files:"
ls -la "$OUTDIR"
