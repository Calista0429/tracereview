#!/usr/bin/env python
"""Generate the four fictional Capital Call Notice fixtures and ``fixtures/manifest.json``.

The layout is fixed so that every label and value sits at known coordinates. The output is
byte-for-byte reproducible (ReportLab ``invariant=1``), so the SHA-256 values in the
manifest only change when the content changes.

Usage:  python scripts/generate_fixtures.py [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from reportlab.lib import pdfencrypt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
MARKER = "TRACEREVIEW-CALL-V1"
PAGE_W, PAGE_H = A4

# Layout constants (PDF points, measured from the top-left of the page).
LABEL_X = 72
VALUE_X = 300
FIRST_ROW_BASELINE = 300
ROW_SPACING = 32
FONT = ("Helvetica", 11)

LABELS = [
    "Fund name",
    "Currency",
    "Payment due date",
    "Investment contribution",
    "Management fee",
    "Total amount due",
]


def row_baseline(index: int) -> float:
    """Distance of the text baseline of row ``index`` from the top of the page."""
    return FIRST_ROW_BASELINE + ROW_SPACING * index


def normal_rows(
    fund: str,
    due: str,
    *,
    investment: str = "48,000.00",
    fee: str = "2,000.00",
    total: str = "50,000.00",
    currency: str = "USD",
) -> list[tuple[str, str]]:
    values = [fund, currency, due, investment, fee, total]
    return list(zip(LABELS, values, strict=True))


def build_pdf(
    path: Path,
    rows: list[tuple[str, str]],
    *,
    marker: str | None = MARKER,
    pages: int = 1,
    rotate: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    user_password: str | None = None,
    owner_password: str | None = None,
    text_layer: bool = True,
    extra_lines: tuple[str, ...] = (),
) -> None:
    """Draw a notice. Options beyond the defaults exist so tests can build unsupported files."""
    encrypt = None
    if user_password is not None or owner_password is not None:
        encrypt = pdfencrypt.StandardEncryption(
            user_password or "", ownerPassword=owner_password or "owner"
        )
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1, encrypt=encrypt)
    c.setTitle("TraceReview fictional capital call notice")
    c.setAuthor("TraceReview fixtures")
    for _ in range(pages):
        if rotate:
            c.setPageRotation(rotate)
        if cropbox:
            c.setCropBox(cropbox)
        if text_layer:
            _draw_page(c, rows, marker, extra_lines)
        else:
            # A "scan": drawn shapes only, no text layer.
            c.rect(72, 200, 400, 400, stroke=1, fill=0)
        c.showPage()
    c.save()


def _draw_page(
    c: canvas.Canvas, rows: list[tuple[str, str]], marker: str | None, extra_lines: tuple[str, ...]
) -> None:
    def y(from_top: float) -> float:
        return PAGE_H - from_top

    c.setFont("Helvetica-Bold", 12)
    c.drawString(LABEL_X, y(90), "FICTIONAL DEMO DATA")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(LABEL_X, y(140), "Capital Call Notice")
    if marker:
        c.setFont("Helvetica", 9)
        c.drawString(LABEL_X, y(180), marker)
    c.setFont(*FONT)
    for index, (label, value) in enumerate(rows):
        baseline = y(row_baseline(index))
        c.drawString(LABEL_X, baseline, label)
        if value:
            c.drawString(VALUE_X, baseline, value)
    for offset, line in enumerate(extra_lines):
        c.drawString(LABEL_X, y(row_baseline(len(rows)) + ROW_SPACING * (offset + 1)), line)
    c.setFont("Helvetica", 8)
    c.drawString(LABEL_X, y(790), "Invented for software demonstration only. Not a real fund or notice.")


SAMPLES = [
    {
        "id": "normal",
        "profile": "none",
        "title": "Normal notice",
        "description": "All six fields present; extraction is correct.",
        "rows": normal_rows("Example Growth Fund I", "2026-11-10"),
    },
    {
        "id": "amount-error",
        "profile": "total_extra_zero",
        "title": "Preset total error",
        "description": (
            "The PDF says 50,000.00. A deliberately injected extraction fault records "
            "500,000.00 as the candidate total."
        ),
        "rows": normal_rows("Example Income Fund II", "2026-11-17"),
    },
    {
        "id": "missing-extraction",
        "profile": "drop_due_date",
        "title": "Preset missing due date",
        "description": (
            "The due date is in the PDF and can be located. A deliberately injected "
            "extraction fault leaves the candidate empty."
        ),
        "rows": normal_rows("Example Credit Fund III", "2026-11-24"),
    },
    {
        "id": "missing-source",
        "profile": "none",
        "title": "Missing source value",
        "description": "The due-date label is present but its value is blank in the PDF.",
        "rows": normal_rows("Example Venture Fund IV", ""),
    },
]


def generate(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for sample in SAMPLES:
        filename = f"{sample['id']}.pdf"
        target = out_dir / filename
        build_pdf(target, sample["rows"])
        samples.append(
            {
                "id": sample["id"],
                "file": filename,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "profile": sample["profile"],
                "title": sample["title"],
                "description": sample["description"],
            }
        )
    manifest = {"version": 1, "template_id": "capital_call_v1", "samples": samples}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "fixtures")
    args = parser.parse_args()
    manifest = generate(args.out)
    for sample in manifest["samples"]:
        print(f"{sample['file']}  {sample['sha256']}  profile={sample['profile']}")


if __name__ == "__main__":
    main()
