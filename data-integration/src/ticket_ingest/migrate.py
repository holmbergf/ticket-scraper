"""Import a SQLite database into the partitioned Parquet raw zone.

Reads the ``events`` / ``market_snapshots`` / ``listings`` tables, drops
SQLite-only columns (autoincrement ``id``, ``raw_snapshot_path``), aligns
to the frozen raw schemas, and lands everything through the same
content-addressed ``write_dataset`` path as a live crawl — imported rows
are indistinguishable from crawled data, and re-running the import is a
no-op. Run via ``ticket-ingest migrate-sqlite <path>``.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from .clean import EVENTS_NATURAL_KEY, LISTINGS_NATURAL_KEY, SNAPSHOTS_NATURAL_KEY, dedupe
from .models import utc_now_iso
from .schemas import align
from .storage import LocalStorage, write_dataset

log = logging.getLogger(__name__)

_TABLES = {
    "events": EVENTS_NATURAL_KEY,
    "market_snapshots": SNAPSHOTS_NATURAL_KEY,
    "listings": LISTINGS_NATURAL_KEY,
}
_DROP = {"id", "raw_snapshot_path"}


def migrate_sqlite(db_path: Path, storage: LocalStorage) -> dict[str, int]:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    imported = utc_now_iso()
    counts: dict[str, int] = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for dataset, natural_key in _TABLES.items():
            # ORDER BY id: a crawl can store discovery + event-page
            # snapshots under one crawl_ts, with the event-page row
            # authoritative ("latest insert wins"). Natural-key dedupe
            # with keep="last" over id order keeps exactly that row.
            order = " ORDER BY id" if dataset != "events" else ""
            df = pd.read_sql_query(f"SELECT * FROM {dataset}{order}", con)
            df = df.drop(columns=[c for c in df.columns if c in _DROP])
            df["timestamp_imported"] = imported
            if dataset == "market_snapshots" and "lowest_price_includes_fees" in df.columns:
                df["lowest_price_includes_fees"] = df["lowest_price_includes_fees"].map(
                    lambda v: None if pd.isna(v) else bool(v))
            df = dedupe(align(df, dataset), natural_key)
            result = write_dataset(storage, df, dataset, source=f"sqlite-migration:{db_path.name}")
            counts[dataset] = result.rows
            log.info("migrated %s: %d rows -> %d new files", dataset, result.rows, len(result.keys))
    finally:
        con.close()
    return counts
