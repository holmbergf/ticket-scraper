# data-integration

Ingestion package (`ticket-ingest` CLI) for resale ticket prices.
Crawls the marketplaces configured for one collection (see
[`collections/`](../collections/README.md)) and lands content-addressed
Parquet partitions + run manifests under the repo's `data/` directory,
stamped with `(collection_slug, event_key)` canonical identity.
See the repo [README](../README.md) and
[docs/architecture.md](../docs/architecture.md) for the full design.

| Module | Responsibility |
|---|---|
| `config.py` | `Settings` from environment (paths only) |
| `collections.py` | TOML collection loading/validation + canonical-event resolution |
| `parsers/` | Per-marketplace discovery + event-page parsers (raw, unnormalized) |
| `http.py` | HTTP pool + headless Chrome + Playwright fetching, retries, WAF handling |
| `models.py` | `Event`, `MarketSnapshot`, `Listing`, `ParseResult` dataclasses |
| `schemas.py` | Frozen PyArrow raw schemas (the ingestion↔bronze contract) |
| `clean.py` | Content hash + natural-key dedupe shared by jobs |
| `storage.py` | Partitioned Parquet writes, manifests, `StateStore`, raw-HTML store |
| `jobs.py` | Marketplace adapters × collection source settings; crawl orchestration |
| `alerts.py` | Snapshot diffs + price-alert rules over the raw zone |
| `migrate.py` | SQLite → Parquet raw-zone import |
| `publish_warehouse.py` | Exports dbt output + collection/event catalogs to `data/data_warehouse/` |
| `cli.py` | `ticket-ingest {crawl --collection, collections, migrate-sqlite}` |

```bash
pip install -e "./data-integration[dev]"
playwright install chromium
ticket-ingest collections list
ticket-ingest crawl --collection nfl-cowboys-at-seahawks-2026-12-07
ticket-ingest crawl --collection fifa-world-cup-2026 --source gametime
python -m pytest data-integration/tests -q
```
