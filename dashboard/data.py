"""Warehouse access for the dashboard.

Reads the published Parquet exports (``data_warehouse/``) with DuckDB —
never the raw zone. The exports are committed to this repo (serving set)
or bundled by ``export_standalone.sh``, so the app needs no credentials.
``WAREHOUSE_DIR`` (or ``LOCAL_WAREHOUSE_DIR``, pointing at a dir containing
``data_warehouse/``) overrides the default repo location.

Source-subset views (best price across the *selected* sources, filtered
benchmarks/price changes) are computed at read time from the published
semantic tables.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

TABLES = {
    "match_prices": "semantic/semantic_match_prices.parquet",
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


def _source_filter(sources: list[str] | tuple[str, ...] | None, col: str = "source") -> tuple[str, list]:
    if not sources:
        return "", []
    placeholders = ", ".join("?" for _ in sources)
    return f"{col} IN ({placeholders})", list(sources)


def sources() -> list[str]:
    return sorted(load("source_overview")["source"].tolist())


def cities() -> list[str]:
    return sorted(c for c in load("match_prices")["city"].dropna().unique().tolist() if c)


def teams() -> list[str]:
    df = load("match_prices")
    return sorted(t for t in pd.concat([df["team_1"], df["team_2"]]).dropna().unique().tolist()
                  if t and t != "TBD")


def crawl_timestamps() -> list[str]:
    df = _con().execute(
        f"SELECT DISTINCT crawl_ts_utc FROM read_parquet('{_path('price_trends')}') ORDER BY 1").df()
    return df["crawl_ts_utc"].astype(str).tolist()


def match_prices(sources=None, stage=None, city=None, team=None) -> pd.DataFrame:
    """One row per match; best/worst recomputed over the selected sources."""
    sf, params = _source_filter(sources, "sp.source")
    where = f"WHERE sp.lowest_price IS NOT NULL AND sp.match_number IS NOT NULL"
    if sf:
        where += f" AND {sf}"
    sql = f"""
        WITH dim AS (
            SELECT match_number, match_key, display_name, stage, team_1, team_2,
                   event_start_local, match_date, venue_name, city, country, sources_tracking
            FROM read_parquet('{_path('match_prices')}')
        ),
        priced AS (
            SELECT * FROM read_parquet('{_path('source_prices')}') sp {where}
        ),
        agg AS (
            SELECT match_number, MIN(lowest_price) AS best_price, MAX(lowest_price) AS worst_price,
                   COUNT(*) AS sources_with_price, SUM(inventory_count) AS total_inventory,
                   MAX(crawl_ts_utc) AS latest_crawl_ts_utc
            FROM priced GROUP BY 1
        ),
        best AS (
            SELECT match_number, source AS best_source FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY match_number ORDER BY lowest_price, source) AS rn
                FROM priced
            ) WHERE rn = 1
        )
        SELECT d.*, a.best_price, b.best_source, a.worst_price,
               CASE WHEN a.sources_with_price >= 2 THEN a.worst_price - a.best_price END AS savings_vs_worst,
               a.sources_with_price, a.total_inventory, a.latest_crawl_ts_utc
        FROM dim d
        LEFT JOIN agg a USING (match_number)
        LEFT JOIN best b USING (match_number)
    """
    df = _con().execute(sql, params).df()
    # With a source subset, matches no selected source prices drop out.
    if sources:
        df = df[df["sources_with_price"].notna()]
    if stage:
        df = df[df["stage"] == stage]
    if city:
        df = df[df["city"] == city]
    if team:
        df = df[(df["team_1"] == team) | (df["team_2"] == team)]
    return df.sort_values(["event_start_local", "match_number"]).reset_index(drop=True)


def source_prices(sources=None) -> pd.DataFrame:
    df = load("source_prices")
    return df[df["source"].isin(sources)] if sources else df


def source_overview(sources=None) -> pd.DataFrame:
    """Per-source overview recomputed on the selected sources' latest prices."""
    priced = source_prices(sources)
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
    return pd.DataFrame(rows).sort_values("source").reset_index(drop=True)


def market_trends(sources=None) -> pd.DataFrame:
    """Daily benchmarks over the selected sources (daily best per match)."""
    sf, params = _source_filter(sources)
    where = "WHERE lowest_price IS NOT NULL AND match_number IS NOT NULL"
    if sf:
        where += f" AND {sf}"
    return _con().execute(f"""
        WITH daily_best AS (
            SELECT crawl_date, match_number, MIN(lowest_price) AS best_price,
                   SUM(inventory_count) AS total_inventory
            FROM read_parquet('{_path('price_trends')}') {where}
            GROUP BY 1, 2
        )
        SELECT crawl_date, MIN(best_price) AS min_price, MEDIAN(best_price) AS median_price,
               ROUND(AVG(best_price), 2) AS avg_price, MAX(best_price) AS max_price,
               COUNT(*) AS total_events, SUM(total_inventory) AS total_inventory
        FROM daily_best GROUP BY 1 ORDER BY 1
    """, params).df()


def price_changes(sources=None) -> pd.DataFrame:
    """First vs latest daily-best price per match, over the selected sources."""
    sf, params = _source_filter(sources)
    where = "WHERE lowest_price IS NOT NULL AND match_number IS NOT NULL"
    if sf:
        where += f" AND {sf}"
    return _con().execute(f"""
        WITH daily_best AS (
            SELECT crawl_date, match_number, match_key, MIN(lowest_price) AS best_price
            FROM read_parquet('{_path('price_trends')}') {where}
            GROUP BY 1, 2, 3
        ),
        bounds AS (SELECT match_number, MIN(crawl_date) AS fd, MAX(crawl_date) AS ld FROM daily_best GROUP BY 1)
        SELECT f.match_key, b.match_number, f.best_price AS first_price, l.best_price AS latest_price,
               ROUND(l.best_price - f.best_price, 2) AS change_dollars,
               CASE WHEN f.best_price > 0 THEN ROUND((l.best_price - f.best_price) * 100.0 / f.best_price, 1) ELSE 0 END AS change_pct
        FROM bounds b
        JOIN daily_best f ON f.match_number = b.match_number AND f.crawl_date = b.fd
        JOIN daily_best l ON l.match_number = b.match_number AND l.crawl_date = b.ld
    """, params).df()


def price_trends(source: str, event_id_external: str) -> pd.DataFrame:
    df = load("price_trends")
    return (df[(df["source"] == source) & (df["event_id_external"] == event_id_external)]
            .sort_values("crawl_ts_utc").reset_index(drop=True))


def match_sparklines(sources=None) -> pd.DataFrame:
    """Per-match daily best-price series (for inline table sparklines)."""
    sf, params = _source_filter(sources)
    where = "WHERE lowest_price IS NOT NULL AND match_number IS NOT NULL"
    if sf:
        where += f" AND {sf}"
    daily = _con().execute(f"""
        SELECT match_number, crawl_date, MIN(lowest_price) AS best_price
        FROM read_parquet('{_path('price_trends')}') {where}
        GROUP BY 1, 2 ORDER BY 1, 2
    """, params).df()
    return (daily.groupby("match_number")["best_price"]
            .apply(lambda s: [float(v) for v in s]).rename("trend").reset_index())


def daily_best(match_number: int, sources=None) -> pd.DataFrame:
    """Daily best-across-sources price series for one match."""
    sf, params = _source_filter(sources)
    where = "WHERE lowest_price IS NOT NULL AND match_number = ?"
    if sf:
        where += f" AND {sf}"
    return _con().execute(f"""
        SELECT crawl_date, MIN(lowest_price) AS best_price,
               ARG_MIN(source, lowest_price) AS best_source, SUM(inventory_count) AS total_inventory
        FROM read_parquet('{_path('price_trends')}') {where}
        GROUP BY 1 ORDER BY 1
    """, [int(match_number)] + params).df()


def listing_distribution(source: str, event_id_external: str) -> pd.DataFrame:
    df = load("listings_latest")
    out = df[(df["source"] == source) & (df["event_id_external"] == event_id_external)].copy()
    out["price"] = (out["listing_price_cents"] / 100.0).round(2)
    return out.sort_values("listing_price_cents").reset_index(drop=True)
