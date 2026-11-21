"""Storage contract: content-addressed writes + manifest state.

The load-bearing elt-pipeline properties: identical re-runs write zero new
files (idempotency), partitions follow the documented layout, and state is
derived from manifests, never a database.
"""

from __future__ import annotations

from pathlib import Path

from ticket_ingest.models import Event, Listing, MarketSnapshot, utc_now_iso
from ticket_ingest.schemas import events_frame, listings_frame, snapshots_frame
from ticket_ingest.storage import LocalStorage, StateStore, write_dataset

TS = "2026-05-02T09:05:10Z"


def _event() -> Event:
    return Event(source="vivid", event_id_external="5080437",
                 event_url="https://example.com/e/5080437", event_name="USA vs Paraguay",
                 match_number=1, currency="USD")


def _snapshot(price: int = 131300) -> MarketSnapshot:
    return MarketSnapshot(source="vivid", event_id_external="5080437", crawl_ts_utc=TS,
                          event_url="https://example.com/e/5080437", lowest_price_cents=price,
                          average_price_cents=560000, inventory_count=300)


def test_write_is_content_addressed_and_idempotent(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    df = events_frame([_event()], utc_now_iso())
    first = write_dataset(storage, df, "events", "vivid")
    assert len(first.keys) == 1
    assert first.keys[0].startswith("raw/events/source=vivid/part-")
    assert first.keys[0].endswith(".parquet")

    # Same content, later import timestamp: must be a complete no-op.
    second = write_dataset(storage, events_frame([_event()], "2999-01-01T00:00:00Z"), "events", "vivid")
    assert second.keys == []
    assert second.skipped_keys == first.keys


def test_partitions_and_manifest_state(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    write_dataset(storage, snapshots_frame([_snapshot()], TS), "market_snapshots", "vivid")
    write_dataset(storage, listings_frame(
        [Listing(source="vivid", event_id_external="5080437", crawl_ts_utc=TS,
                 listing_price_cents=150000, section="Lower 114")], TS), "listings", "vivid")
    write_dataset(storage, events_frame([_event()], TS), "events", "vivid")

    assert list((tmp_path / "raw/market_snapshots/crawl_date=2026-05-02").glob("part-*.parquet"))
    assert list((tmp_path / "raw/listings/crawl_date=2026-05-02").glob("part-*.parquet"))

    state = StateStore(storage)
    assert state.crawl_timestamps() == [TS]
    assert state.event_ids_for_source("vivid") == ["5080437"]
    manifests = state.manifests("market_snapshots")
    assert manifests[0]["rows"] == 1 and manifests[0]["sources"] == ["vivid"]


def test_changed_content_writes_new_file(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    write_dataset(storage, snapshots_frame([_snapshot(100000)], TS), "market_snapshots", "vivid")
    changed = write_dataset(storage, snapshots_frame([_snapshot(90000)], TS), "market_snapshots", "vivid")
    assert len(changed.keys) == 1  # new content -> new hash -> new file (append-only raw)


def test_empty_frame_writes_nothing(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    result = write_dataset(storage, events_frame([], TS), "events", "vivid")
    assert result.rows == 0 and result.keys == []
    assert not (tmp_path / "raw").exists()
