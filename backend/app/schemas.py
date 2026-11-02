"""Request, response and error shapes shared by the domain and API layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    computed_field,
    field_validator,
    model_validator,
)


class FieldKey(StrEnum):
    # Declaration order is the canonical display/response order (spec section 3.2).
    FUND_NAME = "fund_name"
    CURRENCY = "currency"
    DUE_DATE = "due_date"
    INVESTMENT_AMOUNT = "investment_amount"
    MANAGEMENT_FEE = "management_fee"
    TOTAL_DUE = "total_due"


class SourceParseStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


class RuleId(StrEnum):
    R001_REQUIRED = "R001_REQUIRED"
    R002_TOTAL = "R002_TOTAL"
    R003_EVIDENCE = "R003_EVIDENCE"


class RuleStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class DocumentStatus(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"


class ExtractionProfile(StrEnum):
    NONE = "none"
    TOTAL_EXTRA_ZERO = "total_extra_zero"
    DROP_DUE_DATE = "drop_due_date"


class AuditEventType(StrEnum):
    IMPORTED = "IMPORTED"
    FIELDS_UPDATED = "FIELDS_UPDATED"
    FIELD_VERIFICATION_CHANGED = "FIELD_VERIFICATION_CHANGED"
    CONFIRMED = "CONFIRMED"
    CONFIRMATION_REVOKED = "CONFIRMATION_REVOKED"
    EXPORT_GENERATED = "EXPORT_GENERATED"


class ErrorCode(StrEnum):
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_DUPLICATE = "DOCUMENT_DUPLICATE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    WRITE_CONFLICT = "WRITE_CONFLICT"
    REVIEW_BLOCKED = "REVIEW_BLOCKED"
    REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"
    DOCUMENT_CONFIRMED = "DOCUMENT_CONFIRMED"
    DOCUMENT_NOT_CONFIRMED = "DOCUMENT_NOT_CONFIRMED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_INTEGRITY_MISMATCH = "SOURCE_INTEGRITY_MISMATCH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    INVALID_PDF = "INVALID_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    UNSUPPORTED_LAYOUT = "UNSUPPORTED_LAYOUT"
    UNSUPPORTED_TEMPLATE = "UNSUPPORTED_TEMPLATE"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
    INVALID_FIELD_VALUE = "INVALID_FIELD_VALUE"
    INVALID_REQUEST = "INVALID_REQUEST"
    PARSING_TIMEOUT = "PARSING_TIMEOUT"
    STORAGE_ERROR = "STORAGE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# --- Evidence and fields ------------------------------------------------------------------


class EvidenceBox(BaseModel):
    """Normalised box with a top-left origin; deliberately unconstrained so R003 can judge it."""

    x: float
    y: float
    width: float
    height: float


class Evidence(BaseModel):
    document_sha256: str
    page: int
    bbox: EvidenceBox


class ParsedField(BaseModel):
    """What the template parser found in the PDF for one field. Never edited afterwards."""

    key: FieldKey
    source_text: str | None = None
    source_value: str | None = None
    source_parse_status: SourceParseStatus
    evidence: Evidence | None = None


class ParsedDocument(BaseModel):
    sha256: str
    page_width: float
    page_height: float
    fields: list[ParsedField]


class FieldRecord(BaseModel):
    key: FieldKey
    source_text: str | None = None
    source_value: str | None = None
    source_parse_status: SourceParseStatus
    initial_extracted_value: str | None = None
    current_value: str | None = None
    verified: bool = False
    verified_at: str | None = None
    verified_by: str | None = None
    evidence: Evidence | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def modified(self) -> bool:
        return self.current_value != self.initial_extracted_value


class RuleResult(BaseModel):
    id: RuleId
    status: RuleStatus
    fields: list[FieldKey]
    message: str


class RuleBrief(BaseModel):
    id: RuleId
    status: RuleStatus


class PageInfo(BaseModel):
    number: int = 1
    width: float
    height: float


class Confirmation(BaseModel):
    confirmed_at: str
    confirmed_by: str
    document_version: int


class AuditEventOut(BaseModel):
    id: int
    document_version: int
    event_type: AuditEventType
    actor: str
    created_at: str
    payload: dict[str, Any]


# --- Responses -----------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    id: str
    filename: str
    created_at: str
    status: DocumentStatus
    version: int
    rules: list[RuleBrief]


class DocumentDetail(BaseModel):
    id: str
    filename: str
    sha256: str
    status: DocumentStatus
    version: int
    template_id: str
    parser_version: str
    extraction_profile: ExtractionProfile
    created_at: str
    updated_at: str
    page: PageInfo
    fields: list[FieldRecord]
    rules: list[RuleResult]
    confirmation: Confirmation | None
    audit_events: list[AuditEventOut]


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


@dataclass(frozen=True)
class ExportPayload:
    filename: str
    content_type: str
    body: bytes
    sha256: str


# --- Requests ------------------------------------------------------------------------------

ExpectedVersion = Annotated[StrictInt, Field(ge=1)]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldChange(_StrictRequest):
    key: FieldKey
    value: str | None


class UpdateFieldsRequest(_StrictRequest):
    expected_version: ExpectedVersion
    changes: Annotated[list[FieldChange], Field(min_length=1, max_length=6)]
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_length(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 200:
            raise ValueError("reason must be 1-200 characters after trimming")
        return value

    @model_validator(mode="after")
    def _unique_keys(self) -> UpdateFieldsRequest:
        keys = [c.key for c in self.changes]
        if len(set(keys)) != len(keys):
            raise ValueError("changes must not repeat a field key")
        return self


class VerifyFieldRequest(_StrictRequest):
    expected_version: ExpectedVersion
    field_key: FieldKey
    verified: bool


class ConfirmRequest(_StrictRequest):
    expected_version: ExpectedVersion


class ExportRequest(_StrictRequest):
    expected_version: ExpectedVersion
    format: Literal["json"]
