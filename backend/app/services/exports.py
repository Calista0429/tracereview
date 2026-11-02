"""Confirmed-version JSON export.

Two short transactions, deliberately separate (spec section 11):
1. read, verify every gate and copy the confirmed version into an independent snapshot, then
   end the read transaction;
2. serialise the snapshot, then record EXPORT_GENERATED and return the bytes.
A change made in another window between the two cannot leak into the file: the output is
always the complete confirmed version that was read, and the event points at that version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import ACTOR, Settings, load_settings
from app.domain.rules import RULESET_VERSION
from app.domain.values import FIELD_LABELS
from app.errors import AppError, translate_db_error
from app.models import AuditEvent
from app.schemas import (
    AuditEventType,
    DocumentDetail,
    DocumentStatus,
    ErrorCode,
    ExportPayload,
    RuleStatus,
)
from app.services import documents
from app.timeutil import now_iso

SCHEMA_VERSION = "1.0"
CONTENT_TYPE = "application/json"


def export_filename(document_id: str, version: int) -> str:
    return f"tracereview-{document_id}-v{version}.json"


def export_document(
    document_id: str | UUID,
    expected_version: int,
    session: Session,
    settings: Settings | None = None,
) -> ExportPayload:
    settings = settings or load_settings()
    snapshot = _read_snapshot(session, document_id, expected_version, settings)

    try:
        body = serialize_export(snapshot)
    except Exception:  # noqa: BLE001 - nothing is recorded and no file is returned
        raise AppError(ErrorCode.INTERNAL_ERROR, "The export could not be generated.") from None

    digest = hashlib.sha256(body).hexdigest()
    version = snapshot["document"]["version"]
    filename = export_filename(snapshot["document"]["id"], version)
    try:
        session.add(
            AuditEvent(
                document_id=snapshot["document"]["id"],
                document_version=version,  # the exported version, even if the record has moved on
                event_type=AuditEventType.EXPORT_GENERATED.value,
                actor=ACTOR,
                created_at=now_iso(),
                payload_json=json.dumps(
                    {
                        "exported_version": version,
                        "format": "json",
                        "filename": filename,
                        "output_sha256": digest,
                        "ruleset_version": RULESET_VERSION,
                        "rules": snapshot["rules"]["results"],
                    },
                    sort_keys=True,
                ),
            )
        )
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise translate_db_error(exc) from None
    return ExportPayload(filename=filename, content_type=CONTENT_TYPE, body=body, sha256=digest)


def _read_snapshot(
    session: Session, document_id: str | UUID, expected_version: int, settings: Settings
) -> dict[str, Any]:
    try:
        document = documents.load_document(session, document_id, refresh=True)
        if document.version != expected_version:
            raise AppError(
                ErrorCode.VERSION_CONFLICT,
                "This document has changed. Reload before continuing.",
                {"expected_version": expected_version, "actual_version": document.version},
            )
        if document.status != DocumentStatus.CONFIRMED.value:
            raise AppError(
                ErrorCode.DOCUMENT_NOT_CONFIRMED, "Only a confirmed review can be exported."
            )
        documents.require_intact_original(settings, document)
        detail = documents.build_detail(session, document)
        failing = [r for r in detail.rules if r.status is not RuleStatus.PASS]
        if failing:
            raise AppError(
                ErrorCode.REVIEW_BLOCKED,
                "Resolve the failing checks before exporting.",
                {"rules": [r.model_dump(mode="json") for r in failing]},
            )
        unverified = [f.key.value for f in detail.fields if not f.verified]
        if unverified:
            raise AppError(
                ErrorCode.REVIEW_INCOMPLETE,
                "Check every field against the PDF before exporting.",
                {"unverified": unverified},
            )
        return build_snapshot(detail)
    finally:
        session.rollback()  # end the read transaction; the snapshot is an independent copy


def build_snapshot(detail: DocumentDetail) -> dict[str, Any]:
    assert detail.confirmation is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "document": {
            "id": detail.id,
            "filename": detail.filename,
            "sha256": detail.sha256,
            "version": detail.version,
            "status": detail.status.value,
            "template_id": detail.template_id,
            "parser_version": detail.parser_version,
            "extraction_profile": detail.extraction_profile.value,
            "page": detail.page.model_dump(mode="json"),
        },
        "confirmation": detail.confirmation.model_dump(mode="json"),
        "fields": [
            {
                "key": f.key.value,
                "label": FIELD_LABELS[f.key],
                "current_value": f.current_value,
                "initial_extracted_value": f.initial_extracted_value,
                "modified": f.modified,
                "source_text": f.source_text,
                "source_value": f.source_value,
                "source_parse_status": f.source_parse_status.value,
                "evidence": f.evidence.model_dump(mode="json") if f.evidence else None,
                "verified": f.verified,
                "verified_at": f.verified_at,
                "verified_by": f.verified_by,
            }
            for f in detail.fields
        ],
        "rules": {
            "ruleset_version": RULESET_VERSION,
            "results": [r.model_dump(mode="json") for r in detail.rules],
        },
        # Business history up to this version; export records are never nested inside exports.
        "history": [
            e.model_dump(mode="json")
            for e in detail.audit_events
            if e.event_type is not AuditEventType.EXPORT_GENERATED and e.document_version <= detail.version
        ],
    }


def serialize_export(snapshot: dict[str, Any]) -> bytes:
    """Amounts are already strings, so no float ever stands in for money."""
    return (json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
