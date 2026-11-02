import dataclasses
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
from app.main import create_app
from app.schemas import ErrorCode, FieldChange, UpdateFieldsRequest, VerifyFieldRequest
from app.services import documents, reviews

from .conftest import API, confirm, import_fixture, patch_fields, verify, verify_all

CONFLICT_CODES = {ErrorCode.VERSION_CONFLICT, ErrorCode.WRITE_CONFLICT}


def update_request(version: int, key: str, value: str) -> UpdateFieldsRequest:
    return UpdateFieldsRequest(
        expected_version=version, changes=[FieldChange(key=key, value=value)], reason="Edited in a window."
    )


def stored(session_factory, doc_id: str):
    with session_factory() as session:
        return documents.get_detail(session, doc_id)


def test_two_windows_editing_the_same_version_cannot_both_win(review_client, session_factory):
    doc = import_fixture(review_client, "amount-error")
    window_a, window_b = session_factory(), session_factory()
    try:
        documents.get_detail(window_a, doc["id"])  # both windows have read version 1
        documents.get_detail(window_b, doc["id"])

        first = reviews.update_fields(doc["id"], update_request(1, "total_due", "50000.00"), window_a)
        assert first.version == 2

        with pytest.raises(AppError) as exc:
            reviews.update_fields(doc["id"], update_request(1, "fund_name", "Overwrite"), window_b)
        assert exc.value.code in CONFLICT_CODES
    finally:
        window_a.close()
        window_b.close()

    final = stored(session_factory, doc["id"])
    assert final.version == 2
    values = {f.key.value: f.current_value for f in final.fields}
    assert values["total_due"] == "50000.00"
    assert values["fund_name"] == "Example Income Fund II"  # the late edit did not land
    assert [e.event_type.value for e in final.audit_events] == ["IMPORTED", "FIELDS_UPDATED"]


def test_stale_verification_and_confirmation_across_windows(review_client, session_factory):
    doc = import_fixture(review_client, "normal")
    window_a, window_b = session_factory(), session_factory()
    try:
        documents.get_detail(window_b, doc["id"])
        reviews.set_field_verification(
            doc["id"], VerifyFieldRequest(expected_version=1, field_key="total_due", verified=True), window_a
        )
        with pytest.raises(AppError) as exc:
            reviews.set_field_verification(
                doc["id"], VerifyFieldRequest(expected_version=1, field_key="fund_name", verified=True), window_b
            )
        assert exc.value.code in CONFLICT_CODES
    finally:
        window_a.close()
        window_b.close()
    final = stored(session_factory, doc["id"])
    assert [f.key.value for f in final.fields if f.verified] == ["total_due"]


def test_concurrent_edit_on_a_confirmed_document_is_refused_not_merged(review_client, session_factory):
    doc = import_fixture(review_client, "normal")
    doc = confirm(review_client, verify_all(review_client, doc)).json()
    # Window B still believes the document is at the version before confirmation.
    stale = patch_fields(review_client, doc, {"fund_name": "Late"}, version=doc["version"] - 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert review_client.get(f"{API}/documents/{doc['id']}").json()["status"] == "CONFIRMED"


def test_a_locked_database_is_a_write_conflict_and_changes_nothing(settings, tmp_path, monkeypatch):
    short = dataclasses.replace(settings, sqlite_timeout_seconds=0.2)
    with TestClient(create_app(short)) as client:
        from app.services import imports as imports_service
        from app.services.pdf_parser import parse_pdf

        monkeypatch.setattr(imports_service, "run_parser", lambda path, s: parse_pdf(path))
        doc = import_fixture(client, "normal")

        blocker = sqlite3.connect(short.db_path, isolation_level=None, timeout=1)
        try:
            blocker.execute("BEGIN IMMEDIATE")  # another writer holds the lock
            response = patch_fields(client, doc, {"fund_name": "Blocked Edit"})
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "WRITE_CONFLICT"
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()

        unchanged = client.get(f"{API}/documents/{doc['id']}").json()
        assert unchanged == doc
        # Once the lock is gone the same request, with the same version, succeeds.
        assert patch_fields(client, doc, {"fund_name": "Blocked Edit"}).status_code == 200


def test_after_a_conflict_the_client_can_reload_and_retry(review_client):
    doc = import_fixture(review_client, "amount-error")
    patch_fields(review_client, doc, {"total_due": "50000.00"})
    rejected = patch_fields(review_client, doc, {"fund_name": "Retry Me"})
    assert rejected.status_code == 409
    fresh = review_client.get(f"{API}/documents/{doc['id']}").json()
    assert patch_fields(review_client, fresh, {"fund_name": "Retry Me"}).status_code == 200
    assert verify(review_client, fresh, "fund_name", version=fresh["version"]).status_code == 409  # version moved again
