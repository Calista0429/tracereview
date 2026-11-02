// Client-side mirror of the server's field rules, for immediate feedback only. The server is
// the authority. Amounts are handled as digit strings and BigInt: never as floating point.

import {
  AMOUNT_KEYS,
  FIELD_KEYS,
  type FieldChange,
  type FieldKey,
  type FieldRecord,
} from "./types";

export type Normalized = { ok: true; value: string | null } | { ok: false; message: string };

const AMOUNT_RE = /^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]{1,2}))?$/;
const DATE_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const MAX_UNITS = 999_999_999n;
const FUND_NAME_MAX = 120;

export function normalizeFieldInput(key: FieldKey, raw: string): Normalized {
  const text = raw.trim();
  if (text === "") return { ok: true, value: null };
  if (AMOUNT_KEYS.includes(key)) return normalizeAmount(text);
  if (key === "fund_name") {
    return [...text].length > FUND_NAME_MAX
      ? { ok: false, message: `Use at most ${FUND_NAME_MAX} characters.` }
      : { ok: true, value: text };
  }
  if (key === "currency") {
    return text === "USD" ? { ok: true, value: "USD" } : { ok: false, message: "Currency must be USD." };
  }
  return normalizeDate(text);
}

function normalizeAmount(text: string): Normalized {
  const match = AMOUNT_RE.exec(text);
  if (!match) {
    return { ok: false, message: "Enter an amount such as 48,000.00: digits, optional commas, up to 2 decimals." };
  }
  const units = BigInt(text.split(".")[0]!.replaceAll(",", ""));
  const cents = (match[1] ?? "").padEnd(2, "0");
  if (units > MAX_UNITS) {
    return { ok: false, message: "Amount must not exceed 999,999,999.99." };
  }
  return { ok: true, value: `${units}.${cents}` };
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function normalizeDate(text: string): Normalized {
  const match = DATE_RE.exec(text);
  if (!match) return { ok: false, message: "Use the format YYYY-MM-DD." };
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    return { ok: false, message: "That is not a real calendar date." };
  }
  return { ok: true, value: text };
}

export type Drafts = Partial<Record<FieldKey, string>>;

export interface DraftResult {
  changes: FieldChange[];
  errors: Partial<Record<FieldKey, string>>;
}

/** Real changes (normalised, differing from the saved value) and per-field format errors. */
export function computeDraft(fields: FieldRecord[], drafts: Drafts): DraftResult {
  const saved = new Map(fields.map((f) => [f.key, f.current_value]));
  const changes: FieldChange[] = [];
  const errors: Partial<Record<FieldKey, string>> = {};
  for (const key of FIELD_KEYS) {
    const raw = drafts[key];
    if (raw === undefined) continue;
    const result = normalizeFieldInput(key, raw);
    if (!result.ok) {
      errors[key] = result.message;
    } else if (result.value !== (saved.get(key) ?? null)) {
      changes.push({ key, value: result.value });
    }
  }
  return { changes, errors };
}

/** Anything typed that is not just the saved value again: unsaved work the user could lose. */
export function isDirty(fields: FieldRecord[], drafts: Drafts): boolean {
  const { changes, errors } = computeDraft(fields, drafts);
  return changes.length > 0 || Object.keys(errors).length > 0;
}
