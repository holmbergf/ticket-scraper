"""Price-alert evaluation over the raw Parquet zone (DuckDB).

Compares the current crawl against the previous crawl per source/event,
then flags large drops, inventory collapses, and cross-market gaps.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import SnapshotDiff

log = logging.getLogger(__name__)

ALERT_THRESHOLDS = {
    "absolute_drop_cents": 10000,
    "percentage_drop": 0.10,
    "cross_market_gap": 0.15,
}

EXPECTED_EVENT_COUNTS: dict[str, int] = {
    "vivid": 80,
    "gametime": 80,
    "stubhub": 80,
    "viagogo": 80,
    "fifacollect": 90,
}


def get_snapshot_diffs(data_dir: Path, source: str, crawl_ts_utc: str, *, changed_only: bool = True) -> list[SnapshotDiff]:
    """Diff one crawl against the previous crawl, read from raw Parquet."""
    import duckdb

    snapshots_glob = str(Path(data_dir) / "raw" / "market_snapshots" / "**" / "*.parquet")
    events_glob = str(Path(data_dir) / "raw" / "events" / "**" / "*.parquet")
    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            WITH snaps AS (
                SELECT * FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                WHERE source = ?
            ),
            ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY event_id_external, crawl_ts_utc
                                          ORDER BY timestamp_imported DESC) AS rn
                FROM snaps
            ),
            current AS (SELECT * FROM ranked WHERE crawl_ts_utc = ? AND rn = 1),
            previous AS (
                SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id_external
                                                 ORDER BY crawl_ts_utc DESC) AS prn
                    FROM ranked WHERE crawl_ts_utc < ? AND rn = 1
                ) WHERE prn = 1
            ),
            events AS (
                SELECT event_id_external, ANY_VALUE(event_name) AS event_name
                FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                WHERE source = ? GROUP BY 1
            )
            SELECT c.source, c.event_id_external, e.event_name, c.event_url, c.crawl_ts_utc,
                   p.crawl_ts_utc, c.lowest_price_cents, p.lowest_price_cents,
                   c.average_price_cents, p.average_price_cents,
                   c.inventory_count, p.inventory_count
            FROM current c
            LEFT JOIN previous p USING (event_id_external)
            LEFT JOIN events e USING (event_id_external)
            ORDER BY c.event_id_external
            """,
            [snapshots_glob, source, crawl_ts_utc, crawl_ts_utc, events_glob, source],
        ).fetchall()
    except Exception as exc:  # no raw data yet (first crawl)
        log.warning("snapshot diffs unavailable for %s: %s", source, exc)
        return []
    finally:
        con.close()

    diffs: list[SnapshotDiff] = []
    for r in rows:
        diff = SnapshotDiff(
            source=r[0], event_id_external=r[1], event_name=r[2], event_url=r[3],
            crawl_ts_utc=r[4], previous_crawl_ts_utc=r[5],
            current_lowest_price_cents=r[6], previous_lowest_price_cents=r[7],
            current_average_price_cents=r[8], previous_average_price_cents=r[9],
            current_inventory_count=r[10], previous_inventory_count=r[11],
        )
        if changed_only and not diff.has_changes:
            continue
        diffs.append(diff)
    return diffs


def evaluate_alerts(source_diffs: list[tuple[str, list[SnapshotDiff]]]) -> list[str]:
    alerts: list[str] = []
    abs_threshold = ALERT_THRESHOLDS["absolute_drop_cents"]
    pct_threshold = ALERT_THRESHOLDS["percentage_drop"]

    for source, diffs in source_diffs:
        for diff in diffs:
            label = diff.event_name or diff.event_id_external
            cur, prev = diff.current_lowest_price_cents, diff.previous_lowest_price_cents
            if cur is not None and prev is not None and cur < prev:
                drop = prev - cur
                pct = drop / prev if prev > 0 else 0
                if drop >= abs_threshold:
                    alerts.append(f"[{source}] {label}: price drop ${drop / 100:,.0f} (${prev / 100:,.0f} -> ${cur / 100:,.0f})")
                elif pct >= pct_threshold:
                    alerts.append(f"[{source}] {label}: price drop {pct:.0%} (${prev / 100:,.0f} -> ${cur / 100:,.0f})")
            if diff.inventory_count_change is not None and diff.inventory_count_change < -50:
                alerts.append(
                    f"[{source}] {label}: inventory dropped by {abs(diff.inventory_count_change)} "
                    f"({diff.previous_inventory_count} -> {diff.current_inventory_count})"
                )

    lowest_by_event: dict[str, list[tuple[str, int]]] = {}
    for source, diffs in source_diffs:
        for diff in diffs:
            if diff.current_lowest_price_cents:
                lowest_by_event.setdefault(diff.event_id_external, []).append((source, diff.current_lowest_price_cents))

    gap_threshold = ALERT_THRESHOLDS["cross_market_gap"]
    for event_id, prices in lowest_by_event.items():
        if len(prices) < 2:
            continue
        prices.sort(key=lambda x: x[1])
        cheapest_source, cheapest = prices[0]
        for other_source, other_price in prices[1:]:
            gap = (other_price - cheapest) / cheapest if cheapest > 0 else 0
            if gap >= gap_threshold:
                alerts.append(
                    f"[{cheapest_source}] {event_id}: ${cheapest / 100:,.0f} is "
                    f"{gap:.0%} cheaper than {other_source} (${other_price / 100:,.0f})"
                )
                break
    return alerts
