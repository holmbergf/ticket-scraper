"""Dashboard data-layer tests against synthetic published exports.

No warehouse, network, or Streamlit runtime needed: the fixture writes the
serving-set Parquet files data.py reads and points WAREHOUSE_DIR at them.
Two collections share match_number=1 to prove collection isolation.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

COLL = "test-cup"
OTHER = "other-cup"
UID = f"{COLL}:a-vs-b"


def _event(collection=COLL, key="a-vs-b", name="A vs B (Final)"):
    return {
        "collection_slug": collection, "event_key": key, "event_uid": f"{collection}:{key}",
        "match_number": 1, "match_key": f"{collection}:{key}", "display_name": name,
        "stage": "Final", "team_1": "A", "team_2": "B",
        "participant_1": "A", "participant_2": "B",
        "event_start_local": pd.Timestamp("2026-07-19 15:00"),
        "event_date": pd.Timestamp("2026-07-19").date(),
        "match_date": pd.Timestamp("2026-07-19").date(),
        "venue_name": "MetLife", "city": "New York/New Jersey", "country": "United States",
    }


@pytest.fixture()
def warehouse(tmp_path, monkeypatch):
    root = tmp_path / "data_warehouse"
    (root / "semantic").mkdir(parents=True)
    (root / "gold").mkdir()
    (root / "silver").mkdir()
    pd.DataFrame([
        {"collection_slug": COLL, "title": "Test Cup", "kind": "tournament", "status": "active",
         "description": "", "timezone": "UTC", "icon": "T", "accent_color": "#000",
         "configured_events": 0, "warehouse_events": 1, "event_count": 1, "priced_events": 1,
         "cheapest_price": 100.0},
        {"collection_slug": OTHER, "title": "Other Cup", "kind": "game", "status": "active",
         "description": "", "timezone": "UTC", "icon": "T", "accent_color": "#000",
         "configured_events": 1, "warehouse_events": 1, "event_count": 1, "priced_events": 1,
         "cheapest_price": 50.0},
    ]).to_parquet(root / "semantic/semantic_collections.parquet", index=False)
    catalog = pd.DataFrame([
        {**_event(), "has_warehouse_data": True, "sources_tracking": 2},
        {**_event(OTHER, "c-vs-d", "C vs D"), "has_warehouse_data": True, "sources_tracking": 1},
    ])
    catalog.to_parquet(root / "semantic/semantic_event_catalog.parquet", index=False)
    pd.DataFrame([
        {**_event(), "sources_tracking": 2, "sources_with_price": 2, "best_price": 100.0,
         "best_source": "vivid", "worst_price": 150.0, "savings_vs_worst": 50.0,
         "total_inventory": 10, "latest_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
        {**_event(OTHER, "c-vs-d", "C vs D"), "sources_tracking": 1, "sources_with_price": 1,
         "best_price": 50.0, "best_source": "vivid", "worst_price": 50.0,
         "savings_vs_worst": None, "total_inventory": 3,
         "latest_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
    ]).to_parquet(root / "semantic/semantic_event_prices.parquet", index=False)

    def source_row(source, ext, low, coll=COLL, key="a-vs-b", name="A vs B (Final)"):
        base = _event(coll, key, name)
        return {"collection_slug": coll, "event_key": key, "event_uid": f"{coll}:{key}",
                "source": source, "event_id_external": ext, "event_url": "u",
                "display_name": name, "match_number": 1, "match_key": f"{coll}:{key}",
                "stage": "Final", "team_1": "A", "team_2": "B",
                "event_start_local": base["event_start_local"], "venue_name": "MetLife",
                "city": "New York/New Jersey", "country": "United States", "currency": "USD",
                "lowest_price": low, "average_price": low + 100, "highest_price": low + 200,
                "inventory_count": 4, "lowest_price_includes_fees": True,
                "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")}

    pd.DataFrame([
        source_row("vivid", "e1", 100.0),
        source_row("gametime", "e2", 150.0),
        source_row("vivid", "e9", 50.0, OTHER, "c-vs-d", "C vs D"),
    ]).to_parquet(root / "semantic/semantic_source_prices.parquet", index=False)

    def trend(day, price, coll=COLL, key="a-vs-b", name="A vs B (Final)"):
        return {"collection_slug": coll, "event_key": key, "event_uid": f"{coll}:{key}",
                "source": "vivid", "event_id_external": "e1", "match_number": 1,
                "match_key": f"{coll}:{key}", "display_name": name,
                "crawl_ts_utc": pd.Timestamp(day), "crawl_date": pd.Timestamp(day).date(),
                "lowest_price": price, "average_price": 200.0,
                "highest_price": 300.0, "inventory_count": 5}

    pd.DataFrame([
        trend("2026-05-01 09:00", 120.0), trend("2026-05-02 09:00", 100.0),
        trend("2026-05-02 09:00", 50.0, OTHER, "c-vs-d", "C vs D"),
    ]).to_parquet(root / "semantic/semantic_price_trends.parquet", index=False)
    pd.DataFrame([
        {"collection_slug": COLL, "source": "vivid", "total_events": 1, "events_with_price": 1,
         "min_price": 100.0, "median_price": 100.0, "avg_price": 100.0, "max_price": 100.0,
         "total_inventory": 4, "last_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
        {"collection_slug": OTHER, "source": "vivid", "total_events": 1, "events_with_price": 1,
         "min_price": 50.0, "median_price": 50.0, "avg_price": 50.0, "max_price": 50.0,
         "total_inventory": 3, "last_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
    ]).to_parquet(root / "semantic/semantic_source_overview.parquet", index=False)
    pd.DataFrame([{"x": 1}]).to_parquet(root / "semantic/semantic_market_trends.parquet", index=False)
    pd.DataFrame([{"x": 1}]).to_parquet(root / "gold/analytics_tickets_price_changes.parquet", index=False)
    pd.DataFrame([{
        "collection_slug": COLL, "event_key": "a-vs-b", "event_uid": UID,
        "source": "vivid", "event_id_external": "e1", "match_number": 1,
        "match_key": UID, "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00"),
        "crawl_date": pd.Timestamp("2026-05-02").date(), "listing_price_cents": 11000,
        "section": "Lower 114", "row": "5", "deal_score": 9.0, "deal_label": "Great",
        "notes": None, "timestamp_imported": pd.Timestamp("2026-05-02 09:05"),
    }]).to_parquet(root / "silver/fct_tickets_listings_latest.parquet", index=False)
    monkeypatch.setenv("WAREHOUSE_DIR", str(root))
    import data
    return data


def test_event_prices_recompute_and_collection_isolation(warehouse):
    df = warehouse.event_prices(COLL, ["gametime"])
    assert len(df) == 1
    assert df.iloc[0]["best_price"] == 150.0 and df.iloc[0]["best_source"] == "gametime"
    all_df = warehouse.event_prices(COLL)
    assert all_df.iloc[0]["best_price"] == 100.0
    assert set(all_df["collection_slug"]) == {COLL}


def test_market_trends_and_price_changes_from_published(warehouse):
    trends = warehouse.market_trends(COLL, ["vivid"])
    assert len(trends) == 2 and trends.iloc[-1]["min_price"] == 100.0
    changes = warehouse.price_changes(COLL, ["vivid"])
    assert changes.iloc[0]["first_price"] == 120.0 and changes.iloc[0]["latest_price"] == 100.0


def test_sparklines_and_daily_best(warehouse):
    spark = warehouse.event_sparklines(COLL, ["vivid"])
    assert spark.iloc[0]["trend"] == [120.0, 100.0]
    daily = warehouse.daily_best(UID, ["vivid"])
    assert daily["best_price"].tolist() == [120.0, 100.0]
    assert warehouse.warehouse_version()


def test_listing_distribution_dollars(warehouse):
    df = warehouse.listing_distribution(COLL, "vivid", "e1")
    assert df.iloc[0]["price"] == 110.0
