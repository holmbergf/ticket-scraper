"""Published collection/event catalogs (dashboard page registry)."""

from __future__ import annotations

import pandas as pd

from ticket_ingest.collections import list_collections
from ticket_ingest.publish_warehouse import build_catalog_frames


def test_catalog_includes_configured_event_without_warehouse_rows():
    collections_df, events_df = build_catalog_frames(
        list_collections(), pd.DataFrame(), pd.DataFrame())
    cowboys = events_df[events_df["collection_slug"] == "nfl-cowboys-at-seahawks-2026-12-07"]
    assert len(cowboys) == 1
    row = cowboys.iloc[0]
    assert row["event_key"] == "dallas-cowboys-at-seattle-seahawks"
    assert row["display_name"] == "Dallas Cowboys at Seattle Seahawks"
    assert not row["has_warehouse_data"]
    assert set(collections_df["collection_slug"]) == {
        "fifa-world-cup-2026", "masters-2027", "nfl-cowboys-at-seahawks-2026-12-07"}


def test_catalog_warehouse_rows_win_and_dates_are_iso_strings():
    dim = pd.DataFrame([{
        "collection_slug": "nfl-cowboys-at-seahawks-2026-12-07",
        "event_key": "dallas-cowboys-at-seattle-seahawks",
        "event_uid": "nfl-cowboys-at-seahawks-2026-12-07:dallas-cowboys-at-seattle-seahawks",
        "display_name": "Dallas Cowboys vs Seattle Seahawks (Monday Night Football)",
        "stage": "Monday Night Football", "match_number": 1,
        "participant_1": "Dallas Cowboys", "participant_2": "Seattle Seahawks",
        "team_1": "Dallas Cowboys", "team_2": "Seattle Seahawks",
        "event_start_local": pd.Timestamp("2026-12-07 17:15"),
        "venue_name": "Lumen Field", "city": "Seattle", "country": "United States",
        "sources_tracking": 4,
    }])
    collections_df, events_df = build_catalog_frames(list_collections(), dim, pd.DataFrame())
    row = events_df[events_df["collection_slug"].str.startswith("nfl-")].iloc[0]
    assert row["has_warehouse_data"]
    assert isinstance(row["event_start_local"], str) and row["event_start_local"].startswith("2026-12-07")
    coll = collections_df[collections_df["collection_slug"].str.startswith("nfl-")].iloc[0]
    assert coll["warehouse_events"] == 1
