"""Publish dbt silver/gold/semantic models to data_warehouse/ Parquet.

dbt builds modeled tables inside a DuckDB file; this step exports each
registered model to ``data/data_warehouse/<layer>/<table>.parquet``
(zstd), which the dashboard reads and the ingest workflow commits. The
Parquet export is the serving contract. Publishing is a full overwrite —
idempotent and immune to partial-failure states, at the cost of rewriting
a few megabytes. Run after `dbt build`:

  python -m ticket_ingest.publish_warehouse [path/to/warehouse.duckdb]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .config import REPO_ROOT, Settings

log = logging.getLogger(__name__)

# dbt model name -> (layer, published table name)
MODELS: dict[str, tuple[str, str]] = {
    "clean_tickets_events": ("silver", "clean_tickets_events"),
    "clean_tickets_market_snapshots": ("silver", "clean_tickets_market_snapshots"),
    "clean_tickets_listings": ("silver", "clean_tickets_listings"),
    "dim_tickets_matches": ("silver", "dim_tickets_matches"),
    "fct_tickets_market_snapshots": ("silver", "fct_tickets_market_snapshots"),
    "fct_tickets_latest_prices": ("silver", "fct_tickets_latest_prices"),
    "fct_tickets_listings_latest": ("silver", "fct_tickets_listings_latest"),
    "analytics_tickets_market_benchmarks": ("gold", "analytics_tickets_market_benchmarks"),
    "analytics_tickets_source_overviews": ("gold", "analytics_tickets_source_overviews"),
    "analytics_tickets_price_changes": ("gold", "analytics_tickets_price_changes"),
    "semantic_match_prices": ("semantic", "semantic_match_prices"),
    "semantic_source_prices": ("semantic", "semantic_source_prices"),
    "semantic_price_trends": ("semantic", "semantic_price_trends"),
    "semantic_market_trends": ("semantic", "semantic_market_trends"),
    "semantic_source_overview": ("semantic", "semantic_source_overview"),
}


def publish(db_path: Path, warehouse_dir: Path | None = None) -> dict[str, int]:
    import duckdb

    out_root = Path(warehouse_dir) if warehouse_dir else Settings.from_env().warehouse_dir
    con = duckdb.connect(str(db_path), read_only=True)
    counts: dict[str, int] = {}
    try:
        available = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables UNION SELECT view_name FROM duckdb_views()").fetchall()}
        for model, (layer, table) in MODELS.items():
            if model not in available:
                raise RuntimeError(f"dbt model {model} not found in {db_path}; run dbt build first")
            # ORDER BY ALL: deterministic bytes across rebuilds, so an
            # ingest run that changed nothing produces a git no-op for the
            # committed serving files instead of Parquet byte churn.
            arrow = con.execute(f'SELECT * FROM "{model}" ORDER BY ALL').fetch_arrow_table()
            # All-null columns arrive with a null type; cast to string so the
            # published schema stays stable for readers.
            arrow = arrow.cast(pa.schema([
                pa.field(f.name, pa.string() if pa.types.is_null(f.type) else f.type)
                for f in arrow.schema
            ]))
            dest = out_root / layer / f"{table}.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(arrow, dest, compression="zstd")
            counts[table] = arrow.num_rows
            log.info("published %s/%s: %d rows", layer, table, arrow.num_rows)
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    db_path = Path(args[0]) if args else REPO_ROOT / "dbt-transform" / "warehouse.duckdb"
    publish(db_path)


if __name__ == "__main__":
    main()
