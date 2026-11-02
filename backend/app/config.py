from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

ACTOR = "local-reviewer"  # the only identity; callers can never choose it
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5,242,880


@dataclass(frozen=True)
class Settings:
    data_dir: Path = REPO_ROOT / "data"
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    parse_timeout_seconds: float = 10.0
    sqlite_timeout_seconds: float = 5.0
    manifest_path: Path = REPO_ROOT / "fixtures" / "manifest.json"
    parser_command: tuple[str, ...] = (sys.executable, "-m", "app.services.pdf_worker")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tracereview.sqlite3"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for folder in (self.data_dir, self.originals_dir, self.tmp_dir):
            folder.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data_dir = os.environ.get("TRACEREVIEW_DATA_DIR")
    if data_dir:
        return Settings(data_dir=Path(data_dir).expanduser().resolve())
    return Settings()
