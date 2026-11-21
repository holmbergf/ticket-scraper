# ticket-scraper

ELT pipeline for FIFA World Cup 2026 resale ticket prices: crawl five
marketplaces, land partitioned Parquet **in this repository**, model it
with dbt, and serve a Streamlit dashboard from the published semantic
layer. No cloud storage, no database server, no secrets.

Fork of `fholmberg/fifa_tickets`, restructured on the conventions of
`holmbergf/elt-pipeline` with the git repo replacing Cloudflare R2/Basin
as the storage layer. The legacy design committed a monolithic SQLite
file that grew past GitHub's 100 MB per-file limit and got its scheduled
workflow disabled; this one stores the full history as ~4 MB of
append-only Parquet partitions (~125 KB per crawl). Full design and the
storage math: [docs/architecture.md](docs/architecture.md).

Production entry point is GitHub Actions — the pipeline runs autonomously
on schedule (see [Autonomous operation](#autonomous-operation)).

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

- **Ingestion** ([`data-integration/`](data-integration/)): the legacy
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
└── .github/workflows/      # autonomous ingest + per-module CI
```

## Autonomous operation

| Workflow | Trigger | What it does |
|---|---|---|
| `ingest` | 00:00, 08:00, 16:00 UTC daily + manual | `ticket-ingest crawl` → `dbt build --target prod` → publish → commit `data/`; price-alert and failure issues |
| `ci/data-integration` | Changes under `data-integration/**` | pytest, byte-compile, CLI smoke |
| `ci/dbt` | Changes under `dbt-transform/**` | Full dbt build + data tests on mock fixtures; slim selection vs prod manifest reported informationally |
| `ci/dashboard` | Changes under `dashboard/**` | pytest data layer, byte-compile |

Workflows are path-filtered and independent. There is no infra workflow —
there is no infrastructure.

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

# One-off: migrate a legacy fifa_tickets SQLite DB into the raw zone
ticket-ingest migrate-sqlite path/to/test_full3.db

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
and in GitHub Actions. No secrets are required anywhere; the ingest
workflow commits with the default `GITHUB_TOKEN`.

## Data notes

- Migrated history covers 2026-04-04 → 2026-05-04 (154 crawls): 481
  source events over 104 matches, 35,484 canonical market snapshots,
  591,953 listings — 4.3 MB of Parquet vs the legacy 103 MB SQLite file.
- One canonical snapshot per (source, event, crawl): where the legacy
  crawler stored discovery-page and event-page rows under one timestamp,
  the event-page row (its own `MAX(id)` winner) is kept. Benchmarks built
  on that differ from legacy on 261 of 3,224 game-days (legacy included
  discovery-page teaser prices there); every other surface matches
  legacy output exactly. See
  [docs/architecture.md §5](docs/architecture.md).
- Prices are integer cents until the semantic layer. Raw schemas are
  frozen contracts in `ticket_ingest/schemas.py`.
- `match_number` (1–104) is the conformed cross-source match key.
- After the tournament, marketplace WC pages will retire and the
  schedule will raise data-quality alert issues by design; disable the
  `schedule:` block in `.github/workflows/ingest.yml` then.
