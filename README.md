# ticket-scraper

ELT pipeline for FIFA World Cup 2026 resale ticket prices: crawl five
marketplaces, land partitioned Parquet **in this repository**, model it
with dbt, and serve a Streamlit dashboard from the published semantic
layer. The full history is ~4 MB of append-only Parquet partitions
(~125 KB per crawl). Full design: [docs/architecture.md](docs/architecture.md).

Ingestion runs on demand (GitHub Actions `workflow_dispatch` or locally);
there is no schedule — the tournament has concluded.

## Architecture

```text
Vivid Seats ─┐
Gametime ────┤
StubHub ─────┤  ticket-ingest ─► data/raw/<dataset>/…  partitioned Parquet
Viagogo ─────┤    (Python)       data/_manifests/…     run state (no DB)
FIFA Collect ┘                          │
                       dbt (DuckDB) ────┤ bronze views (1:1 casts)
                                        ├─ silver: clean staging, dim, facts
                                        ├─ gold: analytics marts
                                        └─ semantic: dollars, dashboard surface
                                               │
                       publish_warehouse ─► data/data_warehouse/{silver,gold,semantic}/*.parquet
                                               │
                       Streamlit dashboard (reads published Parquet only)
```

- **Ingestion** ([`data-integration/`](data-integration/)): marketplace
  parsers/fetch layer, landing as-fetched rows aligned to frozen
  PyArrow schemas. Writes are content-addressed (`part-<hash>.parquet`) —
  re-runs write zero new files. State lives in `data/_manifests/`.
- **Warehouse** ([`dbt-transform/`](dbt-transform/)): 18 models — bronze
  1:1 casts, silver normalization (seed-driven team/city/stage/country
  mappings) + conformed match dim + facts, gold benchmarks/overviews/
  price changes, semantic in dollars. Schema + singular data tests; CI
  builds the exact production models on committed mock fixtures.
- **Dashboard** ([`dashboard/`](dashboard/)): Streamlit app over the
  semantic exports (scorecards, market trend, best deals, price history,
  listing drill-down). Source filters recompute at read time. Exports
  standalone for Streamlit Cloud via `dashboard/export_standalone.sh`.

## Repository structure

```text
ticket-scraper/
├── data-integration/       # Ingestion package (ticket-ingest CLI)
│   ├── src/ticket_ingest/  # parsers, http, schemas, storage, jobs, alerts
│   ├── tests/              # pytest (committed HTML fixtures, offline)
│   └── Dockerfile          # Stateless runner image
├── dbt-transform/          # dbt warehouse (DuckDB)
│   ├── models/connector/tickets/{bronze,silver,gold,semantic}/
│   ├── seeds/              # team/city/stage/country mappings
│   └── tests/fixtures/     # mock raw samples for CI
├── dashboard/              # Streamlit app + tests
├── data/                   # THE STORAGE LAYER (committed)
│   ├── raw/                # partitioned Parquet, append-only
│   ├── _manifests/         # run manifests (pipeline state)
│   └── data_warehouse/     # published serving exports
└── .github/workflows/      # manual ingest + per-module CI
```

## Operation

| Workflow | Trigger | What it does |
|---|---|---|
| `ingest` | Manual (`workflow_dispatch`, optional single source) | `ticket-ingest crawl` → `dbt build --target prod` → publish → commit `data/`; price-alert and failure issues |
| `ci/data-integration` | Changes under `data-integration/**` | pytest, byte-compile, CLI smoke |
| `ci/dbt` | Changes under `dbt-transform/**` | Full dbt build + data tests on mock fixtures; slim selection vs prod manifest reported informationally |
| `ci/dashboard` | Changes under `dashboard/**` | pytest data layer, byte-compile |

CI workflows are path-filtered and independent. Ingestion has no
schedule: the tournament has concluded, so crawls run on demand only.

## Local development

Prerequisites: Python 3.11+, Google Chrome (Vivid Seats browser fallback).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./data-integration[dev]" dbt-duckdb duckdb
pip install -r dashboard/requirements.txt
playwright install chromium
cp .env.example .env   # optional path overrides only; no secrets exist
```

```bash
# Crawl (all sources, or one)
ticket-ingest crawl
ticket-ingest crawl --source gametime --max-events 5

# Warehouse
cd dbt-transform && dbt build --target prod --profiles-dir . && cd ..
python -m ticket_ingest.publish_warehouse

# Import a SQLite DB (events/market_snapshots/listings) into the raw zone
ticket-ingest migrate-sqlite path/to/tickets.db

# Tests
python -m pytest data-integration/tests dashboard/tests -q
cd dbt-transform && RAW_BASE_PATH=tests/fixtures dbt build --profiles-dir .

# Dashboard
streamlit run dashboard/streamlit_app.py
```

Use the library directly:

```python
from pathlib import Path
from ticket_ingest.storage import LocalStorage, StateStore

state = StateStore(LocalStorage(Path("data")))
print(state.crawl_timestamps()[-1], len(state.event_ids_for_source("stubhub")))
```

## Configuration

Paths only (see [`.env.example`](.env.example)): `DATA_DIR`,
`RAW_HTML_DIR`, `RAW_BASE_PATH`, `WAREHOUSE_DIR` — identical names locally
and in GitHub Actions. The ingest workflow commits with the default
`GITHUB_TOKEN`.

## Data notes

- Committed history covers 2026-04-04 → 2026-05-04 (154 crawls): 481
  source events over 104 matches, 35,484 canonical market snapshots,
  591,953 listings (4.3 MB of Parquet).
- One canonical snapshot per (source, event, crawl): where a crawl
  produces discovery-page and event-page rows under one timestamp, the
  event-page row is kept (latest insert wins).
- Prices are integer cents until the semantic layer. Raw schemas are
  frozen contracts in `ticket_ingest/schemas.py`.
- `match_number` (1–104) is the conformed cross-source match key.
