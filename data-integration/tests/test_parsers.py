from __future__ import annotations

from pathlib import Path
import json
import unittest

from ticket_ingest.http import _looks_like_challenge_page
from ticket_ingest.shape import check_html_shape
from ticket_ingest.parsers.gametime import discover_events as discover_gametime_events
from ticket_ingest.parsers.gametime import parse_event_page as parse_gametime_event_page
from ticket_ingest.parsers.stubhub import discover_events as discover_stubhub_events
from ticket_ingest.parsers.stubhub import _price_range_from_sliders as stubhub_price_range
from ticket_ingest.parsers.stubhub import parse_event_page as parse_stubhub_event_page
from ticket_ingest.parsers.viagogo import discover_events as discover_viagogo_events
from ticket_ingest.parsers.viagogo import _price_range_from_sliders as viagogo_price_range
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

    def test_stubhub_synthetic_event_page(self) -> None:
        result = parse_stubhub_event_page(
            _synthetic_event_html("stubhub"),
            "https://www.stubhub.com/example-tickets-6-11-2026/event/100000001/",
            "2026-04-04T14:48:50Z",
        )
        self.assertEqual(result.events[0].event_name, "Mexico vs South Africa - Match 1 (Group A)")
        self.assertEqual(result.events[0].currency, "USD")
        self.assertEqual(result.snapshots[0].lowest_price_cents, 210600)
        self.assertEqual(result.snapshots[0].highest_price_cents, 499000)
        self.assertGreaterEqual(len(result.listings), 5)
        self.assertTrue({item.section for item in result.listings})

    def test_stubhub_synthetic_discovery(self) -> None:
        result = discover_stubhub_events(
            _synthetic_discovery_html("stubhub"),
            "https://www.stubhub.com/example-tickets/grouping/1",
            "2026-04-04T14:48:50Z",
        )
        self.assertGreaterEqual(len(result.events), 5)

    def test_viagogo_synthetic_event_page(self) -> None:
        result = parse_viagogo_event_page(
            _synthetic_event_html("viagogo"),
            "https://www.viagogo.com/example/E-100000001",
            "2026-04-04T14:48:50Z",
        )
        self.assertEqual(result.events[0].event_name, "Mexico vs South Africa - Match 1 (Group A)")
        self.assertEqual(result.snapshots[0].lowest_price_cents, 210600)
        self.assertEqual(result.snapshots[0].inventory_count, 298)
        self.assertGreaterEqual(len(result.listings), 5)

    def test_viagogo_synthetic_discovery(self) -> None:
        result = discover_viagogo_events(
            _synthetic_discovery_html("viagogo"),
            "https://www.viagogo.com/example",
            "2026-04-04T14:48:50Z",
        )
        self.assertGreaterEqual(len(result.events), 5)

    def test_single_slider_has_no_fabricated_high(self) -> None:
        html = '<div aria-valuetext="$100"></div>'
        self.assertEqual(stubhub_price_range(html), (10000, None))
        self.assertEqual(viagogo_price_range(html), (10000, None))

    def test_shape_check_synthetic_pages_no_warnings(self) -> None:
        cases = [
            ("stubhub", "discovery", _synthetic_discovery_html("stubhub")),
            ("stubhub", "event", _synthetic_event_html("stubhub")),
            ("viagogo", "discovery", _synthetic_discovery_html("viagogo")),
            ("viagogo", "event", _synthetic_event_html("viagogo")),
            ("vivid", "event", read_fixture("vivid_event.html")),
            ("gametime", "event", read_fixture("gametime_event.html")),
        ]
        for source, page_type, html in cases:
            with self.subTest(source=source, page_type=page_type):
                self.assertEqual(check_html_shape(source, page_type, html), [])

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


def _synthetic_sports_node(index: int, source: str) -> dict[str, object]:
    event_id = 100000000 + index
    if source == "viagogo":
        url = f"https://www.viagogo.com/example/E-{event_id}"
    else:
        url = f"https://www.stubhub.com/example-tickets/event/{event_id}/"
    return {
        "@type": "SportsEvent",
        "name": f"Mexico vs South Africa - Group A (Match {index})" if index == 1
                else f"Example Home {index} vs Example Away {index} (Match {index})",
        "startDate": "2026-06-11T09:00:00-06:00",
        "url": url,
        "location": {
            "@type": "Place", "name": "Example Stadium",
            "address": {"addressLocality": "Example City", "addressRegion": "EX",
                        "addressCountry": "US"},
        },
        "offers": {
            "@type": "AggregateOffer", "url": url, "priceCurrency": "USD",
            "lowPrice": 2106, "validFrom": "2026-04-04T14:48:50Z",
            "inventoryLevel": {"name": "298"},
        },
    }


def _synthetic_discovery_html(source: str) -> str:
    nodes = [_synthetic_sports_node(i, source) for i in range(1, 6)]
    links = "".join(f'<a href="{node["url"]}">event</a>' for node in nodes)
    return _json_ld_html({"@context": "https://schema.org", "@graph": nodes}) + links


def _synthetic_event_html(source: str) -> str:
    node = _synthetic_sports_node(1, source)
    items = [
        {"section": f"S{i}", "row": str(i), "rawPrice": 2106 + i * 100,
         "listingNotes": [{"formattedListingNoteContent": "Synthetic fixture"}]}
        for i in range(1, 6)
    ]
    state = {
        "eventUrl": node["url"], "availableTickets": 298,
        "grid": {"buyerCurrencyCode": "USD", "minPrice": 2106,
                 "averagePrice": 2605, "maxPrice": 4990, "items": items},
    }
    markers = ('<div data-listing-id="synthetic-1" data-price="2106" '
               'aria-valuetext="$2,106"></div>'
               '<div aria-valuetext="$4,990"></div>')
    return _json_ld_html({"@context": "https://schema.org", **node}) + _application_json_html(state) + markers


def _json_ld_html(payload: dict[str, object]) -> str:
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def _application_json_html(payload: dict[str, object]) -> str:
    return f'<script type="application/json">{json.dumps(payload)}</script>'


if __name__ == "__main__":
    unittest.main()
