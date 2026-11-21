"""Parser for FIFA Collect Right-to-Ticket (RTT) marketplace.

The RTT page at https://collect.fifa.com/right-to-ticket is a JS SPA
that fetches data from a public REST API.  We call the API directly
with browser-like headers — no auth required.

API endpoints:
  GET /marketplace/rtts/filters?language=en-UK  →  RTT listing data
  GET /collectibles/get-match-unique-cities-teams-rounds?language=en-UK  →  filter metadata

Each RTT item represents one match + category (1/2/3) with the lowest
current marketplace price.  We map these to our Event / MarketSnapshot
model, using the match number as event_id_external and the cheapest
category price as the snapshot price.
"""
from __future__ import annotations

import json
import logging

from ticket_ingest.models import Event, Listing, MarketSnapshot, ParseResult
from ticket_ingest.utils import unique_by_key

log = logging.getLogger(__name__)

SOURCE = "fifacollect"

API_BASE = "https://api.prod.rock-palisade-352518.com"
RTT_FILTERS_URL = f"{API_BASE}/marketplace/rtts/filters?language=en-UK"
RTT_METADATA_URL = f"{API_BASE}/collectibles/get-match-unique-cities-teams-rounds?language=en-UK"

_ROUND_STAGE_MAP: dict[str, str] = {
    "wc-2026-group-stage": "Group Stage",
    "wc-2026-round-32": "Round of 32",
    "wc-2026-round-of-32": "Round of 32",
    "wc-2026-round-16": "Round of 16",
    "wc-2026-round-of-16": "Round of 16",
    "wc-2026-quarter-final": "Quarter-Final",
    "wc-2026-quarter-finals": "Quarter-Final",
    "wc-2026-semi-final": "Semi-Final",
    "wc-2026-semi-finals": "Semi-Final",
    "wc-2026-third-place": "Bronze Final",
    "wc-2026-final": "Final",
}


def discover_events(response_text: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    """Parse the JSON API response from /marketplace/rtts/filters.

    ``response_text`` is the raw JSON body (not HTML).  The crawler
    fetches ``RTT_FILTERS_URL`` and passes the body here.
    """
    try:
        items = json.loads(response_text)
    except json.JSONDecodeError:
        log.warning("[%s] Could not decode API response as JSON", SOURCE)
        return ParseResult()

    if not isinstance(items, list):
        log.warning("[%s] Expected list from API, got %s", SOURCE, type(items).__name__)
        return ParseResult()

    events: list[Event] = []
    snapshots: list[MarketSnapshot] = []
    listings: list[Listing] = []

    match_best: dict[int, dict] = {}

    for item in items:
        match_num = item.get("match")
        if match_num is None:
            continue

        price_cents = item.get("price")
        category = item.get("category", "?")

        if match_num not in match_best or (price_cents and (
            match_best[match_num]["price"] is None
            or price_cents < match_best[match_num]["price"]
        )):
            match_best[match_num] = {**item, "price": price_cents}

        if price_cents:
            listings.append(Listing(
                source=SOURCE,
                event_id_external=str(match_num),
                crawl_ts_utc=crawl_ts_utc,
                listing_price_cents=price_cents,
                section=f"Category {category}",
                notes="rtt-collectible",
            ))

    for match_num, item in match_best.items():
        event_id = str(match_num)
        stage = _normalize_stage(item.get("roundSlug"), item.get("roundName"))
        team_a = item.get("teamAName")
        team_b = item.get("teamBName")

        event_name = _build_event_name(team_a, team_b, match_num, stage)
        event_url = f"https://collect.fifa.com/right-to-ticket?match={match_num}"

        events.append(Event(
            source=SOURCE,
            event_id_external=event_id,
            event_url=event_url,
            event_name=event_name,
            match_number=match_num,
            stage=stage,
            team_1=team_a,
            team_2=team_b,
            event_start_local=item.get("matchDate"),
            venue_name=item.get("stadiumName"),
            city=item.get("cityName"),
            country=item.get("countryName"),
            currency="USD",
        ))

        price_cents = item.get("price")
        if price_cents is not None:
            category_prices = [
                i["price"] for i in items
                if i.get("match") == match_num and i.get("price") is not None
            ]
            snapshots.append(MarketSnapshot(
                source=SOURCE,
                event_id_external=event_id,
                crawl_ts_utc=crawl_ts_utc,
                event_url=event_url,
                lowest_price_cents=min(category_prices) if category_prices else price_cents,
                highest_price_cents=max(category_prices) if category_prices else None,
                average_price_cents=_avg(category_prices),
                inventory_count=len(category_prices),
                lowest_price_includes_fees=True,
                listing_quality_label="rtt-marketplace",
            ))

    return ParseResult(
        events=unique_by_key(events, lambda e: (e.source, e.event_id_external)),
        snapshots=unique_by_key(snapshots, lambda s: (s.source, s.event_id_external)),
        listings=listings,
    )


def _normalize_stage(slug: str | None, name: str | None) -> str | None:
    if slug and slug in _ROUND_STAGE_MAP:
        return _ROUND_STAGE_MAP[slug]
    return name or None


def _build_event_name(
    team_a: str | None, team_b: str | None,
    match_num: int, stage: str | None,
) -> str:
    if team_a and team_b:
        label = f"{team_a} vs {team_b}"
    else:
        label = f"Match {match_num}"
    if stage:
        label += f" ({stage})"
    return label


def _avg(values: list[int]) -> int | None:
    if not values:
        return None
    return sum(values) // len(values)
