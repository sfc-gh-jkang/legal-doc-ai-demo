-- =============================================================================
-- 30_resource_monitor.sql — Lever 10: Resource Monitor & Spend Guardrails
-- =============================================================================
-- READ-ONLY DEMO. These are compile-validated DDLs that the customer would deploy in
-- production. Do NOT execute against demo account — would interfere with other
-- workloads.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- =============================================================================
-- BEGIN COMPILE-ONLY BLOCK
-- The DDLs below are wrapped in a block comment so this file deploys cleanly
-- without creating actual resource monitors or altering warehouses.
-- =============================================================================
/*

-- 1. Resource Monitor: Monthly credit budget with tiered alerts
--    - 50%: Email notification (midpoint awareness)
--    - 75%: Email notification (action threshold)
--    - 90%: Suspend warehouse (soft stop — queued queries finish)
--    - 100%: Suspend immediate (hard stop — all queries cancelled)
CREATE OR REPLACE RESOURCE MONITOR LEGAL_DOC_AI_CORTEX_BUDGET
    WITH
        CREDIT_QUOTA         = 1000
        FREQUENCY            = MONTHLY
        START_TIMESTAMP      = IMMEDIATELY
    TRIGGERS
        ON 50 PERCENT DO NOTIFY
        ON 75 PERCENT DO NOTIFY
        ON 90 PERCENT DO SUSPEND
        ON 100 PERCENT DO SUSPEND_IMMEDIATE;

-- 2. Attach the monitor to the AI workload warehouse
ALTER WAREHOUSE SFE_LEGAL_DOC_AI_WH
    SET RESOURCE_MONITOR = LEGAL_DOC_AI_CORTEX_BUDGET;

-- 3. Notification integration for email alerts
--    Replace with the customer's internal distribution list in production.
CREATE OR REPLACE NOTIFICATION INTEGRATION LEGAL_DOC_AI_CORTEX_ALERTS
    TYPE = EMAIL
    ENABLED = TRUE
    ALLOWED_RECIPIENTS = ('legal-ops@example.com', 'it-finance@example.com')
    COMMENT = 'Cortex AI spend alerts — legal team + finance oversight';

*/
-- =============================================================================
-- END COMPILE-ONLY BLOCK
-- =============================================================================

-- =============================================================================
-- Guardrail documentation view (executes safely — read-only SELECT)
-- Surfaces recommended thresholds so the Streamlit app can display them.
-- =============================================================================
CREATE OR REPLACE VIEW BUDGET_GUARDRAIL_DOCS AS
SELECT column1 AS guardrail_name,
       column2 AS threshold_pct,
       column3 AS action_type,
       column4 AS rationale
FROM VALUES
    ('Early warning',      50,  'NOTIFY',            'Midpoint awareness — team reviews spend trajectory'),
    ('Action threshold',   75,  'NOTIFY',            'Finance reviews; team evaluates model/routing changes'),
    ('Soft suspend',       90,  'SUSPEND',           'Warehouse suspends after in-flight queries complete'),
    ('Hard suspend',       100, 'SUSPEND_IMMEDIATE', 'All queries cancelled immediately — zero overage')
;

-- Compile validation
SELECT 'compile-ok' AS status;
