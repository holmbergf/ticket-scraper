"""Collection config + canonical-event resolution contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ticket_ingest.collections import EventResolver, list_collections, load_collection
from ticket_ingest.jobs import build_source_configs
from ticket_ingest.models import Event, Listing, MarketSnapshot, ParseResult
from ticket_ingest.parsers.gametime import _extract_listings_from_cards, discover_events

REPO = Path(__file__).resolve().parents[2]


def test_repo_collections_load():
    slugs = [c.slug for c in list_collections()]
    assert slugs == ["fifa-world-cup-2026", "nfl-cowboys-at-seahawks-2026-12-07"]


def test_fifa_config_covers_all_adapters():
    c = load_collection("fifa-world-cup-2026")
    configs = build_source_configs(c)
    assert sorted(configs) == ["fifacollect", "gametime", "stubhub", "viagogo", "vivid"]
    assert configs["stubhub"]["expand_subpages"] if "expand_subpages" in configs["stubhub"] else \
        "extract_subpage_urls" in configs["stubhub"]
    assert c.expected_events("fifacollect") == 90


def test_stubhub_warmup_urls_are_configured():
    c = load_collection("nfl-cowboys-at-seahawks-2026-12-07")
    configs = build_source_configs(c)
    assert configs["stubhub"]["warmup_urls"][0] == "https://www.stubhub.com/"
    assert configs["gametime"]["event_wait_selector"]


def test_resolver_assigns_canonical_event_and_stamps_rows():
    c = load_collection("nfl-cowboys-at-seahawks-2026-12-07")
    resolver = EventResolver(c)
    event = Event(source="gametime", event_id_external="695daa7b5a70588e305211c4",
                  event_url="https://example.test/e", event_name="Cowboys at Seahawks")
    snap = MarketSnapshot(source="gametime", event_id_external="695daa7b5a70588e305211c4",
                          crawl_ts_utc="2026-11-21T00:00:00Z", event_url="https://example.test/e",
                          lowest_price_cents=26100)
    listing = Listing(source="gametime", event_id_external="695daa7b5a70588e305211c4",
                      crawl_ts_utc="2026-11-21T00:00:00Z", listing_price_cents=26100)
    other = Event(source="gametime", event_id_external="other-game",
                  event_url="https://example.test/other", event_name="Giants at Seahawks")
    out = resolver.assign_result(ParseResult(events=[event, other], snapshots=[snap], listings=[listing]))
    assert [e.event_key for e in out.events] == ["dallas-cowboys-at-seattle-seahawks"]
    assert out.events[0].team_1 == "Dallas Cowboys"
    assert out.snapshots[0].collection_slug == c.slug
    assert out.listings[0].event_key == "dallas-cowboys-at-seattle-seahawks"


def test_derived_keys_for_undeclared_collections():
    c = load_collection("fifa-world-cup-2026")
    resolver = EventResolver(c)
    event = Event(source="vivid", event_id_external="1", event_url="https://x.test",
                  event_name="A vs B", match_number=42)
    assert resolver.assign_event(event)
    assert event.event_key == "match-42" and event.collection_slug == c.slug


def test_gametime_listing_cards_and_generic_terms():
    html = """
    <a data-analytics-listing_id="abc" data-analytics-displayed_price="261"
       data-analytics-payload_section="326" data-analytics-payload_row="CC"
       data-analytics-payload_deal_type="cheapest" data-testid="listing-card-0" href="/x">
      <h3>Upper Level End Zone</h3>
      <price-display cents="26100"></price-display>
    </a>"""
    listings = _extract_listings_from_cards(html, "evt1", "2026-11-21T00:00:00Z")
    assert len(listings) == 1
    assert listings[0].section == "Upper Level End Zone 326"
    assert listings[0].listing_price_cents == 26100
    assert listings[0].deal_label == "Cheapest"

    # Generic discovery accepts non-World-Cup SportsEvents when no terms required.
    ld = """<script type="application/ld+json">
    {"@type":"SportsEvent","name":"Dallas Cowboys at Seattle Seahawks",
     "startDate":"2026-12-07T17:15:00",
     "location":{"name":"Lumen Field","address":{"addressLocality":"Seattle"}},
     "offers":{"url":"/nfl-football/x/events/abc12345","lowPrice":245}}
    </script>"""
    out = discover_events(ld, "https://gametime.co/", "2026-11-21T00:00:00Z", required_terms=())
    assert len(out.events) == 1 and out.events[0].team_1 == "Dallas Cowboys"


def test_invalid_collection_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('slug = "other"\ntitle = "x"\n[sources.gametime]\ndiscovery_url = "https://x.test"\n')
    with pytest.raises(ValueError, match="filename must match slug"):
        load_collection(bad)
