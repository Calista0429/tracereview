"""One error shape for the whole API (spec section 10.5)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.schemas import ErrorBody, ErrorCode, ErrorResponse

logger = logging.getLogger("tracereview")

STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.DOCUMENT_NOT_FOUND: 404,
    ErrorCode.DOCUMENT_DUPLICATE: 409,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.WRITE_CONFLICT: 409,
    ErrorCode.REVIEW_BLOCKED: 409,
    ErrorCode.REVIEW_INCOMPLETE: 409,
    ErrorCode.DOCUMENT_CONFIRMED: 409,
    ErrorCode.DOCUMENT_NOT_CONFIRMED: 409,
    ErrorCode.SOURCE_UNAVAILABLE: 409,
    ErrorCode.SOURCE_INTEGRITY_MISMATCH: 409,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_FILE_TYPE: 415,
    ErrorCode.INVALID_PDF: 422,
    ErrorCode.ENCRYPTED_PDF: 422,
    ErrorCode.UNSUPPORTED_LAYOUT: 422,
    ErrorCode.UNSUPPORTED_TEMPLATE: 422,
    ErrorCode.UNSUPPORTED_CURRENCY: 422,
    ErrorCode.INVALID_FIELD_VALUE: 422,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.PARSING_TIMEOUT: 504,
    ErrorCode.STORAGE_ERROR: 500,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE[self.code]


def not_found() -> AppError:
    return AppError(ErrorCode.DOCUMENT_NOT_FOUND, "Document not found.")


def translate_db_error(exc: Exception) -> AppError:
    """Map a database failure to a user-facing error without leaking SQL or paths."""
    orig = str(getattr(exc, "orig", exc)).lower()
    if isinstance(exc, OperationalError) and ("locked" in orig or "busy" in orig):
        return AppError(
            ErrorCode.WRITE_CONFLICT,
            "The database is busy or the document changed. Reload and try again.",
        )
    return AppError(ErrorCode.STORAGE_ERROR, "The data could not be saved.")


def error_response(error: AppError) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=error.code, message=error.message, details=error.details)
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": str(e["msg"])}
            for e in exc.errors()
        ]
        return error_response(
            AppError(ErrorCode.INVALID_REQUEST, "The request is not valid.", {"errors": problems})
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s", type(exc).__name__)
        return error_response(AppError(ErrorCode.INTERNAL_ERROR, "Something went wrong."))
