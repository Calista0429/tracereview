import { afterEach, describe, expect, it } from "vitest";

import {
  canvasBackingSize,
  scaleForZoom,
  toCssBox,
} from "../src/features/review/evidenceGeometry";

const bbox = { x: 0.65, y: 0.43, width: 0.16, height: 0.02 };

describe("toCssBox", () => {
  it("maps a normalised box onto the CSS size of the rendered page", () => {
    const box = toCssBox(bbox, 595, 842);
    expect(box.left).toBeCloseTo(386.75, 6);
    expect(box.top).toBeCloseTo(362.06, 6);
    expect(box.width).toBeCloseTo(95.2, 6);
    expect(box.height).toBeCloseTo(16.84, 6);
  });

  it("scales in proportion when the page is shown larger or smaller", () => {
    const base = toCssBox(bbox, 400, 600);
    const bigger = toCssBox(bbox, 1200, 1800);
    expect(bigger.left).toBeCloseTo(base.left * 3, 6);
    expect(bigger.top).toBeCloseTo(base.top * 3, 6);
    expect(bigger.width).toBeCloseTo(base.width * 3, 6);
    expect(bigger.height).toBeCloseTo(base.height * 3, 6);
  });

  it("keeps the same fractions at 100% and 150%", () => {
    const at100 = toCssBox(bbox, 595.2756 * 1, 841.8898 * 1);
    const at150 = toCssBox(bbox, 595.2756 * 1.5, 841.8898 * 1.5);
    expect(at150.left / 1.5).toBeCloseTo(at100.left, 6);
    expect(at150.height / 1.5).toBeCloseTo(at100.height, 6);
  });

  describe("with a high device pixel ratio", () => {
    const original = window.devicePixelRatio;
    afterEach(() => {
      Object.defineProperty(window, "devicePixelRatio", { value: original, configurable: true });
    });

    it("is unchanged by devicePixelRatio, because it uses CSS pixels", () => {
      const before = toCssBox(bbox, 595, 842);
      Object.defineProperty(window, "devicePixelRatio", { value: 2, configurable: true });
      expect(toCssBox(bbox, 595, 842)).toEqual(before);
    });
  });
});

describe("canvasBackingSize", () => {
  it("multiplies by the pixel ratio for the bitmap but not for the CSS size", () => {
    expect(canvasBackingSize(595, 842, 2)).toEqual({ pixelWidth: 1190, pixelHeight: 1684 });
    expect(canvasBackingSize(595.5, 842.25, 1)).toEqual({ pixelWidth: 596, pixelHeight: 842 });
  });

  it("never returns a zero-sized bitmap", () => {
    expect(canvasBackingSize(0, 0, 2)).toEqual({ pixelWidth: 1, pixelHeight: 1 });
  });
});

describe("scaleForZoom", () => {
  it("uses fixed scales for 100% and 150%", () => {
    expect(scaleForZoom("100", 800, 595.2756)).toBe(1);
    expect(scaleForZoom("150", 800, 595.2756)).toBe(1.5);
  });

  it("fits the available width and never collapses to zero", () => {
    expect(scaleForZoom("fit", 595.2756, 595.2756)).toBeCloseTo(1, 6);
    expect(scaleForZoom("fit", 300, 600)).toBeCloseTo(0.5, 6);
    expect(scaleForZoom("fit", 0, 600)).toBeGreaterThan(0);
  });
});
