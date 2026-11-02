import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError, documentApi } from "../src/api/documents";
import type { DocumentDetail } from "../src/domain/types";
import { allVerified, confirmed, makeDoc, renderAt, withFields } from "./helpers";

vi.mock("../src/api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/documents")>();
  return {
    ...actual,
    documentApi: {
      list: vi.fn(), upload: vi.fn(), get: vi.fn(), getFile: vi.fn(),
      updateFields: vi.fn(), verifyField: vi.fn(), confirm: vi.fn(), export: vi.fn(),
    },
  };
});

// The canvas renderer is covered by viewer.test.tsx and the browser tests; here it is a probe.
vi.mock("../src/features/review/PdfEvidenceViewer", () => ({
  PdfEvidenceViewer: (props: { selection: { key: string; evidence: unknown } | null }) => (
    <div
      data-testid="viewer"
      data-selected={props.selection?.key ?? ""}
      data-has-box={String(Boolean(props.selection?.evidence))}
    />
  ),
}));

const api = vi.mocked(documentApi);

beforeEach(() => {
  vi.resetAllMocks();
  api.getFile.mockResolvedValue(new Blob(["%PDF-1.4"], { type: "application/pdf" }));
  api.list.mockResolvedValue([]);
});

async function open(doc: DocumentDetail) {
  api.get.mockResolvedValue(doc);
  const view = renderAt(`/documents/${doc.id}`);
  await screen.findByRole("heading", { name: doc.filename });
  await waitFor(() => expect(api.getFile).toHaveBeenCalled());
  return view;
}

const field = (name: string) => screen.getByRole("textbox", { name });
const check = (name: string) => screen.getByRole("checkbox", { name: new RegExp(name) });
const button = (name: string | RegExp) => screen.getByRole("button", { name });

async function type(user: ReturnType<typeof userEvent.setup>, name: string, text: string) {
  const input = field(name);
  await user.clear(input);
  if (text) await user.type(input, text);
}

describe("review page: reading", () => {
  it("shows six fields with the extracted value and PDF text kept beside a correction", async () => {
    const doc = withFields(makeDoc(), {
      total_due: { initial_extracted_value: "500000.00", current_value: "50000.00", modified: true },
    });
    await open(doc);
    const row = screen.getByTestId("field-total_due");
    expect(within(row).getByRole("textbox", { name: "Total amount due" })).toHaveValue("50000.00");
    expect(within(row).getByText("500000.00")).toBeInTheDocument(); // initial extraction
    expect(within(row).getByText("50,000.00")).toBeInTheDocument(); // PDF text
    expect(within(row).getByText("Edited")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^field-/)).toHaveLength(6);
  });

  it("labels whether the extraction is a template parse or a preset demo fault", async () => {
    await open(makeDoc());
    expect(screen.getByText("Template parse")).toBeInTheDocument();
    await open(makeDoc({ id: "doc-2", filename: "amount-error.pdf", extraction_profile: "total_extra_zero" }));
    expect(screen.getByText(/Preset extraction error/)).toBeInTheDocument();
  });

  it("shows rule results as text, not colour alone, and says they describe the saved version", async () => {
    const doc = makeDoc({
      rules: [
        { id: "R001_REQUIRED", status: "PASS", fields: [], message: "ok" },
        { id: "R002_TOTAL", status: "FAIL", fields: ["total_due"], message: "Total does not match the sum of line items. Line items sum to 50000.00, total is 500000.00, difference 450000.00." },
        { id: "R003_EVIDENCE", status: "NOT_EVALUATED", fields: [], message: "n/a" },
      ],
    });
    const user = userEvent.setup();
    await open(doc);
    expect(screen.getByText("Fail")).toBeInTheDocument();
    expect(screen.getByText(/difference 450000.00/)).toBeInTheDocument();
    expect(screen.getByText("Not evaluated")).toBeInTheDocument();
    expect(screen.queryByText(/rules describe the saved version/i)).not.toBeInTheDocument();
    await type(user, "Fund name", "Another");
    expect(screen.getByText(/rules describe the saved version/i)).toBeInTheDocument();
  });

  it("points at the evidence of the selected field", async () => {
    const user = userEvent.setup();
    await open(makeDoc());
    await user.click(field("Management fee"));
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-selected", "management_fee");
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-has-box", "true");
  });

  it("never pretends to locate a value that has no source evidence", async () => {
    const doc = withFields(makeDoc(), {
      due_date: { source_text: null, source_value: null, source_parse_status: "missing", evidence: null, initial_extracted_value: null, current_value: null },
    });
    const user = userEvent.setup();
    await open(doc);
    const row = screen.getByTestId("field-due_date");
    expect(within(row).getByText(/No source location/i)).toBeInTheDocument();
    expect(within(row).getByRole("checkbox")).toBeDisabled();
    await user.click(field("Payment due date"));
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-selected", "due_date");
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-has-box", "false");
  });

  it("explains an original that cannot be loaded and blocks confirmation", async () => {
    api.getFile.mockRejectedValue(new ApiError(409, "SOURCE_INTEGRITY_MISMATCH", "The stored original no longer matches its recorded hash."));
    api.get.mockResolvedValue(allVerified(makeDoc()));
    renderAt("/documents/doc-1");
    expect(await screen.findByText(/no longer matches its recorded hash/)).toBeInTheDocument();
    expect(button("Confirm review")).toBeDisabled();
  });

  it("explains a missing document", async () => {
    api.get.mockRejectedValue(new ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found."));
    renderAt("/documents/ghost");
    expect(await screen.findByText("Document not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /all documents/i })).toBeInTheDocument();
  });
});

describe("review page: drafts and saving", () => {
  it("keeps edits as an unsaved draft and blocks confirming until they are saved", async () => {
    const user = userEvent.setup();
    await open(allVerified(makeDoc()));
    expect(button("Confirm review")).toBeEnabled();
    await type(user, "Fund name", "Renamed Fund");
    expect(button("Confirm review")).toBeDisabled();
    expect(api.updateFields).not.toHaveBeenCalled();
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  });

  it("needs a real change, a valid value and a reason before saving", async () => {
    const user = userEvent.setup();
    await open(makeDoc());
    expect(button("Save changes")).toBeDisabled();

    await type(user, "Total amount due", "50,000"); // normalises to the saved value
    expect(button("Save changes")).toBeDisabled();

    await type(user, "Total amount due", "1.001");
    expect(screen.getByText(/up to 2 decimals/)).toBeInTheDocument();
    expect(button("Save changes")).toBeDisabled();

    await type(user, "Total amount due", "49,000");
    expect(button("Save changes")).toBeDisabled(); // reason still empty
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "Checked against the PDF.");
    expect(button("Save changes")).toBeEnabled();
  });

  it("sends only the real changes with the current version, then adopts the server's new version", async () => {
    const user = userEvent.setup();
    const saved = withFields({ ...makeDoc(), version: 2 }, { total_due: { current_value: "49000.00", modified: true } });
    api.updateFields.mockResolvedValue(saved);
    await open(makeDoc());
    await type(user, "Total amount due", "49,000");
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "  Fixed total.  ");
    await user.click(button("Save changes"));

    expect(api.updateFields).toHaveBeenCalledWith("doc-1", {
      expectedVersion: 1,
      changes: [{ key: "total_due", value: "49000.00" }],
      reason: "Fixed total.",
    });
    await waitFor(() => expect(field("Total amount due")).toHaveValue("49000.00"));
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();

    api.verifyField.mockResolvedValue({ ...saved, version: 3 });
    await user.click(check("Fund name"));
    expect(api.verifyField).toHaveBeenCalledWith("doc-1", { expectedVersion: 2, fieldKey: "fund_name", verified: true });
  });

  it("keeps the draft and says why when the server rejects the save", async () => {
    const user = userEvent.setup();
    api.updateFields.mockRejectedValue(
      new ApiError(422, "INVALID_FIELD_VALUE", "One or more values are not valid.", {
        errors: [{ key: "total_due", message: "Amount must not exceed 999,999,999.99." }],
      }),
    );
    await open(makeDoc());
    await type(user, "Total amount due", "49,000");
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "Fix.");
    await user.click(button("Save changes"));

    expect(await screen.findByText("Amount must not exceed 999,999,999.99.")).toBeInTheDocument();
    expect(field("Total amount due")).toHaveValue("49,000");
    expect(screen.getByRole("textbox", { name: "Reason for change" })).toHaveValue("Fix.");
    expect(button("Save changes")).toBeEnabled();
  });

  it("never overwrites silently after a version conflict: keeps the draft and waits for an explicit reload", async () => {
    const user = userEvent.setup();
    api.updateFields.mockRejectedValueOnce(
      new ApiError(409, "VERSION_CONFLICT", "This document has changed. Reload before continuing.", { expected_version: 1, actual_version: 3 }),
    );
    await open(makeDoc());
    await type(user, "Total amount due", "49,000");
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "Fix.");
    await user.click(button("Save changes"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed in another window/i);
    expect(api.updateFields).toHaveBeenCalledTimes(1); // no automatic retry
    expect(field("Total amount due")).toHaveValue("49,000");
    expect(api.get).toHaveBeenCalledTimes(1); // no automatic reload either

    const latest = withFields({ ...makeDoc(), version: 3 }, { fund_name: { current_value: "Edited elsewhere", modified: true } });
    api.get.mockResolvedValue(latest);
    await user.click(button("Reload latest"));
    await waitFor(() => expect(field("Fund name")).toHaveValue("Edited elsewhere"));
    expect(field("Total amount due")).toHaveValue("49,000"); // draft survives the reload

    api.updateFields.mockResolvedValue({ ...latest, version: 4 });
    await user.click(button("Save changes"));
    expect(api.updateFields).toHaveBeenLastCalledWith("doc-1", expect.objectContaining({ expectedVersion: 3 }));
  });

  it("treats a dropped connection as an unknown result: no retry, draft kept, check before trying again", async () => {
    const user = userEvent.setup();
    api.updateFields.mockRejectedValue(new NetworkError());
    await open(makeDoc());
    await type(user, "Total amount due", "49,000");
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "Fix.");
    await user.click(button("Save changes"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not confirm whether/i);
    expect(api.updateFields).toHaveBeenCalledTimes(1);
    expect(field("Total amount due")).toHaveValue("49,000");
    expect(button("Reload latest")).toBeEnabled();
  });

  it("can discard the draft", async () => {
    const user = userEvent.setup();
    await open(makeDoc());
    await type(user, "Fund name", "Something else");
    await user.click(button("Discard changes"));
    expect(field("Fund name")).toHaveValue("Example Growth Fund I");
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();
  });
});

describe("review page: checks and confirmation", () => {
  it("sends one write at a time and chains each request on the version the server returned", async () => {
    const user = userEvent.setup();
    let resolveFirst!: (doc: DocumentDetail) => void;
    api.verifyField.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    await open(makeDoc());

    await user.click(check("Fund name"));
    expect(api.verifyField).toHaveBeenCalledTimes(1);
    for (const name of ["Currency", "Payment due date", "Total amount due"]) {
      expect(check(name)).toBeDisabled(); // cannot start a second write while one is in flight
    }
    expect(button("Save changes")).toBeDisabled();

    const next = withFields({ ...makeDoc(), version: 2 }, { fund_name: { verified: true } });
    await act(async () => resolveFirst(next));
    await waitFor(() => expect(check("Currency")).toBeEnabled());

    api.verifyField.mockResolvedValueOnce({ ...next, version: 3 });
    await user.click(check("Currency"));
    expect(api.verifyField).toHaveBeenLastCalledWith("doc-1", { expectedVersion: 2, fieldKey: "currency", verified: true });
  });

  it("returns keyboard focus to the check box once its write finishes", async () => {
    const user = userEvent.setup();
    let resolve!: (doc: DocumentDetail) => void;
    api.verifyField.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    await open(makeDoc());
    await user.click(check("Fund name"));
    // Browsers drop focus from a control that becomes disabled mid-request (jsdom cannot
    // blur a disabled element, so park focus on a probe to model that).
    const probe = document.body.appendChild(document.createElement("button"));
    probe.focus();
    expect(check("Fund name")).not.toHaveFocus();
    await act(async () => resolve(withFields({ ...makeDoc(), version: 2 }, { fund_name: { verified: true } })));
    await waitFor(() => expect(check("Fund name")).toHaveFocus());
    probe.remove();
  });

  it("does not offer checks while there are unsaved edits", async () => {
    const user = userEvent.setup();
    await open(makeDoc());
    await type(user, "Fund name", "Changed");
    expect(check("Currency")).toBeDisabled();
  });

  it("only allows confirmation when all rules pass and all six fields are checked", async () => {
    await open(makeDoc());
    expect(button("Confirm review")).toBeDisabled();
    expect(screen.getByText(/0 of 6 fields checked/i)).toBeInTheDocument();
  });

  it("is blocked by a failing rule even when every field has been checked", async () => {
    const doc = allVerified({
      ...makeDoc(),
      rules: [
        { id: "R001_REQUIRED", status: "PASS", fields: [], message: "ok" },
        { id: "R002_TOTAL", status: "FAIL", fields: ["total_due"], message: "Total does not match." },
        { id: "R003_EVIDENCE", status: "PASS", fields: [], message: "ok" },
      ],
    });
    await open(doc);
    expect(button("Confirm review")).toBeDisabled();
  });

  it("confirms with the current version and then shows a read-only confirmed record", async () => {
    const user = userEvent.setup();
    const start = allVerified({ ...makeDoc(), version: 7 });
    api.confirm.mockResolvedValue(confirmed(start));
    await open(start);
    await user.click(button("Confirm review"));
    expect(api.confirm).toHaveBeenCalledWith("doc-1", 7);
    expect(await screen.findByText(/Confirmed by local-reviewer/)).toBeInTheDocument();
    expect(field("Total amount due")).toBeDisabled();
    expect(button("Edit fields")).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Confirm review" })).not.toBeInTheDocument();
  });

  it("surfaces a server-side refusal to confirm and stays unconfirmed", async () => {
    const user = userEvent.setup();
    api.confirm.mockRejectedValue(new ApiError(409, "REVIEW_BLOCKED", "Resolve the failing checks before confirming."));
    await open(allVerified(makeDoc()));
    await user.click(button("Confirm review"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Resolve the failing checks before confirming.");
    expect(button("Confirm review")).toBeEnabled();
  });

  it("unlocks a confirmed record only when asked, and revoking is what saving does", async () => {
    const user = userEvent.setup();
    const done = confirmed(makeDoc());
    await open(done);
    expect(field("Management fee")).toBeDisabled();
    await user.click(button("Edit fields"));
    expect(field("Management fee")).toBeEnabled();

    const revoked = withFields({ ...makeDoc(), version: done.version + 1 }, { management_fee: { current_value: "2100.00", modified: true } });
    api.updateFields.mockResolvedValue(revoked);
    await type(user, "Management fee", "2,100");
    await user.type(screen.getByRole("textbox", { name: "Reason for change" }), "Fee revised.");
    await user.click(button("Save changes"));
    await waitFor(() => expect(screen.queryByText(/Confirmed by/)).not.toBeInTheDocument());
    expect(button("Confirm review")).toBeDisabled();
  });
});

describe("review page: leaving with a draft", () => {
  it("asks the browser to confirm closing or reloading only while there is a draft", async () => {
    const user = userEvent.setup();
    await open(makeDoc());
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    await type(user, "Fund name", "Changed");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("asks before in-app navigation throws a draft away", async () => {
    const user = userEvent.setup();
    const { router } = await open(makeDoc());
    await type(user, "Fund name", "Changed");

    await user.click(screen.getByRole("link", { name: /all documents/i }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/unsaved changes/i);
    await user.click(button("Keep editing"));
    expect(router.state.location.pathname).toBe("/documents/doc-1");
    expect(field("Fund name")).toHaveValue("Changed");

    await user.click(screen.getByRole("link", { name: /all documents/i }));
    await user.click(await screen.findByRole("button", { name: "Leave without saving" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });
});

describe("review page: export", () => {
  let downloaded: { name: string; href: string }[];

  beforeEach(() => {
    downloaded = [];
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:export-1"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloaded.push({ name: this.download, href: this.href });
    });
  });

  it("is unavailable until the review is confirmed", async () => {
    await open(allVerified(makeDoc()));
    expect(button("Export JSON")).toBeDisabled();
  });

  it("is unavailable while there are unsaved edits, even on a confirmed record", async () => {
    const user = userEvent.setup();
    await open(confirmed(makeDoc()));
    expect(button("Export JSON")).toBeEnabled();
    await user.click(button("Edit fields"));
    expect(button("Export JSON")).toBeEnabled(); // unlocked but nothing typed yet
    await type(user, "Fund name", "Typed but not saved");
    expect(button("Export JSON")).toBeDisabled();
  });

  it("asks the server for the confirmed version and downloads the file it returns", async () => {
    const user = userEvent.setup();
    const done = confirmed({ ...makeDoc(), version: 7 });
    api.export.mockResolvedValue({ blob: new Blob(["{}"], { type: "application/json" }), filename: "tracereview-doc-1-v8.json", sha256: "h" });
    await open(done);
    const refreshed = {
      ...done,
      audit_events: [...done.audit_events, { id: 9, document_version: 8, event_type: "EXPORT_GENERATED" as const, actor: "local-reviewer", created_at: "2026-11-02T10:00:00.000Z", payload: { exported_version: 8 } }],
    };
    api.get.mockResolvedValue(refreshed);

    await user.click(button("Export JSON"));
    expect(api.export).toHaveBeenCalledWith("doc-1", 8);
    await waitFor(() => expect(downloaded).toHaveLength(1));
    expect(downloaded[0]!.name).toBe("tracereview-doc-1-v8.json");
    expect(downloaded[0]!.href).toContain("blob:export-1");
    expect(await screen.findByText("Downloaded tracereview-doc-1-v8.json")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/History \(2\)/)).toBeInTheDocument()); // history shows the generation event
  });

  it("does not download anything when the server refuses, and explains why", async () => {
    const user = userEvent.setup();
    api.export.mockRejectedValue(new ApiError(409, "SOURCE_UNAVAILABLE", "The original PDF is missing from local storage."));
    await open(confirmed(makeDoc()));
    await user.click(button("Export JSON"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The original PDF is missing from local storage.");
    expect(downloaded).toHaveLength(0);
  });

  it("treats an export of an outdated version as a conflict and asks for an explicit reload", async () => {
    const user = userEvent.setup();
    api.export.mockRejectedValue(new ApiError(409, "VERSION_CONFLICT", "This document has changed.", { expected_version: 2, actual_version: 3 }));
    await open(confirmed(makeDoc()));
    await user.click(button("Export JSON"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed in another window/i);
    expect(downloaded).toHaveLength(0);
    expect(button("Reload latest")).toBeEnabled();
  });
});

