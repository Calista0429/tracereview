"""Subprocess entry point: ``python -m app.services.pdf_worker <path>``.

stdout carries exactly one JSON document: the parsed document on success (exit 0) or
``{"error": {"code": ...}}`` on failure (non-zero exit). Nothing about the file's text or
location is ever printed.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from app.schemas import ErrorCode
from app.services.pdf_parser import PdfParseError, parse_pdf


def _emit_error(code: ErrorCode) -> None:
    sys.stdout.write(json.dumps({"error": {"code": code.value}}))


def main(argv: list[str]) -> int:
    logging.disable(logging.CRITICAL)  # pdfminer logs warnings that may include file details
    if len(argv) != 2:
        _emit_error(ErrorCode.INTERNAL_ERROR)
        return 64
    try:
        document = parse_pdf(Path(argv[1]))
    except PdfParseError as exc:
        _emit_error(exc.code)
        return 2
    except Exception:  # noqa: BLE001 - never let a traceback (and its paths) reach the parent
        _emit_error(ErrorCode.INTERNAL_ERROR)
        return 3
    sys.stdout.write(document.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
