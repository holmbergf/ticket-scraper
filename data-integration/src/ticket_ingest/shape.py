"""Detect HTML structural changes that signal a parser may be stale.

Each source has a set of expected markers that should be present in the HTML.
After parsing, call ``check_html_shape`` to log warnings for any missing
markers. This is purely observational — it never blocks parsing.

Shape signatures in ``_SHAPE_CHECKS`` are maintained per scraper (stubhub was the
first baseline; viagogo, vivid, gametime, etc. follow the same pattern). Add or
adjust entries when a source's HTML changes or when new sources are integrated.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def check_html_shape(source: str, page_type: str, html: str) -> list[str]:
    """Return a list of warning strings for missing expected markers."""
    checks = _SHAPE_CHECKS.get((source, page_type), [])
    warnings: list[str] = []
    for label, test_fn in checks:
        if not test_fn(html):
            msg = f"[{source}] {page_type}: missing expected marker '{label}'"
            warnings.append(msg)
            log.warning(msg)
    return warnings


def _has(pattern: str, flags: int = re.IGNORECASE):
    compiled = re.compile(pattern, flags)
    return lambda html: compiled.search(html) is not None


def _has_text(needle: str):
    lower = needle.lower()
    return lambda html: lower in html.lower()


_SHAPE_CHECKS: dict[tuple[str, str], list[tuple[str, ...]]] = {
    ("stubhub", "discovery"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("event link /event/", _has(r'href="[^"]*?/event/\d+')),
    ],
    ("stubhub", "event"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("data-listing-id attribute", _has_text("data-listing-id=")),
        ("data-price attribute", _has_text("data-price=")),
        ("price slider aria-valuetext", _has(r'aria-valuetext="\$?[\d,]+')),
        ("offers.lowPrice in JSON-LD", _has(r'"lowPrice"\s*:\s*[\d.]+')),
    ],
    ("viagogo", "discovery"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("event link /E-", _has(r'href="[^"]*?/E-\d+')),
    ],
    ("viagogo", "event"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("data-listing-id attribute", _has_text("data-listing-id=")),
        ("data-price attribute", _has_text("data-price=")),
        ("price slider aria-valuetext", _has(r'aria-valuetext="\$?[\d,]+')),
        ("inventoryLevel in JSON-LD", _has_text('"inventoryLevel"')),
    ],
    ("vivid", "discovery"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("production link", _has(r'href="[^"]*?/production/\d+')),
    ],
    ("vivid", "event"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
        ("Lowest price label", _has_text("Lowest price")),
        ("dollar price", _has(r'\$[\d,]+(?:\.\d{2})?')),
    ],
    ("gametime", "discovery"): [
        ("JSON-LD script tag", _has_text("application/ld+json")),
        ("SportsEvent type", _has_text('"SportsEvent"')),
    ],
    ("gametime", "event"): [
        ("dollar price", _has(r'\$[\d,]+(?:\.\d{2})?')),
        ("Includes Fees", _has_text("Includes Fees")),
    ],
}
