"""Per-source crawl jobs: fetch -> parse -> land raw Parquet.

Orchestration ported from fifa_tickets' cli.py with one structural change:
results are accumulated in memory per source and landed once via
``write_dataset`` (content-addressed Parquet + manifest) instead of being
written row-by-row into SQLite during the crawl. Fetch/parse behaviour —
per-source fetch modes, StubHub sequential city sub-pages with WAF backoff,
Viagogo cross-source expansion, event prioritisation — is unchanged.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .clean import EVENTS_NATURAL_KEY, LISTINGS_NATURAL_KEY, SNAPSHOTS_NATURAL_KEY, dedupe
from .config import Settings
from .http import (
    BrowserFetchConfig,
    FetchError,
    FetchResponse,
    close_playwright,
    fetch_auto,
    fetch_many,
    fetch_text,
    fetch_text_browser,
    fetch_text_playwright,
    fetch_with_retry,
)
from .models import Event, ParseResult, utc_now_iso
from .parsers import (
    discover_fifacollect_events,
    discover_gametime_events,
    discover_stubhub_events,
    discover_viagogo_events,
    discover_vivid_events,
    extract_stubhub_city_urls,
    parse_gametime_event_page,
    parse_stubhub_event_page,
    parse_viagogo_event_page,
    parse_vivid_event_page,
)
from .schemas import events_frame, listings_frame, snapshots_frame
from .shape import check_html_shape
from .storage import LocalStorage, RawHtmlStore, StateStore, write_dataset

log = logging.getLogger(__name__)

VIVID_URL = "https://www.vividseats.com/world-cup-soccer-tickets--sports-soccer/performer/944"
GAMETIME_URL = "https://gametime.co/2026-fifa-world-cup-tickets/performers/soccerworldcup"
STUBHUB_URL = "https://www.stubhub.com/world-cup-tickets/grouping/45410"
VIAGOGO_URL = "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets"
FIFACOLLECT_URL = "https://api.prod.rock-palisade-352518.com/marketplace/rtts/filters?language=en-UK"

SOURCE_CONFIGS = {
    "vivid": {
        "discovery_url": VIVID_URL,
        "page_key": "world-cup-performer",
        "discover": discover_vivid_events,
        "parse_event": parse_vivid_event_page,
        "fetch_mode": "browser",
    },
    "gametime": {
        "discovery_url": GAMETIME_URL,
        "page_key": "world-cup-performer",
        "discover": discover_gametime_events,
        "parse_event": parse_gametime_event_page,
    },
    "stubhub": {
        "discovery_url": STUBHUB_URL,
        "page_key": "world-cup-grouping",
        "discover": discover_stubhub_events,
        "parse_event": parse_stubhub_event_page,
        "extract_subpage_urls": extract_stubhub_city_urls,
        "fetch_mode": "playwright",
        "max_workers": 1,
        "subpage_interval_s": 10,
    },
    "viagogo": {
        "discovery_url": VIAGOGO_URL,
        "page_key": "world-cup-grouping",
        "discover": discover_viagogo_events,
        "parse_event": parse_viagogo_event_page,
        "build_event_url_from_id": lambda eid: f"https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-{eid}",
        "cross_source": "stubhub",
        "fetch_mode": "playwright",
        "max_workers": 2,
    },
    "fifacollect": {
        "discovery_url": FIFACOLLECT_URL,
        "page_key": "rtt-marketplace",
        "discover": discover_fifacollect_events,
        "fetch_mode": "http",
    },
}

SOURCES = tuple(SOURCE_CONFIGS)


@dataclass
class SourceStats:
    source: str
    elapsed_s: float = 0.0
    events_discovered: int = 0
    events_fetched: int = 0
    snapshots: int = 0
    listings: int = 0
    fetch_errors: int = 0
    changed_events: int = 0
    error_message: str | None = None
    alerts: list[str] = field(default_factory=list)


@dataclass
class CrawlOptions:
    max_events: int = 0
    timeout: float = 30.0
    fetch_mode: str = "auto"
    workers: int = 8
    parallel: bool = True
    browser_config: BrowserFetchConfig = field(default_factory=BrowserFetchConfig)


def run_crawl(
    settings: Settings,
    storage: LocalStorage,
    sources: list[str],
    options: CrawlOptions,
) -> dict[str, tuple[str, SourceStats]]:
    """Crawl the selected sources; returns {source: (crawl_ts_utc, stats)}."""
    html_store = RawHtmlStore(settings.raw_html_dir)
    state = StateStore(storage)
    fetch_fn = _build_fetch_fn(options.fetch_mode, options.timeout, options.browser_config)
    results: dict[str, tuple[str, SourceStats]] = {}
    try:
        if options.parallel and len(sources) > 1:
            results = _crawl_sources_parallel(sources, storage, html_store, state, fetch_fn, options)
        else:
            known_ids: dict[str, list[str]] = {}
            for source in sources:
                crawl_ts, stats, event_ids = _crawl_source(
                    source, storage, html_store, state, fetch_fn, options, known_ids)
                results[source] = (crawl_ts, stats)
                known_ids[source] = event_ids
    finally:
        close_playwright()
    return results


def _crawl_sources_parallel(sources, storage, html_store, state, fetch_fn, options):
    results: dict[str, tuple[str, SourceStats]] = {}
    known_ids: dict[str, list[str]] = {}
    depends_on = {s: SOURCE_CONFIGS[s].get("cross_source") for s in sources}
    independent = [s for s in sources if not depends_on.get(s) or depends_on[s] not in sources]
    dependent = [s for s in sources if s not in independent]

    def run_group(group):
        with ThreadPoolExecutor(max_workers=min(len(group), 4)) as pool:
            futures = {
                pool.submit(_crawl_source, s, storage, html_store, state, fetch_fn, options, dict(known_ids)): s
                for s in group
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    crawl_ts, stats, event_ids = future.result()
                    results[source] = (crawl_ts, stats)
                    known_ids[source] = event_ids
                except Exception as exc:  # one source must never sink the run
                    log.error("Source %s failed: %s", source, exc)
                    results[source] = (utc_now_iso(), SourceStats(source=source, error_message=str(exc)))

    run_group(independent)
    if dependent:
        run_group(dependent)
    return results


def _crawl_source(source, storage, html_store, state, fetch_fn, options, known_ids):
    config = SOURCE_CONFIGS[source]
    crawl_ts_utc = utc_now_iso()
    t0 = time.monotonic()
    stats = SourceStats(source=source)

    source_fetch_fn, source_discovery_fn = fetch_fn, fetch_fn
    if "fetch_mode" in config:
        source_discovery_fn = _build_fetch_fn(config["fetch_mode"], options.timeout, options.browser_config, scroll=True)
        source_fetch_fn = _build_fetch_fn(config["fetch_mode"], options.timeout, options.browser_config, scroll=False)

    try:
        discovery_response = source_discovery_fn(config["discovery_url"])
    except FetchError as exc:
        stats.elapsed_s = time.monotonic() - t0
        stats.error_message = f"discovery failed: {exc}"
        log.error("[%s] Discovery failed: %s", source, exc)
        return crawl_ts_utc, stats, []

    html_store.save(source, config["page_key"], crawl_ts_utc, discovery_response.text)
    try:
        discovery = config["discover"](discovery_response.text, discovery_response.url, crawl_ts_utc)
    except Exception as exc:
        stats.elapsed_s = time.monotonic() - t0
        stats.error_message = f"discovery parse failed: {exc}"
        log.error("[%s] Discovery parse failed: %s", source, exc)
        return crawl_ts_utc, stats, []

    if "parse_event" in config:
        stats.fetch_errors += len(check_html_shape(source, "discovery", discovery_response.text))
    log.info("[%s] Discovered %d events", source, len(discovery.events))

    combined = ParseResult(events=list(discovery.events), snapshots=list(discovery.snapshots), listings=list(discovery.listings))
    source_workers = config.get("max_workers", options.workers)

    if "extract_subpage_urls" in config:
        errors = _expand_from_subpages(
            config, source, html_store, crawl_ts_utc, discovery_response, combined,
            source_fetch_fn, min(source_workers, 3))
        stats.fetch_errors += errors
        log.info("[%s] After sub-pages: %d events (%d fetch errors)", source, len(combined.events), errors)

    if "cross_source" in config:
        before = len(combined.events)
        _expand_from_cross_source(config, source, state, known_ids, combined)
        log.info("[%s] Cross-source added %d events", source, len(combined.events) - before)

    stats.events_discovered = len(combined.events)
    prioritized = _prioritize_events(combined.events)
    events_to_fetch = prioritized[: options.max_events] if options.max_events > 0 else prioritized
    if events_to_fetch and "parse_event" in config:
        stats.fetch_errors += _fetch_event_pages(
            events_to_fetch, config, source, html_store, crawl_ts_utc, combined, source_fetch_fn, source_workers)

    _land(storage, source, combined, crawl_ts_utc)
    stats.events_fetched = min(len(events_to_fetch), len(combined.snapshots))
    stats.snapshots = len(combined.snapshots)
    stats.listings = len(combined.listings)
    stats.elapsed_s = time.monotonic() - t0
    log.info("[%s] Done in %.1fs: %d events, %d snapshots, %d listings, %d errors",
             source, stats.elapsed_s, stats.events_discovered, stats.snapshots, stats.listings, stats.fetch_errors)
    return crawl_ts_utc, stats, [e.event_id_external for e in combined.events]


def _land(storage: LocalStorage, source: str, result: ParseResult, crawl_ts_utc: str) -> None:
    """Land one source's crawl as content-addressed Parquet + manifests."""
    imported = utc_now_iso()
    write_dataset(storage, dedupe(events_frame(result.events, imported), EVENTS_NATURAL_KEY), "events", source)
    write_dataset(storage, dedupe(snapshots_frame(result.snapshots, imported), SNAPSHOTS_NATURAL_KEY), "market_snapshots", source)
    write_dataset(storage, dedupe(listings_frame(result.listings, imported), LISTINGS_NATURAL_KEY), "listings", source)


def _expand_from_subpages(config, source, html_store, crawl_ts_utc, discovery_response, combined, fetch_fn, max_workers):
    subpage_urls = config["extract_subpage_urls"](discovery_response.text, discovery_response.url)
    if not subpage_urls:
        return 0
    interval = config.get("subpage_interval_s", 0)
    if interval > 0:
        return _fetch_subpages_sequential(config, source, html_store, crawl_ts_utc, subpage_urls, combined, fetch_fn, interval)
    error_count = 0

    def on_error(url, exc):
        nonlocal error_count
        error_count += 1

    responses = fetch_many(subpage_urls, fetch_fn=fetch_fn, max_workers=max_workers, on_error=on_error)
    seen_ids = {e.event_id_external for e in combined.events}
    for url, response in responses.items():
        city_key = url.rstrip("/").rsplit("/", 2)[-2] if "/" in url else "city"
        html_store.save(source, f"city-{city_key}", crawl_ts_utc, response.text)
        sub_result = config["discover"](response.text, response.url, crawl_ts_utc)
        if len(response.text) < 5000:
            log.warning("[%s] Sub-page %s returned suspiciously small page (%d bytes)", source, city_key, len(response.text))
        for event in sub_result.events:
            if event.event_id_external not in seen_ids:
                seen_ids.add(event.event_id_external)
                combined.events.append(event)
        combined.snapshots.extend(sub_result.snapshots)
    return error_count


def _fetch_subpages_sequential(config, source, html_store, crawl_ts_utc, subpage_urls, combined, fetch_fn, interval_s):
    """Fetch sub-pages one at a time with a cooldown (StubHub WAF avoidance).

    On challenge-page failure, backs off 45s then retries once. Without this,
    StubHub blocks datacenter IPs after ~5 rapid /grouping/ requests.
    """
    error_count = 0
    seen_ids = {e.event_id_external for e in combined.events}
    for i, url in enumerate(subpage_urls):
        if i > 0:
            time.sleep(interval_s)
        city_key = url.rstrip("/").rsplit("/", 2)[-2] if "/" in url else "city"
        response = None
        for attempt in range(2):
            try:
                response = fetch_fn(url)
                break
            except FetchError as exc:
                if attempt == 0 and "challenge" in str(exc).lower():
                    log.warning("[%s] Sub-page %s hit challenge, backing off 45s", source, city_key)
                    time.sleep(45)
                else:
                    log.warning("[%s] Sub-page %s failed: %s", source, city_key, exc)
                    error_count += 1
        if response is None:
            continue
        html_store.save(source, f"city-{city_key}", crawl_ts_utc, response.text)
        sub_result = config["discover"](response.text, response.url, crawl_ts_utc)
        new_count = sum(1 for e in sub_result.events if e.event_id_external not in seen_ids)
        log.info("[%s] Sub-page %s [%d/%d]: %d events (%d new)", source, city_key, i + 1, len(subpage_urls), len(sub_result.events), new_count)
        if len(response.text) < 5000:
            log.warning("[%s] Sub-page %s returned suspiciously small page (%d bytes)", source, city_key, len(response.text))
        for event in sub_result.events:
            if event.event_id_external not in seen_ids:
                seen_ids.add(event.event_id_external)
                combined.events.append(event)
        combined.snapshots.extend(sub_result.snapshots)
    return error_count


def _fetch_event_pages(events, config, source, html_store, crawl_ts_utc, combined, fetch_fn, max_workers):
    url_to_event = {e.event_url: e for e in events}
    error_count = 0

    def on_error(url, exc):
        nonlocal error_count
        error_count += 1

    responses = fetch_many(list(url_to_event), fetch_fn=fetch_fn, max_workers=max_workers, on_error=on_error)
    for url, response in responses.items():
        event = url_to_event[url]
        html_store.save(source, event.event_id_external, crawl_ts_utc, response.text)
        try:
            result = config["parse_event"](response.text, response.url, crawl_ts_utc)
        except Exception as exc:
            error_count += 1
            log.warning("[%s] Parse error for %s: %s", source, event.event_id_external, exc)
            continue
        check_html_shape(source, "event", response.text)
        combined.snapshots.extend(result.snapshots)
        combined.listings.extend(result.listings)
    return error_count


def _expand_from_cross_source(config, source, state: StateStore, known_ids, combined):
    cross_source = config["cross_source"]
    build_url = config["build_event_url_from_id"]
    cross_ids = known_ids.get(cross_source) or state.event_ids_for_source(cross_source)
    seen_ids = {e.event_id_external for e in combined.events}
    from .utils import extract_event_id_from_url

    for cross_id in cross_ids:
        event_url = build_url(cross_id)
        event_id = extract_event_id_from_url(event_url)
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        combined.events.append(Event(source=source, event_id_external=event_id, event_url=event_url))


US_TEAM_KEYWORDS = {"usa", "united states", "u.s."}
HIGH_PRIORITY_STAGES = {"final", "semi-final", "semifinal", "quarter-final", "quarterfinal", "round of 16"}


def _prioritize_events(events: list[Event]) -> list[Event]:
    def priority_key(event: Event) -> tuple[int, str]:
        stage_lower = (event.stage or "").lower()
        teams = f"{event.team_1 or ''} {event.team_2 or ''}".lower()
        is_us = any(kw in teams for kw in US_TEAM_KEYWORDS)
        is_knockout = any(kw in stage_lower for kw in HIGH_PRIORITY_STAGES)
        is_final = "final" in stage_lower and "quarter" not in stage_lower and "semi" not in stage_lower
        tier = 0 if is_final else 1 if is_us else 2 if is_knockout else 3
        return (tier, event.event_id_external)

    return sorted(events, key=priority_key)


def _build_fetch_fn(fetch_mode: str, timeout: float, browser_config: BrowserFetchConfig, scroll: bool = False, min_interval: float | None = None):
    if fetch_mode == "browser":
        base_fn = lambda url: fetch_text_browser(url, timeout=timeout, config=browser_config)  # noqa: E731
    elif fetch_mode == "http":
        base_fn = lambda url: fetch_text(url, timeout=timeout)  # noqa: E731
    elif fetch_mode == "playwright":
        base_fn = lambda url: fetch_text_playwright(url, timeout=timeout, scroll=scroll, min_interval=min_interval)  # noqa: E731
    else:
        base_fn = lambda url: fetch_auto(url, timeout=timeout, config=browser_config)  # noqa: E731

    def fn_with_retry(url: str) -> FetchResponse:
        return fetch_with_retry(url, fetch_fn=base_fn, max_retries=browser_config.max_retries, base_delay_s=browser_config.base_delay_s)

    return fn_with_retry
