## Summary

<!-- 1–2 sentences. What does this PR do, why? -->

## Linked issue

Closes #<!-- issue number -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (fix or feature requiring users to redeploy)
- [ ] Documentation only
- [ ] CI / repo metadata only

## Tests run locally

- [ ] `cd tests && uv run pytest -q` (all passing)
- [ ] `uv tool run ruff check streamlit/ scripts/ tests/` (clean)
- [ ] `uv tool run ruff format --check streamlit/ scripts/ tests/` (clean)
- [ ] If SQL changed: compile-checked the affected file via `snow sql --enable-templating NONE -f sql/<file>` against my own connection
- [ ] If Streamlit changed: re-deployed locally and clicked through the affected tab(s)
- [ ] If diagrams changed: re-rendered both PNGs via `npx @mermaid-js/mermaid-cli` and visually inspected

## Cost implications

<!-- Does running this PR cost more credits than the previous version? Best/avg/worst case for an end-to-end demo. -->

## Risk

<!-- What could regress? Worst case if this PR is wrong? -->

## Screenshots / output

<!-- If UI or output changes, paste before/after. -->

## Checklist

- [ ] Read `CONTRIBUTING.md`
- [ ] No secrets, account locators, customer slugs, or internal Snowflake URLs introduced
- [ ] Documentation updated for any user-facing change
- [ ] CHANGELOG.md updated under "Unreleased"
