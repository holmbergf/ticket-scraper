# AGENTS.md

## Project

Generic ELT pipeline for resale ticket prices. Tracked tournaments,
games, and multi-session events are **collections** declared in
`collections/*.toml` (see `collections/README.md`); canonical identity is
`(collection_slug, event_key)` end to end. The git repo is the storage
layer. Design: [docs/architecture.md](docs/architecture.md). Ingestion is
manual per collection (no schedules).

## Build & Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./data-integration[dev]" dbt-duckdb duckdb
pip install -r dashboard/requirements.txt
playwright install chromium
ticket-ingest crawl --collection fifa-world-cup-2026   # land raw Parquet
cd dbt-transform && dbt build --target prod --profiles-dir . && cd ..
python -m ticket_ingest.publish_warehouse             # serving exports
streamlit run dashboard/streamlit_app.py              # localhost:8501
```

## Testing

```bash
python -m pytest data-integration/tests dashboard/tests -q
cd dbt-transform && RAW_BASE_PATH=tests/fixtures dbt build --profiles-dir .
```

Run after any change to parsers, storage, schemas, or dbt models.

## Key Conventions

- Python 3.11+. `from __future__ import annotations` in every module.
- Prices stored as **integer cents** through raw/bronze/silver/gold. Only
  dbt semantic models convert to dollars.
- Normalization (team, city, stage, country) lives in dbt silver staging +
  seeds — never in parsers or the dashboard.
- Raw schemas are frozen contracts in `ticket_ingest/schemas.py`; bronze
  casts 1:1 so source schema changes fail loudly.
- Every write is content-addressed/idempotent (`part-<hash>.parquet`,
  hash excludes `timestamp_imported`). Re-running any job is a no-op.
- State derives from `data/_manifests/` — there is no state database.
- `data/raw/` is append-only and irreplaceable; everything in
  `data/data_warehouse/` is derived and disposable.
- Timestamps: `datetime.now(timezone.utc)`, never `datetime.utcnow()`.
- Regex patterns compiled at module level.

## Architecture

```
Parsers → raw Parquet (repo) → dbt bronze/silver/gold/semantic (DuckDB)
        → publish_warehouse → data_warehouse/ Parquet → Streamlit dashboard
```

Parsers return raw data. Ingestion lands it unchanged. dbt shapes it.
Dashboard only reads published Parquet.

## Adding a Collection

Follow `collections/README.md`: copy a TOML, declare canonical events (or
derive them), configure per-source discovery/event URLs, validate
(`ticket-ingest collections validate <slug>`), crawl, rebuild + publish,
and copy a caller workflow (`.github/workflows/ingest-<slug>.yml`).
Dashboard pages are generated from the published catalog — no code.

## Adding a New Source

1. Create `data-integration/src/ticket_ingest/parsers/<source>.py` — expose
   `discover_events()` and `parse_event_page()` returning `ParseResult`.
2. Register the adapter in `SOURCE_ADAPTERS` in `ticket_ingest/jobs.py`
   and the name in `KNOWN_SOURCES` in `ticket_ingest/collections.py`.
3. Add fixtures in `data-integration/tests/fixtures/` and parser tests.
4. Add the source to `accepted_values` in `dbt-transform/.../_schema.yml`
   and `SOURCE_COLORS` / `SOURCE_DISPLAY_NAMES` in the dashboard.
5. Update `README.md` and `docs/architecture.md`.
