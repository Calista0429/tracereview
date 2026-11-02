"""Field normalisation and exact money arithmetic (integer US cents, never floats)."""

from __future__ import annotations

import re
from datetime import date

from app.schemas import FieldKey

FIELD_ORDER: tuple[FieldKey, ...] = tuple(FieldKey)

# The label printed on the template and shown in messages (spec section 3.2).
FIELD_LABELS: dict[FieldKey, str] = {
    FieldKey.FUND_NAME: "Fund name",
    FieldKey.CURRENCY: "Currency",
    FieldKey.DUE_DATE: "Payment due date",
    FieldKey.INVESTMENT_AMOUNT: "Investment contribution",
    FieldKey.MANAGEMENT_FEE: "Management fee",
    FieldKey.TOTAL_DUE: "Total amount due",
}

AMOUNT_KEYS: tuple[FieldKey, ...] = (
    FieldKey.INVESTMENT_AMOUNT,
    FieldKey.MANAGEMENT_FEE,
    FieldKey.TOTAL_DUE,
)

MAX_MINOR = 99_999_999_999  # 999,999,999.99
FUND_NAME_MAX = 120

# ASCII-only on purpose: `\d` would accept full-width and other Unicode digits.
_AMOUNT_RE = re.compile(r"^(?P<int>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.(?P<frac>[0-9]{1,2}))?$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class FieldValueError(ValueError):
    def __init__(self, key: FieldKey | None, message: str):
        super().__init__(message)
        self.key = key
        self.message = message


def to_minor(value: str) -> int:
    """Parse a valid amount string into integer cents, e.g. ``"48000.00" -> 4800000``."""
    return _amount_to_minor(None, value)


def from_minor(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    units, cents = divmod(abs(minor), 100)
    return f"{sign}{units}.{cents:02d}"


def normalize_field(key: FieldKey, raw: str | None) -> str | None:
    """Return the canonical stored form of ``raw`` or ``None`` for unknown.

    Blank input means "unknown" and is never turned into zero. A non-blank value that is
    not valid for the field raises :class:`FieldValueError`.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    if key in AMOUNT_KEYS:
        return from_minor(_amount_to_minor(key, text))
    if key is FieldKey.FUND_NAME:
        if len(text) > FUND_NAME_MAX:
            raise FieldValueError(key, f"Fund name must be at most {FUND_NAME_MAX} characters.")
        return text
    if key is FieldKey.CURRENCY:
        if text != "USD":
            raise FieldValueError(key, "Currency must be USD.")
        return text
    if key is FieldKey.DUE_DATE:
        return _normalize_date(key, text)
    raise FieldValueError(key, "Unknown field.")  # pragma: no cover - exhaustive above


def _amount_to_minor(key: FieldKey | None, raw: str) -> int:
    match = _AMOUNT_RE.match(raw.strip())
    if match is None:
        raise FieldValueError(
            key, "Enter an amount such as 48,000.00 (digits, optional commas, up to 2 decimals)."
        )
    units = int(match.group("int").replace(",", ""))
    cents = int((match.group("frac") or "").ljust(2, "0") or "0")
    minor = units * 100 + cents
    if minor > MAX_MINOR:
        raise FieldValueError(key, "Amount must not exceed 999,999,999.99.")
    return minor


def _normalize_date(key: FieldKey, text: str) -> str:
    if not _DATE_RE.match(text):
        raise FieldValueError(key, "Date must use the format YYYY-MM-DD.")
    try:
        parsed = date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        raise FieldValueError(key, "Date is not a valid calendar date.") from None
    return parsed.isoformat()
