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


def _discover_repo_root() -> Path:
    """Find the checkout root from cwd or this file's location.

    An editable install resolves inside the checkout, but a regular
    install lands in site-packages — there the working directory (CI and
    local runs start at the repo root) is the only reliable anchor.
    """
    here = Path(__file__).resolve()
    for start in (Path.cwd(), here):
        for parent in (start, *start.parents):
            if (parent / "collections").is_dir() and (parent / "dbt-transform").is_dir():
                return parent
    # Editable layout fallback: ticket_ingest/ -> src/ -> data-integration/ -> root.
    return here.parents[3]


REPO_ROOT = _discover_repo_root()


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
