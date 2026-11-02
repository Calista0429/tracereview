import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Evidence } from "../src/domain/types";
import { toCssBox } from "../src/features/review/evidenceGeometry";

const mocks = vi.hoisted(() => {
  return {
    getDocument: vi.fn(),
    render: vi.fn(),
    cancel: vi.fn(),
    destroy: vi.fn(),
  };
});

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: mocks.getDocument,
}));
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/worker.js" }));

import { PdfEvidenceViewer } from "../src/features/review/PdfEvidenceViewer";

const PAGE = { width: 595.2756, height: 841.8898 };
const evidence: Evidence = {
  document_sha256: "a".repeat(64),
  page: 1,
  bbox: { x: 0.65, y: 0.43, width: 0.16, height: 0.02 },
};
const selection = { key: "total_due" as const, label: "Total amount due", evidence };

const blob = (name = "x") =>
  ({ arrayBuffer: async () => new TextEncoder().encode(name).buffer }) as unknown as Blob;

function setupPdfjs() {
  mocks.render.mockImplementation(() => ({ promise: Promise.resolve(), cancel: mocks.cancel }));
  mocks.getDocument.mockImplementation(() => ({
    promise: Promise.resolve({
      getPage: async () => ({
        getViewport: ({ scale }: { scale: number }) => ({ width: PAGE.width * scale, height: PAGE.height * scale }),
        render: mocks.render,
      }),
      destroy: mocks.destroy,
    }),
    destroy: mocks.destroy,
  }));
}

function overlay() {
  return screen.queryByTestId("evidence-box");
}

function px(el: HTMLElement, prop: "left" | "top" | "width" | "height") {
  return parseFloat(el.style[prop]);
}

const original = { dpr: window.devicePixelRatio };

beforeEach(() => {
  vi.clearAllMocks();
  setupPdfjs();
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 700 });
});
afterEach(() => {
  Object.defineProperty(window, "devicePixelRatio", { value: original.dpr, configurable: true });
  // @ts-expect-error restore jsdom default
  delete HTMLElement.prototype.clientWidth;
});

const props = { page: PAGE, caption: "normal.pdf", fileProblem: null };

describe("PdfEvidenceViewer", () => {
  it("frames the selected value with a box in CSS pixels of the rendered page", async () => {
    render(<PdfEvidenceViewer {...props} file={blob()} selection={selection} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    const box = overlay()!;
    const page = screen.getByTestId("pdf-page");
    const expected = toCssBox(evidence.bbox, px(page, "width"), px(page, "height"));
    expect(px(box, "left")).toBeCloseTo(expected.left, 3);
    expect(px(box, "top")).toBeCloseTo(expected.top, 3);
    expect(px(box, "width")).toBeCloseTo(expected.width, 3);
    expect(px(box, "height")).toBeCloseTo(expected.height, 3);
    expect(box).toHaveTextContent("Total amount due");
  });

  it("keeps the box on the same text at fit width, 100% and 150%", async () => {
    render(<PdfEvidenceViewer {...props} file={blob()} selection={selection} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    const fractions = () => {
      const page = screen.getByTestId("pdf-page");
      const box = overlay()!;
      return [px(box, "left") / px(page, "width"), px(box, "top") / px(page, "height"),
        px(box, "width") / px(page, "width"), px(box, "height") / px(page, "height")];
    };
    const widths: number[] = [];
    for (const name of ["Fit width", "100%", "150%"]) {
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(screen.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true"));
      widths.push(px(screen.getByTestId("pdf-page"), "width"));
      const [x, y, w, h] = fractions();
      expect(x).toBeCloseTo(0.65, 6);
      expect(y).toBeCloseTo(0.43, 6);
      expect(w).toBeCloseTo(0.16, 6);
      expect(h).toBeCloseTo(0.02, 6);
    }
    expect(widths[1]).toBeCloseTo(PAGE.width, 3);
    expect(widths[2]).toBeCloseTo(PAGE.width * 1.5, 3);
  });

  it("draws the bitmap at devicePixelRatio but lays the overlay out in CSS pixels", async () => {
    Object.defineProperty(window, "devicePixelRatio", { value: 2, configurable: true });
    render(<PdfEvidenceViewer {...props} file={blob()} selection={selection} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    const page = screen.getByTestId("pdf-page");
    const canvas = screen.getByTestId("pdf-canvas") as HTMLCanvasElement;
    expect(canvas.width).toBe(Math.round(px(page, "width") * 2));
    expect(canvas.height).toBe(Math.round(px(page, "height") * 2));
    const call = mocks.render.mock.calls.at(-1)![0];
    expect(call.transform[0]).toBeCloseTo(canvas.width / px(page, "width"), 6);
    const expected = toCssBox(evidence.bbox, px(page, "width"), px(page, "height"));
    expect(px(overlay()!, "width")).toBeCloseTo(expected.width, 3); // not doubled
  });

  it("says so, and draws no box, when the value has no usable location", async () => {
    render(<PdfEvidenceViewer {...props} file={blob()} selection={{ ...selection, evidence: null }} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    expect(overlay()).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/could not be located/i);
  });

  it("draws no box and no message when nothing is selected", async () => {
    render(<PdfEvidenceViewer {...props} file={blob()} selection={null} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    expect(overlay()).toBeNull();
    expect(screen.queryByText(/could not be located/i)).not.toBeInTheDocument();
  });

  it("cancels an in-flight render when it goes away", async () => {
    mocks.render.mockImplementation(() => ({ promise: new Promise(() => {}), cancel: mocks.cancel }));
    const { unmount } = render(<PdfEvidenceViewer {...props} file={blob()} selection={selection} />);
    await waitFor(() => expect(mocks.render).toHaveBeenCalled());
    unmount();
    expect(mocks.cancel).toHaveBeenCalled();
  });

  it("ignores a slow load of an older file once a newer one is shown", async () => {
    let releaseOld!: () => void;
    const oldFile = {
      arrayBuffer: () => new Promise<ArrayBuffer>((resolve) => { releaseOld = () => resolve(new TextEncoder().encode("old").buffer as ArrayBuffer); }),
    } as unknown as Blob;
    const { rerender } = render(<PdfEvidenceViewer {...props} file={oldFile} selection={selection} />);
    rerender(<PdfEvidenceViewer {...props} file={blob("new")} selection={selection} />);
    await waitFor(() => expect(mocks.getDocument).toHaveBeenCalledTimes(1));
    await act(async () => releaseOld());
    expect(mocks.getDocument).toHaveBeenCalledTimes(1);
    const data = mocks.getDocument.mock.calls[0]![0].data as Uint8Array;
    expect(new TextDecoder().decode(data)).toBe("new");
  });

  it("shows the reason when the original cannot be shown", () => {
    render(<PdfEvidenceViewer {...props} file={null} fileProblem="The original PDF is missing from local storage." selection={selection} />);
    expect(screen.getByText(/missing from local storage/)).toBeInTheDocument();
    expect(mocks.getDocument).not.toHaveBeenCalled();
  });
});
