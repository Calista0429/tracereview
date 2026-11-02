from sqlalchemy import select

from app.models import Document

from .conftest import API, fixture_bytes, import_fixture


def test_empty_list_is_an_empty_array(client):
    response = client.get(f"{API}/documents")
    assert response.status_code == 200
    assert response.json() == []


def test_list_is_newest_first_with_compact_rule_status(client, session_factory):
    first = import_fixture(client, "normal")
    second = import_fixture(client, "amount-error")
    with session_factory() as session:  # make the order independent of clock resolution
        session.get(Document, first["id"]).created_at = "2026-11-02T10:00:00.000Z"
        session.get(Document, second["id"]).created_at = "2026-11-02T11:00:00.000Z"
        session.commit()

    items = client.get(f"{API}/documents").json()
    assert [i["id"] for i in items] == [second["id"], first["id"]]
    top = items[0]
    assert set(top) == {"id", "filename", "created_at", "status", "version", "rules"}
    assert top["filename"] == "amount-error.pdf"
    assert top["status"] == "REVIEW_REQUIRED" and top["version"] == 1
    assert top["rules"] == [
        {"id": "R001_REQUIRED", "status": "PASS"},
        {"id": "R002_TOTAL", "status": "FAIL"},
        {"id": "R003_EVIDENCE", "status": "PASS"},
    ]


def test_detail_matches_the_documented_shape(client):
    created = import_fixture(client, "normal")
    response = client.get(f"{API}/documents/{created['id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail == created
    assert set(detail) >= {
        "id", "filename", "sha256", "status", "version", "extraction_profile",
        "page", "fields", "rules", "confirmation", "audit_events",
    }
    assert detail["page"]["number"] == 1 and detail["page"]["width"] > 0
    assert detail["created_at"].endswith("Z") and detail["updated_at"].endswith("Z")
    first_field = detail["fields"][0]
    assert set(first_field) >= {
        "key", "source_text", "source_value", "source_parse_status",
        "initial_extracted_value", "current_value", "modified", "verified", "evidence",
    }
    assert set(first_field["evidence"]["bbox"]) == {"x", "y", "width", "height"}
    text = response.text
    assert "stored_path" not in text and "/data/" not in text


def test_unknown_and_malformed_ids_are_404_with_the_standard_error_body(client):
    for bad in ("00000000-0000-4000-8000-000000000000", "not-a-uuid"):
        for suffix in ("", "/file"):
            response = client.get(f"{API}/documents/{bad}{suffix}")
            assert response.status_code == 404
            assert response.json() == {
                "error": {
                    "code": "DOCUMENT_NOT_FOUND",
                    "message": "Document not found.",
                    "details": {},
                }
            }


def test_original_is_served_as_a_pdf_blob(client):
    created = import_fixture(client, "normal")
    response = client.get(f"{API}/documents/{created['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == fixture_bytes("normal")


def test_openapi_lists_the_implemented_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/documents"]) == {"get", "post"}
    assert "get" in paths[f"{API}/documents/{{document_id}}"]
    assert "get" in paths[f"{API}/documents/{{document_id}}/file"]


def test_server_errors_hide_paths_and_tracebacks(app, settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.services import documents as documents_service

    def explode(*args, **kwargs):
        raise RuntimeError("secret path /Users/someone/data")

    monkeypatch.setattr(documents_service, "list_summaries", explode)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"{API}/documents")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "/Users/someone" not in response.text and "Traceback" not in response.text


def test_database_row_count_matches_list(client, session_factory):
    import_fixture(client, "normal")
    with session_factory() as session:
        assert len(session.scalars(select(Document)).all()) == len(client.get(f"{API}/documents").json())
