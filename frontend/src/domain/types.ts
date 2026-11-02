// Mirrors the backend response shapes (backend/app/schemas.py). Amounts are decimal strings.

export const FIELD_KEYS = [
  "fund_name",
  "currency",
  "due_date",
  "investment_amount",
  "management_fee",
  "total_due",
] as const;
export type FieldKey = (typeof FIELD_KEYS)[number];

export const FIELD_LABELS: Record<FieldKey, string> = {
  fund_name: "Fund name",
  currency: "Currency",
  due_date: "Payment due date",
  investment_amount: "Investment contribution",
  management_fee: "Management fee",
  total_due: "Total amount due",
};

export const AMOUNT_KEYS: readonly FieldKey[] = ["investment_amount", "management_fee", "total_due"];

export type SourceParseStatus = "valid" | "missing" | "ambiguous" | "invalid";
export type RuleId = "R001_REQUIRED" | "R002_TOTAL" | "R003_EVIDENCE";
export type RuleStatus = "PASS" | "FAIL" | "NOT_EVALUATED";
export type DocumentStatus = "REVIEW_REQUIRED" | "CONFIRMED";
export type ExtractionProfile = "none" | "total_extra_zero" | "drop_due_date";

export interface EvidenceBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Evidence {
  document_sha256: string;
  page: number;
  bbox: EvidenceBox;
}

export interface FieldRecord {
  key: FieldKey;
  source_text: string | null;
  source_value: string | null;
  source_parse_status: SourceParseStatus;
  initial_extracted_value: string | null;
  current_value: string | null;
  modified: boolean;
  verified: boolean;
  verified_at: string | null;
  verified_by: string | null;
  evidence: Evidence | null;
}

export interface RuleResult {
  id: RuleId;
  status: RuleStatus;
  fields: FieldKey[];
  message: string;
}

export interface AuditEvent {
  id: number;
  document_version: number;
  event_type:
    | "IMPORTED"
    | "FIELDS_UPDATED"
    | "FIELD_VERIFICATION_CHANGED"
    | "CONFIRMED"
    | "CONFIRMATION_REVOKED"
    | "EXPORT_GENERATED";
  actor: string;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface Confirmation {
  confirmed_at: string;
  confirmed_by: string;
  document_version: number;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  sha256: string;
  status: DocumentStatus;
  version: number;
  template_id: string;
  parser_version: string;
  extraction_profile: ExtractionProfile;
  created_at: string;
  updated_at: string;
  page: { number: number; width: number; height: number };
  fields: FieldRecord[];
  rules: RuleResult[];
  confirmation: Confirmation | null;
  audit_events: AuditEvent[];
}

export interface DocumentSummary {
  id: string;
  filename: string;
  created_at: string;
  status: DocumentStatus;
  version: number;
  rules: { id: RuleId; status: RuleStatus }[];
}

export interface FieldChange {
  key: FieldKey;
  value: string | null;
}

export interface SampleInfo {
  id: string;
  file: string;
  sha256: string;
  profile: ExtractionProfile;
  title: string;
  description: string;
}
