"""Temp uploads and the hash-named original store. No upload filename ever builds a path."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from app.config import Settings
from app.errors import AppError
from app.schemas import ErrorCode

_CHUNK = 1 << 20
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class Promoted:
    path: Path
    created: bool  # True only when this call created the file


def original_path(settings: Settings, sha256: str) -> Path:
    if not _SHA_RE.match(sha256):
        raise ValueError("not a sha256 hex digest")
    return settings.originals_dir / f"{sha256}.pdf"


def save_upload(source: BinaryIO, settings: Settings) -> StoredUpload:
    """Stream ``source`` to a random temp file, hashing it and enforcing the size limit."""
    settings.ensure_dirs()
    path = settings.tmp_dir / f"{uuid.uuid4().hex}.upload"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "xb") as out:
            while chunk := source.read(_CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise AppError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"The file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MiB limit.",
                    )
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        discard(path)
        raise
    return StoredUpload(path=path, sha256=digest.hexdigest(), size=size)


def promote(tmp_path: Path, sha256: str, settings: Settings) -> Promoted:
    """Move a verified temp upload into the original store, creating the file atomically.

    ``os.link`` fails if the target exists, so exactly one caller ever "creates" a given
    original. A pre-existing file with the right hash is reused; a corrupt one is replaced.
    """
    target = original_path(settings, sha256)
    try:
        os.link(tmp_path, target)
    except FileExistsError:
        if sha256_of(target) == sha256:
            return Promoted(path=target, created=False)
        os.replace(tmp_path, target)
        return Promoted(path=target, created=True)
    return Promoted(path=target, created=True)


def discard(path: Path | None) -> None:
    if path is not None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def original_status(settings: Settings, sha256: str) -> Literal["ok", "missing", "mismatch"]:
    path = original_path(settings, sha256)
    try:
        actual = sha256_of(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "missing"
    return "ok" if actual == sha256 else "mismatch"
