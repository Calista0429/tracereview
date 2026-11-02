import pytest

from app.domain.rules import validate_document
from app.schemas import (
    Evidence,
    EvidenceBox,
    FieldKey,
    RuleId,
    RuleStatus,
    SourceParseStatus,
)

from .conftest import SHA, make_fields, replace_field

IDS = [RuleId.R001_REQUIRED, RuleId.R002_TOTAL, RuleId.R003_EVIDENCE]


def by_id(results):
    return {r.id: r for r in results}


def statuses(results):
    return [r.status for r in results]


def test_normal_document_passes_all_three_rules_in_fixed_order():
    results = validate_document(make_fields(), SHA)
    assert [r.id for r in results] == IDS
    assert statuses(results) == [RuleStatus.PASS] * 3
    assert by_id(results)[RuleId.R002_TOTAL].fields == [
        FieldKey.INVESTMENT_AMOUNT,
        FieldKey.MANAGEMENT_FEE,
        FieldKey.TOTAL_DUE,
    ]


def test_wrong_total_fails_only_r002_and_explains_the_difference():
    results = by_id(validate_document(make_fields(total_due="500000.00"), SHA))
    assert results[RuleId.R001_REQUIRED].status == RuleStatus.PASS
    assert results[RuleId.R003_EVIDENCE].status == RuleStatus.PASS
    r002 = results[RuleId.R002_TOTAL]
    assert r002.status == RuleStatus.FAIL
    assert "50000.00" in r002.message
    assert "500000.00" in r002.message
    assert "450000.00" in r002.message


def test_missing_amount_fails_r001_and_leaves_r002_not_evaluated():
    results = by_id(validate_document(make_fields(management_fee=None), SHA))
    r001 = results[RuleId.R001_REQUIRED]
    assert r001.status == RuleStatus.FAIL
    assert r001.fields == [FieldKey.MANAGEMENT_FEE]
    assert results[RuleId.R002_TOTAL].status == RuleStatus.NOT_EVALUATED
    assert results[RuleId.R003_EVIDENCE].status == RuleStatus.PASS


def test_missing_due_date_fails_r001_but_r002_still_runs():
    results = by_id(validate_document(make_fields(due_date=None), SHA))
    assert results[RuleId.R001_REQUIRED].status == RuleStatus.FAIL
    assert results[RuleId.R001_REQUIRED].fields == [FieldKey.DUE_DATE]
    assert results[RuleId.R002_TOTAL].status == RuleStatus.PASS


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        (FieldKey.TOTAL_DUE, "1.001"),
        (FieldKey.DUE_DATE, "2026-02-30"),
        (FieldKey.CURRENCY, "EUR"),
        (FieldKey.FUND_NAME, "  "),
    ],
)
def test_invalid_or_blank_current_value_fails_r001(key, bad):
    results = by_id(validate_document(make_fields(**{key.value: bad}), SHA))
    assert results[RuleId.R001_REQUIRED].status == RuleStatus.FAIL
    assert key in results[RuleId.R001_REQUIRED].fields


def test_invalid_amount_makes_r002_not_evaluated():
    results = by_id(validate_document(make_fields(total_due="abc"), SHA))
    assert results[RuleId.R002_TOTAL].status == RuleStatus.NOT_EVALUATED


def test_scaling_all_three_amounts_by_ten_still_passes_the_amount_rule():
    fields = make_fields(
        investment_amount="480000.00", management_fee="20000.00", total_due="500000.00"
    )
    results = validate_document(fields, SHA)
    # The rules only say "no problem found"; they cannot prove the values match the PDF.
    assert statuses(results) == [RuleStatus.PASS] * 3
    assert all(not f.verified for f in fields)  # nothing here ever marks a human check


def test_empty_source_text_fails_r003():
    fields = replace_field(make_fields(), FieldKey.TOTAL_DUE, source_text="  ")
    r003 = by_id(validate_document(fields, SHA))[RuleId.R003_EVIDENCE]
    assert r003.status == RuleStatus.FAIL
    assert r003.fields == [FieldKey.TOTAL_DUE]


@pytest.mark.parametrize(
    "status",
    [SourceParseStatus.MISSING, SourceParseStatus.AMBIGUOUS, SourceParseStatus.INVALID],
)
def test_non_valid_source_status_fails_r003(status):
    fields = replace_field(
        make_fields(), FieldKey.DUE_DATE, source_parse_status=status
    )
    r003 = by_id(validate_document(fields, SHA))[RuleId.R003_EVIDENCE]
    assert r003.status == RuleStatus.FAIL
    assert r003.fields == [FieldKey.DUE_DATE]
    assert "Payment due date" in r003.message


def test_missing_evidence_object_fails_r003():
    fields = replace_field(make_fields(), FieldKey.CURRENCY, evidence=None)
    r003 = by_id(validate_document(fields, SHA))[RuleId.R003_EVIDENCE]
    assert r003.status == RuleStatus.FAIL
    assert r003.fields == [FieldKey.CURRENCY]


def _ev(sha=SHA, page=1, **box):
    base = dict(x=0.5, y=0.5, width=0.1, height=0.02)
    base.update(box)
    return Evidence(document_sha256=sha, page=page, bbox=EvidenceBox(**base))


@pytest.mark.parametrize(
    "evidence",
    [
        _ev(x=-0.01),
        _ev(y=-0.01),
        _ev(x=0.95, width=0.1),  # right edge past the page
        _ev(y=0.99, height=0.02),  # bottom edge past the page
        _ev(width=0),
        _ev(height=0),
        _ev(width=-0.1),
        _ev(x=float("nan")),
        _ev(width=float("inf")),
        _ev(page=0),
        _ev(page=2),
        _ev(sha="b" * 64),
    ],
    ids=[
        "x<0", "y<0", "right-overflow", "bottom-overflow", "zero-width", "zero-height",
        "negative-width", "nan", "inf", "page0", "page2", "wrong-hash",
    ],
)
def test_out_of_bounds_or_stale_evidence_fails_r003(evidence):
    fields = replace_field(make_fields(), FieldKey.INVESTMENT_AMOUNT, evidence=evidence)
    r003 = by_id(validate_document(fields, SHA))[RuleId.R003_EVIDENCE]
    assert r003.status == RuleStatus.FAIL
    assert r003.fields == [FieldKey.INVESTMENT_AMOUNT]


def test_box_touching_the_page_edge_is_accepted():
    fields = replace_field(
        make_fields(), FieldKey.TOTAL_DUE, evidence=_ev(x=0.9, width=0.1, y=0.98, height=0.02)
    )
    assert by_id(validate_document(fields, SHA))[RuleId.R003_EVIDENCE].status == RuleStatus.PASS


def test_rules_are_independent_and_do_not_mutate_input():
    fields = make_fields(total_due=None)
    fields = replace_field(fields, FieldKey.DUE_DATE, evidence=None, source_parse_status=SourceParseStatus.MISSING)
    before = [f.model_dump() for f in fields]
    results = by_id(validate_document(fields, SHA))
    assert results[RuleId.R001_REQUIRED].status == RuleStatus.FAIL
    assert results[RuleId.R002_TOTAL].status == RuleStatus.NOT_EVALUATED
    assert results[RuleId.R003_EVIDENCE].status == RuleStatus.FAIL
    assert [f.model_dump() for f in fields] == before


def test_a_missing_field_record_counts_as_null_and_missing_source():
    fields = [f for f in make_fields() if f.key != FieldKey.MANAGEMENT_FEE]
    results = by_id(validate_document(fields, SHA))
    assert FieldKey.MANAGEMENT_FEE in results[RuleId.R001_REQUIRED].fields
    assert FieldKey.MANAGEMENT_FEE in results[RuleId.R003_EVIDENCE].fields
    assert results[RuleId.R002_TOTAL].status == RuleStatus.NOT_EVALUATED
