"""Settings from environment. See .env.example at the repo root.

The repository working tree is the storage layer — data lives under
``data/`` and is committed by the ingest workflow — so the only settings
are paths. GitHub Actions and local runs use identical variable names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# data-integration/src/ticket_ingest/config.py -> repo root is 3 parents up
# from the package dir: ticket_ingest/ -> src/ -> data-integration/ -> root.
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    # Root of the committed data zones: raw/, _manifests/, data_warehouse/.
    data_dir: Path = REPO_ROOT / "data"
    # Raw HTML/JSON page snapshots for debugging. Gitignored, never committed:
    # pages are re-fetchable and would dwarf the Parquet raw zone.
    raw_html_dir: Path = REPO_ROOT / "data" / "raw_html"
    # Collection definitions (one TOML file per tracked collection).
    collections_dir: Path = REPO_ROOT / "collections"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", str(REPO_ROOT / "data")))
        return cls(
            data_dir=data_dir,
            raw_html_dir=Path(os.getenv("RAW_HTML_DIR", str(data_dir / "raw_html"))),
            collections_dir=Path(os.getenv("COLLECTIONS_DIR", str(REPO_ROOT / "collections"))),
        )

    @property
    def warehouse_dir(self) -> Path:
        return self.data_dir / "data_warehouse"
