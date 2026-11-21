"""Frozen raw schemas — the contract between ingestion and dbt bronze.

These PyArrow schemas are enforced on every Parquet write, and dbt bronze
models cast 1:1 against them, so a parser/source schema change fails
loudly at the bronze cast rather than drifting downstream.

Conventions:
- Prices are integer cents. Only dbt semantic models convert to dollars.
- Timestamps land as ISO-8601 UTC strings; bronze casts them to TIMESTAMP.
- No ``raw_snapshot_path`` column: raw HTML snapshots are local debugging
  artifacts under ``data/raw_html/`` (gitignored), so their paths would be
  meaningless in a committed dataset.
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pyarrow as pa

from .models import Event, Listing, MarketSnapshot

EVENTS_SCHEMA = pa.schema([
    ("source", pa.string()),
    ("event_id_external", pa.string()),
    ("event_url", pa.string()),
    ("event_name", pa.string()),
    ("match_number", pa.int64()),
    ("stage", pa.string()),
    ("team_1", pa.string()),
    ("team_2", pa.string()),
    ("event_start_local", pa.string()),
    ("venue_name", pa.string()),
    ("city", pa.string()),
    ("region", pa.string()),
    ("country", pa.string()),
    ("currency", pa.string()),
    ("timestamp_imported", pa.string()),
])

MARKET_SNAPSHOTS_SCHEMA = pa.schema([
    ("source", pa.string()),
    ("event_id_external", pa.string()),
    ("crawl_ts_utc", pa.string()),
    ("event_url", pa.string()),
    ("lowest_price_cents", pa.int64()),
    ("average_price_cents", pa.int64()),
    ("highest_price_cents", pa.int64()),
    ("inventory_count", pa.int64()),
    ("lowest_price_includes_fees", pa.bool_()),
    ("listing_quality_label", pa.string()),
    ("price_refresh_ts_utc", pa.string()),
    ("timestamp_imported", pa.string()),
])

LISTINGS_SCHEMA = pa.schema([
    ("source", pa.string()),
    ("event_id_external", pa.string()),
    ("crawl_ts_utc", pa.string()),
    ("listing_price_cents", pa.int64()),
    ("section", pa.string()),
    ("row", pa.string()),
    ("deal_score", pa.float64()),
    ("deal_label", pa.string()),
    ("notes", pa.string()),
    ("timestamp_imported", pa.string()),
])

SCHEMAS: dict[str, pa.Schema] = {
    "events": EVENTS_SCHEMA,
    "market_snapshots": MARKET_SNAPSHOTS_SCHEMA,
    "listings": LISTINGS_SCHEMA,
}

DATASETS = tuple(SCHEMAS)


def align(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Align a frame to the frozen schema: add missing, drop extras, cast.

    Name-based (never positional) so a parser adding a field cannot silently
    shift values into the wrong column.
    """
    schema = SCHEMAS[dataset]
    df = df.copy()
    for field in schema:
        if field.name not in df.columns:
            df[field.name] = None
    df = df[[field.name for field in schema]]
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    return table.to_pandas()


def events_frame(events: list[Event], timestamp_imported: str) -> pd.DataFrame:
    rows = [{**asdict(e), "timestamp_imported": timestamp_imported} for e in events]
    return align(pd.DataFrame(rows), "events")


def snapshots_frame(snapshots: list[MarketSnapshot], timestamp_imported: str) -> pd.DataFrame:
    rows = [
        {k: v for k, v in asdict(s).items() if k != "raw_snapshot_path"} | {"timestamp_imported": timestamp_imported}
        for s in snapshots
    ]
    return align(pd.DataFrame(rows), "market_snapshots")


def listings_frame(listings: list[Listing], timestamp_imported: str) -> pd.DataFrame:
    rows = [{**asdict(x), "timestamp_imported": timestamp_imported} for x in listings]
    return align(pd.DataFrame(rows), "listings")
