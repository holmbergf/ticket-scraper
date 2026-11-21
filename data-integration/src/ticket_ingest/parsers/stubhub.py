from __future__ import annotations

import re
from typing import Any

from ticket_ingest.models import Event, Listing, MarketSnapshot, ParseResult
from ticket_ingest.utils import (
    absolute_url,
    clean_text,
    extract_event_id_from_url,
    iter_application_json_objects,
    iter_sports_event_objects,
    parse_match_metadata,
    parse_money_to_cents,
    unique_by_key,
)


GRID_LINK_PATTERN = re.compile(
    r'title="(?P<title>[^"]+)"[^>]*href="(?P<href>[^"]*?/event/\d+[^"]*)"',
    re.IGNORECASE,
)
CITY_SUBGROUPING_PATTERN = re.compile(
    r'(?:href|"url")\s*[:=]\s*"(?P<href>(?:https?://[^"]*)?/world-cup-tickets/grouping/\d+/[a-z0-9-]+-city/\d+)"',
    re.IGNORECASE,
)
LISTING_BUTTON_PATTERN = re.compile(
    r'data-listing-id="(?P<listing_id>\d+)"'
    r'(?:\s+data-[a-z-]+="[^"]*")*?'
    r'\s+data-price="(?P<price>[^"]*)"',
    re.IGNORECASE,
)
SLIDER_VALUE_PATTERN = re.compile(
    r'aria-valuetext="\$?(?P<value>[\d,]+)\+?"',
    re.IGNORECASE,
)


def discover_events(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    events: list[Event] = []
    snapshots: list[MarketSnapshot] = []

    for node in iter_sports_event_objects(html):
        event_name = _normalize_event_name(clean_text(node.get("name")))
        if not _is_primary_event(event_name):
            continue
        offers = _offers_dict(node.get("offers"))
        location = _dict_value(node.get("location"))
        address = _dict_value(location.get("address"))
        event_url = absolute_url(page_url, offers.get("url") or node.get("url") or page_url)
        event_id = extract_event_id_from_url(event_url)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="stubhub",
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
                country=_country_name(address.get("addressCountry")),
                currency=clean_text(offers.get("priceCurrency")) or None,
            )
        )
        low_price = parse_money_to_cents(offers.get("lowPrice"))
        if low_price is not None:
            snapshots.append(
                MarketSnapshot(
                    source="stubhub",
                    event_id_external=event_id,
                    crawl_ts_utc=crawl_ts_utc,
                    event_url=event_url,
                    lowest_price_cents=low_price,
                    price_refresh_ts_utc=clean_text(offers.get("validFrom")) or None,
                    listing_quality_label="discovery-page",
                )
            )

    seen_ids = {event.event_id_external for event in events}
    for grid_event in _discover_from_grid_links(html, page_url, crawl_ts_utc):
        if grid_event.event_id_external not in seen_ids:
            seen_ids.add(grid_event.event_id_external)
            events.append(grid_event)

    return ParseResult(
        events=unique_by_key(events, lambda item: (item.source, item.event_id_external)),
        snapshots=unique_by_key(
            snapshots,
            lambda item: (item.source, item.event_id_external, item.lowest_price_cents, item.price_refresh_ts_utc),
        ),
    )


_STUBHUB_CITY_SUBPAGES: list[str] = [
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/arlington-city/326",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/atlanta-city/392",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/ciudad-de-mexico-city/1502",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/east-rutherford-city/1958",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/foxborough-city/2311",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/houston-city/3063",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/inglewood-city/3157",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/kansas-city-city/3335",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/miami-city/4429",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/monterrey-city/60048",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/philadelphia-city/5418",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/santa-clara-city/6290",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/seattle-city/6449",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/toronto-city/7180",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/vancouver-city/7408",
    "https://www.stubhub.com/world-cup-tickets/grouping/45410/zapopan-city/7996",
]


def extract_city_subgrouping_urls(html: str, page_url: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in CITY_SUBGROUPING_PATTERN.finditer(html):
        url = absolute_url(page_url, match.group("href"))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        urls = list(_STUBHUB_CITY_SUBPAGES)
    return urls


_JSON_EVENT_PATTERN = re.compile(
    r'"eventId"\s*:\s*(?P<id>\d+)\s*,\s*"name"\s*:\s*"(?P<name>[^"]+)"\s*,\s*"url"\s*:\s*"(?P<url>[^"]+)"',
    re.IGNORECASE,
)


def _discover_from_grid_links(html: str, page_url: str, crawl_ts_utc: str) -> list[Event]:
    events: list[Event] = []

    for match in GRID_LINK_PATTERN.finditer(html):
        title = clean_text(match.group("title"))
        href = match.group("href")
        if not title or not _is_primary_event(title):
            continue
        event_name = _normalize_event_name(title)
        event_url = absolute_url(page_url, href)
        event_id = extract_event_id_from_url(event_url)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="stubhub",
                event_id_external=event_id,
                event_url=event_url,
                event_name=event_name,
                match_number=match_number,
                stage=stage,
                team_1=team_1,
                team_2=team_2,
            )
        )

    seen_ids = {e.event_id_external for e in events}
    for match in _JSON_EVENT_PATTERN.finditer(html):
        name = clean_text(match.group("name"))
        if not name or not _is_primary_event(name):
            continue
        event_name = _normalize_event_name(name)
        event_url = match.group("url")
        event_id = extract_event_id_from_url(event_url)
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        events.append(
            Event(
                source="stubhub",
                event_id_external=event_id,
                event_url=event_url,
                event_name=event_name,
                match_number=match_number,
                stage=stage,
                team_1=team_1,
                team_2=team_2,
            )
        )

    return events


def parse_event_page(html: str, page_url: str, crawl_ts_utc: str) -> ParseResult:
    event = _event_from_json_ld(html, page_url)
    state = _market_state(html)
    grid = _dict_value(state.get("grid")) if state else {}

    if event is None:
        event_url = clean_text(state.get("eventUrl")) or page_url
        event_name = _normalize_event_name(clean_text(state.get("name")))
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        event = Event(
            source="stubhub",
            event_id_external=extract_event_id_from_url(event_url),
            event_url=event_url,
            event_name=event_name,
            match_number=match_number,
            stage=stage,
            team_1=team_1,
            team_2=team_2,
            event_start_local=clean_text(state.get("formattedLocalEventDateTime")) or None,
            venue_name=clean_text(state.get("venueName")) or None,
            city=clean_text(state.get("venueCity")) or None,
            region=clean_text(state.get("venueStateProvinceName")) or None,
            country=clean_text(state.get("venueCountry")) or None,
            currency=clean_text(grid.get("buyerCurrencyCode")) or None,
        )

    if event.currency is None:
        event.currency = clean_text(grid.get("buyerCurrencyCode")) or clean_text(grid.get("listingCurrencyCode")) or None

    listings = _extract_listings(grid.get("items"), event.event_id_external, crawl_ts_utc)
    if not listings:
        listings = _extract_listings_from_html(html, event.event_id_external, crawl_ts_utc, "stubhub")

    json_ld_low = _low_price_from_json_ld(html)
    slider_low, slider_high = _price_range_from_sliders(html)
    json_ld_inventory = _inventory_from_json_ld(html)

    snapshot = MarketSnapshot(
        source="stubhub",
        event_id_external=event.event_id_external,
        crawl_ts_utc=crawl_ts_utc,
        event_url=event.event_url,
        lowest_price_cents=(
            _grid_price_cents(grid, "minPrice", "lowPrice")
            or json_ld_low
            or slider_low
            or (min(l.listing_price_cents for l in listings) if listings else None)
        ),
        average_price_cents=_positive_price_cents(grid.get("averagePrice")),
        highest_price_cents=(
            _grid_price_cents(grid, "maxPrice", "highPrice")
            or slider_high
        ),
        inventory_count=(
            _positive_int(state.get("availableTickets"))
            or _positive_int(state.get("totalListings"))
            or json_ld_inventory
        ),
        lowest_price_includes_fees=True,
        listing_quality_label="event-page",
        price_refresh_ts_utc=_price_refresh_ts_from_json_ld(html),
    )

    return ParseResult(events=[event], snapshots=[snapshot], listings=listings)


def _event_from_json_ld(html: str, page_url: str) -> Event | None:
    for node in iter_sports_event_objects(html):
        event_name = _normalize_event_name(clean_text(node.get("name")))
        if not _is_primary_event(event_name):
            continue
        offers = _offers_dict(node.get("offers"))
        location = _dict_value(node.get("location"))
        address = _dict_value(location.get("address"))
        event_url = absolute_url(page_url, offers.get("url") or node.get("url") or page_url)
        team_1, team_2, match_number, stage = parse_match_metadata(event_name)
        return Event(
            source="stubhub",
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
            country=_country_name(address.get("addressCountry")),
            currency=clean_text(offers.get("priceCurrency")) or None,
        )
    return None


def _market_state(html: str) -> dict[str, Any]:
    for payload in iter_application_json_objects(html):
        if isinstance(payload, dict) and isinstance(payload.get("grid"), dict) and payload.get("eventUrl"):
            return payload
    return {}


def _extract_listings(items: object, event_id_external: str, crawl_ts_utc: str) -> list[Listing]:
    if not isinstance(items, list):
        return []

    listings: list[Listing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        price_cents = parse_money_to_cents(item.get("rawPrice")) or parse_money_to_cents(item.get("price"))
        if not price_cents:
            continue
        listings.append(
            Listing(
                source="stubhub",
                event_id_external=event_id_external,
                crawl_ts_utc=crawl_ts_utc,
                listing_price_cents=price_cents,
                section=clean_text(item.get("section")) or None,
                row=_row_text(item),
                deal_score=_deal_score(item),
                deal_label=_deal_label(item),
                notes=_listing_notes(item),
            )
        )
    return unique_by_key(
        listings,
        lambda item: (item.section, item.row, item.listing_price_cents, item.deal_label, item.notes),
    )


def _row_text(item: dict[str, Any]) -> str | None:
    for key in ("row", "rowText", "rowContent"):
        value = clean_text(item.get(key))
        if value and value.lower() != "row":
            return value
    return None


def _deal_score(item: dict[str, Any]) -> float | None:
    inventory_score = _dict_value(item.get("inventoryListingScore"))
    value = inventory_score.get("dealScore")
    if value not in (None, ""):
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    value = clean_text(item.get("formattedDealScore"))
    if value and value != "0.0":
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _deal_label(item: dict[str, Any]) -> str | None:
    highlight_data = _dict_value(item.get("listingHighlightData"))
    messages = highlight_data.get("highlightSiteMessagesWithType")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                label = clean_text(message.get("message"))
                if label:
                    return label
    if item.get("showCheapestTag"):
        return "Best price"
    return None


def _listing_notes(item: dict[str, Any]) -> str | None:
    notes = []
    raw_notes = item.get("listingNotes")
    if isinstance(raw_notes, list):
        for note in raw_notes[:3]:
            if isinstance(note, dict):
                content = clean_text(note.get("formattedListingNoteContent"))
                if content:
                    notes.append(content)
    return "; ".join(notes) or None


def _extract_listings_from_html(
    html: str, event_id_external: str, crawl_ts_utc: str, source: str,
) -> list[Listing]:
    matches = list(LISTING_BUTTON_PATTERN.finditer(html))
    if not matches:
        return []

    listings: list[Listing] = []
    for i, m in enumerate(matches):
        price_cents = parse_money_to_cents(m.group("price"))
        if not price_cents:
            continue
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else m.start() + 5000
        block = html[m.start():end_pos]
        text_nodes = [t.strip() for t in re.findall(r">([^<]+)<", block) if t.strip() and len(t.strip()) > 1]

        section = None
        row = None
        deal_label = None
        notes_parts: list[str] = []
        for t in text_nodes:
            t_lower = t.lower()
            if t_lower in ("preview", "no image available", "&nbsp; incl. fees"):
                continue
            if t_lower.startswith("section ") or t_lower.startswith("category "):
                section = t
            elif re.match(r"^row\s+\S", t, re.IGNORECASE):
                row = t.split(None, 1)[1] if " " in t else t
            elif t_lower in ("best price", "fan favorite", "great value"):
                deal_label = deal_label or t
            elif t_lower in ("clear view", "last tickets", "away fans section"):
                notes_parts.append(t)
            elif re.match(r"^\d+ tickets? together$", t_lower):
                notes_parts.append(t)
            elif re.match(r"^only \d+ left$", t_lower):
                notes_parts.append(t)

        if section is None:
            for t in text_nodes:
                if re.match(r"^[A-Z].*(?:Tier|Level|Floor|Supporter)", t):
                    section = t
                    break

        listings.append(
            Listing(
                source=source,
                event_id_external=event_id_external,
                crawl_ts_utc=crawl_ts_utc,
                listing_price_cents=price_cents,
                section=section,
                row=row,
                deal_label=deal_label,
                notes="; ".join(notes_parts) or None,
            )
        )
    return unique_by_key(
        listings,
        lambda item: (item.section, item.row, item.listing_price_cents, item.deal_label, item.notes),
    )


def _price_range_from_sliders(html: str) -> tuple[int | None, int | None]:
    values = [parse_money_to_cents(f"${m.group('value')}") for m in SLIDER_VALUE_PATTERN.finditer(html)]
    values = [v for v in values if v]
    if not values:
        return None, None
    return min(values), max(values) if len(values) > 1 else (min(values), None)


def _low_price_from_json_ld(html: str) -> int | None:
    for node in iter_sports_event_objects(html):
        offers = _offers_dict(node.get("offers"))
        price = parse_money_to_cents(offers.get("lowPrice"))
        if price and price > 0:
            return price
    return None


def _inventory_from_json_ld(html: str) -> int | None:
    for node in iter_sports_event_objects(html):
        offers = _offers_dict(node.get("offers"))
        inv = _dict_value(offers.get("inventoryLevel")).get("name")
        number = _positive_int(inv)
        if number is not None:
            return number
    return None


def _grid_price_cents(grid: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = grid.get(key)
        cents = parse_money_to_cents(value)
        if cents:
            return cents
    return None


def _positive_price_cents(value: object) -> int | None:
    cents = parse_money_to_cents(value)
    if cents and cents > 0:
        return cents
    return None


def _positive_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _offers_dict(value: object) -> dict[str, Any]:
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _country_name(value: object) -> str | None:
    if isinstance(value, dict):
        return clean_text(value.get("name")) or None
    return clean_text(str(value)) or None


def _normalize_event_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = clean_text(name)
    if normalized.startswith("PARKING PASSES ONLY"):
        return normalized
    normalized = normalized.replace(" - World Cup - ", " - ")
    match = re.search(r"^(?P<teams>.+?) - (?P<stage>.+?) \(Match (?P<num>\d+)\)$", normalized)
    if match:
        return f"{match.group('teams')} - Match {match.group('num')} ({clean_text(match.group('stage'))})"
    return normalized


def _is_primary_event(event_name: str | None) -> bool:
    return bool(event_name) and not event_name.upper().startswith("PARKING PASSES ONLY")


def _price_refresh_ts_from_json_ld(html: str) -> str | None:
    for node in iter_sports_event_objects(html):
        offers = _offers_dict(node.get("offers"))
        refreshed = clean_text(offers.get("validFrom"))
        if refreshed:
            return refreshed
    return None
