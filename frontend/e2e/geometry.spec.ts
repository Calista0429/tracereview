import { expect, test } from "@playwright/test";

import { expectMarqueeOnValue, openSample, selectField, waitForPdf } from "./helpers";

// The evidence box must stay on the printed value whatever the zoom, window size or
// pixel density. deviceScaleFactor 2 makes the canvas bitmap twice its CSS size.
const KEYS = ["Fund name", "Investment contribution", "Management fee", "Total amount due"];

for (const [label, viewport] of [
  ["desktop 1440px", { width: 1440, height: 900 }],
  ["phone 390px", { width: 390, height: 844 }],
] as const) {
  test.describe(label, () => {
    test.use({ viewport, deviceScaleFactor: 2 });

    test("box frames the value at fit width, 100% and 150%", async ({ page }) => {
      await openSample(page, "Preset total error", "amount-error.pdf");
      await waitForPdf(page);

      for (const zoom of ["Fit width", "100%", "150%"]) {
        await page.getByRole("button", { name: zoom }).click();
        await expect(page.getByRole("button", { name: zoom })).toHaveAttribute("aria-pressed", "true");
        await waitForPdf(page);
        for (const key of KEYS) {
          await selectField(page, key);
          await expect(page.getByTestId("evidence-box")).toContainText(key);
          await expectMarqueeOnValue(page);
        }
      }
    });

    test("canvas bitmap is twice the CSS size, the overlay is not", async ({ page }) => {
      await openSample(page, "Preset total error", "amount-error.pdf");
      await waitForPdf(page);
      await selectField(page, "Total amount due");
      const sizes = await page.evaluate(() => {
        const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="pdf-canvas"]')!;
        const sheet = document.querySelector<HTMLElement>('[data-testid="pdf-page"]')!;
        const box = document.querySelector<HTMLElement>('[data-testid="evidence-box"]')!;
        return {
          ratio: window.devicePixelRatio,
          bitmapWidth: canvas.width,
          cssWidth: sheet.getBoundingClientRect().width,
          boxFraction: box.getBoundingClientRect().width / sheet.getBoundingClientRect().width,
        };
      });
      expect(sizes.ratio).toBe(2);
      expect(sizes.bitmapWidth).toBeCloseTo(sizes.cssWidth * 2, 0);
      expect(sizes.boxFraction).toBeGreaterThan(0.03);
      expect(sizes.boxFraction).toBeLessThan(0.2);
    });

    test("selecting a field brings its box into view", async ({ page }) => {
      await openSample(page, "Preset total error", "amount-error.pdf");
      await waitForPdf(page);
      await page.getByRole("button", { name: "150%" }).click();
      await selectField(page, "Total amount due");
      await expect(page.getByTestId("evidence-box")).toBeInViewport();
    });
  });
}
