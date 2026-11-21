# FIFA 2026 Ticket Tracker (Streamlit)

Dashboard over the semantic layer (`semantic_match_prices`,
`semantic_source_prices`, `semantic_price_trends`). It reads only the
published Parquet exports (`data/data_warehouse/`) — never the raw zone.

Four pages (sidebar radio), with global source/stage/city/team filters:

- **Matches** — a match "card" (team-vs-team header, metric tiles,
  inventory share bar, per-source price bars, benchmark compare bars, and a
  price-context expander) over a clickable all-games table with daily-best
  sparklines. Tick a row's checkbox to load that match; sort by kickoff,
  cheapest, or biggest drop.
- **Market** — scorecards, market price trend (median/average/cheapest,
  zoomable), price by source, stage, and city (+ map in an expander).
- **Deals** — cross-source savings, biggest first-to-latest drops, and the
  current price distribution, as switchable views.
- **History** — per-game price lines by source against the tournament
  median, days-to-kickoff comparison curves, and a listing drill-down
  with section medians.

Design language: dark theme (`.streamlit/config.toml`), narrow 1180px
content column, custom metric-card CSS, per-source colors used
consistently across bars/tables/legends, buyer-colored deltas
(green = cheaper, always captioned), and Altair charts with tooltips
throughout (Plotly only for the city map). Data loads are cached for an
hour, keyed on a published-exports version stamp so a publish is picked
up immediately.

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
