from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


JSON_LD_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
APPLICATION_JSON_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
PRICE_PATTERN = re.compile(r"\$([\d,]+)(?:\.(\d{2}))?")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_PATTERN.sub(" ", unescape(value)).strip()


def strip_tags(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(TAG_PATTERN.sub(" ", value))


PLAIN_NUMBER_PATTERN = re.compile(r"^[\d,]+(?:\.\d{1,2})?$")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
EVENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{6,}")
MATCHUP_PATTERN = re.compile(r"(.+?)\s+(?:vs\.?|at|@)\s+(.+?)(?:\s+-\s+|\s+\(|$)", re.IGNORECASE)
MATCH_NUMBER_PATTERN = re.compile(r"\bMatch\s+(\d+)\b", re.IGNORECASE)
PAREN_PATTERN = re.compile(r"\(([^)]+)\)")


def parse_money_to_cents(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value) * 100))
    text = clean_text(str(value))
    match = PRICE_PATTERN.search(text)
    if match:
        dollars = int(match.group(1).replace(",", ""))
        cents = int(match.group(2) or "00")
        return dollars * 100 + cents
    if text.replace(",", "").isdigit():
        return int(text.replace(",", "")) * 100
    # Decimals without a leading $ (e.g. "12.50"): PRICE_PATTERN needs "$", and isdigit() is false here.
    if PLAIN_NUMBER_PATTERN.match(text):
        return int(round(float(text.replace(",", "")) * 100))
    return None


def extract_first_price_cents(text: str, label: str | None = None) -> int | None:
    haystack = text
    if label:
        match = re.search(
            rf"{re.escape(label)}[\s:.-]*[^$]{{0,80}}?\$([\d,]+)(?:\.(\d{{2}}))?",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            return parse_money_to_cents(f"${match.group(1)}.{match.group(2) or '00'}")
    match = PRICE_PATTERN.search(haystack)
    if not match:
        return None
    return parse_money_to_cents(f"${match.group(1)}.{match.group(2) or '00'}")


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "searchsession", "irclickid", "irgwc"))
    ]
    normalized = parsed._replace(query=urlencode(filtered_query), fragment="")
    return urlunparse(normalized)


def absolute_url(base_url: str, href: str) -> str:
    return canonicalize_url(urljoin(base_url, href))


def iter_json_ld_objects(html: str) -> Iterable[Any]:
    for raw_script in JSON_LD_PATTERN.findall(html):
        payload = clean_text(raw_script)
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        yield data


def iter_application_json_objects(html: str) -> Iterable[Any]:
    for raw_script in APPLICATION_JSON_PATTERN.findall(html):
        payload = raw_script.strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        yield data


def iter_nested_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_nested_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_nested_dicts(child)


def iter_sports_event_objects(html: str) -> Iterable[dict[str, Any]]:
    for top_level in iter_json_ld_objects(html):
        for node in iter_nested_dicts(top_level):
            if str(node.get("@type", "")).lower() == "sportsevent":
                yield node


def extract_title(html: str) -> str | None:
    match = TITLE_PATTERN.search(html)
    if not match:
        return None
    return strip_tags(match.group(1))


def extract_event_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for part in reversed(parts):
        if EVENT_ID_PATTERN.fullmatch(part):
            return part
    return parsed.path.strip("/") or url


def parse_match_metadata(name: str | None) -> tuple[str | None, str | None, int | None, str | None]:
    if not name:
        return None, None, None, None
    cleaned = clean_text(name)
    teams: tuple[str | None, str | None] = (None, None)
    matchup = MATCHUP_PATTERN.search(cleaned)
    if matchup:
        teams = (clean_text(matchup.group(1)), clean_text(matchup.group(2)))
    match_number = None
    match_number_match = MATCH_NUMBER_PATTERN.search(cleaned)
    if match_number_match:
        match_number = int(match_number_match.group(1))
    stage = None
    paren = PAREN_PATTERN.search(cleaned)
    if paren:
        stage = clean_text(paren.group(1))
    elif " - " in cleaned:
        suffix = cleaned.split(" - ", 1)[1]
        if not MATCH_NUMBER_PATTERN.search(suffix):
            stage = clean_text(suffix)
    return teams[0], teams[1], match_number, stage


def find_nearby_text(html: str, needle: str, radius: int = 800) -> str:
    index = html.find(needle)
    if index == -1:
        return ""
    start = max(index - radius, 0)
    end = min(index + radius, len(html))
    return strip_tags(html[start:end])


def unique_by_key(items: Iterable[Any], key_func) -> list[Any]:
    seen: set[Any] = set()
    unique: list[Any] = []
    for item in items:
        key = key_func(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
