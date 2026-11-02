import { describe, expect, it } from "vitest";

import {
  computeDraft,
  isDirty,
  normalizeFieldInput,
} from "../src/domain/fieldInput";
import { FIELD_KEYS, type FieldRecord } from "../src/domain/types";

const ok = (value: string | null) => ({ ok: true, value });

describe("normalizeFieldInput (mirrors the server, never uses floats)", () => {
  it.each([
    ["48,000", "48000.00"],
    ["48000.0", "48000.00"],
    [" 0.1 ", "0.10"],
    ["0", "0.00"],
    ["999,999,999.99", "999999999.99"],
  ])("accepts amount %s", (input, expected) => {
    expect(normalizeFieldInput("total_due", input)).toEqual(ok(expected));
  });

  it.each([
    "1.001", "-1", "+5", "1e3", "NaN", "Infinity", "12,34", "1,0000", "$5.00", ".5", "5.",
    "1,000,000,000.00", "１２",
  ])("rejects amount %s", (input) => {
    const result = normalizeFieldInput("investment_amount", input);
    expect(result.ok).toBe(false);
  });

  it("keeps exactness where floats would not", () => {
    expect(normalizeFieldInput("management_fee", "0.30")).toEqual(ok("0.30"));
    expect(normalizeFieldInput("management_fee", "999999999.99")).toEqual(ok("999999999.99"));
  });

  it("treats blank as unknown, not zero", () => {
    for (const key of FIELD_KEYS) {
      expect(normalizeFieldInput(key, "")).toEqual(ok(null));
      expect(normalizeFieldInput(key, "   ")).toEqual(ok(null));
    }
  });

  it.each([
    ["2024-02-29", true],
    ["2020-01-15", true],
    ["2026-02-30", false],
    ["2023-02-29", false],
    ["2026-13-01", false],
    ["2026-1-5", false],
    ["20261110", false],
    ["2026/11/10", false],
  ])("date %s -> %s", (input, valid) => {
    expect(normalizeFieldInput("due_date", input).ok).toBe(valid);
  });

  it("limits the fund name to 1-120 trimmed characters and the currency to USD", () => {
    expect(normalizeFieldInput("fund_name", "  Example Fund  ")).toEqual(ok("Example Fund"));
    expect(normalizeFieldInput("fund_name", "x".repeat(121)).ok).toBe(false);
    expect(normalizeFieldInput("currency", "USD")).toEqual(ok("USD"));
    expect(normalizeFieldInput("currency", "usd").ok).toBe(false);
    expect(normalizeFieldInput("currency", "EUR").ok).toBe(false);
  });
});

function field(key: (typeof FIELD_KEYS)[number], current: string | null): FieldRecord {
  return {
    key, source_text: current, source_value: current, source_parse_status: "valid",
    initial_extracted_value: current, current_value: current, modified: false,
    verified: false, verified_at: null, verified_by: null, evidence: null,
  };
}

describe("computeDraft", () => {
  const fields = [field("fund_name", "Example Fund"), field("total_due", "50000.00"), field("due_date", null)];

  it("ignores entries that normalise to the saved value", () => {
    const draft = computeDraft(fields, { total_due: "50,000", fund_name: " Example Fund " });
    expect(draft.changes).toEqual([]);
    expect(draft.errors).toEqual({});
    expect(isDirty(fields, { total_due: "50,000" })).toBe(false);
  });

  it("collects real changes, including clearing a value", () => {
    const draft = computeDraft(fields, { total_due: "49,000", fund_name: "" });
    expect(draft.changes).toEqual([
      { key: "fund_name", value: null },
      { key: "total_due", value: "49000.00" },
    ]);
  });

  it("reports an invalid entry as an error and as dirty, never as a change", () => {
    const draft = computeDraft(fields, { total_due: "1.001" });
    expect(draft.changes).toEqual([]);
    expect(Object.keys(draft.errors)).toEqual(["total_due"]);
    expect(isDirty(fields, { total_due: "1.001" })).toBe(true);
  });

  it("treats typing into an empty field as a change", () => {
    expect(computeDraft(fields, { due_date: "2026-11-10" }).changes).toEqual([
      { key: "due_date", value: "2026-11-10" },
    ]);
  });
});
