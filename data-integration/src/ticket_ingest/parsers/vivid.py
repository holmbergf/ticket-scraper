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


PRODUCTION_LINK_PATTERN = re.compile(r'href="(?P<href>/[^"]+/production/\d+)"', re.IGNORECASE)
PRICE_REFRESH_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)")
LISTING_PATTERN = re.compile(
    r"(?P<section>(?:Section|Sec\.?|Upper|Lower|Category|CAT)\s*[A-Za-z0-9\- ]{1,40})"
    r"(?:\s*,?\s*Row\s*(?P<row>[A-Za-z0-9\-]+))?"
    r"[^$]{0,80}?\$(?P<price>[\d,]+(?:\.\d{2})?)"
    r"(?:[^0-9]{0,40}(?:Deal Score|DealScore)\s*(?P<score>\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)


def discover_events(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    events: list[Event] = []
    snapshots: list[MarketSnapshot] = []

    for node in iter_sports_event_objects(html):
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        location = node.get("location") or {}
        address = location.get("address") or {}
        event_url = absolute_url(page_url, offers.get("url") or node.get("url") or node.get("URL") or page_url)
        event_id = extract_event_id_from_url(event_url)
        event_name = _normalize_discovery_event_name(clean_text(node.get("name")))
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="vivid",
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
                country=_extract_country(address.get("addressCountry")),
                currency=clean_text(offers.get("priceCurrency")) or None,
            )
        )
        discovery_price = parse_money_to_cents(offers.get("lowPrice"))
        if discovery_price is not None:
            snapshots.append(
                MarketSnapshot(
                    source="vivid",
                    event_id_external=event_id,
                    crawl_ts_utc=crawl_ts_utc,
                    event_url=event_url,
                    lowest_price_cents=discovery_price,
                    highest_price_cents=parse_money_to_cents(offers.get("highPrice")),
                    lowest_price_includes_fees=True,
                    listing_quality_label="discovery-page",
                    price_refresh_ts_utc=offers.get("validFrom"),
                )
            )

    if events:
        return ParseResult(
            events=unique_by_key(events, lambda item: (item.source, item.event_id_external)),
            snapshots=unique_by_key(
                snapshots,
                lambda item: (
                    item.source,
                    item.event_id_external,
                    item.lowest_price_cents,
                    item.price_refresh_ts_utc,
                ),
            ),
        )

    for match in PRODUCTION_LINK_PATTERN.finditer(html):
        event_url = absolute_url(page_url, match.group("href"))
        event_id = extract_event_id_from_url(event_url)
        snippet = find_nearby_text(html, match.group("href"), radius=1200)
        event_name = _extract_event_name_from_snippet(snippet)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="vivid",
                event_id_external=event_id,
                event_url=event_url,
                event_name=event_name,
                match_number=match_number,
                stage=stage,
                team_1=team_1,
                team_2=team_2,
            )
        )
        discovery_price = extract_first_price_cents(snippet, "From")
        if discovery_price is not None:
            snapshots.append(
                MarketSnapshot(
                    source="vivid",
                    event_id_external=event_id,
                    crawl_ts_utc=crawl_ts_utc,
                    event_url=event_url,
                    lowest_price_cents=discovery_price,
                    lowest_price_includes_fees=True,
                    listing_quality_label="discovery-page",
                )
            )

    return ParseResult(
        events=unique_by_key(events, lambda item: (item.source, item.event_id_external)),
        snapshots=snapshots,
    )


def parse_event_page(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    event = _event_from_json_ld(html, page_url)
    if event is None:
        title = extract_title(html) or "Unknown event"
        team_1, team_2, match_number, stage = parse_match_metadata(title)
        event = Event(
            source="vivid",
            event_id_external=extract_event_id_from_url(page_url),
            event_url=page_url,
            event_name=title,
            match_number=match_number,
            stage=stage,
            team_1=team_1,
            team_2=team_2,
        )

    page_text = strip_tags(html)
    snapshot = MarketSnapshot(
        source="vivid",
        event_id_external=event.event_id_external,
        crawl_ts_utc=crawl_ts_utc,
        event_url=event.event_url,
        lowest_price_cents=extract_first_price_cents(page_text, "Lowest price"),
        average_price_cents=extract_first_price_cents(page_text, "Average price"),
        lowest_price_includes_fees=True,
        listing_quality_label="event-page",
        price_refresh_ts_utc=_extract_price_refresh_ts(page_text),
    )

    if snapshot.lowest_price_cents is None:
        for node in iter_sports_event_objects(html):
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            snapshot.lowest_price_cents = parse_money_to_cents(offers.get("lowPrice"))
            if event.currency is None:
                event.currency = clean_text(offers.get("priceCurrency")) or None
            if snapshot.lowest_price_cents is not None:
                break

    listings = _extract_listings(page_text, event.event_id_external, crawl_ts_utc)
    return ParseResult(events=[event], snapshots=[snapshot], listings=listings)


def _event_from_json_ld(html: str, page_url: str) -> Event | None:
    for node in iter_sports_event_objects(html):
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        event_url = absolute_url(page_url, offers.get("url") or node.get("url") or page_url)
        location = node.get("location") or {}
        address = location.get("address") or {}
        event_name = clean_text(node.get("name")) or extract_title(html)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        return Event(
            source="vivid",
            event_id_external=extract_event_id_from_url(event_url),
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
            country=_extract_country(address.get("addressCountry")),
            currency=clean_text(offers.get("priceCurrency")) or None,
        )
    return None


def _extract_event_name_from_snippet(snippet: str) -> str | None:
    if not snippet:
        return None
    match = re.search(r"([A-Z][A-Za-z0-9 .,'()-]+?Match\s+\d+(?:\s+\([^)]+\))?)", snippet)
    if match:
        return clean_text(match.group(1))
    match = re.search(r"([A-Z][A-Za-z0-9 .,'()-]+?)\s+From\s+\$", snippet)
    if match:
        return clean_text(match.group(1))
    return None


def _normalize_discovery_event_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = clean_text(name)
    normalized = re.sub(r"^[A-Za-z .'-]+,?\s*[A-Z]{2}\s+-\s+", "", normalized)
    normalized = normalized.replace(" - World Cup - ", " - ")
    return normalized


def _extract_country(value: object) -> str | None:
    if isinstance(value, dict):
        return clean_text(value.get("name")) or None
    return clean_text(str(value)) or None


def _extract_price_refresh_ts(page_text: str) -> str | None:
    match = PRICE_REFRESH_PATTERN.search(page_text)
    return match.group(1) if match else None


def _extract_listings(page_text: str, event_id_external: str, crawl_ts_utc: str) -> list[Listing]:
    listings: list[Listing] = []
    for match in LISTING_PATTERN.finditer(page_text):
        listings.append(
            Listing(
                source="vivid",
                event_id_external=event_id_external,
                crawl_ts_utc=crawl_ts_utc,
                section=clean_text(match.group("section")) or None,
                row=clean_text(match.group("row")) or None,
                listing_price_cents=parse_money_to_cents(match.group("price")) or 0,
                deal_score=float(match.group("score")) if match.group("score") else None,
            )
        )
    return unique_by_key(
        [listing for listing in listings if listing.listing_price_cents > 0],
        lambda item: (item.section, item.row, item.listing_price_cents, item.deal_score),
    )
