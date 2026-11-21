"""Storage: partitioned Parquet in the repo working tree + JSON run manifests.

Layout under ``data/`` (the git repository is the storage layer):

  raw/events/source=<source>/part-<content_hash>.parquet
  raw/market_snapshots/crawl_date=<date>/part-<content_hash>.parquet
  raw/listings/crawl_date=<date>/part-<content_hash>.parquet
  _manifests/<dataset>/<run_id>.json
  data_warehouse/{silver,gold,semantic}/<table>.parquet   (publish step)

Keys are content-addressed, so re-running a crawl is a no-op rather than
appending duplicates. Manifests are the watermark/state store: they
record covered crawl timestamps and row counts per run. There is no state
database to back up or disagree with the data. A crawl commit only ever
adds its own small partition files (~125 KB); no existing file is
rewritten or grows.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .clean import content_hash
from .config import Settings
from .schemas import DATASETS, SCHEMAS, align

log = logging.getLogger(__name__)


@dataclass
class WriteResult:
    dataset: str
    keys: list[str] = field(default_factory=list)
    skipped_keys: list[str] = field(default_factory=list)
    rows: int = 0
    covered_crawl_ts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


class LocalStorage:
    """Filesystem backend rooted at ``data/`` (the committed data zones)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def put_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def list_keys(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


def get_storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.data_dir)


def _partition_groups(df: pd.DataFrame, dataset: str):
    if dataset == "events":
        for source, part in df.groupby(df["source"].astype(str)):
            yield f"source={source}", part
    else:  # market_snapshots, listings: one partition per crawl day
        for date, part in df.groupby(df["crawl_ts_utc"].astype(str).str[:10]):
            yield f"crawl_date={date}", part


def write_dataset(storage: LocalStorage, df: pd.DataFrame, dataset: str, source: str) -> WriteResult:
    """Write df as content-addressed Parquet partitions + one run manifest."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}, expected one of {DATASETS}")
    result = WriteResult(dataset=dataset, rows=len(df))
    if df.empty:
        return result
    df = align(df, dataset)
    if "crawl_ts_utc" in df.columns:
        result.covered_crawl_ts = sorted(df["crawl_ts_utc"].astype(str).unique())
    result.sources = sorted(df["source"].astype(str).unique())
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + content_hash(df)
    for partition, part in _partition_groups(df, dataset):
        # Hash without the import timestamp: identical data re-fetched later
        # must map to the same key (idempotent), not a new file per run.
        hash_part = part.drop(columns=["timestamp_imported"], errors="ignore")
        key = f"raw/{dataset}/{partition}/part-{content_hash(hash_part)}.parquet"
        if storage.exists(key):
            result.skipped_keys.append(key)
            continue
        buf = io.BytesIO()
        # Write with the frozen schema: an all-null column must still land
        # typed (VARCHAR), not Parquet NULL, or strict readers fail on it.
        pq.write_table(
            pa.Table.from_pandas(part, schema=SCHEMAS[dataset], preserve_index=False),
            buf, compression="zstd")
        storage.put_bytes(key, buf.getvalue())
        result.keys.append(key)
    manifest = {
        "run_id": run_id,
        "dataset": dataset,
        "source": source,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "rows": result.rows,
        "keys": result.keys,
        "skipped_keys": result.skipped_keys,
        "covered_crawl_ts": result.covered_crawl_ts,
        "sources": result.sources,
        "content_hash": content_hash(df),
    }
    storage.put_bytes(f"_manifests/{dataset}/{run_id}.json", json.dumps(manifest, indent=2).encode())
    log.info("wrote %s: %d rows, %d new files, %d skipped", dataset, result.rows, len(result.keys), len(result.skipped_keys))
    return result


class StateStore:
    """Watermarks derived from run manifests + the raw zone itself."""

    def __init__(self, storage: LocalStorage):
        self.storage = storage

    def manifests(self, dataset: str) -> list[dict]:
        out = []
        for key in self.storage.list_keys(f"_manifests/{dataset}/"):
            if key.endswith(".json"):
                out.append(json.loads(self.storage.get_bytes(key)))
        return out

    def crawl_timestamps(self, dataset: str = "market_snapshots") -> list[str]:
        stamps: set[str] = set()
        for m in self.manifests(dataset):
            stamps.update(m.get("covered_crawl_ts") or [])
        return sorted(stamps)

    def event_ids_for_source(self, source: str) -> list[str]:
        """Known event ids for a source, from the raw events partition.

        Used for Viagogo cross-source expansion (event URLs are built from
        StubHub ids) when StubHub was not crawled in the same run.
        """
        keys = [k for k in self.storage.list_keys(f"raw/events/source={source}/") if k.endswith(".parquet")]
        ids: set[str] = set()
        for key in keys:
            table = pq.read_table(io.BytesIO(self.storage.get_bytes(key)), columns=["event_id_external"])
            ids.update(v for v in table.column("event_id_external").to_pylist() if v)
        return sorted(ids)


class RawHtmlStore:
    """Raw page snapshots for debugging (gitignored, never committed)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, source: str, page_key: str, crawl_ts_utc: str, body: str, suffix: str = ".html") -> str:
        safe_key = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in page_key)[:120]
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
        path = self.root / source / f"{crawl_ts_utc.replace(':', '-')}_{safe_key}_{digest}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return str(path)
