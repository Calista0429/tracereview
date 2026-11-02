import hashlib
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuditEvent
from app.schemas import ErrorCode, FieldChange, UpdateFieldsRequest
from app.services import documents, exports, reviews

from .conftest import (
    API,
    ALL_KEYS,
    confirm,
    import_fixture,
    patch_fields,
    verify_all,
)


def confirmed_doc(client, fixture="normal", fix=None):
    doc = import_fixture(client, fixture)
    if fix:
        doc = patch_fields(client, doc, fix).json()
    doc = verify_all(client, doc)
    done = confirm(client, doc)
    assert done.status_code == 200, done.text
    return done.json()


def export(client, doc, *, version=None, fmt="json"):
    return client.post(
        f"{API}/documents/{doc['id']}/exports",
        json={"expected_version": doc["version"] if version is None else version, "format": fmt},
    )


def detail(client, doc):
    return client.get(f"{API}/documents/{doc['id']}").json()


def error(response):
    return response.json()["error"]


def export_events(session_factory, doc_id):
    with session_factory() as session:
        rows = session.scalars(
            select(AuditEvent).where(AuditEvent.document_id == doc_id, AuditEvent.event_type == "EXPORT_GENERATED").order_by(AuditEvent.id)
        ).all()
        return [(e.document_version, json.loads(e.payload_json)) for e in rows]


# --- refusals --------------------------------------------------------------------------------


def test_an_unconfirmed_document_cannot_be_exported(review_client, session_factory):
    doc = import_fixture(review_client, "normal")
    response = export(review_client, doc)
    assert response.status_code == 409 and error(response)["code"] == "DOCUMENT_NOT_CONFIRMED"
    assert export_events(session_factory, doc["id"]) == []


def test_a_checked_but_unconfirmed_document_cannot_be_exported(review_client):
    doc = verify_all(review_client, import_fixture(review_client, "normal"))
    assert error(export(review_client, doc))["code"] == "DOCUMENT_NOT_CONFIRMED"


def test_an_old_version_is_refused(review_client, session_factory):
    doc = confirmed_doc(review_client)
    patch_fields(review_client, doc, {"management_fee": "2100.00"})  # revokes: version moves on
    response = export(review_client, doc)  # still asks for the confirmed version
    assert response.status_code == 409
    assert error(response)["code"] == "VERSION_CONFLICT"
    assert error(response)["details"]["actual_version"] == doc["version"] + 1
    assert export_events(session_factory, doc["id"]) == []


def test_a_missing_or_altered_original_blocks_export(review_client, settings, session_factory):
    doc = confirmed_doc(review_client)
    stored = settings.originals_dir / f"{doc['sha256']}.pdf"
    original = stored.read_bytes()

    stored.write_bytes(original + b"x")
    response = export(review_client, doc)
    assert response.status_code == 409 and error(response)["code"] == "SOURCE_INTEGRITY_MISMATCH"

    stored.unlink()
    assert error(export(review_client, doc))["code"] == "SOURCE_UNAVAILABLE"
    assert export_events(session_factory, doc["id"]) == []

    stored.write_bytes(original)
    assert export(review_client, doc).status_code == 200


def test_only_json_is_supported_and_unknown_documents_are_404(review_client):
    doc = confirmed_doc(review_client)
    assert error(export(review_client, doc, fmt="csv"))["code"] == "INVALID_REQUEST"
    ghost = {"id": "00000000-0000-4000-8000-000000000000", "version": 1}
    assert export(review_client, ghost).status_code == 404


# --- content ----------------------------------------------------------------------------------


def test_export_is_a_complete_exact_snapshot_of_the_confirmed_version(review_client):
    doc = confirmed_doc(review_client, "amount-error", fix={"total_due": "50000.00"})
    response = export(review_client, doc)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == f'attachment; filename="tracereview-{doc["id"]}-v{doc["version"]}.json"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-export-sha256"] == hashlib.sha256(response.content).hexdigest()

    data = json.loads(response.content)
    assert data["schema_version"] == "1.0"
    assert data["generated_at"].endswith("Z")
    assert data["document"] == {
        "id": doc["id"], "filename": "amount-error.pdf", "sha256": doc["sha256"], "version": doc["version"],
        "status": "CONFIRMED", "template_id": "capital_call_v1", "parser_version": "v1",
        "extraction_profile": "total_extra_zero", "page": {"number": 1, "width": doc["page"]["width"], "height": doc["page"]["height"]},
    }
    assert data["confirmation"]["confirmed_by"] == "local-reviewer"
    assert data["confirmation"]["document_version"] == doc["version"]

    assert [f["key"] for f in data["fields"]] == ALL_KEYS
    total = data["fields"][-1]
    assert total["current_value"] == "50000.00" and total["initial_extracted_value"] == "500000.00"
    assert total["source_text"] == "50,000.00" and total["source_value"] == "50000.00"
    assert total["modified"] is True and total["verified"] is True and total["verified_by"] == "local-reviewer"
    assert set(total["evidence"]["bbox"]) == {"x", "y", "width", "height"}
    assert total["evidence"]["document_sha256"] == doc["sha256"]
    for f in data["fields"]:
        assert f["label"]
        for name in ("current_value", "initial_extracted_value", "source_value"):
            assert f[name] is None or isinstance(f[name], str)  # never a JSON number

    assert data["rules"]["ruleset_version"] == "v1"
    assert [(r["id"], r["status"]) for r in data["rules"]["results"]] == [
        ("R001_REQUIRED", "PASS"), ("R002_TOTAL", "PASS"), ("R003_EVIDENCE", "PASS")
    ]

    kinds = [e["event_type"] for e in data["history"]]
    assert kinds[0] == "IMPORTED" and kinds[-1] == "CONFIRMED"
    assert "FIELDS_UPDATED" in kinds and "EXPORT_GENERATED" not in kinds
    updated = next(e for e in data["history"] if e["event_type"] == "FIELDS_UPDATED")
    assert updated["payload"]["changes"] == [{"key": "total_due", "before": "500000.00", "after": "50000.00"}]
    assert all(e["document_version"] <= doc["version"] for e in data["history"])


def test_exporting_records_a_generation_event_but_not_a_new_version(review_client, session_factory):
    doc = confirmed_doc(review_client)
    response = export(review_client, doc)
    digest = hashlib.sha256(response.content).hexdigest()

    after = detail(review_client, doc)
    assert after["version"] == doc["version"] and after["status"] == "CONFIRMED"
    events = export_events(session_factory, doc["id"])
    assert len(events) == 1
    version, payload = events[0]
    assert version == doc["version"]
    assert payload["exported_version"] == doc["version"]
    assert payload["output_sha256"] == digest
    assert payload["filename"] == f"tracereview-{doc['id']}-v{doc['version']}.json"
    assert payload["ruleset_version"] == "v1"
    assert [r["status"] for r in payload["rules"]] == ["PASS", "PASS", "PASS"]
    assert after["audit_events"][-1]["event_type"] == "EXPORT_GENERATED"


def test_a_second_export_does_not_embed_the_first_export_event(review_client, session_factory):
    doc = confirmed_doc(review_client)
    export(review_client, doc)
    second = export(review_client, doc)
    history = json.loads(second.content)["history"]
    assert "EXPORT_GENERATED" not in [e["event_type"] for e in history]
    assert len(export_events(session_factory, doc["id"])) == 2


# --- consistency under interleaving and failure ---------------------------------------------


def edit_in_other_window(session_factory, doc_id, version):
    with session_factory() as other:
        reviews.update_fields(
            doc_id,
            UpdateFieldsRequest(
                expected_version=version,
                changes=[FieldChange(key="management_fee", value="2100.00")],
                reason="Edited while an export was running.",
            ),
            other,
        )


def test_a_change_after_the_snapshot_cannot_leak_into_the_export(review_client, session_factory, settings, monkeypatch):
    doc = confirmed_doc(review_client)
    real = exports.serialize_export

    def serialize_then_race(snapshot):
        edit_in_other_window(session_factory, doc["id"], doc["version"])  # lands after the read
        return real(snapshot)

    monkeypatch.setattr(exports, "serialize_export", serialize_then_race)
    with session_factory() as session:
        payload = exports.export_document(doc["id"], doc["version"], session, settings)
    monkeypatch.undo()

    data = json.loads(payload.body)
    assert data["document"]["version"] == doc["version"] and data["document"]["status"] == "CONFIRMED"
    fee = next(f for f in data["fields"] if f["key"] == "management_fee")
    assert fee["current_value"] == "2000.00" and fee["verified"] is True
    assert data["confirmation"]["document_version"] == doc["version"]
    assert [e["event_type"] for e in data["history"]][-1] == "CONFIRMED"
    assert all(r["status"] == "PASS" for r in data["rules"]["results"])

    # The record now reflects the late edit, and the export event points at the old version.
    now = detail(review_client, doc)
    assert now["version"] == doc["version"] + 1 and now["status"] == "REVIEW_REQUIRED"
    (version, event), = export_events(session_factory, doc["id"])
    assert version == doc["version"] and event["exported_version"] == doc["version"]
    assert event["output_sha256"] == payload.sha256 == hashlib.sha256(payload.body).hexdigest()


def test_an_edit_before_the_snapshot_is_a_version_conflict_not_a_mixed_file(review_client, session_factory, settings):
    doc = confirmed_doc(review_client)
    edit_in_other_window(session_factory, doc["id"], doc["version"])
    with session_factory() as session:
        with pytest.raises(AppError) as exc:
            exports.export_document(doc["id"], doc["version"], session, settings)
    assert exc.value.code is ErrorCode.VERSION_CONFLICT
    assert export_events(session_factory, doc["id"]) == []


def test_a_serialisation_failure_records_nothing_and_returns_no_file(review_client, session_factory, monkeypatch):
    doc = confirmed_doc(review_client)

    def explode(snapshot):
        raise ValueError("cannot serialise")

    monkeypatch.setattr(exports, "serialize_export", explode)
    from fastapi.testclient import TestClient

    with TestClient(review_client.app, raise_server_exceptions=False) as client:
        response = client.post(f"{API}/documents/{doc['id']}/exports", json={"expected_version": doc["version"], "format": "json"})
    monkeypatch.undo()
    assert response.status_code == 500 and error(response)["code"] == "INTERNAL_ERROR"
    assert export_events(session_factory, doc["id"]) == []
    assert response.headers["content-type"].startswith("application/json")


def test_a_failure_recording_the_event_means_no_download(review_client, session_factory, monkeypatch):
    doc = confirmed_doc(review_client)

    def failing_commit(self):
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(Session, "commit", failing_commit)
    response = export(review_client, doc)
    monkeypatch.undo()
    assert response.status_code == 500 and error(response)["code"] == "STORAGE_ERROR"
    assert b"schema_version" not in response.content
    assert export_events(session_factory, doc["id"]) == []
    assert detail(review_client, doc)["version"] == doc["version"]


def test_export_service_can_be_called_directly(review_client, session_factory, settings):
    doc = confirmed_doc(review_client)
    with session_factory() as session:
        payload = exports.export_document(doc["id"], doc["version"], session, settings)
        assert payload.content_type == "application/json"
        assert payload.filename == f"tracereview-{doc['id']}-v{doc['version']}.json"
        assert documents.get_detail(session, doc["id"]).version == doc["version"]
