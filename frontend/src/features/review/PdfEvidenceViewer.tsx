import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import type { Evidence, FieldKey } from "../../domain/types";
import {
  canvasBackingSize,
  scaleForZoom,
  toCssBox,
  type ZoomMode,
} from "./evidenceGeometry";

// Bundled with the app: no CDN at runtime.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const PAGE_PADDING = 32; // breathing room around the sheet inside the scroller

export interface Selection {
  key: FieldKey;
  label: string;
  evidence: Evidence | null;
}

interface Props {
  file: Blob | null;
  fileProblem: string | null;
  page: { width: number; height: number };
  caption: string;
  selection: Selection | null;
}

const ZOOMS: { mode: ZoomMode; label: string }[] = [
  { mode: "fit", label: "Fit width" },
  { mode: "100", label: "100%" },
  { mode: "150", label: "150%" },
];

type LoadState = "idle" | "loading" | "ready" | "error";

export function PdfEvidenceViewer({ file, fileProblem, page, caption, selection }: Props) {
  const [zoom, setZoom] = useState<ZoomMode>("fit");
  const [availableWidth, setAvailableWidth] = useState(0);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const scrollerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // CSS pixels per PDF point, and the CSS size of the sheet. The overlay and the canvas
  // both use this size; the canvas bitmap alone is multiplied by devicePixelRatio.
  const scale = scaleForZoom(zoom, availableWidth - PAGE_PADDING, page.width);
  const cssWidth = page.width * scale;
  const cssHeight = page.height * scale;

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const measure = () => setAvailableWidth(scroller.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  // Load the document. A slow load of an older file must never replace a newer one.
  useEffect(() => {
    if (!file) {
      setPdf(null);
      setState("idle");
      return;
    }
    let cancelled = false;
    let loading: ReturnType<typeof pdfjs.getDocument> | null = null;
    setState("loading");
    (async () => {
      try {
        const data = new Uint8Array(await file.arrayBuffer());
        if (cancelled) return;
        loading = pdfjs.getDocument({ data });
        const loaded = await loading.promise;
        if (cancelled) {
          void loading.destroy();
          return;
        }
        setPdf(loaded);
        setState("ready");
      } catch {
        if (!cancelled) {
          setPdf(null);
          setState("error");
        }
      }
    })();
    return () => {
      cancelled = true;
      void loading?.destroy();
    };
  }, [file]);

  // Draw page 1. Re-runs on zoom or pixel-ratio changes and cancels the render it replaces.
  const pixelRatio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!pdf || !canvas) return;
    let cancelled = false;
    let task: { promise: Promise<unknown>; cancel: () => void } | null = null;
    (async () => {
      const pdfPage = await pdf.getPage(1);
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale });
      const { pixelWidth, pixelHeight } = canvasBackingSize(viewport.width, viewport.height, pixelRatio);
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
      task = pdfPage.render({
        canvas,
        viewport,
        transform: [pixelWidth / viewport.width, 0, 0, pixelHeight / viewport.height, 0, 0],
      });
      await task.promise;
    })().catch((error: unknown) => {
      if ((error as { name?: string } | null)?.name === "RenderingCancelledException") return;
      if (!cancelled) setState("error");
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, scale, pixelRatio]);

  const evidence = selection?.evidence ?? null;
  const box = evidence ? toCssBox(evidence.bbox, cssWidth, cssHeight) : null;

  // Bring the framed value into view (also scrolls the page itself on narrow screens).
  useEffect(() => {
    const reduceMotion =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    boxRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
  }, [selection?.key, evidence, scale]);

  return (
    <div className="viewer">
      <div className="viewer__bar">
        <p className="viewer__caption">
          {caption} <span className="viewer__page">Page 1</span>
        </p>
        <div className="viewer__zoom" role="group" aria-label="Zoom">
          {ZOOMS.map(({ mode, label }) => (
            <button
              key={mode}
              type="button"
              className="btn btn--quiet"
              aria-pressed={zoom === mode}
              onClick={() => setZoom(mode)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <p className="viewer__status" role="status">
        {selection && !evidence
          ? `${selection.label} could not be located uniquely in the PDF, so nothing is highlighted.`
          : ""}
        {state === "loading" && !fileProblem ? "Loading the original PDF…" : ""}
        {state === "error" ? "The PDF could not be displayed." : ""}
      </p>

      <div className="viewer__scroller" ref={scrollerRef}>
        {fileProblem ? (
          <p className="viewer__problem">{fileProblem}</p>
        ) : (
          <div
            className="sheet"
            data-testid="pdf-page"
            style={{ width: `${cssWidth}px`, height: `${cssHeight}px` }}
          >
            <canvas ref={canvasRef} className="sheet__canvas" data-testid="pdf-canvas" aria-label="Original PDF, page 1" />
            {box && selection && (
              <div
                ref={boxRef}
                className="marquee"
                data-testid="evidence-box"
                style={{
                  left: `${box.left}px`,
                  top: `${box.top}px`,
                  width: `${box.width}px`,
                  height: `${box.height}px`,
                }}
              >
                <span className="marquee__flag">{selection.label}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
