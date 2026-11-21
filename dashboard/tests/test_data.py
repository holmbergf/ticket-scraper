"""Dashboard data-layer tests against synthetic published exports.

No warehouse, network, or Streamlit runtime needed: the fixture writes the
serving-set Parquet files data.py reads and points WAREHOUSE_DIR at them.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def warehouse(tmp_path, monkeypatch):
    root = tmp_path / "data_warehouse"
    (root / "semantic").mkdir(parents=True)
    (root / "gold").mkdir()
    (root / "silver").mkdir()
    pd.DataFrame([{
        "match_number": 1, "match_key": "match-1", "display_name": "A vs B (Final)",
        "stage": "Final", "team_1": "A", "team_2": "B",
        "event_start_local": pd.Timestamp("2026-07-19 15:00"), "match_date": pd.Timestamp("2026-07-19").date(),
        "venue_name": "MetLife", "city": "New York/New Jersey", "country": "United States",
        "sources_tracking": 2, "sources_with_price": 2, "best_price": 100.0, "best_source": "vivid",
        "worst_price": 150.0, "savings_vs_worst": 50.0, "total_inventory": 10,
        "latest_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00"),
    }]).to_parquet(root / "semantic/semantic_match_prices.parquet", index=False)
    pd.DataFrame([
        {"source": "vivid", "event_id_external": "e1", "event_url": "u", "display_name": "A vs B (Final)",
         "match_number": 1, "match_key": "match-1", "stage": "Final", "team_1": "A", "team_2": "B",
         "event_start_local": pd.Timestamp("2026-07-19 15:00"), "venue_name": "MetLife",
         "city": "New York/New Jersey", "country": "United States", "currency": "USD",
         "lowest_price": 100.0, "average_price": 200.0, "highest_price": 300.0, "inventory_count": 4,
         "lowest_price_includes_fees": True, "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
        {"source": "gametime", "event_id_external": "e2", "event_url": "u", "display_name": "A vs B (Final)",
         "match_number": 1, "match_key": "match-1", "stage": "Final", "team_1": "A", "team_2": "B",
         "event_start_local": pd.Timestamp("2026-07-19 15:00"), "venue_name": "MetLife",
         "city": "New York/New Jersey", "country": "United States", "currency": "USD",
         "lowest_price": 150.0, "average_price": 250.0, "highest_price": 350.0, "inventory_count": 6,
         "lowest_price_includes_fees": False, "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")},
    ]).to_parquet(root / "semantic/semantic_source_prices.parquet", index=False)
    pd.DataFrame([
        {"source": "vivid", "event_id_external": "e1", "match_number": 1, "match_key": "match-1",
         "display_name": "A vs B (Final)", "crawl_ts_utc": pd.Timestamp("2026-05-01 09:00"),
         "crawl_date": pd.Timestamp("2026-05-01").date(), "lowest_price": 120.0,
         "average_price": 200.0, "highest_price": 300.0, "inventory_count": 5},
        {"source": "vivid", "event_id_external": "e1", "match_number": 1, "match_key": "match-1",
         "display_name": "A vs B (Final)", "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00"),
         "crawl_date": pd.Timestamp("2026-05-02").date(), "lowest_price": 100.0,
         "average_price": 200.0, "highest_price": 300.0, "inventory_count": 4},
    ]).to_parquet(root / "semantic/semantic_price_trends.parquet", index=False)
    pd.DataFrame([{"source": "vivid", "total_events": 1, "events_with_price": 1, "min_price": 100.0,
                   "median_price": 100.0, "avg_price": 100.0, "max_price": 100.0, "total_inventory": 4,
                   "last_crawl_ts_utc": pd.Timestamp("2026-05-02 09:00")}]).to_parquet(
        root / "semantic/semantic_source_overview.parquet", index=False)
    pd.DataFrame([{"x": 1}]).to_parquet(root / "semantic/semantic_market_trends.parquet", index=False)
    pd.DataFrame([{"x": 1}]).to_parquet(root / "gold/analytics_tickets_price_changes.parquet", index=False)
    pd.DataFrame([{"source": "vivid", "event_id_external": "e1", "match_number": 1, "match_key": "match-1",
                   "crawl_ts_utc": pd.Timestamp("2026-05-02 09:00"), "crawl_date": pd.Timestamp("2026-05-02").date(),
                   "listing_price_cents": 11000, "section": "Lower 114", "row": "5",
                   "deal_score": 9.0, "deal_label": "Great", "notes": None,
                   "timestamp_imported": pd.Timestamp("2026-05-02 09:05")}]).to_parquet(
        root / "silver/fct_tickets_listings_latest.parquet", index=False)
    monkeypatch.setenv("WAREHOUSE_DIR", str(root))
    import data
    return data


def test_match_prices_recomputes_best_over_selected_sources(warehouse):
    df = warehouse.match_prices(["gametime"])
    assert len(df) == 1
    assert df.iloc[0]["best_price"] == 150.0 and df.iloc[0]["best_source"] == "gametime"
    all_df = warehouse.match_prices()
    assert all_df.iloc[0]["best_price"] == 100.0


def test_market_trends_and_price_changes_from_published(warehouse):
    trends = warehouse.market_trends(["vivid"])
    assert len(trends) == 2 and trends.iloc[-1]["min_price"] == 100.0
    changes = warehouse.price_changes(["vivid"])
    assert changes.iloc[0]["first_price"] == 120.0 and changes.iloc[0]["latest_price"] == 100.0


def test_listing_distribution_dollars(warehouse):
    df = warehouse.listing_distribution("vivid", "e1")
    assert df.iloc[0]["price"] == 110.0
