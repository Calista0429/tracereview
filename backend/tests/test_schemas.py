import pytest
from pydantic import ValidationError

from app.schemas import (
    ConfirmRequest,
    ExportRequest,
    FieldKey,
    FieldRecord,
    SourceParseStatus,
    UpdateFieldsRequest,
    VerifyFieldRequest,
)


def test_update_request_trims_reason_and_accepts_null_value():
    req = UpdateFieldsRequest(
        expected_version=1,
        changes=[{"key": "total_due", "value": None}],
        reason="  Corrected after checking the PDF.  ",
    )
    assert req.reason == "Corrected after checking the PDF."
    assert req.changes[0].value is None


@pytest.mark.parametrize("reason", ["", "   ", "x" * 201])
def test_update_request_rejects_bad_reason(reason):
    with pytest.raises(ValidationError):
        UpdateFieldsRequest(
            expected_version=1, changes=[{"key": "total_due", "value": "1.00"}], reason=reason
        )


def test_update_request_reason_boundary_200_is_ok():
    UpdateFieldsRequest(
        expected_version=1, changes=[{"key": "total_due", "value": "1.00"}], reason="x" * 200
    )


def test_update_request_changes_must_be_1_to_6_unique_keys():
    ok = {"key": "total_due", "value": "1.00"}
    with pytest.raises(ValidationError):
        UpdateFieldsRequest(expected_version=1, changes=[], reason="r")
    with pytest.raises(ValidationError):
        UpdateFieldsRequest(expected_version=1, changes=[ok, ok], reason="r")
    with pytest.raises(ValidationError):
        UpdateFieldsRequest(
            expected_version=1, changes=[{"key": "nope", "value": "1"}], reason="r"
        )
    all_six = [{"key": k.value, "value": "x"} for k in FieldKey]
    assert len(UpdateFieldsRequest(expected_version=1, changes=all_six, reason="r").changes) == 6


def test_numeric_values_are_not_coerced_to_strings():
    with pytest.raises(ValidationError):
        UpdateFieldsRequest(
            expected_version=1, changes=[{"key": "total_due", "value": 50000.0}], reason="r"
        )


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.5])
def test_expected_version_must_be_a_positive_int(version):
    with pytest.raises(ValidationError):
        ConfirmRequest(expected_version=version)


def test_confirm_request_accepts_no_extra_parameters():
    with pytest.raises(ValidationError):
        ConfirmRequest(expected_version=1, ignore_errors=True)
    with pytest.raises(ValidationError):
        ConfirmRequest(expected_version=1, fields={"total_due": "1.00"})


def test_export_request_only_supports_json():
    assert ExportRequest(expected_version=3, format="json").format == "json"
    with pytest.raises(ValidationError):
        ExportRequest(expected_version=3, format="csv")


def test_verify_request_shape():
    req = VerifyFieldRequest(expected_version=2, field_key="total_due", verified=True)
    assert req.field_key is FieldKey.TOTAL_DUE


def test_modified_is_derived_from_current_vs_initial():
    base = dict(key=FieldKey.TOTAL_DUE, source_parse_status=SourceParseStatus.VALID)
    assert not FieldRecord(**base, initial_extracted_value="1.00", current_value="1.00").modified
    assert FieldRecord(**base, initial_extracted_value="1.00", current_value="2.00").modified
    assert FieldRecord(**base, initial_extracted_value=None, current_value="2.00").modified
    dumped = FieldRecord(**base, initial_extracted_value="1.00", current_value="2.00").model_dump()
    assert dumped["modified"] is True
