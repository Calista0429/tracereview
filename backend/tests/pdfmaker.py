"""Shared access to the fixture generator for tests that need custom PDFs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import generate_fixtures as gf  # noqa: E402

build_pdf = gf.build_pdf
normal_rows = gf.normal_rows
LABELS = gf.LABELS


def manifest() -> dict:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def expected(sample_id: str) -> dict:
    return json.loads((FIXTURES / "expected" / f"{sample_id}.json").read_text(encoding="utf-8"))
