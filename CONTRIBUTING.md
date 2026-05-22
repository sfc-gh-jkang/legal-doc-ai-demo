# Contributing

Thanks for your interest in this demo. A few expectations up front:

> **This is a Snowflake Sales Engineering sample, not a productized framework.** Pull requests are welcome but the maintainer's bandwidth is limited and review may take a few weeks. For anything urgent, reach out to the AE/SE on your account.

## What we accept

- Bug fixes (typos, broken links, SQL that doesn't compile, scripts that fail on a fresh clone)
- Documentation improvements (clearer explanations, additional Q&A pairs, customer-objection prep)
- Compatibility fixes for new Snowflake regions, Cortex AI feature changes, or Container Runtime updates
- New corpus PDFs from public-domain sources (govinfo.gov, federalregister.gov, EU regulatory portals)
- Regression tests under `tests/` for any of the above

## What we don't accept (without prior discussion)

- New levers beyond the 11 documented (please open an issue first to discuss)
- Major refactors of `streamlit/app.py` (it's intentionally one file for easy demo presentation; v1.1 may split it)
- Changes that break Apache-2.0 license compatibility (no GPL/AGPL deps)
- New external service dependencies (PyPI, Docker, cloud APIs) — the demo deliberately uses only Snowflake-native paths
- Customer-specific business logic (this is a portable sample)

## Filing an issue

Use the appropriate issue template:

- **Bug**: include Snowflake region, edition, role, exact error, repro steps. Template at `.github/ISSUE_TEMPLATE/bug_report.md`.
- **Feature request**: what you want, why, and how it would interact with the existing 11 levers. Template at `.github/ISSUE_TEMPLATE/feature_request.md`.
- **Security vulnerability**: do NOT use a public issue. See `SECURITY.md`.

## Submitting a pull request

1. Fork the repo and branch from `master` (e.g. `fix/typo-in-readme` or `feat/add-eu-corpus`).
2. Run the local test gate before pushing:

   ```bash
   cd tests && uv sync && uv run pytest -q
   uv tool run ruff check ../streamlit ../scripts ../tests
   uv tool run ruff format --check ../streamlit ../scripts ../tests
   ```

   All three must pass.

3. If your change touches SQL: compile-check the affected files via `snow sql --enable-templating NONE -f sql/<file>` against your own connection.
4. If your change touches the Streamlit app: re-deploy locally and click through the affected tab(s) before opening the PR.
5. Open a PR using the template at `.github/PULL_REQUEST_TEMPLATE.md`. Link any related issue. Note any cost implications (does running this PR cost more than the previous version?).
6. CI runs on every push to your branch (pytest + ruff). PRs with red CI cannot be merged.

## Local development setup

```bash
# Clone
git clone https://github.com/sfc-gh-jkang/legal-doc-ai-demo.git
cd legal-doc-ai-demo

# Install streamlit deps
cd streamlit && uv sync && cd ..

# Install test deps
cd tests && uv sync && cd ..

# Configure Snowflake CLI connection (substitute your own alias)
snow connection add --connection-name <your-alias> ...
```

## Code style

- **Python**: follow the `[tool.ruff]` config (line length 120, target-version py311, select E/F/W/I).
- **SQL**: UPPER for keywords, `_` separator for identifiers (matches Snowflake conventions), no inline lower-case shortcuts.
- **Markdown**: GitHub-flavored. Tables prefer **bold** for emphasis over backticks (backticks force monospace and break wrap on Obsidian / mobile).
- **Diagrams**: source in `docs/*.mmd`, rendered to `docs/*.png` via `npx @mermaid-js/mermaid-cli`. Re-render after every edit.

## License

By contributing you agree your contributions are licensed under Apache-2.0 (see `LICENSE`).
