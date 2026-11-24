# Contributing

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./data-integration[dev]" "dbt-duckdb==1.10.0" "duckdb==1.4.4"
pip install -r dashboard/requirements.txt
playwright install chrome chromium
```

## Before opening a pull request

```bash
.venv/bin/python -m pytest data-integration/tests dashboard/tests -q
.venv/bin/ruff check data-integration/src dashboard data-integration/tests dashboard/tests
cd dbt-transform && RAW_BASE_PATH=tests/fixtures dbt build --profiles-dir .
```

- Keep prices in integer cents below the semantic layer.
- Put all normalization in dbt silver/seeds, never in parsers or the dashboard.
- Treat frozen schemas in `ticket_ingest/schemas.py` as contracts; changing
  one requires matching bronze/silver updates and tests.
- Capture minimal synthetic HTML excerpts for parser tests. Do not commit
  full marketplace page captures, cookies, browser profiles, `.env` files,
  tokens, or `data/raw_html/` output.
- New tracked events belong in `collections/` (see
  `collections/README.md`); new behavior needs a test that would fail
  without the change.

By contributing, you agree your contributions are licensed under the
repository's MIT License.
