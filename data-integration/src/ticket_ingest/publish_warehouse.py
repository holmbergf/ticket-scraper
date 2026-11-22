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

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .collections import CollectionConfig, list_collections
from .config import REPO_ROOT, Settings

log = logging.getLogger(__name__)

# dbt model name -> (layer, published table name)
MODELS: dict[str, tuple[str, str]] = {
    "clean_tickets_events": ("silver", "clean_tickets_events"),
    "clean_tickets_market_snapshots": ("silver", "clean_tickets_market_snapshots"),
    "clean_tickets_listings": ("silver", "clean_tickets_listings"),
    "dim_tickets_events": ("silver", "dim_tickets_events"),
    "fct_tickets_market_snapshots": ("silver", "fct_tickets_market_snapshots"),
    "fct_tickets_latest_prices": ("silver", "fct_tickets_latest_prices"),
    "fct_tickets_listings_latest": ("silver", "fct_tickets_listings_latest"),
    "analytics_tickets_market_benchmarks": ("gold", "analytics_tickets_market_benchmarks"),
    "analytics_tickets_source_overviews": ("gold", "analytics_tickets_source_overviews"),
    "analytics_tickets_price_changes": ("gold", "analytics_tickets_price_changes"),
    "semantic_event_prices": ("semantic", "semantic_event_prices"),
    "semantic_source_prices": ("semantic", "semantic_source_prices"),
    "semantic_price_trends": ("semantic", "semantic_price_trends"),
    "semantic_market_trends": ("semantic", "semantic_market_trends"),
    "semantic_source_overview": ("semantic", "semantic_source_overview"),
}


_STALE_OUTPUTS = (
    "semantic/semantic_match_prices.parquet",
    "silver/dim_tickets_matches.parquet",
)


def _catalog_display_name(ev) -> str:
    if ev.name:
        return ev.name
    if ev.participant_1 and ev.participant_2:
        base = f"{ev.participant_1} vs {ev.participant_2}"
        return f"{base} ({ev.stage})" if ev.stage else base
    if ev.stage and ev.city:
        return f"{ev.stage} — {ev.city}"
    return ev.key


def build_catalog_frames(
    configs: list[CollectionConfig],
    dim: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collection + canonical-event catalogs for dashboard navigation.

    Config-declared events appear even before their first crawl; warehouse
    dimension rows win where both exist.
    """
    dim = dim.copy() if dim is not None else pd.DataFrame()
    prices = prices.copy() if prices is not None else pd.DataFrame()
    event_rows: dict[tuple[str, str], dict] = {}

    for c in configs:
        for ev in c.events:
            event_rows[(c.slug, ev.key)] = {
                "collection_slug": c.slug,
                "event_key": ev.key,
                "event_uid": f"{c.slug}:{ev.key}",
                "display_name": _catalog_display_name(ev),
                "event_name": ev.name,
                "stage": ev.stage,
                "sequence": ev.sequence,
                "match_number": ev.sequence,
                "participant_1": ev.participant_1,
                "participant_2": ev.participant_2,
                "team_1": ev.participant_1,
                "team_2": ev.participant_2,
                "event_start_local": ev.starts_at_local,
                "venue_name": ev.venue_name,
                "city": ev.city,
                "region": ev.region,
                "country": ev.country,
                "sources_tracking": 0,
                "has_warehouse_data": False,
            }
    if not dim.empty:
        for _, r in dim.iterrows():
            key = (str(r["collection_slug"]), str(r["event_key"]))
            row = event_rows.get(key, {})
            row.update({
                "collection_slug": key[0], "event_key": key[1],
                "event_uid": r.get("event_uid") or f"{key[0]}:{key[1]}",
                "display_name": r.get("display_name"),
                "event_name": row.get("event_name"),
                "stage": r.get("stage"),
                "sequence": r.get("match_number"),
                "match_number": r.get("match_number"),
                "participant_1": r.get("participant_1") if "participant_1" in dim.columns else r.get("team_1"),
                "participant_2": r.get("participant_2") if "participant_2" in dim.columns else r.get("team_2"),
                "team_1": r.get("team_1"), "team_2": r.get("team_2"),
                "event_start_local": r.get("event_start_local"),
                "venue_name": r.get("venue_name"), "city": r.get("city"),
                "region": row.get("region"), "country": r.get("country"),
                "sources_tracking": int(r.get("sources_tracking") or 0),
                "has_warehouse_data": True,
            })
            event_rows[key] = row

    events = pd.DataFrame(
        list(event_rows.values()),
        columns=["collection_slug", "event_key", "event_uid", "display_name",
                 "event_name", "stage", "sequence", "match_number",
                 "participant_1", "participant_2", "team_1", "team_2",
                 "event_start_local", "venue_name", "city", "region",
                 "country", "sources_tracking", "has_warehouse_data"],
    )
    if not events.empty:
        # Keep starts as ISO strings uniformly: config rows carry strings
        # (some with UTC offsets) while warehouse rows carry timestamps;
        # a mixed object column would publish as epoch integers.
        def _iso(value):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            parsed = pd.to_datetime(value, errors="coerce")
            return parsed.isoformat() if pd.notna(parsed) else str(value)

        events["event_start_local"] = events["event_start_local"].map(_iso)
        events["event_date"] = pd.to_datetime(events["event_start_local"], errors="coerce", utc=True)
        events = events.sort_values(
            ["collection_slug", "event_date", "sequence", "display_name"],
            na_position="last").reset_index(drop=True)
        events["event_date"] = events["event_date"].dt.date

    priced = prices[prices["best_price"].notna()] if "best_price" in prices.columns else prices
    collection_rows = []
    for c in configs:
        evs = events[events["collection_slug"] == c.slug] if not events.empty else events
        pr = priced[priced["collection_slug"] == c.slug] if "collection_slug" in priced.columns else priced.iloc[0:0]
        collection_rows.append({
            "collection_slug": c.slug,
            "title": c.title,
            "kind": c.kind,
            "status": c.status,
            "description": c.description,
            "timezone": c.timezone,
            "icon": c.icon,
            "accent_color": c.accent_color,
            "configured_events": len(c.events),
            "warehouse_events": int(evs["has_warehouse_data"].sum()) if len(evs) else 0,
            "event_count": len(evs),
            "priced_events": len(pr),
            "first_event_start": evs["event_start_local"].min() if len(evs) else None,
            "last_event_start": evs["event_start_local"].max() if len(evs) else None,
            "latest_crawl_ts_utc": pr["latest_crawl_ts_utc"].max() if len(pr) else None,
            "cheapest_price": float(pr["best_price"].min()) if len(pr) else None,
        })
    return pd.DataFrame(collection_rows), events


def publish(db_path: Path, warehouse_dir: Path | None = None,
            settings: Settings | None = None) -> dict[str, int]:
    import duckdb

    settings = settings or Settings.from_env()
    out_root = Path(warehouse_dir) if warehouse_dir else settings.warehouse_dir
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
            rel = con.execute(f'SELECT * FROM "{model}" ORDER BY ALL')
            # DuckDB renamed fetch_arrow_table() to to_arrow_table().
            arrow = rel.to_arrow_table() if hasattr(rel, "to_arrow_table") else rel.fetch_arrow_table()
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

        # Catalog tables drive the dashboard collection switcher. They are built
        # from the same DuckDB build plus collection TOML files, so a
        # configured collection/event appears even before its first crawl.
        dim = con.execute('SELECT * FROM "dim_tickets_events"').df()
        prices = con.execute('SELECT * FROM "semantic_event_prices"').df()
        try:
            configs = list_collections(settings)
        except FileNotFoundError:
            configs = []
        collections_df, events_df = build_catalog_frames(configs, dim, prices)
        for name, frame in (
            ("semantic_collections", collections_df),
            ("semantic_event_catalog", events_df),
        ):
            dest = out_root / "semantic" / f"{name}.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(frame, preserve_index=False)
            table = table.cast(pa.schema([
                pa.field(f.name, pa.string() if pa.types.is_null(f.type) else f.type)
                for f in table.schema
            ]))
            pq.write_table(table, dest, compression="zstd")
            counts[name] = len(frame)
            log.info("published semantic/%s: %d rows", name, len(frame))

        for stale in _STALE_OUTPUTS:
            p = out_root / stale
            if p.exists():
                p.unlink()
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
