import type { DocumentStatus, ExtractionProfile, RuleId, RuleStatus } from "../domain/types";

const formatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Server timestamps are UTC; say so wherever one is shown. */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${formatter.format(date)} UTC`;
}

export const RULE_NAMES: Record<RuleId, string> = {
  R001_REQUIRED: "Required values",
  R002_TOTAL: "Total matches line items",
  R003_EVIDENCE: "Source evidence",
};

export const RULE_STATUS_TEXT: Record<RuleStatus, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  NOT_EVALUATED: "Not evaluated",
};

export const RULE_GLYPH: Record<RuleStatus, string> = { PASS: "✓", FAIL: "✕", NOT_EVALUATED: "–" };

export const STATUS_TEXT: Record<DocumentStatus, string> = {
  REVIEW_REQUIRED: "Needs review",
  CONFIRMED: "Confirmed",
};

export function isPresetFault(profile: ExtractionProfile): boolean {
  return profile !== "none";
}

export function profileLabel(profile: ExtractionProfile): string {
  return isPresetFault(profile) ? "Preset extraction error (demo fault)" : "Template parse";
}

export function ruleSummary(rules: { status: RuleStatus }[]): string {
  const failing = rules.filter((r) => r.status === "FAIL").length;
  const open = rules.filter((r) => r.status === "NOT_EVALUATED").length;
  if (failing > 0) return `${failing} ${failing === 1 ? "rule" : "rules"} failing`;
  if (open > 0) return `${open} not evaluated`;
  return "All rules pass";
}
