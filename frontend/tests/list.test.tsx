import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError, documentApi } from "../src/api/documents";
import type { DocumentSummary } from "../src/domain/types";
import { makeDoc, renderAt } from "./helpers";

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
vi.mock("../src/features/review/PdfEvidenceViewer", () => ({ PdfEvidenceViewer: () => <div /> }));

const api = vi.mocked(documentApi);

const manifest = {
  samples: [
    { id: "normal", file: "normal.pdf", sha256: "1", profile: "none", title: "Normal notice", description: "All six fields present; extraction is correct." },
    { id: "amount-error", file: "amount-error.pdf", sha256: "2", profile: "total_extra_zero", title: "Preset total error", description: "Injected fault." },
  ],
};

const summary = (over: Partial<DocumentSummary> = {}): DocumentSummary => ({
  id: "doc-1", filename: "normal.pdf", created_at: "2026-11-02T09:00:00.000Z", status: "REVIEW_REQUIRED", version: 1,
  rules: [
    { id: "R001_REQUIRED", status: "PASS" }, { id: "R002_TOTAL", status: "FAIL" }, { id: "R003_EVIDENCE", status: "PASS" },
  ],
  ...over,
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.resetAllMocks();
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/samples/manifest.json") return new Response(JSON.stringify(manifest));
    return new Response(new Uint8Array([37, 80, 68, 70]), { headers: { "content-type": "application/pdf" } });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("document list", () => {
  it("invites the first upload when there is nothing yet", async () => {
    api.list.mockResolvedValue([]);
    renderAt("/");
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
  });

  it("lists each document with rule outcome, review state and version as text", async () => {
    api.list.mockResolvedValue([summary(), summary({ id: "doc-2", filename: "done.pdf", status: "CONFIRMED", version: 8, rules: summary().rules.map((r) => ({ ...r, status: "PASS" as const })) })]);
    renderAt("/");
    const row = (await screen.findByRole("link", { name: "normal.pdf" })).closest("tr")!;
    expect(row).toHaveTextContent("Needs review");
    expect(row).toHaveTextContent("1 rule failing");
    expect(row).toHaveTextContent("v1");
    expect(screen.getByRole("link", { name: "normal.pdf" })).toHaveAttribute("href", "/documents/doc-1");
    const done = screen.getByRole("link", { name: "done.pdf" }).closest("tr")!;
    expect(done).toHaveTextContent("Confirmed");
    expect(done).toHaveTextContent("All rules pass");
  });

  it("explains a load failure and lets the user retry", async () => {
    const user = userEvent.setup();
    api.list.mockRejectedValueOnce(new NetworkError());
    renderAt("/");
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be reached/i);
    api.list.mockResolvedValue([summary()]);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "normal.pdf" })).toBeInTheDocument();
  });

  it("uploads a chosen PDF and opens its review page", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue([]);
    api.upload.mockResolvedValue(makeDoc({ id: "new-id", filename: "chosen.pdf" }));
    api.get.mockResolvedValue(makeDoc({ id: "new-id", filename: "chosen.pdf" }));
    api.getFile.mockResolvedValue(new Blob(["%PDF"]));
    const { router } = renderAt("/");
    const file = new File(["%PDF-1.4"], "chosen.pdf", { type: "application/pdf" });
    await user.upload(await screen.findByLabelText(/Choose a PDF/), file);
    expect(api.upload).toHaveBeenCalledWith(file);
    await waitFor(() => expect(router.state.location.pathname).toBe("/documents/new-id"));
  });

  it("points at the existing record when the file was already imported", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue([]);
    api.upload.mockRejectedValue(
      new ApiError(409, "DOCUMENT_DUPLICATE", "This file has already been imported.", { existing_document_id: "abc" }),
    );
    renderAt("/");
    await user.upload(await screen.findByLabelText(/Choose a PDF/), new File(["x"], "again.pdf", { type: "application/pdf" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This file has already been imported.");
    expect(within(alert).getByRole("link", { name: "Open the existing record" })).toHaveAttribute("href", "/documents/abc");
  });

  it("shows why an upload was refused, leaving no half-created record", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue([]);
    api.upload.mockRejectedValue(new ApiError(422, "UNSUPPORTED_LAYOUT", "Only single-page, unrotated, uncropped PDFs with a text layer are supported."));
    renderAt("/");
    await user.upload(await screen.findByLabelText(/Choose a PDF/), new File(["x"], "scan.pdf", { type: "application/pdf" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("scan.pdf was not imported.");
    expect(alert).toHaveTextContent("Only single-page");
    expect(screen.getByText(/No documents yet/)).toBeInTheDocument();
  });

  it("imports a sample through the normal upload path", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue([]);
    api.upload.mockResolvedValue(makeDoc({ id: "s1" }));
    api.get.mockResolvedValue(makeDoc({ id: "s1" }));
    api.getFile.mockResolvedValue(new Blob(["%PDF"]));
    renderAt("/");
    const card = (await screen.findByText("Preset total error")).closest("li")!;
    expect(within(card).getByText(/Preset extraction error/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Import sample" }));
    await waitFor(() => expect(api.upload).toHaveBeenCalled());
    const uploaded = api.upload.mock.calls[0]![0];
    expect(uploaded.name).toBe("amount-error.pdf");
    expect(fetchMock).toHaveBeenCalledWith("/samples/amount-error.pdf");
  });
});
