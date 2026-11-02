import dataclasses
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.config import Settings
from app.main import create_app
from app.models import Document, DocumentField
from app.schemas import ErrorCode
from app.errors import AppError
from app.services import imports as imports_service
from app.services import storage as storage_module

from .conftest import API, data_files, fixture_bytes, import_fixture, upload
from .pdfmaker import build_pdf, normal_rows

MAX = 5_242_880


def error_of(response) -> dict:
    return response.json()["error"]


def field(detail: dict, key: str) -> dict:
    return next(f for f in detail["fields"] if f["key"] == key)


def rule(detail: dict, rule_id: str) -> dict:
    return next(r for r in detail["rules"] if r["id"] == rule_id)


def assert_nothing_persisted(client, settings):
    assert client.get(f"{API}/documents").json() == []
    assert data_files(settings) == {"originals": [], "tmp": []}


# --- successful imports --------------------------------------------------------------------


def test_normal_import_returns_a_reviewable_document(client):
    response = upload(client, fixture_bytes("normal"), "normal.pdf")
    assert response.status_code == 201
    detail = response.json()
    assert detail["version"] == 1
    assert detail["status"] == "REVIEW_REQUIRED"
    assert detail["filename"] == "normal.pdf"
    assert detail["extraction_profile"] == "none"
    assert detail["confirmation"] is None
    assert [f["key"] for f in detail["fields"]] == [
        "fund_name", "currency", "due_date", "investment_amount", "management_fee", "total_due"
    ]
    assert [(r["id"], r["status"]) for r in detail["rules"]] == [
        ("R001_REQUIRED", "PASS"), ("R002_TOTAL", "PASS"), ("R003_EVIDENCE", "PASS")
    ]
    for f in detail["fields"]:
        assert f["initial_extracted_value"] == f["source_value"] == f["current_value"]
        assert f["modified"] is False and f["verified"] is False
        assert f["evidence"]["document_sha256"] == detail["sha256"]
    assert field(detail, "total_due")["current_value"] == "50000.00"
    assert detail["page"]["number"] == 1
    assert [e["event_type"] for e in detail["audit_events"]] == ["IMPORTED"]
    assert detail["audit_events"][0]["actor"] == "local-reviewer"
    assert "stored_path" not in response.text


def test_amount_error_keeps_the_pdf_value_and_injects_the_candidate_fault(client):
    detail = import_fixture(client, "amount-error")
    total = field(detail, "total_due")
    assert detail["extraction_profile"] == "total_extra_zero"
    assert total["source_text"] == "50,000.00"
    assert total["source_value"] == "50000.00"
    assert total["initial_extracted_value"] == "500000.00"
    assert total["current_value"] == "500000.00"
    assert total["modified"] is False
    assert [(r["id"], r["status"]) for r in detail["rules"]] == [
        ("R001_REQUIRED", "PASS"), ("R002_TOTAL", "FAIL"), ("R003_EVIDENCE", "PASS")
    ]


def test_missing_extraction_has_a_locatable_source_but_no_candidate(client):
    detail = import_fixture(client, "missing-extraction")
    due = field(detail, "due_date")
    assert detail["extraction_profile"] == "drop_due_date"
    assert due["source_value"] == "2026-11-24"
    assert due["evidence"] is not None
    assert due["initial_extracted_value"] is None and due["current_value"] is None
    assert rule(detail, "R001_REQUIRED")["status"] == "FAIL"
    assert rule(detail, "R003_EVIDENCE")["status"] == "PASS"


def test_missing_source_fails_required_and_evidence_rules(client):
    detail = import_fixture(client, "missing-source")
    due = field(detail, "due_date")
    assert due["source_parse_status"] == "missing"
    assert due["evidence"] is None and due["source_text"] is None and due["current_value"] is None
    assert rule(detail, "R001_REQUIRED")["status"] == "FAIL"
    assert rule(detail, "R002_TOTAL")["status"] == "PASS"
    assert rule(detail, "R003_EVIDENCE")["status"] == "FAIL"
    assert rule(detail, "R003_EVIDENCE")["fields"] == ["due_date"]


def test_original_is_stored_under_its_hash_and_not_under_the_upload_name(client, settings):
    detail = import_fixture(client, "normal")
    assert data_files(settings) == {"originals": [f"{detail['sha256']}.pdf"], "tmp": []}
    stored = settings.originals_dir / f"{detail['sha256']}.pdf"
    assert stored.read_bytes() == fixture_bytes("normal")


def test_upload_filename_is_display_text_only(client, settings):
    response = upload(client, fixture_bytes("normal"), "../../etc/evil name.pdf")
    assert response.status_code == 201
    assert response.json()["filename"] == "evil name.pdf"
    assert data_files(settings)["originals"] == [f"{response.json()['sha256']}.pdf"]


# --- fault profiles can only come from the manifest ------------------------------------------


def test_profile_does_not_apply_to_a_look_alike_file_with_different_bytes(client):
    # Same layout and a name copied from a fixture, but not the manifest's exact bytes.
    buffer = io.BytesIO()
    path = client.app.state.settings.data_dir / "lookalike.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(path, normal_rows("Example Income Fund II", "2026-11-17", total="50,000.00"),
              extra_lines=("Duplicate of the amount-error sample",))
    response = upload(client, path.read_bytes(), "amount-error.pdf")
    assert response.status_code == 201
    detail = response.json()
    assert detail["extraction_profile"] == "none"
    assert field(detail, "total_due")["initial_extracted_value"] == "50000.00"


def test_client_cannot_request_a_profile(client):
    response = upload(client, fixture_bytes("normal"), "normal.pdf", profile="total_extra_zero")
    assert response.status_code == 201
    assert response.json()["extraction_profile"] == "none"
    assert field(response.json(), "total_due")["current_value"] == "50000.00"


# --- duplicates ----------------------------------------------------------------------------


def test_same_bytes_again_is_a_duplicate_pointing_at_the_original_record(client, settings):
    first = import_fixture(client, "normal")
    second = upload(client, fixture_bytes("normal"), "renamed.pdf")
    assert second.status_code == 409
    err = error_of(second)
    assert err["code"] == "DOCUMENT_DUPLICATE"
    assert err["details"]["existing_document_id"] == first["id"]
    assert len(client.get(f"{API}/documents").json()) == 1
    assert data_files(settings) == {"originals": [f"{first['sha256']}.pdf"], "tmp": []}
    assert client.get(f"{API}/documents/{first['id']}/file").status_code == 200


def test_reupload_never_overwrites_a_reviewed_record(client, session_factory):
    first = import_fixture(client, "amount-error")
    with session_factory() as session:
        fields = session.scalars(select(DocumentField).where(DocumentField.key == "total_due")).all()
        fields[0].current_value = "50000.00"
        doc = session.get(Document, first["id"])
        doc.version = 2
        session.commit()

    again = upload(client, fixture_bytes("amount-error"), "amount-error.pdf")
    assert again.status_code == 409
    after = client.get(f"{API}/documents/{first['id']}").json()
    assert after["version"] == 2
    assert field(after, "total_due")["current_value"] == "50000.00"
    assert field(after, "total_due")["initial_extracted_value"] == "500000.00"


def test_same_filename_with_different_bytes_creates_a_new_record(client):
    first = import_fixture(client, "normal")
    second = upload(client, fixture_bytes("amount-error"), "normal.pdf")
    assert second.status_code == 201
    assert second.json()["id"] != first["id"]
    assert second.json()["filename"] == "normal.pdf"


# --- rejected files leave no trace -------------------------------------------------------


def test_file_one_byte_over_the_limit_is_rejected(client, settings):
    response = upload(client, b"%PDF-" + b"0" * (MAX + 1 - 5))
    assert response.status_code == 413
    assert error_of(response)["code"] == "FILE_TOO_LARGE"
    assert_nothing_persisted(client, settings)


def test_file_exactly_at_the_limit_passes_size_check_and_fails_parsing(client, settings):
    response = upload(client, b"%PDF-" + b"0" * (MAX - 5))
    assert response.status_code == 422
    assert error_of(response)["code"] == "INVALID_PDF"
    assert_nothing_persisted(client, settings)


def test_a_far_oversized_upload_is_refused_before_it_is_read(client, settings):
    response = upload(client, b"%PDF-" + b"0" * (MAX * 2))
    assert response.status_code == 413
    assert error_of(response)["code"] == "FILE_TOO_LARGE"
    assert_nothing_persisted(client, settings)


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("notes.txt", "text/plain"), ("image.png", "image/png"), ("scan.pdf", "image/png"), ("noext", "application/pdf")],
)
def test_wrong_extension_or_mime_is_unsupported_file_type(client, settings, filename, content_type):
    response = upload(client, fixture_bytes("normal"), filename, content_type)
    assert response.status_code == 415
    assert error_of(response)["code"] == "UNSUPPORTED_FILE_TYPE"
    assert_nothing_persisted(client, settings)


def test_extension_and_mime_are_only_a_first_check(client, settings):
    response = upload(client, b"just some text", "fake.pdf")
    assert response.status_code == 422
    assert error_of(response)["code"] == "INVALID_PDF"
    assert_nothing_persisted(client, settings)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"pages": 2}, "UNSUPPORTED_LAYOUT"),
        ({"rotate": 90}, "UNSUPPORTED_LAYOUT"),
        ({"cropbox": (10, 10, 500, 800)}, "UNSUPPORTED_LAYOUT"),
        ({"text_layer": False}, "UNSUPPORTED_LAYOUT"),
        ({"marker": None}, "UNSUPPORTED_TEMPLATE"),
        ({"user_password": "secret"}, "ENCRYPTED_PDF"),
        ({"owner_password": "owner"}, "ENCRYPTED_PDF"),
    ],
    ids=["multipage", "rotated", "cropped", "scanned", "wrong-template", "password", "owner-only"],
)
def test_unsupported_pdfs_get_their_specific_error_and_leave_nothing_behind(
    client, settings, tmp_path, kwargs, code
):
    path = tmp_path / "bad.pdf"
    build_pdf(path, normal_rows("Example Bad Fund", "2026-11-10"), **kwargs)
    response = upload(client, path.read_bytes())
    assert response.status_code == 422
    assert error_of(response)["code"] == code
    assert str(tmp_path) not in response.text
    assert_nothing_persisted(client, settings)


def test_other_currency_is_rejected(client, settings, tmp_path):
    path = tmp_path / "eur.pdf"
    build_pdf(path, normal_rows("Example Euro Fund", "2026-11-10", currency="EUR"))
    response = upload(client, path.read_bytes())
    assert response.status_code == 422
    assert error_of(response)["code"] == "UNSUPPORTED_CURRENCY"
    assert_nothing_persisted(client, settings)


def test_missing_file_part_is_an_invalid_request(client):
    response = client.post(f"{API}/documents", data={"x": "y"})
    assert response.status_code == 422
    assert error_of(response)["code"] == "INVALID_REQUEST"


# --- parser timeout --------------------------------------------------------------------------


def test_a_hung_parser_is_killed_after_the_timeout(settings, tmp_path):
    pid_file = tmp_path / "worker.pid"
    script = tmp_path / "slow_worker.py"
    script.write_text(
        f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    )
    slow = dataclasses.replace(
        settings, parser_command=(sys.executable, str(script)), parse_timeout_seconds=0.5
    )
    from fastapi.testclient import TestClient

    with TestClient(create_app(slow)) as client:
        started = time.monotonic()
        response = upload(client, fixture_bytes("normal"))
        assert time.monotonic() - started < 10
        assert response.status_code == 504
        assert error_of(response)["code"] == "PARSING_TIMEOUT"
        assert_nothing_persisted(client, slow)

    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("worker process was still alive after the timeout")


def test_a_worker_that_prints_garbage_is_an_internal_error(settings, tmp_path):
    script = tmp_path / "garbage_worker.py"
    script.write_text("print('not json at /private/path')\n")
    broken = dataclasses.replace(settings, parser_command=(sys.executable, str(script)))
    from fastapi.testclient import TestClient

    with TestClient(create_app(broken)) as client:
        response = upload(client, fixture_bytes("normal"))
        assert response.status_code == 500
        assert error_of(response)["code"] == "INTERNAL_ERROR"
        assert "/private/path" not in response.text
        assert_nothing_persisted(client, broken)


# --- persistence failures ----------------------------------------------------------------------


def test_storage_failure_leaves_no_record_and_no_file(client, settings, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk exploded at /secret/place")

    monkeypatch.setattr(storage_module, "promote", boom)
    response = upload(client, fixture_bytes("normal"))
    assert response.status_code == 500
    assert error_of(response)["code"] == "STORAGE_ERROR"
    assert "/secret/place" not in response.text and "Traceback" not in response.text
    monkeypatch.undo()
    assert_nothing_persisted(client, settings)


def test_commit_failure_removes_the_new_original_and_leaves_no_rows(client, settings, monkeypatch):
    def failing_commit(self):
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(Session, "commit", failing_commit)
    response = upload(client, fixture_bytes("normal"))
    monkeypatch.undo()
    assert response.status_code == 500
    assert error_of(response)["code"] == "STORAGE_ERROR"
    assert_nothing_persisted(client, settings)


def test_a_locked_database_is_reported_as_write_conflict(client, settings, monkeypatch):
    def locked_commit(self):
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(Session, "commit", locked_commit)
    response = upload(client, fixture_bytes("normal"))
    monkeypatch.undo()
    assert response.status_code == 409
    assert error_of(response)["code"] == "WRITE_CONFLICT"
    assert_nothing_persisted(client, settings)


# --- concurrency ---------------------------------------------------------------------------


def make_upload(data: bytes, name: str = "normal.pdf") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data), filename=name, size=len(data),
        headers=Headers({"content-type": "application/pdf"}),
    )


def test_simultaneous_identical_imports_create_one_record_and_keep_the_original(app, settings):
    data = fixture_bytes("normal")

    def attempt(_):
        with app.state.session_factory() as session:
            try:
                return imports_service.import_document(make_upload(data), session, settings)
            except AppError as exc:
                return exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))

    winners = [r for r in results if not isinstance(r, AppError)]
    losers = [r for r in results if isinstance(r, AppError)]
    assert len(winners) == 1
    assert all(e.code is ErrorCode.DOCUMENT_DUPLICATE for e in losers), [e.code for e in losers]
    assert all(e.details["existing_document_id"] == winners[0].id for e in losers)
    with app.state.session_factory() as session:
        assert len(session.scalars(select(Document)).all()) == 1
    assert data_files(settings) == {"originals": [f"{winners[0].sha256}.pdf"], "tmp": []}
    stored = settings.originals_dir / f"{winners[0].sha256}.pdf"
    assert stored.read_bytes() == data


# --- original integrity --------------------------------------------------------------------


def test_missing_or_altered_original_blocks_file_reads(client, settings):
    detail = import_fixture(client, "normal")
    stored = settings.originals_dir / f"{detail['sha256']}.pdf"

    stored.write_bytes(fixture_bytes("amount-error"))
    altered = client.get(f"{API}/documents/{detail['id']}/file")
    assert altered.status_code == 409
    assert error_of(altered)["code"] == "SOURCE_INTEGRITY_MISMATCH"

    stored.unlink()
    gone = client.get(f"{API}/documents/{detail['id']}/file")
    assert gone.status_code == 409
    assert error_of(gone)["code"] == "SOURCE_UNAVAILABLE"
    assert client.get(f"{API}/documents/{detail['id']}").status_code == 200  # record still readable


def test_temp_uploads_left_by_a_crashed_process_are_removed_at_startup(settings):
    settings.ensure_dirs()
    leftover = settings.tmp_dir / "crashed-midway.upload"
    leftover.write_bytes(b"%PDF-partial")
    kept = settings.originals_dir / ("b" * 64 + ".pdf")
    kept.write_bytes(b"an original must never be touched")

    create_app(settings)

    assert not leftover.exists()
    assert kept.exists()
