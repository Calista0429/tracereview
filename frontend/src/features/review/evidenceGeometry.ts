import type { EvidenceBox } from "../../domain/types";

export interface CssBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export type ZoomMode = "fit" | "100" | "150";

/**
 * Normalised page fractions (origin top-left) -> CSS pixels of the rendered page.
 * Always pass the CSS size of the page element, never the canvas bitmap size: the bitmap is
 * multiplied by devicePixelRatio, the layout is not.
 */
export function toCssBox(bbox: EvidenceBox, cssWidth: number, cssHeight: number): CssBox {
  return {
    left: bbox.x * cssWidth,
    top: bbox.y * cssHeight,
    width: bbox.width * cssWidth,
    height: bbox.height * cssHeight,
  };
}

/** Bitmap size for a canvas whose CSS size is cssWidth x cssHeight. */
export function canvasBackingSize(cssWidth: number, cssHeight: number, pixelRatio: number) {
  return {
    pixelWidth: Math.max(1, Math.round(cssWidth * pixelRatio)),
    pixelHeight: Math.max(1, Math.round(cssHeight * pixelRatio)),
  };
}

/** CSS pixels per PDF point. "100%" is one CSS pixel per point. */
export function scaleForZoom(mode: ZoomMode, availableWidth: number, pageWidthPoints: number): number {
  if (mode === "100") return 1;
  if (mode === "150") return 1.5;
  if (availableWidth <= 0 || pageWidthPoints <= 0) return 1;
  return Math.max(0.1, availableWidth / pageWidthPoints);
}
