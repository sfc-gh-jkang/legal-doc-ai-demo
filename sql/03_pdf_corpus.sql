-- =============================================================================
-- 03_pdf_corpus.sql — Public legal corpus documentation + verification
-- =============================================================================
-- The actual PDF downloads happen via scripts/fetch_corpus.py.
-- Upload via scripts/upload_pdfs.py or: snow stage put data/corpus_v2/*.pdf @PDF_STAGE
--
-- PUBLIC LEGAL CORPUS (all freely available from www.govinfo.gov, no customer data):
--
-- LARGE STATUTES (text-heavy, multi-hundred-page):
--   1. plaw_111publ148_aca.pdf — Affordable Care Act (2010)
--   2. plaw_111publ203_dodd_frank.pdf — Dodd-Frank Wall Street Reform Act (2010)
--   3. plaw_118publ31_ndaa_2024.pdf — National Defense Authorization Act FY2024
--   4. plaw_115publ232_ndaa.pdf — National Defense Authorization Act FY2019
--
-- MID-SIZE STATUTES (typical legal-PDF length):
--   5. plaw_104publ191_hipaa.pdf — HIPAA (1996)
--   6. plaw_110publ343_eesa.pdf — Emergency Economic Stabilization Act / TARP (2008)
--   7. plaw_107publ204_sarbanes_oxley.pdf — Sarbanes-Oxley Act (2002)
--
-- COMPACT REGULATIONS (CFR parts, structured tables/headings):
--   8. cfr_title16_part1_ftc.pdf — FTC general procedures for consumer protection
--   9. cfr_title12_part1_banking.pdf — Banking regulations on investment securities
--
-- =============================================================================

USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Verify uploaded files after running scripts/upload_pdfs.py
LIST @PDF_STAGE;
