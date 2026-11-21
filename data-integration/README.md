# data-integration

Ingestion package (`ticket-ingest` CLI) for FIFA World Cup 2026 resale
ticket prices. Crawls five marketplaces and lands content-addressed
Parquet partitions + run manifests under the repo's `data/` directory.
See the repo [README](../README.md) and
[docs/architecture.md](../docs/architecture.md) for the full design.

| Module | Responsibility |
|---|---|
| `config.py` | `Settings` from environment (data paths only — no cloud backend) |
| `parsers/` | Per-marketplace discovery + event-page parsers (raw, unnormalized) |
| `http.py` | HTTP pool + headless Chrome + Playwright fetching, retries, WAF handling |
| `models.py` | `Event`, `MarketSnapshot`, `Listing`, `ParseResult` dataclasses |
| `schemas.py` | Frozen PyArrow raw schemas (the ingestion↔bronze contract) |
| `clean.py` | Content hash + natural-key dedupe shared by jobs |
| `storage.py` | Partitioned Parquet writes, manifests, `StateStore`, raw-HTML store |
| `jobs.py` | Per-source crawl orchestration (fetch → parse → land) |
| `alerts.py` | Snapshot diffs + price-alert rules over the raw zone |
| `migrate.py` | SQLite → Parquet raw-zone import |
| `publish_warehouse.py` | Exports dbt output to `data/data_warehouse/` Parquet |
| `cli.py` | `ticket-ingest {crawl,migrate-sqlite}` |

```bash
pip install -e "./data-integration[dev]"
playwright install chromium
ticket-ingest crawl                       # all sources
ticket-ingest crawl --source gametime     # one source
python -m pytest data-integration/tests -q
```
