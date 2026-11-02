"""Read side: turn stored rows into API responses and verify the stored original."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.domain.rules import validate_document
from app.domain.values import FIELD_ORDER
from app.errors import AppError, not_found
from app.models import AuditEvent, Document, DocumentField
from app.schemas import (
    AuditEventOut,
    Confirmation,
    DocumentDetail,
    DocumentStatus,
    DocumentSummary,
    ErrorCode,
    Evidence,
    ExtractionProfile,
    FieldKey,
    FieldRecord,
    PageInfo,
    RuleBrief,
    SourceParseStatus,
)
from app.services import storage


def normalise_id(document_id: str | UUID) -> str:
    return str(document_id)


def load_document(session: Session, document_id: str | UUID, *, refresh: bool = False) -> Document:
    """Fetch a document or raise 404. ``refresh`` re-reads state already in the identity map."""
    key = normalise_id(document_id)
    if refresh:
        row = session.execute(
            select(Document)
            .where(Document.id == key)
            .options(selectinload(Document.fields))
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    else:
        row = session.get(Document, key)
    if row is None:
        raise not_found()
    return row


def to_field_record(row: DocumentField) -> FieldRecord:
    return FieldRecord(
        key=FieldKey(row.key),
        source_text=row.source_text,
        source_value=row.source_value,
        source_parse_status=SourceParseStatus(row.source_parse_status),
        initial_extracted_value=row.initial_extracted_value,
        current_value=row.current_value,
        verified=row.verified,
        verified_at=row.verified_at,
        verified_by=row.verified_by,
        evidence=Evidence.model_validate_json(row.evidence_json) if row.evidence_json else None,
    )


def field_records(document: Document) -> list[FieldRecord]:
    order = {key.value: index for index, key in enumerate(FIELD_ORDER)}
    return [to_field_record(r) for r in sorted(document.fields, key=lambda r: order[r.key])]


def build_detail(session: Session, document: Document) -> DocumentDetail:
    fields = field_records(document)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.document_id == document.id).order_by(AuditEvent.id)
    ).all()
    confirmation = None
    if document.status == DocumentStatus.CONFIRMED.value and document.confirmed_at:
        confirmation = Confirmation(
            confirmed_at=document.confirmed_at,
            confirmed_by=document.confirmed_by or "",
            document_version=document.version,
        )
    return DocumentDetail(
        id=document.id,
        filename=document.original_filename,
        sha256=document.sha256,
        status=DocumentStatus(document.status),
        version=document.version,
        template_id=document.template_id,
        parser_version=document.parser_version,
        extraction_profile=ExtractionProfile(document.extraction_profile),
        created_at=document.created_at,
        updated_at=document.updated_at,
        page=PageInfo(number=1, width=document.page_width, height=document.page_height),
        fields=fields,
        rules=validate_document(fields, document.sha256),
        confirmation=confirmation,
        audit_events=[
            AuditEventOut(
                id=e.id,
                document_version=e.document_version,
                event_type=e.event_type,
                actor=e.actor,
                created_at=e.created_at,
                payload=json.loads(e.payload_json),
            )
            for e in events
        ],
    )


def get_detail(session: Session, document_id: str | UUID) -> DocumentDetail:
    return build_detail(session, load_document(session, document_id))


def list_summaries(session: Session) -> list[DocumentSummary]:
    rows = session.scalars(
        select(Document)
        .options(selectinload(Document.fields))
        .order_by(Document.created_at.desc(), Document.id.desc())
    ).all()
    return [
        DocumentSummary(
            id=d.id,
            filename=d.original_filename,
            created_at=d.created_at,
            status=DocumentStatus(d.status),
            version=d.version,
            rules=[
                RuleBrief(id=r.id, status=r.status)
                for r in validate_document(field_records(d), d.sha256)
            ],
        )
        for d in rows
    ]


def require_intact_original(settings: Settings, document: Document) -> None:
    """Raise unless the stored original exists and still hashes to the recorded value."""
    state = storage.original_status(settings, document.sha256)
    if state == "missing":
        raise AppError(
            ErrorCode.SOURCE_UNAVAILABLE, "The original PDF is missing from local storage."
        )
    if state == "mismatch":
        raise AppError(
            ErrorCode.SOURCE_INTEGRITY_MISMATCH,
            "The stored original no longer matches its recorded hash.",
        )


def read_original(session: Session, settings: Settings, document_id: str | UUID) -> bytes:
    document = load_document(session, document_id)
    # Hash the exact bytes we are about to serve, so the check cannot race a file swap.
    try:
        content = storage.original_path(settings, document.sha256).read_bytes()
    except OSError:
        raise AppError(
            ErrorCode.SOURCE_UNAVAILABLE, "The original PDF is missing from local storage."
        ) from None
    if hashlib.sha256(content).hexdigest() != document.sha256:
        raise AppError(
            ErrorCode.SOURCE_INTEGRITY_MISMATCH,
            "The stored original no longer matches its recorded hash.",
        )
    return content
