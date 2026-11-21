# Ticket Scraper (Streamlit)

Dashboard over the semantic layer (`semantic_collections`,
`semantic_event_catalog`, `semantic_event_prices`, `semantic_source_prices`,
`semantic_price_trends`). It reads only the
published Parquet exports (`data/data_warehouse/`) — never the raw zone.

Navigation is generated from the published catalogs:

- **Home** — every collection with coverage, cheapest event, and links.
- **Market / Deals / History** — shared analytics scoped to the sidebar's
  analytics collection (trends, cross-source savings/drops, per-event
  history, days-to-event curves, listing drill-down).
- **One overview per collection** — an event card plus a clickable
  all-events table with daily-best sparklines.
- **One dedicated page per canonical event** — event card, price history,
  and listings for exactly that event (e.g.
  `event-nfl-cowboys-at-seahawks-2026-12-07--dallas-cowboys-at-seattle-seahawks`).

New collections and events appear automatically after the next publish;
no dashboard code changes are needed.

Design language: dark theme (`.streamlit/config.toml`), narrow 1180px
content column, custom metric-card CSS, per-source colors used
consistently across bars/tables/legends, buyer-colored deltas
(green = cheaper, always captioned), and Altair charts with tooltips
throughout (Plotly only for the city map). Data loads are cached for an
hour, keyed on a published-exports version stamp so a publish is picked
up immediately.

## Data path

`dashboard/warehouse.py` reads `data_warehouse/{semantic,gold,silver}` with
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
