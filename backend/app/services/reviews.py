"""Edit, per-field human check and confirmation. Every write is one transaction.

Rules of the road (spec sections 5.4, 6, 10):
* the caller names the version it saw; a different stored version is a 409, always first;
* a real change bumps ``version`` exactly once and writes its history event(s) in the same
  transaction; a no-op changes nothing and writes nothing;
* any real field edit clears all six human checks and revokes a standing confirmation;
* confirmation re-checks every gate on the server; nothing the client sends can waive one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.config import ACTOR, Settings, load_settings
from app.domain.rules import RULESET_VERSION, evidence_problem, is_valid_value, validate_document
from app.domain.values import FieldValueError, normalize_field
from app.errors import AppError, translate_db_error
from app.models import AuditEvent, Document
from app.schemas import (
    AuditEventType,
    DocumentDetail,
    DocumentStatus,
    ErrorCode,
    FieldChange,
    FieldKey,
    RuleStatus,
    UpdateFieldsRequest,
    VerifyFieldRequest,
)
from app.services import documents
from app.timeutil import now_iso


def add_event(
    session: Session, document: Document, event_type: AuditEventType, payload: dict[str, Any]
) -> None:
    """Append a history row stamped with the document's (already bumped) version."""
    session.add(
        AuditEvent(
            document_id=document.id,
            document_version=document.version,
            event_type=event_type.value,
            actor=ACTOR,
            created_at=now_iso(),
            payload_json=json.dumps(payload, sort_keys=True),
        )
    )


def _version_conflict(expected: int, actual: int) -> AppError:
    return AppError(
        ErrorCode.VERSION_CONFLICT,
        "This document has changed. Reload before continuing.",
        {"expected_version": expected, "actual_version": actual},
    )


def _bump(document: Document) -> None:
    document.version = document.version + 1
    document.updated_at = now_iso()


def _write(
    session: Session,
    document_id: str | UUID,
    expected_version: int,
    mutate: Callable[[Document], bool],
) -> DocumentDetail:
    """Load, check the version, apply ``mutate`` and commit. ``mutate`` returns False for a no-op."""
    try:
        document = documents.load_document(session, document_id, refresh=True)
        if document.version != expected_version:
            raise _version_conflict(expected_version, document.version)
        if mutate(document):
            session.commit()
    except StaleDataError:
        # Someone committed between our read and our write: the version guard did its job.
        session.rollback()
        actual = session.scalar(
            select(Document.version).where(Document.id == documents.normalise_id(document_id))
        )
        raise _version_conflict(expected_version, actual if actual is not None else -1) from None
    except SQLAlchemyError as exc:
        session.rollback()
        raise translate_db_error(exc) from None
    except BaseException:
        session.rollback()
        raise
    return documents.get_detail(session, document_id)


# --- edit ------------------------------------------------------------------------------------


def _normalise_changes(changes: list[FieldChange]) -> dict[FieldKey, str | None]:
    normalised: dict[FieldKey, str | None] = {}
    problems: list[dict[str, str]] = []
    for change in changes:
        try:
            normalised[change.key] = normalize_field(change.key, change.value)
        except FieldValueError as exc:
            problems.append({"key": change.key.value, "message": exc.message})
    if problems:
        raise AppError(
            ErrorCode.INVALID_FIELD_VALUE, "One or more values are not valid.", {"errors": problems}
        )
    return normalised


def update_fields(
    document_id: str | UUID, request: UpdateFieldsRequest, session: Session
) -> DocumentDetail:
    def mutate(document: Document) -> bool:
        new_values = _normalise_changes(request.changes)  # format errors reject the whole batch
        rows = {row.key: row for row in document.fields}
        changed = [
            (key, rows[key.value].current_value, value)
            for key, value in new_values.items()
            if rows[key.value].current_value != value
        ]
        if not changed:
            return False

        previously_verified = [k for k, row in rows.items() if row.verified]
        was_confirmed = document.status == DocumentStatus.CONFIRMED.value
        confirmed_at, confirmed_by = document.confirmed_at, document.confirmed_by

        for key, _before, value in changed:
            rows[key.value].current_value = value
        for row in rows.values():
            row.verified = False
            row.verified_at = None
            row.verified_by = None
        revoked_version = document.version
        if was_confirmed:
            document.status = DocumentStatus.REVIEW_REQUIRED.value
            document.confirmed_at = None
            document.confirmed_by = None
        _bump(document)

        add_event(
            session,
            document,
            AuditEventType.FIELDS_UPDATED,
            {
                "changes": [{"key": k.value, "before": b, "after": a} for k, b, a in changed],
                "reason": request.reason,
                "checks_cleared": previously_verified,
            },
        )
        if was_confirmed:
            add_event(
                session,
                document,
                AuditEventType.CONFIRMATION_REVOKED,
                {
                    "reason": "Fields were changed after confirmation.",
                    "revoked_version": revoked_version,
                    "confirmed_at": confirmed_at,
                    "confirmed_by": confirmed_by,
                },
            )
        return True

    return _write(session, document_id, request.expected_version, mutate)


# --- per-field human check -------------------------------------------------------------------


def set_field_verification(
    document_id: str | UUID, request: VerifyFieldRequest, session: Session
) -> DocumentDetail:
    key = request.field_key

    def mutate(document: Document) -> bool:
        if document.status == DocumentStatus.CONFIRMED.value:
            raise AppError(
                ErrorCode.DOCUMENT_CONFIRMED,
                "This document is confirmed. Edit a field to start a new review.",
            )
        row = next(r for r in document.fields if r.key == key.value)
        if row.verified == request.verified:
            return False
        if request.verified:
            record = documents.to_field_record(row)
            if not is_valid_value(key, record.current_value):
                raise AppError(
                    ErrorCode.REVIEW_BLOCKED,
                    "This field has no valid value to check. Enter a valid value first.",
                    {"field": key.value},
                )
            problem = evidence_problem(record, document.sha256)
            if problem is not None:
                raise AppError(
                    ErrorCode.REVIEW_BLOCKED,
                    "This field has no usable source evidence, so it cannot be checked.",
                    {"field": key.value, "problem": problem},
                )
            row.verified, row.verified_at, row.verified_by = True, now_iso(), ACTOR
        else:
            row.verified, row.verified_at, row.verified_by = False, None, None
        _bump(document)
        add_event(
            session,
            document,
            AuditEventType.FIELD_VERIFICATION_CHANGED,
            {"field_key": key.value, "verified": request.verified, "previous": not request.verified},
        )
        return True

    return _write(session, document_id, request.expected_version, mutate)


# --- confirmation ----------------------------------------------------------------------------


def confirm_document(
    document_id: str | UUID,
    expected_version: int,
    session: Session,
    settings: Settings | None = None,
) -> DocumentDetail:
    settings = settings or load_settings()

    def mutate(document: Document) -> bool:
        if document.status == DocumentStatus.CONFIRMED.value:
            return False  # same version, already confirmed: idempotent
        documents.require_intact_original(settings, document)
        records = documents.field_records(document)

        results = validate_document(records, document.sha256)
        failing = [r for r in results if r.status is not RuleStatus.PASS]
        if failing:
            raise AppError(
                ErrorCode.REVIEW_BLOCKED,
                "Resolve the failing checks before confirming.",
                {"rules": [r.model_dump(mode="json") for r in failing]},
            )
        unverified = [r.key.value for r in records if not r.verified]
        if unverified:
            raise AppError(
                ErrorCode.REVIEW_INCOMPLETE,
                "Check every field against the PDF before confirming.",
                {"unverified": unverified},
            )

        document.status = DocumentStatus.CONFIRMED.value
        document.confirmed_at = now_iso()
        document.confirmed_by = ACTOR
        _bump(document)
        add_event(
            session,
            document,
            AuditEventType.CONFIRMED,
            {
                "ruleset_version": RULESET_VERSION,
                "rules": [r.model_dump(mode="json") for r in results],
            },
        )
        return True

    return _write(session, document_id, expected_version, mutate)
