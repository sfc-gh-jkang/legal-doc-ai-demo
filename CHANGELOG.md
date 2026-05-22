# Changelog

All notable changes to this demo are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `SECURITY.md` — vulnerability disclosure path
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- `CONTRIBUTING.md` — how to file issues, submit PRs, and run the local test gate
- `CODEOWNERS` — auto-assigns sfc-gh-jkang as default reviewer
- `.github/ISSUE_TEMPLATE/bug_report.md` and `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/dependabot.yml` — weekly pip + monthly github-actions dependency updates
- `.github/workflows/ci.yml` — pytest + ruff on push to master and on PRs
- `ruff.toml` — root ruff config covering `scripts/` and `tests/`
- `sql/00_prereqs.sql` — one-time `PYPI_ACCESS_INTEGRATION` setup as ACCOUNTADMIN
- README badges (license, release, last commit, CI)

### Changed
- `deploy.sql` — usage block now includes `sql/00_prereqs.sql` and optional `sql/30_resource_monitor.sql`
- `docs/customer-narrative.md` — replaced 5 stale TODO placeholders with measured eval verdicts (PASS / PASS / PASS / MOOT / PASS); fixed embedding model name (`snowflake-arctic-embed-m-v1.5`); fixed deprecated `CORTEX_FUNCTIONS_USAGE_HISTORY` reference; scrubbed Obsidian-vault link
- `docs/lever-cost-comparison.md` — replaced 15+ TODOs with measured per-lever and cumulative cost tables

### Removed
- All Obsidian-vault references and personal-account identifiers from public docs

## [1.0.0] — 2026-05-22

Initial public release. Apache-2.0 licensed.

### Added
- 11-lever Cortex AI cost optimization framework (6 stackable + 5 operational)
- 9-document federal-regulatory corpus (Sarbanes-Oxley, Dodd-Frank, HIPAA, ACA, EESA, NDAA-2018/2024, CFR Banking, CFR FTC) — all from public-domain govinfo.gov sources
- Per-lever quality gate eval suite (`eval/30_*.sql` through `eval/41_*.sql`)
- 6-tab Streamlit-on-Snowflake Container Runtime app (`streamlit/app.py`)
- Cortex Search Service (7,958 chunks) + Cortex Agent over the federal corpus
- Architecture diagrams in baseline / optimized variants (`docs/*.mmd` + rendered PNGs)
- Customer-facing narrative + demo runbook + per-lever cost comparison docs
- 36-test pytest suite covering retrieval recall@5, MRR, full-doc baseline similarity, structured-output field identity, and routing agreement

### Pareto results (from initial release eval)
- `claude-haiku-4-5` dominates the scorer step: 92.1% credit savings vs `claude-4-sonnet`, 100% mode agreement, 0.86 reasoning-text similarity
- Retrieval: recall@5 = 1.0, MRR = 1.0, end-to-end answer similarity = 96.2% of full-doc baseline (across 10 hand-built Q&A pairs)
- Lever verdicts: 1=PASS, 2=PASS, 3=PASS, 4=MOOT (corpus rarely fails free-text), 5=PASS

[Unreleased]: https://github.com/sfc-gh-jkang/legal-doc-ai-demo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/sfc-gh-jkang/legal-doc-ai-demo/releases/tag/v1.0.0
