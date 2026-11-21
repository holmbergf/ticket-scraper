"""Cleaning helpers shared by crawl and migration jobs.

Deliberately thin, following elt-pipeline: ingestion lands data close to its
native shape. All real shaping (team/city/stage normalisation, dedupe across
crawls, joins) happens in dbt silver — never here and never in parsers.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

# Natural keys: one row per key within a single crawl batch.
EVENTS_NATURAL_KEY = ["source", "event_id_external"]
SNAPSHOTS_NATURAL_KEY = ["source", "event_id_external", "crawl_ts_utc"]
LISTINGS_NATURAL_KEY = [
    "source", "event_id_external", "crawl_ts_utc",
    "listing_price_cents", "section", "row",
]


def dedupe(df: pd.DataFrame, natural_key: list[str]) -> pd.DataFrame:
    key = [c for c in natural_key if c in df.columns]
    if key:
        df = df.drop_duplicates(subset=key, keep="last")
    return df.drop_duplicates().reset_index(drop=True)


def content_hash(df: pd.DataFrame) -> str:
    """Stable hash of frame content; identical re-runs produce identical keys."""
    if df.empty:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    # Sort rows on every column so fetch order never changes the key.
    ordered = df.sort_values(by=list(df.columns), kind="mergesort").reset_index(drop=True)
    hashed = pd.util.hash_pandas_object(ordered.sort_index(axis=1), index=False)
    return hashlib.sha256(
        hashed.values.tobytes() + json.dumps(list(df.columns)).encode()
    ).hexdigest()[:16]
