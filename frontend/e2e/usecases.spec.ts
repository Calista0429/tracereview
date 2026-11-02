import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { check, expectMarqueeOnValue, field, openSample, selectField, tick, waitForPdf } from "./helpers";

/**
 * A person using the product, start to finish, saving a screenshot at each use case for the
 * README. It runs against a fresh database and real Chrome. Skipped unless asked:
 *
 *   SCREENSHOTS=1 npx playwright test e2e/usecases.spec.ts
 */
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to refresh docs/screenshots");
test.describe.configure({ mode: "serial" });

const repoRoot = path.join(fileURLToPath(new URL(".", import.meta.url)), "..", "..");
const shots = path.join(repoRoot, "docs", "screenshots");
const examples = path.join(repoRoot, "docs", "examples");
mkdirSync(shots, { recursive: true });
mkdirSync(examples, { recursive: true });

const DESKTOP = { width: 1440, height: 1500 }; // tall enough to see PDF, rules, six fields and actions at once
const FIELDS = ["Fund name", "Currency", "Payment due date", "Investment contribution", "Management fee", "Total amount due"];

test.use({ viewport: DESKTOP, reducedMotion: "reduce", locale: "en-GB", timezoneId: "UTC" });

async function shot(page: Page, name: string) {
  await page.waitForTimeout(350); // let focus rings, scrolling and canvas settle
  await page.screenshot({ path: path.join(shots, `${name}.png`) });
}

async function toTop(page: Page) {
  await page.evaluate(() => window.scrollTo(0, 0));
}

async function toBottom(page: Page) {
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
}

test("1. First visit: nothing imported yet, four samples to try", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByText(/No documents yet/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Import sample" })).toHaveCount(4);
  await shot(page, "01-home-empty");
});

test("2. A clean notice: every rule passes, but nobody has looked yet", async ({ page }) => {
  await openSample(page, "Normal notice", "normal.pdf");
  await waitForPdf(page);
  await selectField(page, "Total amount due");
  await expectMarqueeOnValue(page);
  await toTop(page);
  await shot(page, "02-clean-notice");
});

test("3. A preset extraction error is caught and traced to the PDF", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  await selectField(page, "Total amount due");
  await expectMarqueeOnValue(page);
  await expect(page.getByRole("listitem").filter({ hasText: "Total matches line items" })).toContainText("Fail");
  await toTop(page);
  await shot(page, "03-error-caught");
});

test("4. Correct the value with a reason, then see the before and after", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  await field(page, "Total amount due").click();
  await field(page, "Total amount due").fill("");
  await field(page, "Total amount due").pressSequentially("50,000", { delay: 70 });
  await page.getByRole("textbox", { name: "Reason for change" }).pressSequentially("Total checked against the PDF.", { delay: 25 });
  await expect(page.getByText("You have unsaved changes.")).toBeVisible();
  await toTop(page);
  await shot(page, "04-correct-with-reason");

  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
  await page.getByText(/^History \(/).click();
  await expect(page.getByText("500000.00 to 50000.00")).toBeVisible();
  await toBottom(page);
  await shot(page, "05-history-before-after");
});

test("5. Check every field against the PDF, then confirm", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  for (const name of FIELDS) await tick(page, name);
  await expect(page.getByText("6 of 6 fields checked")).toBeVisible();
  await page.getByRole("button", { name: "Confirm review" }).click();
  await expect(page.getByText(/Confirmed by local-reviewer/)).toBeVisible();
  await toTop(page);
  await shot(page, "06-confirmed");
});

test("6. Export the confirmed version as JSON", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export JSON" }).click(),
  ]);
  await download.saveAs(path.join(examples, "amount-error-confirmed-export.json"));
  await expect(page.getByText(/^Downloaded tracereview-/)).toBeVisible();
  await page.getByText(/^History \(/).click();
  await expect(page.getByText(/Generated a JSON export/)).toBeVisible();
  await toBottom(page);
  await shot(page, "07-export-json");
});

test("7. Editing a confirmed record withdraws the confirmation", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await waitForPdf(page);
  await page.getByRole("button", { name: "Edit fields" }).click();
  await field(page, "Management fee").fill("");
  await field(page, "Management fee").pressSequentially("2,100", { delay: 70 });
  await page.getByRole("textbox", { name: "Reason for change" }).pressSequentially("Fee revised after review.", { delay: 25 });
  await toBottom(page);
  await shot(page, "08-edit-confirmed-record");

  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/Confirmed by/)).toHaveCount(0);
  await expect(page.getByText("0 of 6 fields checked")).toBeVisible();
  await toTop(page);
  await shot(page, "09-confirmation-withdrawn");
});

test("8. A value the extractor missed is still found in the PDF", async ({ page }) => {
  await openSample(page, "Preset missing due date", "missing-extraction.pdf");
  await waitForPdf(page);
  await selectField(page, "Payment due date");
  await expectMarqueeOnValue(page);
  await toTop(page);
  await shot(page, "10-missing-extraction");
});

test("9. A value with no source in the PDF cannot be checked or confirmed", async ({ page }) => {
  await openSample(page, "Missing source value", "missing-source.pdf");
  await waitForPdf(page);
  await selectField(page, "Payment due date");
  await expect(page.getByText(/could not be located uniquely/)).toBeVisible();
  await toTop(page);
  await shot(page, "11-missing-source-blocked");
});

test("10. Two windows: the late save is refused and the draft is kept", async ({ browser }) => {
  const context = await browser.newContext({ viewport: DESKTOP, reducedMotion: "reduce", locale: "en-GB", timezoneId: "UTC" });
  const first = await context.newPage();
  await openSample(first, "Normal notice", "normal.pdf");
  await waitForPdf(first);
  const second = await context.newPage();
  await second.goto(first.url());
  await waitForPdf(second);

  await tick(first, "Fund name"); // window one moves the record on
  await field(second, "Fund name").click();
  await field(second, "Fund name").fill("");
  await field(second, "Fund name").pressSequentially("Example Growth Fund I (renamed)", { delay: 30 });
  await second.getByRole("textbox", { name: "Reason for change" }).pressSequentially("Legal name changed.", { delay: 25 });
  await second.getByRole("button", { name: "Save changes" }).click();
  await expect(second.getByRole("alert")).toContainText("changed in another window");
  await toTop(second);
  await shot(second, "12-version-conflict");
  await context.close();
});

test("11. The document list, a duplicate upload and a scanned PDF", async ({ page }) => {
  // Finish the clean notice the way a reviewer would, so the list shows a confirmed record too.
  await openSample(page, "Normal notice", "normal.pdf");
  await waitForPdf(page);
  for (const name of FIELDS.slice(1)) await tick(page, name); // Fund name was ticked in test 10
  await page.getByRole("button", { name: "Confirm review" }).click();
  await expect(page.getByText(/Confirmed by local-reviewer/)).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "normal.pdf" })).toBeVisible();
  await shot(page, "13-document-list");

  const card = page.getByRole("listitem").filter({ hasText: "Normal notice" });
  await card.getByRole("button", { name: "Import sample" }).click();
  await expect(page.getByRole("alert")).toContainText("already been imported");
  await shot(page, "14-duplicate-upload");

  const scan = path.join(mkdtempSync(path.join(tmpdir(), "tracereview-scan-")), "scanned-notice.pdf");
  execFileSync(path.join(repoRoot, ".venv", "bin", "python"), [
    "-c",
    "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from generate_fixtures import build_pdf, normal_rows; build_pdf(Path(sys.argv[2]), normal_rows('Scanned Fund', '2026-11-10'), text_layer=False)",
    path.join(repoRoot, "scripts"),
    scan,
  ]);
  await page.getByLabel(/Choose a PDF/).setInputFiles(scan);
  await expect(page.getByRole("alert")).toContainText("text layer");
  await shot(page, "15-rejected-file");
});

test("12. Leaving with unsaved changes asks first", async ({ page }) => {
  await openSample(page, "Preset missing due date", "missing-extraction.pdf");
  await waitForPdf(page);
  await field(page, "Fund name").fill("Half-typed new name");
  await page.getByRole("link", { name: "All documents" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await shot(page, "16-unsaved-changes");
  await page.getByRole("button", { name: "Keep editing" }).click();
});

test("13. On a phone", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    reducedMotion: "reduce", locale: "en-GB", timezoneId: "UTC",
  });
  const page = await context.newPage();
  await openSample(page, "Preset missing due date", "missing-extraction.pdf");
  await waitForPdf(page);
  await selectField(page, "Payment due date");
  await expectMarqueeOnValue(page);
  await page.getByTestId("evidence-box").scrollIntoViewIfNeeded();
  await shot(page, "17-mobile-highlight");
  await check(page, "Fund name").scrollIntoViewIfNeeded();
  await page.getByRole("heading", { name: "Fields" }).scrollIntoViewIfNeeded();
  await shot(page, "18-mobile-fields");
  await context.close();
});
