from __future__ import annotations

import re

from ticket_ingest.models import Event, Listing, MarketSnapshot, ParseResult
from ticket_ingest.utils import (
    absolute_url,
    clean_text,
    extract_event_id_from_url,
    extract_first_price_cents,
    extract_title,
    find_nearby_text,
    iter_sports_event_objects,
    parse_match_metadata,
    parse_money_to_cents,
    strip_tags,
    unique_by_key,
)


EVENT_LINK_PATTERN = re.compile(r'href="(?P<href>/soccer/[^"]+/events/[A-Za-z0-9]+)[^"]*"', re.IGNORECASE)
LISTING_PATTERN = re.compile(
    r"(?:(?P<deal_label>Cheapest|Amazing Deal|Super Deal|Great Deal|Good Deal)\s+)?"
    r"(?P<section>(?:Category|CAT|Upper|Lower|Section)\s*[A-Za-z0-9\- ]{1,40}|[Uu]pper\s+\d{2,4}|[Ll]ower\s+\d{2,4})"
    r"(?:\s*,?\s*Row\s*(?P<row>[A-Za-z0-9\-]+))?"
    r"[^$]{0,120}?Includes Fees[^$]{0,30}?\$(?P<price>[\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)


def discover_events(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    events, snapshots = _discover_from_json_ld(html, page_url, crawl_ts_utc)

    if not events:
        events, snapshots = _discover_from_links(html, page_url, crawl_ts_utc)

    return ParseResult(
        events=unique_by_key(events, lambda item: (item.source, item.event_id_external)),
        snapshots=unique_by_key(
            snapshots,
            lambda item: (item.source, item.event_id_external, item.lowest_price_cents),
        ),
    )


def _discover_from_json_ld(
    html: str, page_url: str, crawl_ts_utc: str,
) -> tuple[list[Event], list[MarketSnapshot]]:
    events: list[Event] = []
    snapshots: list[MarketSnapshot] = []

    for node in iter_sports_event_objects(html):
        event_name = clean_text(node.get("name"))
        if not event_name or not _is_world_cup_event(event_name):
            continue
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        location = node.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") or {}
        event_url = absolute_url(
            page_url, offers.get("url") or node.get("url") or page_url,
        )
        event_id = extract_event_id_from_url(event_url)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="gametime",
                event_id_external=event_id,
                event_url=event_url,
                event_name=event_name,
                match_number=match_number,
                stage=stage,
                team_1=team_1,
                team_2=team_2,
                event_start_local=node.get("startDate"),
                venue_name=clean_text(location.get("name")) or None,
                city=clean_text(address.get("addressLocality")) or None,
                region=clean_text(address.get("addressRegion")) or None,
                country=clean_text(address.get("addressCountry")) or None,
                currency=clean_text(offers.get("priceCurrency")) or None,
            )
        )
        low_price = parse_money_to_cents(offers.get("lowPrice"))
        if low_price is not None:
            snapshots.append(
                MarketSnapshot(
                    source="gametime",
                    event_id_external=event_id,
                    crawl_ts_utc=crawl_ts_utc,
                    event_url=event_url,
                    lowest_price_cents=low_price,
                    highest_price_cents=parse_money_to_cents(offers.get("highPrice")),
                    lowest_price_includes_fees=True,
                    listing_quality_label="discovery-page",
                )
            )
    return events, snapshots


def _discover_from_links(
    html: str, page_url: str, crawl_ts_utc: str,
) -> tuple[list[Event], list[MarketSnapshot]]:
    events: list[Event] = []
    snapshots: list[MarketSnapshot] = []

    for match in EVENT_LINK_PATTERN.finditer(html):
        event_url = absolute_url(page_url, match.group("href"))
        event_id = extract_event_id_from_url(event_url)
        snippet = find_nearby_text(html, match.group("href"), radius=1400)
        event_name = _extract_event_name_from_snippet(snippet)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="gametime",
                event_id_external=event_id,
                event_url=event_url,
                event_name=event_name,
                match_number=match_number,
                stage=stage,
                team_1=team_1,
                team_2=team_2,
            )
        )
        from_price = _extract_discovery_price(snippet)
        if from_price is not None:
            snapshots.append(
                MarketSnapshot(
                    source="gametime",
                    event_id_external=event_id,
                    crawl_ts_utc=crawl_ts_utc,
                    event_url=event_url,
                    lowest_price_cents=from_price,
                    lowest_price_includes_fees=True,
                    listing_quality_label="discovery-page",
                )
            )
    return events, snapshots


def parse_event_page(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    title = extract_title(html) or extract_event_name_from_url(page_url)
    team_1, team_2, match_number, stage = parse_match_metadata(title)
    event = Event(
        source="gametime",
        event_id_external=extract_event_id_from_url(page_url),
        event_url=page_url,
        event_name=title,
        match_number=match_number,
        stage=stage,
        team_1=team_1,
        team_2=team_2,
    )

    page_text = strip_tags(html)
    listings = _extract_listings(page_text, event.event_id_external, crawl_ts_utc)
    lowest_price = min((listing.listing_price_cents for listing in listings), default=None)
    if lowest_price is None:
        lowest_price = extract_first_price_cents(page_text, "Top Deals on Gametime")

    snapshot = MarketSnapshot(
        source="gametime",
        event_id_external=event.event_id_external,
        crawl_ts_utc=crawl_ts_utc,
        event_url=event.event_url,
        lowest_price_cents=lowest_price,
        lowest_price_includes_fees=True,
        listing_quality_label="event-page",
    )
    return ParseResult(events=[event], snapshots=[snapshot], listings=listings)


def extract_event_name_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/events/", 1)[0].split("/soccer/", 1)[-1]
    slug = slug.replace("-tickets", "").replace("-", " ")
    return clean_text(slug.title())


def _extract_event_name_from_snippet(snippet: str) -> str | None:
    if not snippet:
        return None
    match = re.search(r"([A-Z][A-Za-z0-9 .,'()-]+?Match\s+\d+(?:\s+\([^)]+\))?)", snippet)
    if match:
        return clean_text(match.group(1))
    match = re.search(r"([A-Z][A-Za-z0-9 .,'()-]+?)\s+FROM\s+\$", snippet, re.IGNORECASE)
    if match:
        return clean_text(match.group(1))
    return None


def _is_world_cup_event(name: str) -> bool:
    lower = name.lower()
    return "world cup" in lower or "fifa" in lower


def _extract_discovery_price(snippet: str) -> int | None:
    match = re.search(r"FROM\s+\$([\d,]+)\+?", snippet, re.IGNORECASE)
    if not match:
        return None
    return parse_money_to_cents(match.group(1))


def _extract_listings(page_text: str, event_id_external: str, crawl_ts_utc: str) -> list[Listing]:
    listings: list[Listing] = []
    for match in LISTING_PATTERN.finditer(page_text):
        listings.append(
            Listing(
                source="gametime",
                event_id_external=event_id_external,
                crawl_ts_utc=crawl_ts_utc,
                section=clean_text(match.group("section")) or None,
                row=clean_text(match.group("row")) or None,
                listing_price_cents=parse_money_to_cents(match.group("price")) or 0,
                deal_label=clean_text(match.group("deal_label")) or None,
                notes="includes-fees",
            )
        )
    return unique_by_key(
        [listing for listing in listings if listing.listing_price_cents > 0],
        lambda item: (item.section, item.row, item.listing_price_cents, item.deal_label),
    )
