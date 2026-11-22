"""Collection definitions: the unit of composability for ticket-scraper.

A *collection* is one tracked thing with its own crawl configuration and
dashboard presence — a tournament (FIFA World Cup 2026), a single game
(Cowboys at Seahawks), or a multi-session event (the Masters, one
canonical event per round/day). Collections are declared as TOML files in
``collections/``; this module loads, validates, and applies them.

Canonical identity is two-level:
- ``collection_slug`` — which collection a row belongs to.
- ``event_key`` — the canonical event inside the collection, shared by
  every marketplace's listing of that event. ``event_uid`` downstream is
  ``collection_slug:event_key``.

Jobs assign both at land time (see ``assign_result``); parsers stay
source-shaped and collection-agnostic.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import REPO_ROOT, Settings
from .models import Event, ParseResult
from .utils import clean_text, extract_event_id_from_url

DEFAULT_COLLECTION_SLUG = "fifa-world-cup-2026"
KNOWN_SOURCES = ("fifacollect", "gametime", "stubhub", "viagogo", "vivid")
_KINDS = ("tournament", "game", "event", "series")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class CanonicalEvent:
    key: str
    name: str | None = None
    stage: str | None = None
    sequence: int | None = None
    participant_1: str | None = None
    participant_2: str | None = None
    starts_at_local: str | None = None
    venue_name: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    currency: str | None = None
    source_event_ids: dict[str, str] = field(default_factory=dict)
    match_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceEventUrl:
    event_key: str
    url: str


@dataclass(frozen=True)
class CollectionSource:
    source: str
    mode: str = "discovery"  # discovery | event_urls | cross_source
    discovery_url: str | None = None
    page_key: str | None = None
    fetch_mode: str | None = None
    event_scroll: bool = False
    event_wait_selector: str | None = None
    warmup_urls: tuple[str, ...] = ()
    max_workers: int | None = None
    expected_events: int = 0
    expand_subpages: bool = False
    subpage_fallback: bool = False
    subpage_interval_s: float = 0
    cross_source: str | None = None
    event_url_template: str | None = None
    discovery_terms: tuple[str, ...] = ()
    event_urls: tuple[SourceEventUrl, ...] = ()


@dataclass(frozen=True)
class CollectionConfig:
    slug: str
    title: str
    kind: str = "event"
    status: str = "active"
    description: str = ""
    timezone: str = "UTC"
    icon: str = "🎟️"
    accent_color: str = "#3aa76d"
    events: tuple[CanonicalEvent, ...] = ()
    sources: dict[str, CollectionSource] = field(default_factory=dict)
    priority_participants: tuple[str, ...] = ()
    priority_stages: tuple[str, ...] = ()
    path: Path | None = None

    @property
    def canonical_by_key(self) -> dict[str, CanonicalEvent]:
        return {e.key: e for e in self.events}

    def expected_events(self, source: str) -> int:
        cfg = self.sources.get(source)
        return cfg.expected_events if cfg else 0


def collections_dir(settings: Settings | None = None) -> Path:
    return (settings or Settings.from_env()).collections_dir


def load_collection(slug_or_path: str | Path, settings: Settings | None = None) -> CollectionConfig:
    path = Path(slug_or_path)
    if path.suffix != ".toml":
        path = collections_dir(settings) / f"{slug_or_path}.toml"
    if not path.exists():
        raise FileNotFoundError(f"collection config not found: {path}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return _parse_collection(raw, path)


def list_collections(settings: Settings | None = None) -> list[CollectionConfig]:
    root = collections_dir(settings)
    return [load_collection(p) for p in sorted(root.glob("*.toml"))]


def _parse_collection(raw: dict, path: Path) -> CollectionConfig:
    slug = str(raw.get("slug") or "")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"{path}: invalid or missing slug {slug!r}")
    if path.stem != slug:
        raise ValueError(f"{path}: filename must match slug {slug!r}")
    title = str(raw.get("title") or slug)
    kind = str(raw.get("kind") or "event")
    if kind not in _KINDS:
        raise ValueError(f"{path}: kind must be one of {_KINDS}, got {kind!r}")

    events: list[CanonicalEvent] = []
    seen_keys: set[str] = set()
    for item in raw.get("events", []):
        key = str(item.get("key") or "")
        if not _SLUG_RE.match(key):
            raise ValueError(f"{path}: invalid event key {key!r}")
        if key in seen_keys:
            raise ValueError(f"{path}: duplicate event key {key!r}")
        seen_keys.add(key)
        events.append(CanonicalEvent(
            key=key,
            name=_opt_str(item, "name"),
            stage=_opt_str(item, "stage"),
            sequence=int(item["sequence"]) if item.get("sequence") is not None else None,
            participant_1=_opt_str(item, "participant_1"),
            participant_2=_opt_str(item, "participant_2"),
            starts_at_local=_opt_str(item, "starts_at_local"),
            venue_name=_opt_str(item, "venue_name"),
            city=_opt_str(item, "city"),
            region=_opt_str(item, "region"),
            country=_opt_str(item, "country"),
            currency=_opt_str(item, "currency"),
            source_event_ids={str(k): str(v) for k, v in (item.get("source_event_ids") or {}).items()},
            match_terms=tuple(str(v) for v in item.get("match_terms", [])),
        ))

    sources: dict[str, CollectionSource] = {}
    for name, cfg in (raw.get("sources") or {}).items():
        if name not in KNOWN_SOURCES:
            raise ValueError(f"{path}: unknown source {name!r} (known: {KNOWN_SOURCES})")
        mode = str(cfg.get("mode") or "discovery")
        if mode not in ("discovery", "event_urls", "cross_source"):
            raise ValueError(f"{path}: source {name}: unknown mode {mode!r}")
        urls = tuple(
            SourceEventUrl(event_key=str(u["event_key"]), url=str(u["url"]))
            for u in cfg.get("event_urls", [])
        )
        for u in urls:
            if events and u.event_key not in seen_keys:
                raise ValueError(f"{path}: source {name}: event_url references unknown event {u.event_key!r}")
        sources[name] = CollectionSource(
            source=name,
            mode=mode,
            discovery_url=_opt_str(cfg, "discovery_url"),
            page_key=_opt_str(cfg, "page_key"),
            fetch_mode=_opt_str(cfg, "fetch_mode"),
            event_scroll=bool(cfg.get("event_scroll", False)),
            event_wait_selector=_opt_str(cfg, "event_wait_selector"),
            warmup_urls=tuple(str(v) for v in cfg.get("warmup_urls", [])),
            max_workers=int(cfg["max_workers"]) if cfg.get("max_workers") is not None else None,
            expected_events=int(cfg.get("expected_events") or 0),
            expand_subpages=bool(cfg.get("expand_subpages", False)),
            subpage_fallback=bool(cfg.get("subpage_fallback", False)),
            subpage_interval_s=float(cfg.get("subpage_interval_s") or 0),
            cross_source=_opt_str(cfg, "cross_source"),
            event_url_template=_opt_str(cfg, "event_url_template"),
            discovery_terms=tuple(str(v) for v in cfg.get("discovery_terms", [])),
            event_urls=urls,
        )
        if mode == "discovery" and not sources[name].discovery_url:
            raise ValueError(f"{path}: source {name}: discovery mode needs discovery_url")
        if mode == "event_urls" and not urls:
            raise ValueError(f"{path}: source {name}: event_urls mode needs at least one URL")
        if mode == "cross_source" and not (sources[name].cross_source and sources[name].event_url_template):
            raise ValueError(f"{path}: source {name}: cross_source mode needs cross_source + event_url_template")
    if not sources:
        raise ValueError(f"{path}: collection declares no sources")

    return CollectionConfig(
        slug=slug, title=title, kind=kind,
        status=str(raw.get("status") or "active"),
        description=str(raw.get("description") or ""),
        timezone=str(raw.get("timezone") or "UTC"),
        icon=str(raw.get("icon") or "🎟️"),
        accent_color=str(raw.get("accent_color") or "#3aa76d"),
        events=tuple(events), sources=sources,
        priority_participants=tuple(str(v) for v in raw.get("priority_participants", [])),
        priority_stages=tuple(str(v) for v in raw.get("priority_stages", [])),
        path=path,
    )


def _opt_str(item: dict, key: str) -> str | None:
    v = item.get(key)
    return str(v) if v is not None and str(v) != "" else None


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "event"


def _norm_url(url: str) -> str:
    p = urlparse(url or "")
    return f"{p.netloc.lower()}{p.path.rstrip('/')}"


def _date_part(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    return m.group(0) if m else None


class EventResolver:
    """Maps source-shaped events onto canonical collection events."""

    def __init__(self, collection: CollectionConfig):
        self.collection = collection
        self._by_source_id: dict[tuple[str, str], str] = {}
        self._by_url: dict[str, str] = {}
        for ev in collection.events:
            for src, ext in ev.source_event_ids.items():
                self._by_source_id[(src, str(ext))] = ev.key
        for src_name, src in collection.sources.items():
            for u in src.event_urls:
                self._by_url[_norm_url(u.url)] = u.event_key
                self._by_source_id.setdefault(
                    (src_name, extract_event_id_from_url(u.url)), u.event_key)

    def match_canonical(self, event: Event) -> CanonicalEvent | None:
        """The declared canonical event this source event is, if any."""
        by_key = self.collection.canonical_by_key
        if event.event_key and event.event_key in by_key:
            return by_key[event.event_key]
        key = self._by_source_id.get((event.source, str(event.event_id_external)))
        if key:
            return by_key[key]
        key = self._by_url.get(_norm_url(event.event_url))
        if key:
            return by_key[key]
        for ev in self.collection.events:
            if ev.sequence is not None and event.match_number == ev.sequence:
                return ev
        name = clean_text(event.event_name).lower()
        event_date = _date_part(event.event_start_local)
        for ev in self.collection.events:
            terms = [t.lower() for t in ev.match_terms] or [
                t.lower() for t in (ev.participant_1, ev.participant_2) if t]
            participants = {clean_text(event.team_1).lower(), clean_text(event.team_2).lower()}
            wanted = {t.lower() for t in (ev.participant_1, ev.participant_2) if t}
            by_participants = bool(wanted) and wanted <= participants
            by_terms = bool(terms) and all(t in name for t in terms)
            if not (by_participants or by_terms):
                continue
            want_date = _date_part(ev.starts_at_local)
            if want_date and event_date and want_date != event_date:
                continue
            return ev
        return None

    def derive_key(self, event: Event) -> str:
        """Fallback key for collections that don't declare canonical events."""
        if event.event_key:
            return event.event_key
        if event.match_number is not None:
            return f"match-{event.match_number}"
        teams = sorted(t for t in (event.team_1, event.team_2) if t and t != "TBD")
        date = _date_part(event.event_start_local)
        if teams:
            base = "-vs-".join(slugify(t) for t in teams)
            return f"{base}-{date}" if date else base
        if event.event_name:
            base = slugify(re.sub(r"\s*\(.*?\)\s*$", "", event.event_name))
            return f"{base}-{date}" if date else base
        return f"{event.source}-{event.event_id_external}"

    def assign_event(self, event: Event, *, trusted_single: bool = False) -> bool:
        """Stamp collection/event identity (+ fill canonical metadata gaps).

        Returns False when the collection declares canonical events and
        this source event matches none of them (caller drops it)."""
        canonical = self.match_canonical(event)
        if canonical is None and trusted_single and len(self.collection.events) == 1:
            canonical = self.collection.events[0]
        if canonical is None and self.collection.events:
            return False
        event.collection_slug = self.collection.slug
        if canonical is not None:
            event.event_key = canonical.key
            if event.match_number is None:
                event.match_number = canonical.sequence
            for attr, val in (
                ("stage", canonical.stage), ("team_1", canonical.participant_1),
                ("team_2", canonical.participant_2),
                ("event_start_local", canonical.starts_at_local),
                ("venue_name", canonical.venue_name), ("city", canonical.city),
                ("region", canonical.region), ("country", canonical.country),
                ("currency", canonical.currency),
            ):
                if not getattr(event, attr) and val:
                    setattr(event, attr, val)
        else:
            event.event_key = self.derive_key(event)
        return True

    def assign_result(self, result: ParseResult, *, trusted_single: bool = False) -> ParseResult:
        kept_events, key_by_external = [], {}
        for event in result.events:
            if self.assign_event(event, trusted_single=trusted_single):
                kept_events.append(event)
                key_by_external[(event.source, event.event_id_external)] = event.event_key
        kept_ids = set(key_by_external)
        snapshots, listings = [], []
        for snap in result.snapshots:
            key = key_by_external.get((snap.source, snap.event_id_external))
            if key is None and self.collection.events and not trusted_single:
                continue
            snap.collection_slug = self.collection.slug
            snap.event_key = key or snap.event_key
            snapshots.append(snap)
        for listing in result.listings:
            key = key_by_external.get((listing.source, listing.event_id_external))
            if key is None and self.collection.events and not trusted_single:
                continue
            listing.collection_slug = self.collection.slug
            listing.event_key = key or listing.event_key
            listings.append(listing)
        return ParseResult(events=kept_events, snapshots=snapshots, listings=listings)
