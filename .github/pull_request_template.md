## Summary

## Verification

- [ ] `pytest data-integration/tests dashboard/tests -q`
- [ ] `ruff check data-integration/src dashboard data-integration/tests dashboard/tests`
- [ ] `RAW_BASE_PATH=tests/fixtures dbt build` (from `dbt-transform/`)
- [ ] No secrets, browser profiles, raw HTML dumps, or full page captures added
- [ ] Docs/collection config updated where behavior changed
