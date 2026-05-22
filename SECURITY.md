# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this demo, please **do NOT file a public GitHub issue.** Instead, email the maintainer directly:

**john.kang@snowflake.com** — subject line `[SECURITY] legal-doc-ai-demo`

Please include:
- Repository commit SHA
- Affected file(s) and line numbers
- A brief description of the issue and suggested fix (if any)
- Whether you have reproduced the issue locally and how

You can expect:
- Acknowledgement within 5 business days
- A scoped fix or risk-acceptance decision within 30 days
- Credit in the changelog for the disclosure (unless you prefer to remain anonymous)

## Scope

This is a Snowflake Sales Engineering demo, not a productized framework. Security expectations:

- **No bug bounty.** This is a public sample under Apache-2.0; vulnerability disclosure is appreciated but not compensated.
- **No SLA on fixes.** The repository owner addresses disclosures on a best-effort basis around customer engagement work.
- **Vulnerabilities in upstream Snowflake products** (Cortex AI, Cortex Search, Cortex Agent, Streamlit on Snowflake, Snowflake CLI) are out of scope here — please report those through Snowflake's official security channels at `https://www.snowflake.com/security/`.
- **Vulnerabilities in third-party Python dependencies** are tracked via Dependabot in this repository. Please file a regular issue or PR for those.

## In scope

- Hardcoded secrets or credentials accidentally committed to this repo
- SQL injection or prompt-injection bugs in the demo code
- Misconfigurations in `deploy.sql`, `sql/*.sql`, `eval/*.sql`, or the Streamlit app that could expose customer data
- Documentation that could lead a customer to deploy something insecure
- Inappropriate `.gitignore` patterns that allow secrets through

## Out of scope

- The demo's reliance on Apache-2.0 dependencies (those are reviewed by Dependabot)
- Recommendations to harden Snowflake account configuration (those belong with the Snowflake AE/SE)
- Theoretical attacks that require already-elevated Snowflake account privileges
- Findings on customer-deployed copies of this demo (please contact your own Snowflake team)
