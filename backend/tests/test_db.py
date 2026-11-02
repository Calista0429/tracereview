import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.models import AuditEvent, Document, DocumentField


def new_document(session, sha="a" * 64, doc_id="11111111-1111-4111-8111-111111111111") -> Document:
    doc = Document(
        id=doc_id,
        sha256=sha,
        original_filename="x.pdf",
        stored_path=f"/tmp/{sha}.pdf",
        byte_size=10,
        page_width=595.0,
        page_height=842.0,
        template_id="capital_call_v1",
        parser_version="v1",
        extraction_profile="none",
        status="REVIEW_REQUIRED",
        version=1,
        created_at="2026-11-02T00:00:00.000Z",
        updated_at="2026-11-02T00:00:00.000Z",
    )
    session.add(doc)
    return doc


def test_foreign_keys_are_enforced(session_factory):
    with session_factory() as session:
        session.add(
            DocumentField(
                document_id="missing", key="total_due", source_parse_status="valid", verified=False
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_sha256_is_unique(session_factory):
    with session_factory() as session:
        new_document(session)
        session.commit()
        new_document(session, doc_id="22222222-2222-4222-8222-222222222222")
        with pytest.raises(IntegrityError):
            session.flush()


def test_rollback_discards_everything_written_in_the_transaction(session_factory):
    with session_factory() as session:
        new_document(session)
        session.flush()
        session.rollback()
    with session_factory() as session:
        assert session.scalars(select(Document)).all() == []


def test_a_read_only_select_also_runs_inside_a_transaction(session_factory):
    with session_factory() as session:
        session.execute(select(Document)).all()
        assert session.connection().connection.dbapi_connection.in_transaction


def test_a_stale_version_write_is_rejected_and_changes_nothing(session_factory):
    with session_factory() as setup:
        new_document(setup)
        setup.commit()
    first, second = session_factory(), session_factory()
    try:
        doc_a = first.get(Document, "11111111-1111-4111-8111-111111111111")
        doc_b = second.get(Document, "11111111-1111-4111-8111-111111111111")
        doc_a.version = 2
        doc_a.status = "CONFIRMED"
        first.commit()

        doc_b.version = 2
        doc_b.original_filename = "overwritten.pdf"
        with pytest.raises((StaleDataError, OperationalError)):
            second.commit()
        second.rollback()
    finally:
        first.close()
        second.close()
    with session_factory() as check:
        stored = check.get(Document, "11111111-1111-4111-8111-111111111111")
        assert (stored.version, stored.status, stored.original_filename) == (2, "CONFIRMED", "x.pdf")


def test_audit_event_ids_are_monotonic_and_never_reused(session_factory):
    with session_factory() as session:
        new_document(session)
        session.flush()
        for index in range(3):
            session.add(
                AuditEvent(
                    document_id="11111111-1111-4111-8111-111111111111",
                    document_version=1,
                    event_type="IMPORTED",
                    actor="local-reviewer",
                    created_at="2026-11-02T00:00:00.000Z",
                    payload_json="{}",
                )
            )
        session.commit()
        ids = [e.id for e in session.scalars(select(AuditEvent).order_by(AuditEvent.id))]
        assert ids == sorted(ids) and len(set(ids)) == 3
        session.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": ids[-1]})
        session.add(
            AuditEvent(
                document_id="11111111-1111-4111-8111-111111111111",
                document_version=1,
                event_type="IMPORTED",
                actor="local-reviewer",
                created_at="2026-11-02T00:00:00.000Z",
                payload_json="{}",
            )
        )
        session.commit()
        assert max(e.id for e in session.scalars(select(AuditEvent))) > ids[-1]
