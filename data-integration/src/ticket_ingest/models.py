from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Event:
    source: str
    event_id_external: str
    event_url: str
    event_name: str | None = None
    match_number: int | None = None
    stage: str | None = None
    team_1: str | None = None
    team_2: str | None = None
    event_start_local: str | None = None
    venue_name: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    currency: str | None = None
    collection_slug: str = "fifa-world-cup-2026"
    event_key: str | None = None


@dataclass(slots=True)
class MarketSnapshot:
    source: str
    event_id_external: str
    crawl_ts_utc: str
    event_url: str
    lowest_price_cents: int | None = None
    average_price_cents: int | None = None
    highest_price_cents: int | None = None
    inventory_count: int | None = None
    lowest_price_includes_fees: bool | None = None
    listing_quality_label: str | None = None
    price_refresh_ts_utc: str | None = None
    raw_snapshot_path: str | None = None
    collection_slug: str = "fifa-world-cup-2026"
    event_key: str | None = None


@dataclass(slots=True)
class SnapshotDiff:
    source: str
    event_id_external: str
    event_name: str | None
    event_url: str
    crawl_ts_utc: str
    previous_crawl_ts_utc: str | None = None
    current_lowest_price_cents: int | None = None
    previous_lowest_price_cents: int | None = None
    current_average_price_cents: int | None = None
    previous_average_price_cents: int | None = None
    current_inventory_count: int | None = None
    previous_inventory_count: int | None = None
    event_key: str | None = None

    @property
    def lowest_price_change_cents(self) -> int | None:
        return _compute_delta(self.current_lowest_price_cents, self.previous_lowest_price_cents)

    @property
    def average_price_change_cents(self) -> int | None:
        return _compute_delta(self.current_average_price_cents, self.previous_average_price_cents)

    @property
    def inventory_count_change(self) -> int | None:
        return _compute_delta(self.current_inventory_count, self.previous_inventory_count)

    @property
    def has_changes(self) -> bool:
        return any(
            delta not in (None, 0)
            for delta in (
                self.lowest_price_change_cents,
                self.average_price_change_cents,
                self.inventory_count_change,
            )
        )


@dataclass(slots=True)
class Listing:
    source: str
    event_id_external: str
    crawl_ts_utc: str
    listing_price_cents: int
    section: str | None = None
    row: str | None = None
    deal_score: float | None = None
    deal_label: str | None = None
    notes: str | None = None
    collection_slug: str = "fifa-world-cup-2026"
    event_key: str | None = None


@dataclass(slots=True)
class ParseResult:
    events: list[Event] = field(default_factory=list)
    snapshots: list[MarketSnapshot] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)


def _compute_delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
