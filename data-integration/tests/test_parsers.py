from __future__ import annotations

from pathlib import Path
import json
import unittest

from ticket_ingest.http import _looks_like_challenge_page
from ticket_ingest.shape import check_html_shape
from ticket_ingest.parsers.gametime import discover_events as discover_gametime_events
from ticket_ingest.parsers.gametime import parse_event_page as parse_gametime_event_page
from ticket_ingest.parsers.stubhub import discover_events as discover_stubhub_events
from ticket_ingest.parsers.stubhub import parse_event_page as parse_stubhub_event_page
from ticket_ingest.parsers.viagogo import discover_events as discover_viagogo_events
from ticket_ingest.parsers.viagogo import parse_event_page as parse_viagogo_event_page
from ticket_ingest.parsers.vivid import discover_events as discover_vivid_events
from ticket_ingest.parsers.vivid import parse_event_page as parse_vivid_event_page


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_vivid_discovery_and_event_page(self) -> None:
        discovery = discover_vivid_events(
            read_fixture("vivid_performer.html"),
            "https://www.vividseats.com/world-cup-soccer-tickets--sports-soccer/performer/944",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(len(discovery.events), 2)
        self.assertEqual(discovery.events[0].match_number, 4)

        event = parse_vivid_event_page(
            read_fixture("vivid_event.html"),
            "https://www.vividseats.com/world-cup-soccer-tickets-sofi-stadium-6-12-2026--sports-soccer/production/5080437",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(event.snapshots[0].lowest_price_cents, 131100)
        self.assertEqual(event.snapshots[0].average_price_cents, 556900)
        self.assertEqual(event.snapshots[0].price_refresh_ts_utc, "2026-04-03 20:50:40 UTC")
        self.assertGreaterEqual(len(event.listings), 3)

    def test_vivid_browser_discovery_from_structured_data(self) -> None:
        discovery = discover_vivid_events(
            read_fixture("vivid_performer_browser.html"),
            "https://www.vividseats.com/world-cup-soccer-tickets--sports-soccer/performer/944",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(len(discovery.events), 2)
        usa = next(event for event in discovery.events if event.match_number == 4)
        self.assertEqual(usa.team_1, "USA")
        self.assertEqual(usa.team_2, "Paraguay")
        self.assertEqual(usa.venue_name, "SoFi Stadium")
        usa_snapshot = next(
            snapshot for snapshot in discovery.snapshots if snapshot.event_id_external == "5080437"
        )
        self.assertEqual(usa_snapshot.lowest_price_cents, 128500)
        self.assertEqual(usa_snapshot.highest_price_cents, 900000)

    def test_gametime_discovery_and_event_page(self) -> None:
        discovery = discover_gametime_events(
            read_fixture("gametime_performer.html"),
            "https://gametime.co/2026-fifa-world-cup-tickets/performers/soccerworldcup",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(len(discovery.events), 2)
        self.assertEqual(discovery.snapshots[0].lowest_price_cents, 140200)

        event = parse_gametime_event_page(
            read_fixture("gametime_event.html"),
            "https://gametime.co/soccer/fifa-world-cup-usa-vs-paraguay-match-4-group-d-tickets/6-12-2026-inglewood-ca-so-fi-stadium/events/66b123396fd038aea66f23ec",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(event.snapshots[0].lowest_price_cents, 134300)
        self.assertEqual(len(event.listings), 4)
        labels = {listing.deal_label for listing in event.listings if listing.deal_label}
        self.assertIn("Cheapest", labels)
        self.assertIn("Amazing Deal", labels)

    def test_stubhub_discovery_and_event_page(self) -> None:
        discovery_html = _json_ld_html(
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "SportsEvent",
                        "name": "United States vs Paraguay - World Cup - Group D (Match 4)",
                        "startDate": "2026-06-12T15:00:00-07:00",
                        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
                        "location": {
                            "@type": "Place",
                            "name": "SoFi Stadium",
                            "address": {
                                "addressLocality": "Inglewood",
                                "addressRegion": "CA",
                                "addressCountry": "US",
                            },
                        },
                        "offers": {
                            "@type": "AggregateOffer",
                            "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
                            "priceCurrency": "USD",
                            "lowPrice": 1313,
                            "validFrom": "2026-04-03T20:50:40Z",
                        },
                    }
                ],
            }
        )
        discovery = discover_stubhub_events(
            discovery_html,
            "https://www.stubhub.com/world-cup-tickets/grouping/45410",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(len(discovery.events), 1)
        self.assertEqual(discovery.events[0].match_number, 4)
        self.assertEqual(discovery.events[0].team_1, "United States")
        self.assertEqual(discovery.snapshots[0].lowest_price_cents, 131300)

        event_html = (
            _json_ld_html(
                {
                    "@context": "https://schema.org",
                    "@type": "SportsEvent",
                    "name": "United States vs Paraguay - World Cup - Group D (Match 4)",
                    "startDate": "2026-06-12T15:00:00-07:00",
                    "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
                    "location": {
                        "@type": "Place",
                        "name": "SoFi Stadium",
                        "address": {
                            "addressLocality": "Inglewood",
                            "addressRegion": "CA",
                            "addressCountry": "US",
                        },
                    },
                    "offers": {
                        "@type": "AggregateOffer",
                        "priceCurrency": "USD",
                        "validFrom": "2026-04-03T20:50:40Z",
                    },
                }
            )
            + _application_json_html(
                {
                    "eventUrl": "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
                    "availableTickets": 298,
                    "grid": {
                        "buyerCurrencyCode": "USD",
                        "minPrice": 1345,
                        "averagePrice": 1888,
                        "maxPrice": 9021,
                        "items": [
                            {
                                "section": "C217",
                                "row": "8",
                                "rawPrice": 1450,
                                "inventoryListingScore": {"dealScore": 9.4},
                                "listingHighlightData": {
                                    "highlightSiteMessagesWithType": [{"message": "Great Value"}]
                                },
                                "listingNotes": [
                                    {"formattedListingNoteContent": "Clear view"},
                                ],
                            }
                        ],
                    },
                }
            )
        )
        event = parse_stubhub_event_page(
            event_html,
            "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(event.snapshots[0].lowest_price_cents, 134500)
        self.assertEqual(event.snapshots[0].average_price_cents, 188800)
        self.assertEqual(event.snapshots[0].inventory_count, 298)
        self.assertEqual(event.snapshots[0].price_refresh_ts_utc, "2026-04-03T20:50:40Z")
        self.assertEqual(event.listings[0].deal_label, "Great Value")
        self.assertEqual(event.listings[0].notes, "Clear view")

    def test_viagogo_discovery_and_event_page(self) -> None:
        discovery_html = _json_ld_html(
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "SportsEvent",
                        "name": "Mexico vs Switzerland - World Cup - Group Stage (Match 23)",
                        "startDate": "2026-06-19T20:00:00-05:00",
                        "url": "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-153020710",
                        "location": {
                            "@type": "Place",
                            "name": "NRG Stadium",
                            "address": {
                                "addressLocality": "Houston",
                                "addressRegion": "TX",
                                "addressCountry": "US",
                            },
                        },
                        "offers": {
                            "@type": "AggregateOffer",
                            "priceCurrency": "USD",
                            "lowPrice": 875,
                        },
                    }
                ],
            }
        )
        discovery = discover_viagogo_events(
            discovery_html,
            "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(len(discovery.events), 1)
        self.assertEqual(discovery.events[0].match_number, 23)
        self.assertEqual(discovery.events[0].team_1, "Mexico")
        self.assertEqual(discovery.snapshots[0].lowest_price_cents, 87500)

        event_html = (
            _json_ld_html(
                {
                    "@context": "https://schema.org",
                    "@type": "SportsEvent",
                    "name": "Mexico vs Switzerland - World Cup - Group Stage (Match 23)",
                    "startDate": "2026-06-19T20:00:00-05:00",
                    "url": "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-153020710",
                    "location": {
                        "@type": "Place",
                        "name": "NRG Stadium",
                        "address": {
                            "addressLocality": "Houston",
                            "addressRegion": "TX",
                            "addressCountry": "US",
                        },
                    },
                    "offers": {
                        "@type": "AggregateOffer",
                        "priceCurrency": "USD",
                    },
                }
            )
            + _application_json_html(
                {
                    "eventUrl": "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-153020710",
                    "availableTickets": 122,
                    "grid": {
                        "buyerCurrencyCode": "USD",
                        "minPrice": 910,
                        "averagePrice": 1210,
                        "maxPrice": 4100,
                        "items": [
                            {
                                "section": "132",
                                "row": "A",
                                "rawPrice": 950,
                                "showCheapestTag": True,
                                "listingNotes": [
                                    {"formattedListingNoteContent": "Side view"},
                                ],
                            }
                        ],
                    },
                }
            )
        )
        event = parse_viagogo_event_page(
            event_html,
            "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-153020710",
            "2026-04-03T21:00:00Z",
        )
        self.assertEqual(event.snapshots[0].lowest_price_cents, 91000)
        self.assertEqual(event.snapshots[0].highest_price_cents, 410000)
        self.assertEqual(event.snapshots[0].inventory_count, 122)
        self.assertEqual(event.listings[0].deal_label, "Best price")
        self.assertEqual(event.listings[0].notes, "Side view")

    def test_stubhub_live_event_page(self) -> None:
        result = parse_stubhub_event_page(
            read_fixture("stubhub_event_153033405.html"),
            "https://www.stubhub.com/world-cup-ciudad-de-mexico-tickets-6-11-2026/event/153033405/",
            "2026-04-04T14:48:50Z",
        )
        self.assertEqual(result.events[0].event_name, "Mexico vs South Africa - Match 1 (Group A)")
        self.assertEqual(result.events[0].currency, "USD")
        self.assertIsNotNone(result.snapshots[0].lowest_price_cents)
        self.assertGreater(result.snapshots[0].lowest_price_cents, 0)
        self.assertIsNotNone(result.snapshots[0].highest_price_cents)
        self.assertGreaterEqual(len(result.listings), 5)
        sections = {l.section for l in result.listings if l.section}
        self.assertTrue(len(sections) > 0)

    def test_stubhub_live_discovery(self) -> None:
        result = discover_stubhub_events(
            read_fixture("stubhub_discovery.html"),
            "https://www.stubhub.com/world-cup-tickets/grouping/45410",
            "2026-04-04T14:48:50Z",
        )
        self.assertGreaterEqual(len(result.events), 5)

    def test_viagogo_live_event_page(self) -> None:
        result = parse_viagogo_event_page(
            read_fixture("viagogo_event_153033405.html"),
            "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets/E-153033405",
            "2026-04-04T14:48:50Z",
        )
        self.assertEqual(result.events[0].event_name, "Mexico vs South Africa - Match 1 (Group A)")
        self.assertIsNotNone(result.snapshots[0].lowest_price_cents)
        self.assertGreater(result.snapshots[0].lowest_price_cents, 0)
        self.assertIsNotNone(result.snapshots[0].inventory_count)
        self.assertGreater(result.snapshots[0].inventory_count, 100)
        self.assertGreaterEqual(len(result.listings), 5)

    def test_viagogo_live_discovery(self) -> None:
        result = discover_viagogo_events(
            read_fixture("viagogo_discovery.html"),
            "https://www.viagogo.com/Sports-Tickets/Soccer/Soccer-Tournament/World-Cup-Tickets",
            "2026-04-04T14:48:50Z",
        )
        self.assertGreaterEqual(len(result.events), 5)

    def test_vivid_live_event_page(self) -> None:
        result = parse_vivid_event_page(
            read_fixture("vivid_event_5080436.html"),
            "https://www.vividseats.com/world-cup-soccer-tickets-bmo-field-6-12-2026--sports-soccer/production/5080436",
            "2026-04-04T14:48:50Z",
        )
        self.assertIsNotNone(result.snapshots[0].lowest_price_cents)
        self.assertGreater(result.snapshots[0].lowest_price_cents, 0)
        self.assertGreaterEqual(len(result.listings), 3)

    def test_gametime_live_event_page(self) -> None:
        result = parse_gametime_event_page(
            read_fixture("gametime_event_66ac29dc.html"),
            "https://gametime.co/soccer/fifa-world-cup-belgium-vs-egypt-match-16-group-e-tickets/6-15-2026-east-rutherford-nj-metlife-stadium/events/66ac29dc829dc33434fe4ee5",
            "2026-04-04T14:48:50Z",
        )
        self.assertIsNotNone(result.snapshots[0].lowest_price_cents)
        self.assertGreater(result.snapshots[0].lowest_price_cents, 0)
        self.assertGreaterEqual(len(result.listings), 3)

    def test_shape_check_live_fixtures_no_warnings(self) -> None:
        fixture_dir = Path(__file__).parent / "fixtures"
        cases = [
            ("stubhub", "discovery", "stubhub_discovery.html"),
            ("stubhub", "event", "stubhub_event_153033405.html"),
            ("viagogo", "discovery", "viagogo_discovery.html"),
            ("viagogo", "event", "viagogo_event_153033405.html"),
            ("vivid", "event", "vivid_event_5080436.html"),
            ("gametime", "event", "gametime_event_66ac29dc.html"),
        ]
        cases = [(s, p, f) for s, p, f in cases if (fixture_dir / f).exists()]
        for source, page_type, fixture in cases:
            with self.subTest(source=source, page_type=page_type):
                html = read_fixture(fixture)
                warnings = check_html_shape(source, page_type, html)
                self.assertEqual(warnings, [], f"Unexpected warnings for {source}/{page_type}: {warnings}")

    def test_shape_check_detects_missing_markers(self) -> None:
        warnings = check_html_shape("stubhub", "event", "<html><body>empty page</body></html>")
        self.assertGreater(len(warnings), 0)
        labels = " ".join(warnings).lower()
        self.assertIn("json-ld", labels)
        self.assertIn("data-listing-id", labels)

    def test_challenge_page_detection(self) -> None:
        self.assertTrue(_looks_like_challenge_page("<title>Challenge Validation</title>"))
        self.assertTrue(_looks_like_challenge_page('<script src="https://js.datadome.co/tags.js"></script>'))
        self.assertTrue(_looks_like_challenge_page("<title>Vercel Security Checkpoint</title>"))
        self.assertFalse(_looks_like_challenge_page("<html><title>Normal Page</title></html>"))
        long_page = "x" * 15000 + "captcha"
        self.assertFalse(_looks_like_challenge_page(long_page))


def _json_ld_html(payload: dict[str, object]) -> str:
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def _application_json_html(payload: dict[str, object]) -> str:
    return f'<script type="application/json">{json.dumps(payload)}</script>'


if __name__ == "__main__":
    unittest.main()
