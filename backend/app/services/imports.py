"""Upload -> validate -> parse in a worker process -> persist, all-or-nothing."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import uuid
from pathlib import Path, PurePosixPath

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.config import ACTOR, BACKEND_DIR, Settings, load_settings
from app.domain.values import FIELD_ORDER, from_minor, to_minor
from app.errors import AppError, translate_db_error
from app.models import AuditEvent, Document, DocumentField
from app.schemas import (
    AuditEventType,
    DocumentDetail,
    DocumentStatus,
    ErrorCode,
    ExtractionProfile,
    FieldKey,
    ParsedDocument,
)
from app.services import documents, storage
from app.services.pdf_parser import PARSER_VERSION, TEMPLATE_ID
from app.timeutil import now_iso

_ALLOWED_MIME = {"", "application/pdf", "application/x-pdf", "application/octet-stream"}

_WORKER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_PDF: "The file could not be read as a PDF.",
    ErrorCode.ENCRYPTED_PDF: "Encrypted or password-protected PDFs are not supported.",
    ErrorCode.UNSUPPORTED_LAYOUT: (
        "Only single-page, unrotated, uncropped PDFs with a text layer are supported."
    ),
    ErrorCode.UNSUPPORTED_TEMPLATE: "This PDF is not a supported Capital Call Notice template.",
    ErrorCode.UNSUPPORTED_CURRENCY: "Only USD notices are supported.",
}


def import_document(
    file: UploadFile, session: Session, settings: Settings | None = None
) -> DocumentDetail:
    settings = settings or load_settings()
    display_name = _display_name(file.filename)
    _check_file_type(file.filename, file.content_type)

    upload = storage.save_upload(file.file, settings)
    created: Path | None = None
    document_id = str(uuid.uuid4())
    try:
        existing = _existing_id(session, upload.sha256)
        session.rollback()  # end the read snapshot so the insert below takes the write lock fresh
        if existing is not None:
            raise _duplicate(existing)

        parsed = run_parser(upload.path, settings)
        if parsed.sha256 != upload.sha256:
            raise AppError(ErrorCode.INTERNAL_ERROR, "The uploaded file changed while parsing.")
        profile = profile_for(upload.sha256, settings)

        session.add(_build_document(document_id, display_name, upload.size, parsed, profile))
        _flush_or_duplicate(session, upload.sha256)

        # The insert above holds SQLite's write lock until commit, so no other importer can
        # interleave between promoting the file and committing the row.
        promoted = storage.promote(upload.path, upload.sha256, settings)
        created = promoted.path if promoted.created else None
        session.commit()
    except AppError:
        _abort(session, created)
        raise
    except OSError:
        _abort(session, created)
        raise AppError(ErrorCode.STORAGE_ERROR, "The file could not be stored.") from None
    except SQLAlchemyError as exc:
        _abort(session, created)
        raise translate_db_error(exc) from None
    except BaseException:
        _abort(session, created)
        raise
    finally:
        storage.discard(upload.path)
    return documents.get_detail(session, document_id)


def _abort(session: Session, created: Path | None) -> None:
    # Remove a file this request created before the lock is released, so a concurrent
    # importer cannot start relying on a file that is about to disappear.
    storage.discard(created)
    session.rollback()


def _flush_or_duplicate(session: Session, sha256: str) -> None:
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = _existing_id(session, sha256)
        session.rollback()
        if existing is None:
            raise AppError(ErrorCode.STORAGE_ERROR, "The data could not be saved.") from None
        raise _duplicate(existing) from None


def _existing_id(session: Session, sha256: str) -> str | None:
    return session.scalar(select(Document.id).where(Document.sha256 == sha256))


def _duplicate(existing_id: str) -> AppError:
    return AppError(
        ErrorCode.DOCUMENT_DUPLICATE,
        "This file has already been imported.",
        {"existing_document_id": existing_id},
    )


def _display_name(raw: str | None) -> str:
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:255]
    return name or "document.pdf"


def _check_file_type(filename: str | None, content_type: str | None) -> None:
    mime = (content_type or "").split(";")[0].strip().lower()
    if not (filename or "").lower().endswith(".pdf") or mime not in _ALLOWED_MIME:
        raise AppError(ErrorCode.UNSUPPORTED_FILE_TYPE, "Only PDF files can be uploaded.")


# --- parsing in an isolated, time-limited process --------------------------------------------


def run_parser(path: Path, settings: Settings) -> ParsedDocument:
    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR), "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, path is ours
        [*settings.parser_command, str(path)],
        cwd=BACKEND_DIR,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=settings.parse_timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        process.communicate()
        raise AppError(
            ErrorCode.PARSING_TIMEOUT, "Parsing took too long and was stopped."
        ) from None

    if process.returncode == 0:
        try:
            return ParsedDocument.model_validate_json(stdout)
        except ValidationError:
            raise AppError(ErrorCode.INTERNAL_ERROR, "The PDF parser returned an invalid result.") from None
    raise _worker_error(stdout)


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.kill()


def _worker_error(stdout: str) -> AppError:
    try:
        code = ErrorCode(json.loads(stdout)["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return AppError(ErrorCode.INTERNAL_ERROR, "The PDF parser failed.")
    if code in _WORKER_MESSAGES:
        return AppError(code, _WORKER_MESSAGES[code])
    return AppError(ErrorCode.INTERNAL_ERROR, "The PDF parser failed.")


# --- fixture fault profiles ------------------------------------------------------------------


def load_profile_map(manifest_path: Path) -> dict[str, ExtractionProfile]:
    """sha256 -> profile for the bundled sample files. Empty if the manifest is absent."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {s["sha256"]: ExtractionProfile(s["profile"]) for s in manifest["samples"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def profile_for(sha256: str, settings: Settings) -> ExtractionProfile:
    return load_profile_map(settings.manifest_path).get(sha256, ExtractionProfile.NONE)


def candidate_values(
    parsed: ParsedDocument, profile: ExtractionProfile
) -> dict[FieldKey, str | None]:
    """Initial extraction: the parsed source values, then any declared sample fault.

    The fault touches only the candidate, never the source text, value or evidence.
    """
    values: dict[FieldKey, str | None] = {f.key: f.source_value for f in parsed.fields}
    if profile is ExtractionProfile.TOTAL_EXTRA_ZERO and values[FieldKey.TOTAL_DUE] is not None:
        values[FieldKey.TOTAL_DUE] = from_minor(to_minor(values[FieldKey.TOTAL_DUE]) * 10)
    elif profile is ExtractionProfile.DROP_DUE_DATE:
        values[FieldKey.DUE_DATE] = None
    return values


def _build_document(
    document_id: str,
    filename: str,
    size: int,
    parsed: ParsedDocument,
    profile: ExtractionProfile,
) -> Document:
    now = now_iso()
    candidates = candidate_values(parsed, profile)
    by_key = {f.key: f for f in parsed.fields}
    document = Document(
        id=document_id,
        sha256=parsed.sha256,
        original_filename=filename,
        stored_path=f"originals/{parsed.sha256}.pdf",
        byte_size=size,
        page_width=parsed.page_width,
        page_height=parsed.page_height,
        template_id=TEMPLATE_ID,
        parser_version=PARSER_VERSION,
        extraction_profile=profile.value,
        status=DocumentStatus.REVIEW_REQUIRED.value,
        version=1,
        created_at=now,
        updated_at=now,
    )
    for key in FIELD_ORDER:
        parsed_field = by_key[key]
        document.fields.append(
            DocumentField(
                key=key.value,
                source_text=parsed_field.source_text,
                source_value=parsed_field.source_value,
                source_parse_status=parsed_field.source_parse_status.value,
                evidence_json=(
                    parsed_field.evidence.model_dump_json() if parsed_field.evidence else None
                ),
                initial_extracted_value=candidates[key],
                current_value=candidates[key],
                verified=False,
            )
        )
    document.events.append(
        AuditEvent(
            document_version=1,
            event_type=AuditEventType.IMPORTED.value,
            actor=ACTOR,
            created_at=now,
            payload_json=json.dumps(
                {
                    "filename": filename,
                    "sha256": parsed.sha256,
                    "extraction_profile": profile.value,
                    "template_id": TEMPLATE_ID,
                    "parser_version": PARSER_VERSION,
                    "source_status": {f.key.value: f.source_parse_status.value for f in parsed.fields},
                },
                sort_keys=True,
            ),
        )
    )
    return document
