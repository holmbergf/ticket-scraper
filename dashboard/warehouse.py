"""Warehouse access for the dashboard.

Reads the published Parquet exports (``data_warehouse/``) with DuckDB —
never the raw zone. The exports are committed to this repo (serving set)
or bundled by ``export_standalone.sh``, so the app needs no credentials.
``WAREHOUSE_DIR`` (or ``LOCAL_WAREHOUSE_DIR``, pointing at a dir containing
``data_warehouse/``) overrides the default repo location.

Everything is collection-scoped: canonical events carry
``collection_slug`` + ``event_key`` (+ global ``event_uid``), and every
query filters by collection so collections never blend into one another's
benchmarks. Source-subset views are recomputed at read time from the
published semantic tables.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

TABLES = {
    "collections": "semantic/semantic_collections.parquet",
    "event_catalog": "semantic/semantic_event_catalog.parquet",
    "event_prices": "semantic/semantic_event_prices.parquet",
    "source_prices": "semantic/semantic_source_prices.parquet",
    "price_trends": "semantic/semantic_price_trends.parquet",
    "market_trends": "semantic/semantic_market_trends.parquet",
    "source_overview": "semantic/semantic_source_overview.parquet",
    "price_changes": "gold/analytics_tickets_price_changes.parquet",
    "listings_latest": "silver/fct_tickets_listings_latest.parquet",
}

_REPO_ROOT = Path(__file__).resolve().parents[1]


def warehouse_dir() -> Path:
    if os.getenv("WAREHOUSE_DIR"):
        return Path(os.environ["WAREHOUSE_DIR"])
    if os.getenv("LOCAL_WAREHOUSE_DIR"):
        return Path(os.environ["LOCAL_WAREHOUSE_DIR"]) / "data_warehouse"
    # Standalone export layout (data_warehouse/ next to the app), else repo layout.
    bundled = Path(__file__).resolve().parent / "data_warehouse"
    return bundled if bundled.exists() else _REPO_ROOT / "data" / "data_warehouse"


def warehouse_version() -> str:
    """Content stamp of the published warehouse (mtime+size per serving file).

    Every publish rewrites these files, so the stamp changes whenever new
    data lands. The app passes it as an explicit argument to its cached
    loaders, which means long-lived caches can never keep showing
    pre-publish prices after a publish.
    """
    parts = []
    for rel in TABLES.values():
        p = warehouse_dir() / rel
        try:
            s = p.stat()
            parts.append(f"{rel}:{s.st_mtime_ns}:{s.st_size}")
        except OSError:
            parts.append(f"{rel}:missing")
    return "|".join(parts)


def _path(table: str) -> Path:
    p = warehouse_dir() / TABLES[table]
    if not p.exists():
        raise FileNotFoundError(
            f"Published table not found: {p}. Build it with "
            "`dbt build --target prod` + `python -m ticket_ingest.publish_warehouse`, "
            "or set WAREHOUSE_DIR.")
    return p


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def load(table: str) -> pd.DataFrame:
    return _con().execute(f"SELECT * FROM read_parquet('{_path(table)}')").df()


def _filter(values, col: str) -> tuple[str, list]:
    if values is None:
        return "", []
    vals = [values] if isinstance(values, str) else list(values)
    if not vals:
        return "", []
    return f"{col} IN ({', '.join('?' for _ in vals)})", vals


def collections() -> pd.DataFrame:
    """Published collection registry (drives dashboard page generation)."""
    try:
        return load("collections")
    except FileNotFoundError:
        # Older publish without catalog tables: derive from event prices.
        ep = load("event_prices")
        rows = []
        for slug, g in ep.groupby("collection_slug"):
            rows.append({
                "collection_slug": slug, "title": slug, "kind": "event",
                "status": "active", "description": "", "timezone": "UTC",
                "icon": "🎟️", "accent_color": "#3aa76d",
                "configured_events": 0, "warehouse_events": len(g),
                "event_count": len(g),
                "priced_events": int(g["best_price"].notna().sum()),
                "cheapest_price": g["best_price"].min(),
            })
        return pd.DataFrame(rows)


def event_catalog(collection: str | None = None) -> pd.DataFrame:
    df = load("event_catalog")
    return df[df["collection_slug"] == collection].reset_index(drop=True) if collection else df


def sources(collection: str | None = None) -> list[str]:
    df = load("source_overview")
    if collection and "collection_slug" in df.columns:
        df = df[df["collection_slug"] == collection]
    return sorted(df["source"].dropna().unique().tolist())


def cities(collection: str | None = None) -> list[str]:
    df = load("event_prices")
    if collection:
        df = df[df["collection_slug"] == collection]
    return sorted(c for c in df["city"].dropna().unique().tolist() if c)


def participants(collection: str | None = None) -> list[str]:
    df = load("event_prices")
    if collection:
        df = df[df["collection_slug"] == collection]
    cols = [c for c in ("participant_1", "participant_2", "team_1", "team_2") if c in df.columns]
    vals = pd.concat([df[c] for c in cols]) if cols else pd.Series(dtype=object)
    return sorted(t for t in vals.dropna().unique().tolist() if t and t != "TBD")


def teams(collection: str | None = None) -> list[str]:
    return participants(collection)


def stages(collection: str | None = None) -> list[str]:
    df = load("event_prices")
    if collection:
        df = df[df["collection_slug"] == collection]
    return sorted(s for s in df["stage"].dropna().unique().tolist() if s)


def crawl_timestamps(collection: str | None = None) -> list[str]:
    cf, params = _filter(collection, "collection_slug")
    where = f"WHERE {cf}" if cf else ""
    df = _con().execute(
        f"SELECT DISTINCT crawl_ts_utc FROM read_parquet('{_path('price_trends')}') {where} ORDER BY 1",
        params).df()
    return df["crawl_ts_utc"].astype(str).tolist()


def event_prices(collection: str | None = None, sources=None,
                 stage=None, city=None, participant=None) -> pd.DataFrame:
    """One row per canonical event; best/worst over the selected sources."""
    sf, sparams = _filter(sources, "sp.source")
    cf, cparams = _filter(collection, "sp.collection_slug")
    clauses = ["sp.lowest_price IS NOT NULL", "sp.event_key IS NOT NULL"]
    if sf:
        clauses.append(sf)
    if cf:
        clauses.append(cf)
    where = "WHERE " + " AND ".join(clauses)
    sql = f"""
        WITH dim AS (
            SELECT collection_slug, event_key, event_uid, match_number, match_key,
                   display_name, stage, team_1, team_2, participant_1, participant_2,
                   event_start_local, event_date, match_date, venue_name, city,
                   country, sources_tracking
            FROM read_parquet('{_path('event_prices')}')
        ),
        priced AS (
            SELECT * FROM read_parquet('{_path('source_prices')}') sp {where}
        ),
        agg AS (
            SELECT collection_slug, event_uid, MIN(lowest_price) AS best_price,
                   MAX(lowest_price) AS worst_price, COUNT(*) AS sources_with_price,
                   SUM(inventory_count) AS total_inventory, MAX(crawl_ts_utc) AS latest_crawl_ts_utc
            FROM priced GROUP BY 1, 2
        ),
        best AS (
            SELECT collection_slug, event_uid, source AS best_source FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY collection_slug, event_uid
                                             ORDER BY lowest_price, source) AS rn
                FROM priced
            ) WHERE rn = 1
        )
        SELECT d.*, a.best_price, b.best_source, a.worst_price,
               CASE WHEN a.sources_with_price >= 2 THEN a.worst_price - a.best_price END AS savings_vs_worst,
               a.sources_with_price, a.total_inventory, a.latest_crawl_ts_utc
        FROM dim d
        LEFT JOIN agg a USING (collection_slug, event_uid)
        LEFT JOIN best b USING (collection_slug, event_uid)
    """
    df = _con().execute(sql, sparams + cparams).df()
    if collection:
        df = df[df["collection_slug"] == collection]
    if sources:
        df = df[df["sources_with_price"].notna()]
    if stage:
        df = df[df["stage"] == stage]
    if city:
        df = df[df["city"] == city]
    if participant:
        df = df[(df["team_1"] == participant) | (df["team_2"] == participant)
                | (df["participant_1"] == participant) | (df["participant_2"] == participant)]
    return df.sort_values(["event_start_local", "event_uid"]).reset_index(drop=True)


def source_prices(collection: str | None = None, sources=None) -> pd.DataFrame:
    df = load("source_prices")
    if collection:
        df = df[df["collection_slug"] == collection]
    return df[df["source"].isin(sources)] if sources else df


def source_overview(collection: str | None = None, sources=None) -> pd.DataFrame:
    """Per-source overview recomputed on the selected sources' latest prices."""
    priced = source_prices(collection, sources)
    rows = []
    for source, g in priced.groupby("source"):
        p = g["lowest_price"].dropna()
        rows.append({
            "source": source, "total_events": len(g), "events_with_price": len(p),
            "min_price": p.min() if len(p) else None, "median_price": p.median() if len(p) else None,
            "avg_price": round(p.mean(), 2) if len(p) else None, "max_price": p.max() if len(p) else None,
            "total_inventory": g["inventory_count"].sum(min_count=1),
            "last_crawl_ts_utc": g["crawl_ts_utc"].max(),
        })
    if not rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(rows).sort_values("source").reset_index(drop=True)


def market_trends(collection: str | None = None, sources=None) -> pd.DataFrame:
    """Daily benchmarks for one collection (daily best per canonical event)."""
    sf, sparams = _filter(sources, "source")
    cf, cparams = _filter(collection, "collection_slug")
    clauses = ["lowest_price IS NOT NULL", "event_uid IS NOT NULL"]
    if sf:
        clauses.append(sf)
    if cf:
        clauses.append(cf)
    where = "WHERE " + " AND ".join(clauses)
    return _con().execute(f"""
        WITH daily_best AS (
            SELECT collection_slug, crawl_date, event_uid, MIN(lowest_price) AS best_price,
                   SUM(inventory_count) AS total_inventory
            FROM read_parquet('{_path('price_trends')}') {where}
            GROUP BY 1, 2, 3
        )
        SELECT crawl_date, MIN(best_price) AS min_price, MEDIAN(best_price) AS median_price,
               ROUND(AVG(best_price), 2) AS avg_price, MAX(best_price) AS max_price,
               COUNT(*) AS total_events, SUM(total_inventory) AS total_inventory
        FROM daily_best GROUP BY 1 ORDER BY 1
    """, sparams + cparams).df()


def price_changes(collection: str | None = None, sources=None) -> pd.DataFrame:
    """First vs latest daily-best price per canonical event."""
    sf, sparams = _filter(sources, "source")
    cf, cparams = _filter(collection, "collection_slug")
    clauses = ["lowest_price IS NOT NULL", "event_uid IS NOT NULL"]
    if sf:
        clauses.append(sf)
    if cf:
        clauses.append(cf)
    where = "WHERE " + " AND ".join(clauses)
    return _con().execute(f"""
        WITH daily_best AS (
            SELECT collection_slug, crawl_date, event_uid, event_key, match_key,
                   match_number, MIN(lowest_price) AS best_price
            FROM read_parquet('{_path('price_trends')}') {where}
            GROUP BY 1, 2, 3, 4, 5, 6
        ),
        bounds AS (SELECT collection_slug, event_uid, MIN(crawl_date) AS fd, MAX(crawl_date) AS ld
                   FROM daily_best GROUP BY 1, 2)
        SELECT f.collection_slug, f.event_key, f.match_key, b.event_uid, f.match_number,
               f.best_price AS first_price, l.best_price AS latest_price,
               ROUND(l.best_price - f.best_price, 2) AS change_dollars,
               CASE WHEN f.best_price > 0 THEN ROUND((l.best_price - f.best_price) * 100.0 / f.best_price, 1) ELSE 0 END AS change_pct
        FROM bounds b
        JOIN daily_best f ON f.collection_slug = b.collection_slug AND f.event_uid = b.event_uid AND f.crawl_date = b.fd
        JOIN daily_best l ON l.collection_slug = b.collection_slug AND l.event_uid = b.event_uid AND l.crawl_date = b.ld
    """, sparams + cparams).df()


def price_trends(collection: str, source: str, event_id_external: str) -> pd.DataFrame:
    df = load("price_trends")
    return (df[(df["collection_slug"] == collection) & (df["source"] == source)
               & (df["event_id_external"] == event_id_external)]
            .sort_values("crawl_ts_utc").reset_index(drop=True))


def event_sparklines(collection: str | None = None, sources=None) -> pd.DataFrame:
    """Per-event daily best-price series (for inline table sparklines)."""
    sf, sparams = _filter(sources, "source")
    cf, cparams = _filter(collection, "collection_slug")
    clauses = ["lowest_price IS NOT NULL", "event_uid IS NOT NULL"]
    if sf:
        clauses.append(sf)
    if cf:
        clauses.append(cf)
    where = "WHERE " + " AND ".join(clauses)
    daily = _con().execute(f"""
        SELECT collection_slug, event_uid, crawl_date, MIN(lowest_price) AS best_price
        FROM read_parquet('{_path('price_trends')}') {where}
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
    """, sparams + cparams).df()
    if daily.empty:
        return daily.assign(trend=pd.Series(dtype=object))
    return (daily.groupby(["collection_slug", "event_uid"])["best_price"]
            .apply(lambda s: [float(v) for v in s]).rename("trend").reset_index())


def daily_best(event_uid: str, sources=None) -> pd.DataFrame:
    """Daily best-across-sources price series for one canonical event."""
    sf, params = _filter(sources, "source")
    where = "WHERE lowest_price IS NOT NULL AND event_uid = ?"
    if sf:
        where += f" AND {sf}"
    return _con().execute(f"""
        SELECT crawl_date, MIN(lowest_price) AS best_price,
               ARG_MIN(source, lowest_price) AS best_source, SUM(inventory_count) AS total_inventory
        FROM read_parquet('{_path('price_trends')}') {where}
        GROUP BY 1 ORDER BY 1
    """, [event_uid] + params).df()


def listing_distribution(collection: str, source: str, event_id_external: str) -> pd.DataFrame:
    df = load("listings_latest")
    out = df[(df["collection_slug"] == collection) & (df["source"] == source)
             & (df["event_id_external"] == event_id_external)].copy()
    out["price"] = (out["listing_price_cents"] / 100.0).round(2)
    return out.sort_values("listing_price_cents").reset_index(drop=True)
