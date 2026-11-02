import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.schemas import ErrorCode, FieldKey, ParsedDocument, SourceParseStatus
from app.services.pdf_parser import PdfParseError, parse_pdf

from . import pdfmaker
from .pdfmaker import FIXTURES, build_pdf, expected, normal_rows

SAMPLE_IDS = [s["id"] for s in pdfmaker.manifest()["samples"]]
BACKEND_DIR = Path(__file__).resolve().parents[1]


def fields_by_key(doc: ParsedDocument):
    return {f.key: f for f in doc.fields}


def make(tmp_path, rows=None, **kwargs) -> Path:
    path = tmp_path / "sample.pdf"
    build_pdf(path, rows if rows is not None else normal_rows("Example Test Fund", "2026-11-10"), **kwargs)
    return path


# --- fixtures themselves -----------------------------------------------------------------


def test_manifest_hashes_match_the_committed_pdf_bytes():
    for sample in pdfmaker.manifest()["samples"]:
        data = (FIXTURES / sample["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sample["sha256"], sample["id"]


def test_fixture_generation_is_reproducible(tmp_path):
    manifest = pdfmaker.gf.generate(tmp_path)
    assert manifest == pdfmaker.manifest()
    for sample in manifest["samples"]:
        assert (tmp_path / sample["file"]).read_bytes() == (FIXTURES / sample["file"]).read_bytes()


def test_each_sample_has_distinct_content():
    shas = [s["sha256"] for s in pdfmaker.manifest()["samples"]]
    assert len(set(shas)) == len(shas) == 4


# --- parsing the four samples against the hand-written expectations -----------------------


@pytest.mark.parametrize("sample_id", SAMPLE_IDS)
def test_samples_parse_to_the_hand_written_expectations(sample_id):
    sample = next(s for s in pdfmaker.manifest()["samples"] if s["id"] == sample_id)
    exp = expected(sample_id)
    doc = parse_pdf(FIXTURES / sample["file"])

    assert doc.sha256 == sample["sha256"]
    assert [f.key for f in doc.fields] == list(FieldKey)
    assert doc.page_width == pytest.approx(595.2756, abs=0.01)
    assert doc.page_height == pytest.approx(841.8898, abs=0.01)

    for field in doc.fields:
        want = exp["fields"][field.key.value]
        assert field.source_text == want["source_text"], field.key
        assert field.source_value == want["source_value"], field.key
        assert field.source_parse_status.value == want["status"], field.key
        if want["region"] is None:
            assert field.evidence is None, field.key
            continue
        ev = field.evidence
        assert ev is not None and ev.page == 1 and ev.document_sha256 == sample["sha256"]
        box, region = ev.bbox, want["region"]
        assert all(math.isfinite(v) for v in (box.x, box.y, box.width, box.height))
        assert box.width > 0 and box.height > 0
        assert 0 <= box.x and box.x + box.width <= 1
        assert 0 <= box.y and box.y + box.height <= 1
        # The box must sit on the value, not the label or neighbouring rows.
        assert region["x_min"] <= box.x and box.x + box.width <= region["x_max"], field.key
        assert region["y_min"] <= box.y and box.y + box.height <= region["y_max"], field.key


def test_source_of_the_amount_error_sample_is_the_pdf_value_not_the_fault():
    doc = parse_pdf(FIXTURES / "amount-error.pdf")
    total = fields_by_key(doc)[FieldKey.TOTAL_DUE]
    assert total.source_value == "50000.00"
    assert total.source_text == "50,000.00"


def test_missing_value_stays_null_without_an_invented_box():
    doc = parse_pdf(FIXTURES / "missing-source.pdf")
    due = fields_by_key(doc)[FieldKey.DUE_DATE]
    assert due.source_parse_status is SourceParseStatus.MISSING
    assert due.source_text is None and due.source_value is None and due.evidence is None
    others = [f for f in doc.fields if f.key != FieldKey.DUE_DATE]
    assert all(f.source_parse_status is SourceParseStatus.VALID for f in others)


def test_bbox_uses_the_documented_top_left_normalisation(tmp_path):
    doc = parse_pdf(make(tmp_path))
    box = fields_by_key(doc)[FieldKey.TOTAL_DUE].evidence.bbox
    text_width = stringWidth("50,000.00", "Helvetica", 11)
    assert box.x == pytest.approx(300 / 595.2756, abs=0.002)
    assert box.width == pytest.approx(text_width / 595.2756, abs=0.003)
    baseline = 300 + 32 * 5
    assert box.y == pytest.approx((baseline - 8.7) / 841.8898, abs=0.004)
    assert box.height == pytest.approx(11 / 841.8898, abs=0.004)


# --- unreliable sources are flagged, never guessed -----------------------------------------


def test_duplicate_label_is_ambiguous_and_never_picks_the_first_value(tmp_path):
    rows = normal_rows("Example Test Fund", "2026-11-10")
    rows.append(("Management fee", "9,999.00"))
    doc = parse_pdf(make(tmp_path, rows))
    fee = fields_by_key(doc)[FieldKey.MANAGEMENT_FEE]
    assert fee.source_parse_status is SourceParseStatus.AMBIGUOUS
    assert fee.source_text is None and fee.source_value is None and fee.evidence is None
    assert fields_by_key(doc)[FieldKey.TOTAL_DUE].source_parse_status is SourceParseStatus.VALID


def test_label_repeated_in_body_text_is_ambiguous(tmp_path):
    doc = parse_pdf(make(tmp_path, extra_lines=("Please note the Total amount due 1,000.00",)))
    total = fields_by_key(doc)[FieldKey.TOTAL_DUE]
    assert total.source_parse_status is SourceParseStatus.AMBIGUOUS


def test_absent_label_is_missing(tmp_path):
    rows = [r for r in normal_rows("Example Test Fund", "2026-11-10") if r[0] != "Management fee"]
    doc = parse_pdf(make(tmp_path, rows))
    fee = fields_by_key(doc)[FieldKey.MANAGEMENT_FEE]
    assert fee.source_parse_status is SourceParseStatus.MISSING
    assert fee.evidence is None


def test_unparseable_value_is_invalid_but_keeps_text_and_location(tmp_path):
    doc = parse_pdf(make(tmp_path, normal_rows("Example Test Fund", "2026-02-30")))
    due = fields_by_key(doc)[FieldKey.DUE_DATE]
    assert due.source_parse_status is SourceParseStatus.INVALID
    assert due.source_text == "2026-02-30"
    assert due.source_value is None
    assert due.evidence is not None


def test_missing_currency_label_is_kept_null_not_an_error(tmp_path):
    rows = [r for r in normal_rows("Example Test Fund", "2026-11-10") if r[0] != "Currency"]
    cur = fields_by_key(parse_pdf(make(tmp_path, rows)))[FieldKey.CURRENCY]
    assert cur.source_parse_status is SourceParseStatus.MISSING and cur.source_value is None


# --- files the template parser must refuse -------------------------------------------------


def code_of(excinfo) -> ErrorCode:
    return excinfo.value.code


def test_other_currency_is_unsupported(tmp_path):
    rows = normal_rows("Example Test Fund", "2026-11-10", currency="EUR")
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(make(tmp_path, rows))
    assert code_of(exc) is ErrorCode.UNSUPPORTED_CURRENCY


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"pages": 2}, ErrorCode.UNSUPPORTED_LAYOUT),
        ({"rotate": 90}, ErrorCode.UNSUPPORTED_LAYOUT),
        ({"cropbox": (10, 10, 500, 800)}, ErrorCode.UNSUPPORTED_LAYOUT),
        ({"text_layer": False}, ErrorCode.UNSUPPORTED_LAYOUT),
        ({"marker": None}, ErrorCode.UNSUPPORTED_TEMPLATE),
        ({"marker": "SOMETHING-ELSE-V9"}, ErrorCode.UNSUPPORTED_TEMPLATE),
        ({"user_password": "secret"}, ErrorCode.ENCRYPTED_PDF),
        ({"owner_password": "owner-only"}, ErrorCode.ENCRYPTED_PDF),
    ],
    ids=["multipage", "rotated", "cropped", "no-text-layer", "no-marker", "wrong-marker",
         "password-protected", "owner-password-encrypted"],
)
def test_unsupported_files_are_rejected_with_a_specific_code(tmp_path, kwargs, code):
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(make(tmp_path, **kwargs))
    assert code_of(exc) is code


def test_duplicate_marker_is_rejected(tmp_path):
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(make(tmp_path, extra_lines=("TRACEREVIEW-CALL-V1",)))
    assert code_of(exc) is ErrorCode.UNSUPPORTED_TEMPLATE


@pytest.mark.parametrize("data", [b"", b"this is not a pdf", b"%PDF-1.4\n1 0 obj\n<<"])
def test_corrupt_files_are_invalid_pdf(tmp_path, data):
    path = tmp_path / "bad.pdf"
    path.write_bytes(data)
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(path)
    assert code_of(exc) is ErrorCode.INVALID_PDF


def test_truncated_real_pdf_is_invalid_pdf(tmp_path):
    path = tmp_path / "cut.pdf"
    path.write_bytes((FIXTURES / "normal.pdf").read_bytes()[:300])
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(path)
    assert code_of(exc) is ErrorCode.INVALID_PDF


def test_error_messages_do_not_leak_the_local_path(tmp_path):
    path = tmp_path / "secret-dir-name.pdf"
    path.write_bytes(b"garbage")
    with pytest.raises(PdfParseError) as exc:
        parse_pdf(path)
    assert "secret-dir-name" not in str(exc.value) and str(tmp_path) not in str(exc.value)


# --- the isolated worker ------------------------------------------------------------------


def run_worker(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.services.pdf_worker", str(path)],
        cwd=BACKEND_DIR, capture_output=True, text=True, timeout=30,
    )


def test_worker_prints_only_the_parsed_document_json():
    proc = run_worker(FIXTURES / "normal.pdf")
    assert proc.returncode == 0, proc.stderr
    doc = ParsedDocument.model_validate_json(proc.stdout)
    assert doc.sha256 == pdfmaker.manifest()["samples"][0]["sha256"]
    assert str(FIXTURES) not in proc.stdout + proc.stderr


def test_worker_reports_a_structured_error_without_text_or_path(tmp_path):
    path = tmp_path / "leaky-name.pdf"
    path.write_bytes(b"garbage")
    proc = run_worker(path)
    assert proc.returncode != 0
    assert json.loads(proc.stdout) == {"error": {"code": "INVALID_PDF"}}
    assert "leaky-name" not in proc.stdout + proc.stderr


def test_worker_reports_unsupported_layout_code(tmp_path):
    proc = run_worker(make(tmp_path, pages=2))
    assert proc.returncode != 0
    assert json.loads(proc.stdout) == {"error": {"code": "UNSUPPORTED_LAYOUT"}}
