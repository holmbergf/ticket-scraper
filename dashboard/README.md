# FIFA 2026 Ticket Tracker (Streamlit)

Dashboard over the semantic layer (`semantic_match_prices`,
`semantic_source_prices`, `semantic_price_trends`). It reads only the
published Parquet exports (`data/data_warehouse/`) — never the raw zone.

Sections: scorecards, market trend, per-source overview, all-games scatter,
best deals, all-games table with price-change deltas, price by stage/city,
days-to-kickoff curves, per-game price history, listing drill-down.

## Data path

`dashboard/data.py` reads `data_warehouse/{semantic,gold,silver}` with
DuckDB. Location: `$WAREHOUSE_DIR`, else `$LOCAL_WAREHOUSE_DIR/data_warehouse`,
else a bundled `data_warehouse/` next to the app (standalone export), else
the repo's `data/data_warehouse`. Source-subset views are recomputed at
read time from the published tables.

## Local run

```bash
source .venv/bin/activate
pip install -r dashboard/requirements.txt
streamlit run dashboard/streamlit_app.py
python -m pytest dashboard/tests -q
```

## Deploy (Streamlit Community Cloud)

The main repo is private, so export a standalone copy (app + bundled
serving Parquet, no secrets) and deploy that:

```bash
./dashboard/export_standalone.sh /path/to/standalone-checkout
```
