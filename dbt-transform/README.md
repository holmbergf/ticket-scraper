# dbt-transform

dbt warehouse (DuckDB) over the committed Parquet raw zone:
bronze views (1:1 casts) → silver staging/core → gold analytics →
semantic (dollars, dashboard surface). 18 ticket models + 4 mapping seeds.

## Publishing

dbt builds into a local `warehouse.duckdb`;
`python -m ticket_ingest.publish_warehouse` then exports every
silver/gold/semantic model to `data/data_warehouse/<layer>/<table>.parquet`
(zstd, `ORDER BY ALL` for byte-deterministic output). DuckDB reads the
raw zone off disk via `RAW_BASE_PATH`.

## Run

```bash
cd dbt-transform
dbt build --profiles-dir .                  # dev: repo data/ -> dev.duckdb
dbt build --target prod --profiles-dir .    # prod: warehouse.duckdb
RAW_BASE_PATH=tests/fixtures dbt build --profiles-dir .   # CI fixtures
```

Full-refresh throughout; switch facts to
incremental merge on `(source, event_id_external, crawl_ts_utc)` when a
full build approaches ~10 minutes (currently ~2 s on full history).
