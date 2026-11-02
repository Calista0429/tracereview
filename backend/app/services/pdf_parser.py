"""Deterministic source extraction for the single ``capital_call_v1`` template.

For each field the parser finds its unique printed label, takes the words to the right on the
same line and records their text plus the union bounding box. It never guesses: a label that
is missing, repeated or followed by nothing is reported as such and carries no evidence box.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from app.domain.values import FIELD_LABELS, FIELD_ORDER, FieldValueError, normalize_field
from app.schemas import (
    ErrorCode,
    Evidence,
    EvidenceBox,
    FieldKey,
    ParsedDocument,
    ParsedField,
    SourceParseStatus,
)

TEMPLATE_ID = "capital_call_v1"
PARSER_VERSION = "v1"
TEMPLATE_MARKER = "TRACEREVIEW-CALL-V1"

_X_TOLERANCE = 1.5
_Y_TOLERANCE = 3.0
_LINE_TOLERANCE = 3.0  # words whose tops differ by less than this share a line
_BOX_TOLERANCE = 0.01  # points; absorbs float noise on boxes that touch the page edge


class PdfParseError(Exception):
    """A refusal with a stable error code. The message never contains paths or document text."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_pdf(path: Path) -> ParsedDocument:
    sha256 = _sha256(path)
    try:
        return _parse(path, sha256)
    except PdfParseError:
        raise
    except PdfminerException as exc:
        if exc.args and isinstance(exc.args[0], PDFPasswordIncorrect):
            raise PdfParseError(ErrorCode.ENCRYPTED_PDF, "Encrypted PDFs are not supported.") from None
        raise PdfParseError(ErrorCode.INVALID_PDF, "The file is not a readable PDF.") from None
    except Exception:  # noqa: BLE001 - any parser failure on untrusted bytes means "unreadable"
        raise PdfParseError(ErrorCode.INVALID_PDF, "The file is not a readable PDF.") from None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse(path: Path, sha256: str) -> ParsedDocument:
    with pdfplumber.open(path) as pdf:
        if pdf.doc.encryption is not None:
            raise PdfParseError(ErrorCode.ENCRYPTED_PDF, "Encrypted PDFs are not supported.")
        if len(pdf.pages) != 1:
            raise PdfParseError(ErrorCode.UNSUPPORTED_LAYOUT, "Only single-page PDFs are supported.")
        page = pdf.pages[0]
        _require_plain_page(page)
        width, height = float(page.width), float(page.height)
        words = page.extract_words(x_tolerance=_X_TOLERANCE, y_tolerance=_Y_TOLERANCE)

    if not words:
        raise PdfParseError(
            ErrorCode.UNSUPPORTED_LAYOUT, "The PDF has no text layer (scanned files are not supported)."
        )
    if sum(1 for w in words if w["text"] == TEMPLATE_MARKER) != 1:
        raise PdfParseError(ErrorCode.UNSUPPORTED_TEMPLATE, "The document is not a supported template.")

    lines = _group_lines(words)
    fields = [_parse_field(key, lines, sha256, width, height) for key in FIELD_ORDER]
    return ParsedDocument(sha256=sha256, page_width=width, page_height=height, fields=fields)


def _require_plain_page(page: Any) -> None:
    unsupported = PdfParseError(
        ErrorCode.UNSUPPORTED_LAYOUT, "Rotated or cropped pages are not supported."
    )
    if (page.rotation or 0) % 360 != 0:
        raise unsupported
    media, crop = page.mediabox, page.cropbox
    if any(abs(a - b) > _BOX_TOLERANCE for a, b in zip(media, crop, strict=True)):
        raise unsupported
    if abs(media[0]) > _BOX_TOLERANCE or abs(media[1]) > _BOX_TOLERANCE:
        raise unsupported
    if not (math.isfinite(page.width) and math.isfinite(page.height)) or page.width <= 0 or page.height <= 0:
        raise unsupported


def _group_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= _LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _find_label(lines: list[list[dict[str, Any]]], tokens: list[str]) -> list[tuple[list, int]]:
    """Every (line, index of first word after the label) where the label's words appear."""
    matches = []
    n = len(tokens)
    for line in lines:
        texts = [w["text"] for w in line]
        for i in range(len(texts) - n + 1):
            if texts[i : i + n] == tokens:
                matches.append((line, i + n))
    return matches


def _parse_field(
    key: FieldKey, lines: list[list[dict[str, Any]]], sha256: str, width: float, height: float
) -> ParsedField:
    matches = _find_label(lines, FIELD_LABELS[key].split())
    if not matches:
        return ParsedField(key=key, source_parse_status=SourceParseStatus.MISSING)
    if len(matches) > 1:
        return ParsedField(key=key, source_parse_status=SourceParseStatus.AMBIGUOUS)

    line, start = matches[0]
    value_words = line[start:]
    if not value_words:
        return ParsedField(key=key, source_parse_status=SourceParseStatus.MISSING)

    text = " ".join(w["text"] for w in value_words)
    if key is FieldKey.CURRENCY and text != "USD":
        raise PdfParseError(ErrorCode.UNSUPPORTED_CURRENCY, "Only USD notices are supported.")

    box = _normalised_box(value_words, width, height)
    if box is None:
        return ParsedField(key=key, source_text=text, source_parse_status=SourceParseStatus.INVALID)
    evidence = Evidence(document_sha256=sha256, page=1, bbox=box)
    try:
        value = normalize_field(key, text)
    except FieldValueError:
        return ParsedField(
            key=key, source_text=text, source_parse_status=SourceParseStatus.INVALID, evidence=evidence
        )
    return ParsedField(
        key=key,
        source_text=text,
        source_value=value,
        source_parse_status=SourceParseStatus.VALID,
        evidence=evidence,
    )


def _normalised_box(words: list[dict[str, Any]], width: float, height: float) -> EvidenceBox | None:
    """Union of the word boxes as fractions of the page, origin at the top-left corner."""
    x0 = min(w["x0"] for w in words)
    top = min(w["top"] for w in words)
    x1 = max(w["x1"] for w in words)
    bottom = max(w["bottom"] for w in words)
    if not all(math.isfinite(v) for v in (x0, top, x1, bottom)) or x1 <= x0 or bottom <= top:
        return None
    if (
        x0 < -_BOX_TOLERANCE
        or top < -_BOX_TOLERANCE
        or x1 > width + _BOX_TOLERANCE
        or bottom > height + _BOX_TOLERANCE
    ):
        return None
    x0, top = max(x0, 0.0), max(top, 0.0)
    x1, bottom = min(x1, width), min(bottom, height)
    return EvidenceBox(
        x=x0 / width, y=top / height, width=(x1 - x0) / width, height=(bottom - top) / height
    )
