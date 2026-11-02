"""The three pure deterministic rules.

Passing every rule means only that these checks found nothing wrong. It is not a human
review and does not prove a value matches the PDF (spec section 6).
"""

from __future__ import annotations

import math

from app.domain.values import (
    AMOUNT_KEYS,
    FIELD_LABELS,
    FIELD_ORDER,
    FieldValueError,
    from_minor,
    normalize_field,
    to_minor,
)
from app.schemas import (
    Evidence,
    FieldKey,
    FieldRecord,
    RuleId,
    RuleResult,
    RuleStatus,
    SourceParseStatus,
)

RULESET_VERSION = "v1"

_EDGE_EPSILON = 1e-9  # absorbs float rounding when a box touches the page edge


def validate_document(fields: list[FieldRecord], document_sha256: str) -> list[RuleResult]:
    """Evaluate R001, R002 and R003 in that order. Never mutates ``fields``."""
    by_key = {f.key: f for f in fields}
    return [
        _required(by_key),
        _total(by_key),
        _evidence(by_key, document_sha256),
    ]


def _label(key: FieldKey) -> str:
    return FIELD_LABELS[key]


def is_valid_value(key: FieldKey, value: str | None) -> bool:
    try:
        return normalize_field(key, value) is not None
    except FieldValueError:
        return False


def _required(by_key: dict[FieldKey, FieldRecord]) -> RuleResult:
    bad: list[FieldKey] = []
    reasons: list[str] = []
    for key in FIELD_ORDER:
        record = by_key.get(key)
        value = record.current_value if record else None
        if value is None or value.strip() == "":
            bad.append(key)
            reasons.append(f"{_label(key)} (missing)")
        elif not is_valid_value(key, value):
            bad.append(key)
            reasons.append(f"{_label(key)} (invalid)")
    if bad:
        return RuleResult(
            id=RuleId.R001_REQUIRED,
            status=RuleStatus.FAIL,
            fields=bad,
            message="Missing or invalid values: " + ", ".join(reasons) + ".",
        )
    return RuleResult(
        id=RuleId.R001_REQUIRED,
        status=RuleStatus.PASS,
        fields=list(FIELD_ORDER),
        message="All six fields have valid values.",
    )


def _total(by_key: dict[FieldKey, FieldRecord]) -> RuleResult:
    keys = list(AMOUNT_KEYS)
    cents: dict[FieldKey, int] = {}
    unusable: list[str] = []
    for key in keys:
        record = by_key.get(key)
        value = record.current_value if record else None
        try:
            if value is None or value.strip() == "":
                raise FieldValueError(key, "missing")
            cents[key] = to_minor(value)
        except FieldValueError:
            unusable.append(_label(key))
    if unusable:
        return RuleResult(
            id=RuleId.R002_TOTAL,
            status=RuleStatus.NOT_EVALUATED,
            fields=keys,
            message="Not evaluated: missing or invalid amounts: " + ", ".join(unusable) + ".",
        )
    line_items = cents[FieldKey.INVESTMENT_AMOUNT] + cents[FieldKey.MANAGEMENT_FEE]
    total = cents[FieldKey.TOTAL_DUE]
    if line_items == total:
        return RuleResult(
            id=RuleId.R002_TOTAL,
            status=RuleStatus.PASS,
            fields=keys,
            message="Total equals investment contribution plus management fee.",
        )
    return RuleResult(
        id=RuleId.R002_TOTAL,
        status=RuleStatus.FAIL,
        fields=keys,
        message=(
            "Total does not match the sum of line items. "
            f"Line items sum to {from_minor(line_items)}, total is {from_minor(total)}, "
            f"difference {from_minor(total - line_items)}."
        ),
    )


def evidence_problem(record: FieldRecord | None, document_sha256: str) -> str | None:
    """Why this field's source evidence is unusable, or ``None`` if it is complete."""
    if record is None:
        return "missing"
    if record.source_parse_status is not SourceParseStatus.VALID:
        return record.source_parse_status.value
    if record.source_text is None or record.source_text.strip() == "":
        return "empty source text"
    evidence = record.evidence
    if evidence is None:
        return "no evidence box"
    return _box_problem(evidence, document_sha256)


def _box_problem(evidence: Evidence, document_sha256: str) -> str | None:
    if evidence.document_sha256 != document_sha256:
        return "evidence does not belong to this file"
    if evidence.page != 1:
        return "invalid page"
    box = evidence.bbox
    values = (box.x, box.y, box.width, box.height)
    if not all(math.isfinite(v) for v in values):
        return "invalid coordinates"
    if box.width <= 0 or box.height <= 0:
        return "empty box"
    if box.x < 0 or box.y < 0:
        return "box outside page"
    if box.x + box.width > 1 + _EDGE_EPSILON or box.y + box.height > 1 + _EDGE_EPSILON:
        return "box outside page"
    return None


def _evidence(by_key: dict[FieldKey, FieldRecord], document_sha256: str) -> RuleResult:
    bad: list[FieldKey] = []
    reasons: list[str] = []
    for key in FIELD_ORDER:
        problem = evidence_problem(by_key.get(key), document_sha256)
        if problem is not None:
            bad.append(key)
            reasons.append(f"{_label(key)} ({problem})")
    if bad:
        return RuleResult(
            id=RuleId.R003_EVIDENCE,
            status=RuleStatus.FAIL,
            fields=bad,
            message="Source evidence is incomplete: " + ", ".join(reasons) + ".",
        )
    return RuleResult(
        id=RuleId.R003_EVIDENCE,
        status=RuleStatus.PASS,
        fields=list(FIELD_ORDER),
        message="All six fields have complete source evidence.",
    )
