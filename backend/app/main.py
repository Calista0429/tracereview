from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import documents as documents_api
from app.config import Settings, load_settings
from app.db import make_engine, make_session_factory
from app.errors import AppError, error_response, register_error_handlers
from app.models import Base
from app.schemas import ErrorCode

API_PREFIX = "/api/v1"
_MULTIPART_OVERHEAD = 1024 * 1024  # allowance for form framing above the file's own limit


def _clear_stale_uploads(settings: Settings) -> None:
    """Remove temp uploads a crashed process left behind. Only the temp folder is touched,
    and with a single worker nothing can be mid-upload while the app is starting."""
    for leftover in settings.tmp_dir.glob("*.upload"):
        leftover.unlink(missing_ok=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings)
    _clear_stale_uploads(settings)
    Base.metadata.create_all(engine)

    app = FastAPI(title="TraceReview", version="1.0.0")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    register_error_handlers(app)

    @app.middleware("http")
    async def refuse_oversized_uploads(request: Request, call_next) -> JSONResponse:  # noqa: ANN001
        # Cheap early refusal so a huge body is never spooled; the exact limit is enforced
        # again while streaming the file.
        if request.method == "POST" and request.url.path == f"{API_PREFIX}/documents":
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + _MULTIPART_OVERHEAD:
                return error_response(
                    AppError(ErrorCode.FILE_TOO_LARGE, "The file is larger than the 5 MiB limit.")
                )
        return await call_next(request)

    app.include_router(documents_api.router, prefix=API_PREFIX)
    return app
