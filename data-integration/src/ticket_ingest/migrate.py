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


def migrate_sqlite(db_path: Path, storage: LocalStorage,
                   collection_slug: str = "fifa-world-cup-2026") -> dict[str, int]:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    imported = utc_now_iso()
    counts: dict[str, int] = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # Map source events to canonical keys from the events table so
        # snapshots/listings land already stamped with identity.
        key_map: dict[tuple[str, str], str] = {}
        try:
            ev = pd.read_sql_query(
                "SELECT source, event_id_external, match_number FROM events", con)
            for _, r in ev.iterrows():
                key_map[(str(r["source"]), str(r["event_id_external"]))] = (
                    f"match-{int(r['match_number'])}" if pd.notna(r["match_number"])
                    else f"{r['source']}-{r['event_id_external']}")
        except Exception:
            pass
        for dataset, natural_key in _TABLES.items():
            # ORDER BY id: a crawl can store discovery + event-page
            # snapshots under one crawl_ts, with the event-page row
            # authoritative ("latest insert wins"). Natural-key dedupe
            # with keep="last" over id order keeps exactly that row.
            order = " ORDER BY id" if dataset != "events" else ""
            df = pd.read_sql_query(f"SELECT * FROM {dataset}{order}", con)
            df = df.drop(columns=[c for c in df.columns if c in _DROP])
            df["timestamp_imported"] = imported
            if "collection_slug" not in df.columns:
                df["collection_slug"] = collection_slug
            if "event_key" not in df.columns:
                df["event_key"] = [
                    key_map.get((str(s), str(e)))
                    for s, e in zip(df.get("source", []), df.get("event_id_external", []))
                ]
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
