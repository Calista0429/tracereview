from app.schemas import (
    Evidence,
    EvidenceBox,
    FieldKey,
    FieldRecord,
    SourceParseStatus,
)

SHA = "a" * 64

NORMAL_VALUES = {
    FieldKey.FUND_NAME: "Example Growth Fund I",
    FieldKey.CURRENCY: "USD",
    FieldKey.DUE_DATE: "2026-11-10",
    FieldKey.INVESTMENT_AMOUNT: "48000.00",
    FieldKey.MANAGEMENT_FEE: "2000.00",
    FieldKey.TOTAL_DUE: "50000.00",
}

_SOURCE_TEXT = {
    FieldKey.INVESTMENT_AMOUNT: "48,000.00",
    FieldKey.MANAGEMENT_FEE: "2,000.00",
    FieldKey.TOTAL_DUE: "50,000.00",
}


def make_field(key: FieldKey, value: str | None = None, **overrides) -> FieldRecord:
    """A valid, sourced field whose current value equals the source value."""
    value = NORMAL_VALUES[key] if value is None else value
    base = dict(
        key=key,
        source_text=_SOURCE_TEXT.get(key, value),
        source_value=value,
        source_parse_status=SourceParseStatus.VALID,
        initial_extracted_value=value,
        current_value=value,
        evidence=Evidence(
            document_sha256=SHA,
            page=1,
            bbox=EvidenceBox(x=0.65, y=0.43, width=0.16, height=0.02),
        ),
    )
    base.update(overrides)
    return FieldRecord(**base)


def make_fields(**current: str | None) -> list[FieldRecord]:
    """Six fields in spec order; keyword args override ``current_value`` (None allowed)."""
    fields = []
    for key in FieldKey:
        record = make_field(key)
        if key.value in current:
            record = record.model_copy(update={"current_value": current[key.value]})
        fields.append(record)
    return fields


def replace_field(fields: list[FieldRecord], key: FieldKey, **update) -> list[FieldRecord]:
    return [f.model_copy(update=update) if f.key == key else f for f in fields]


# --- application fixtures (Task 3+) --------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from .pdfmaker import FIXTURES  # noqa: E402

API = "/api/v1"


@pytest.fixture
def settings(tmp_path):
    from app.config import Settings

    # Generous parse timeout: worker start-up can take seconds on a busy machine. The
    # timeout test overrides it; the production default stays 10 s.
    return Settings(data_dir=tmp_path / "data", sqlite_timeout_seconds=3.0, parse_timeout_seconds=120.0)


@pytest.fixture
def app(settings):
    from app.main import create_app

    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app):
    return app.state.session_factory


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def upload(client, data: bytes, filename: str = "sample.pdf", content_type: str = "application/pdf", **form):
    return client.post(
        f"{API}/documents", files={"file": (filename, data, content_type)}, data=form or None
    )


def import_fixture(client, name: str):
    response = upload(client, fixture_bytes(name), f"{name}.pdf")
    assert response.status_code == 201, response.text
    return response.json()


def data_files(settings) -> dict[str, list[str]]:
    """Names of files currently held in the originals and temp folders."""
    def names(folder):
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    return {"originals": names(settings.originals_dir), "tmp": names(settings.tmp_dir)}


# --- review-flow helpers (Task 4+) ---------------------------------------------------------


@pytest.fixture
def review_client(client, monkeypatch):
    """A client whose imports parse in-process; worker isolation is covered in test_imports."""
    import json

    from app.services import imports as imports_service
    from app.services.pdf_parser import PdfParseError, parse_pdf

    def in_process(path, settings):
        try:
            return parse_pdf(path)
        except PdfParseError as exc:
            raise imports_service._worker_error(json.dumps({"error": {"code": exc.code.value}})) from None

    monkeypatch.setattr(imports_service, "run_parser", in_process)
    return client


def patch_fields(client, doc, changes: dict, *, version=None, reason="Checked against the PDF."):
    return client.patch(
        f"{API}/documents/{doc['id']}/fields",
        json={
            "expected_version": doc["version"] if version is None else version,
            "changes": [{"key": k, "value": v} for k, v in changes.items()],
            "reason": reason,
        },
    )


def verify(client, doc, key: str, verified: bool = True, *, version=None):
    return client.post(
        f"{API}/documents/{doc['id']}/verify",
        json={
            "expected_version": doc["version"] if version is None else version,
            "field_key": key,
            "verified": verified,
        },
    )


def confirm(client, doc, *, version=None):
    return client.post(
        f"{API}/documents/{doc['id']}/confirm",
        json={"expected_version": doc["version"] if version is None else version},
    )


ALL_KEYS = ["fund_name", "currency", "due_date", "investment_amount", "management_fee", "total_due"]


def verify_all(client, doc, keys=ALL_KEYS) -> dict:
    """Verify each key in turn, always using the version the server just returned."""
    for key in keys:
        response = verify(client, doc, key)
        assert response.status_code == 200, response.text
        doc = response.json()
    return doc
