import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "../src/routes";
import {
  FIELD_KEYS,
  type DocumentDetail,
  type FieldKey,
  type FieldRecord,
  type RuleResult,
} from "../src/domain/types";

const SHA = "a".repeat(64);

const NORMAL: Record<FieldKey, { value: string; text: string }> = {
  fund_name: { value: "Example Growth Fund I", text: "Example Growth Fund I" },
  currency: { value: "USD", text: "USD" },
  due_date: { value: "2026-11-10", text: "2026-11-10" },
  investment_amount: { value: "48000.00", text: "48,000.00" },
  management_fee: { value: "2000.00", text: "2,000.00" },
  total_due: { value: "50000.00", text: "50,000.00" },
};

export function makeField(key: FieldKey, over: Partial<FieldRecord> = {}): FieldRecord {
  const { value, text } = NORMAL[key];
  return {
    key,
    source_text: text,
    source_value: value,
    source_parse_status: "valid",
    initial_extracted_value: value,
    current_value: value,
    modified: false,
    verified: false,
    verified_at: null,
    verified_by: null,
    evidence: {
      document_sha256: SHA,
      page: 1,
      bbox: { x: 0.5, y: 0.35 + FIELD_KEYS.indexOf(key) * 0.04, width: 0.1, height: 0.02 },
    },
    ...over,
  };
}

export const passingRules: RuleResult[] = [
  { id: "R001_REQUIRED", status: "PASS", fields: [...FIELD_KEYS], message: "All six fields have valid values." },
  { id: "R002_TOTAL", status: "PASS", fields: ["investment_amount", "management_fee", "total_due"], message: "Total equals investment contribution plus management fee." },
  { id: "R003_EVIDENCE", status: "PASS", fields: [...FIELD_KEYS], message: "All six fields have complete source evidence." },
];

export function makeDoc(over: Partial<DocumentDetail> = {}): DocumentDetail {
  return {
    id: "doc-1",
    filename: "normal.pdf",
    sha256: SHA,
    status: "REVIEW_REQUIRED",
    version: 1,
    template_id: "capital_call_v1",
    parser_version: "v1",
    extraction_profile: "none",
    created_at: "2026-11-02T09:00:00.000Z",
    updated_at: "2026-11-02T09:00:00.000Z",
    page: { number: 1, width: 595.2756, height: 841.8898 },
    fields: FIELD_KEYS.map((k) => makeField(k)),
    rules: passingRules,
    confirmation: null,
    audit_events: [
      { id: 1, document_version: 1, event_type: "IMPORTED", actor: "local-reviewer", created_at: "2026-11-02T09:00:00.000Z", payload: {} },
    ],
    ...over,
  };
}

export function withFields(doc: DocumentDetail, patch: Partial<Record<FieldKey, Partial<FieldRecord>>>): DocumentDetail {
  return { ...doc, fields: doc.fields.map((f) => ({ ...f, ...(patch[f.key] ?? {}) })) };
}

export function allVerified(doc: DocumentDetail): DocumentDetail {
  return {
    ...doc,
    fields: doc.fields.map((f) => ({ ...f, verified: true, verified_at: "2026-11-02T09:05:00.000Z", verified_by: "local-reviewer" })),
  };
}

export function confirmed(doc: DocumentDetail): DocumentDetail {
  return {
    ...allVerified(doc),
    status: "CONFIRMED",
    version: doc.version + 1,
    confirmation: { confirmed_at: "2026-11-02T09:10:00.000Z", confirmed_by: "local-reviewer", document_version: doc.version + 1 },
  };
}

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<RouterProvider router={router} />);
  return { router, ...view };
}
