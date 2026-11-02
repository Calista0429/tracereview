import path from "node:path";
import { fileURLToPath } from "node:url";

import { test } from "@playwright/test";

import { openSample, selectField, waitForPdf } from "./helpers";

// Refreshes docs/screenshots. Skipped unless asked: SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to refresh docs/screenshots");

const out = (name: string) => path.join(fileURLToPath(new URL(".", import.meta.url)), "..", "..", "docs", "screenshots", name);

test("desktop review page and list", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  await selectField(page, "Total amount due");
  await page.waitForTimeout(600);
  await page.evaluate(() => window.scrollTo(0, 0)); // top of the page: failing rule beside the highlighted value
  await page.waitForTimeout(300);
  await page.screenshot({ path: out("review.png") });
  await page.getByRole("link", { name: "All documents" }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: out("list.png") });
  await context.close();
});

test("phone review page", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  await selectField(page, "Total amount due");
  await page.waitForTimeout(600);
  await page.screenshot({ path: out("review-phone.png") });
  await context.close();
});
