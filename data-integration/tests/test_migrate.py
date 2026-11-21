"""Legacy SQLite -> Parquet migration preserves rows and is idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ticket_ingest.migrate import migrate_sqlite
from ticket_ingest.storage import LocalStorage


def _legacy_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE events (source TEXT, event_id_external TEXT, event_url TEXT,
            event_name TEXT, match_number INTEGER, stage TEXT, team_1 TEXT, team_2 TEXT,
            event_start_local TEXT, venue_name TEXT, city TEXT, region TEXT, country TEXT, currency TEXT);
        CREATE TABLE market_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
            event_id_external TEXT, crawl_ts_utc TEXT, event_url TEXT, lowest_price_cents INTEGER,
            average_price_cents INTEGER, highest_price_cents INTEGER, inventory_count INTEGER,
            lowest_price_includes_fees INTEGER, listing_quality_label TEXT,
            price_refresh_ts_utc TEXT, raw_snapshot_path TEXT);
        CREATE TABLE listings (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
            event_id_external TEXT, crawl_ts_utc TEXT, listing_price_cents INTEGER,
            section TEXT, row TEXT, deal_score REAL, deal_label TEXT, notes TEXT);
        """
    )
    con.execute("INSERT INTO events VALUES ('vivid','1','https://x/1','A vs B',1,'Final','A','B','2026-07-19T15:00:00','MetLife','East Rutherford',NULL,'US','USD')")
    con.execute("INSERT INTO market_snapshots (source,event_id_external,crawl_ts_utc,event_url,lowest_price_cents,lowest_price_includes_fees,raw_snapshot_path) VALUES ('vivid','1','2026-05-02T09:05:10Z','https://x/1',123450,1,'data/raw/x.html')")
    con.execute("INSERT INTO listings (source,event_id_external,crawl_ts_utc,listing_price_cents,section) VALUES ('vivid','1','2026-05-02T09:05:10Z',150000,'Lower 114')")
    con.commit()
    con.close()


def test_migration_roundtrip(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _legacy_db(db)
    storage = LocalStorage(tmp_path / "data")
    counts = migrate_sqlite(db, storage)
    assert counts == {"events": 1, "market_snapshots": 1, "listings": 1}

    import duckdb

    con = duckdb.connect()
    row = con.execute(
        f"SELECT lowest_price_cents, lowest_price_includes_fees FROM read_parquet('{tmp_path}/data/raw/market_snapshots/**/*.parquet')"
    ).fetchone()
    assert row == (123450, True)  # integer cents preserved; SQLite 0/1 -> bool

    # Re-running the migration writes zero new files.
    before = sorted(p.name for p in (tmp_path / "data/raw").rglob("*.parquet"))
    migrate_sqlite(db, storage)
    after = sorted(p.name for p in (tmp_path / "data/raw").rglob("*.parquet"))
    assert before == after
