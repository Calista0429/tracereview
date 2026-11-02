import pytest

from app.domain.values import FieldValueError, from_minor, normalize_field, to_minor
from app.schemas import FieldKey


def test_money_is_exact():
    assert to_minor("0.10") == 10
    assert to_minor("0.20") == 20
    assert to_minor("0.10") + to_minor("0.20") == to_minor("0.30") == 30
    assert to_minor("48000.00") == 4_800_000


def test_from_minor_round_trips_and_signs():
    assert from_minor(5_000_000) == "50000.00"
    assert from_minor(5) == "0.05"
    assert from_minor(-5) == "-0.05"
    assert from_minor(0) == "0.00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("48,000", "48000.00"),
        ("48000.0", "48000.00"),
        ("48000", "48000.00"),
        (" 0.1 ", "0.10"),
        ("0", "0.00"),
        ("1,234,567.89", "1234567.89"),
        ("999,999,999.99", "999999999.99"),
        ("999999999.99", "999999999.99"),
    ],
)
def test_normalize_amount(raw, expected):
    assert normalize_field(FieldKey.INVESTMENT_AMOUNT, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.001",
        "-1",
        "+5",
        "1e3",
        "1E3",
        "NaN",
        "Infinity",
        "-Infinity",
        "12,34",
        "1,0000",
        ",100",
        "1,00",
        "$5.00",
        "USD 5.00",
        "5.",
        ".5",
        "1 000",
        "1,000,000,000.00",
        "1000000000",
        "１２",
        "abc",
    ],
)
def test_normalize_amount_rejects_invalid(raw):
    with pytest.raises(FieldValueError):
        normalize_field(FieldKey.TOTAL_DUE, raw)


@pytest.mark.parametrize("key", list(FieldKey))
def test_null_is_not_zero(key):
    assert normalize_field(key, None) is None
    assert normalize_field(key, "") is None
    assert normalize_field(key, "   ") is None


def test_to_minor_rejects_invalid_input():
    with pytest.raises(FieldValueError):
        to_minor("1.001")


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("2026-02-30", False),
        ("2026-13-01", False),
        ("2023-02-29", False),
        ("2024-02-29", True),
        ("2020-01-15", True),  # a past date is allowed
        ("2026-11-10", True),
        ("2026-1-5", False),
        ("20261110", False),
        ("2026-11-10T00:00:00", False),
        ("2026/11/10", False),
        ("２０２６-11-10", False),
    ],
)
def test_due_date_must_be_a_strict_calendar_date(raw, ok):
    if ok:
        assert normalize_field(FieldKey.DUE_DATE, raw) == raw
    else:
        with pytest.raises(FieldValueError):
            normalize_field(FieldKey.DUE_DATE, raw)


def test_fund_name_is_trimmed_and_length_bounded():
    assert normalize_field(FieldKey.FUND_NAME, "  Example Growth Fund I  ") == "Example Growth Fund I"
    assert normalize_field(FieldKey.FUND_NAME, "x" * 120) == "x" * 120
    with pytest.raises(FieldValueError):
        normalize_field(FieldKey.FUND_NAME, "x" * 121)


def test_currency_is_fixed_to_usd():
    assert normalize_field(FieldKey.CURRENCY, " USD ") == "USD"
    for bad in ("EUR", "usd", "US$"):
        with pytest.raises(FieldValueError):
            normalize_field(FieldKey.CURRENCY, bad)


def test_field_value_error_names_the_field():
    with pytest.raises(FieldValueError) as exc:
        normalize_field(FieldKey.MANAGEMENT_FEE, "1.001")
    assert exc.value.key == FieldKey.MANAGEMENT_FEE
