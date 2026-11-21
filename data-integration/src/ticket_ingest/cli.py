"""ticket-ingest CLI: ``crawl`` and ``migrate-sqlite`` subcommands.

Warehouse publishing is a separate step:
``python -m ticket_ingest.publish_warehouse`` after ``dbt build``.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from .alerts import EXPECTED_EVENT_COUNTS, evaluate_alerts, get_snapshot_diffs
from .config import Settings
from .http import BrowserFetchConfig
from .jobs import SOURCES, CrawlOptions, SourceStats, run_crawl
from .storage import get_storage

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = Settings.from_env()
    if getattr(args, "data_dir", None):
        settings = Settings(data_dir=Path(args.data_dir), raw_html_dir=Path(args.data_dir) / "raw_html")
    storage = get_storage(settings)

    if args.command == "migrate-sqlite":
        from .migrate import migrate_sqlite

        counts = migrate_sqlite(Path(args.db_path), storage)
        print(f"Migrated {counts} from {args.db_path} into {settings.data_dir}/raw")
        return

    _run_crawl_command(settings, storage, args)


def _run_crawl_command(settings, storage, args) -> None:
    selected = args.source or list(SOURCES)
    options = CrawlOptions(
        max_events=args.max_events,
        timeout=args.timeout,
        fetch_mode=args.fetch_mode,
        workers=args.workers,
        parallel=args.parallel,
        browser_config=BrowserFetchConfig(chrome_path=args.chrome_path, browser_timeout_s=args.browser_timeout),
    )
    wall_start = time.monotonic()
    results = run_crawl(settings, storage, selected, options)
    wall_elapsed = time.monotonic() - wall_start

    all_stats: list[SourceStats] = []
    source_diffs = []
    for source in selected:
        crawl_ts, stats = results.get(source, ("", SourceStats(source=source, error_message="crawl failed")))
        if crawl_ts and not stats.error_message:
            diffs = get_snapshot_diffs(settings.data_dir, source, crawl_ts)
            stats.changed_events = len(diffs)
            source_diffs.append((source, diffs))
        all_stats.append(stats)

    alerts = evaluate_alerts(source_diffs)
    for stats in all_stats:
        expected = EXPECTED_EVENT_COUNTS.get(stats.source, 0)
        if expected and stats.events_discovered < expected * 0.5:
            alerts.append(f"[{stats.source}] Data quality: only {stats.events_discovered} events discovered (expected ~{expected})")
        if stats.error_message:
            alerts.append(f"[{stats.source}] Crawl error: {stats.error_message}")
    for stats in all_stats:
        stats.alerts = [a for a in alerts if a.startswith(f"[{stats.source}]")]

    _print_summary(all_stats, wall_elapsed, settings.data_dir)
    for alert in alerts:
        print(f"  ALERT: {alert}")
    if args.alerts_json:
        Path(args.alerts_json).write_text(json.dumps(alerts, indent=2))
        print(f"Wrote {len(alerts)} alert(s) to {args.alerts_json}")


def _print_summary(all_stats, wall_elapsed, data_dir) -> None:
    total_events = total_snapshots = total_listings = total_changed = total_errors = 0
    print()
    print(f"{'Source':<12} {'Time':>6} {'Events':>7} {'Snaps':>7} {'Lists':>7} {'Chg':>5} {'Err':>5}")
    print("-" * 60)
    for s in all_stats:
        if s.error_message:
            print(f"{s.source:<12} {'FAIL':>6}   {s.error_message}")
            continue
        print(f"{s.source:<12} {s.elapsed_s:>5.1f}s {s.events_discovered:>7} {s.snapshots:>7} {s.listings:>7} {s.changed_events:>5} {s.fetch_errors:>5}")
        total_events += s.events_discovered
        total_snapshots += s.snapshots
        total_listings += s.listings
        total_changed += s.changed_events
        total_errors += s.fetch_errors
    print("-" * 60)
    print(f"{'TOTAL':<12} {wall_elapsed:>5.1f}s {total_events:>7} {total_snapshots:>7} {total_listings:>7} {total_changed:>5} {total_errors:>5}")
    print(f"data={data_dir}")
    print()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ticket-ingest", description="Monitor FIFA World Cup 2026 ticket prices.")
    parser.add_argument("--data-dir", default=None, help="Data root (default: repo data/ or $DATA_DIR).")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="Crawl ticket marketplaces and land raw Parquet.")
    crawl.add_argument("--source", action="append", choices=sorted(SOURCES),
                       help="Restrict to one source. Repeatable.")
    crawl.add_argument("--max-events", type=int, default=0,
                       help="Max event pages per source (0 = unlimited).")
    crawl.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    crawl.add_argument("--fetch-mode", choices=["auto", "http", "browser", "playwright"], default="auto")
    crawl.add_argument("--chrome-path", default=None, help="Path to Chrome for browser fetches.")
    crawl.add_argument("--browser-timeout", type=float, default=20.0)
    crawl.add_argument("--workers", type=int, default=8)
    crawl.add_argument("--no-parallel", dest="parallel", action="store_false", default=True)
    crawl.add_argument("--alerts-json", default=None, metavar="PATH",
                       help="Write triggered alerts to JSON (for CI consumption).")
    crawl.add_argument("-v", "--verbose", action="store_true", default=False)

    migrate = sub.add_parser("migrate-sqlite", help="Import a SQLite DB (events/market_snapshots/listings tables) into the raw zone.")
    migrate.add_argument("db_path", help="Path to the SQLite database.")
    migrate.add_argument("-v", "--verbose", action="store_true", default=False)
    return parser


if __name__ == "__main__":
    main()
