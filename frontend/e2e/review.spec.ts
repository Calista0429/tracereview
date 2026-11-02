import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { check, expectMarqueeOnValue, field, openSample, tick, waitForPdf } from "./helpers";

const FIELDS = [
  "Fund name",
  "Currency",
  "Payment due date",
  "Investment contribution",
  "Management fee",
  "Total amount due",
];

// The four samples are imported once each, in order, into one fresh database.
test.describe.configure({ mode: "serial" });

test("preset total error: find it, fix it, check every field, confirm, reload", async ({ page }) => {
  await openSample(page, "Preset total error", "amount-error.pdf");
  await expect(page.getByRole("heading", { name: "amount-error.pdf" })).toBeVisible();
  await expect(page.getByText("Preset extraction error (demo fault)").first()).toBeVisible();
  await waitForPdf(page);

  // The original says 50,000.00; the candidate says 500000.00; the total rule fails.
  const total = page.getByTestId("field-total_due");
  await expect(total.getByText("500000.00", { exact: true })).toBeVisible();
  await expect(total.getByText("50,000.00", { exact: true })).toBeVisible();
  const totalRule = page.getByRole("listitem").filter({ hasText: "Total matches line items" });
  await expect(totalRule).toContainText("Fail");
  await expect(totalRule).toContainText("difference 450000.00");

  // Selecting the field frames the printed value in the real PDF.
  await field(page, "Total amount due").click();
  await expect(page.getByTestId("evidence-box")).toContainText("Total amount due");
  await expectMarqueeOnValue(page);

  // Correct it. Nothing is saved until the button is pressed, and a reason is required.
  await field(page, "Total amount due").fill("50,000");
  await expect(page.getByText("You have unsaved changes.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm review" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Reason for change" }).fill("Total checked against the PDF.");
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
  await expect(totalRule).toContainText("Pass");
  await expect(field(page, "Total amount due")).toHaveValue("50000.00");
  await expect(total.getByText("500000.00", { exact: true })).toBeVisible(); // initial extraction kept
  await expect(total.getByText("Edited")).toBeVisible();

  // The history keeps the before and after.
  await page.getByText(/^History \(/).click();
  await expect(page.getByText("500000.00 to 50000.00")).toBeVisible();
  await expect(page.getByText("Reason: Total checked against the PDF.")).toBeVisible();

  // Rules pass, but a person still has to check each value.
  await expect(page.getByText("0 of 6 fields checked")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm review" })).toBeDisabled();
  for (const [index, name] of FIELDS.entries()) {
    await tick(page, name);
    await expect(page.getByText(`${index + 1} of 6 fields checked`)).toBeVisible();
  }
  await page.getByRole("button", { name: "Confirm review" }).click();
  await expect(page.getByText(/Confirmed by local-reviewer/)).toBeVisible();
  await expect(field(page, "Total amount due")).toBeDisabled();

  // Persisted on the server, not just on screen.
  await page.reload();
  await expect(page.getByText(/Confirmed by local-reviewer/)).toBeVisible();
  await expect(field(page, "Total amount due")).toHaveValue("50000.00");

  // Export: the file is built by the server from the confirmed record.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export JSON" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^tracereview-.+-v9\.json$/);
  const exported = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(exported.document.status).toBe("CONFIRMED");
  expect(exported.fields.find((f: { key: string }) => f.key === "total_due")).toMatchObject({
    current_value: "50000.00",
    initial_extracted_value: "500000.00",
    source_text: "50,000.00",
    verified: true,
  });
  expect(exported.rules.results.map((r: { status: string }) => r.status)).toEqual(["PASS", "PASS", "PASS"]);
  expect(exported.history.map((e: { event_type: string }) => e.event_type)).not.toContain("EXPORT_GENERATED");
  await expect(page.getByText(/^Downloaded tracereview-/)).toBeVisible();

  // Editing a confirmed field withdraws the confirmation and the checks; the old events stay.
  await page.getByRole("button", { name: "Edit fields" }).click();
  await field(page, "Management fee").fill("2,100");
  await expect(page.getByRole("button", { name: "Export JSON" })).toBeDisabled(); // unsaved edit
  await page.getByRole("textbox", { name: "Reason for change" }).fill("Fee revised after review.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/Confirmed by/)).toHaveCount(0);
  await expect(page.getByText("0 of 6 fields checked")).toBeVisible();
  await expect(page.getByRole("button", { name: "Export JSON" })).toBeDisabled();
  await expect(page.getByRole("listitem").filter({ hasText: "Total matches line items" })).toContainText("Fail");
  await page.getByText(/^History \(/).click();
  await expect(page.getByText("Confirmed the review")).toBeVisible();
  await expect(page.getByText("Confirmation revoked because fields changed")).toBeVisible();
});

test("two windows: the late save is refused, the draft survives, nothing is overwritten", async ({ browser }) => {
  const context = await browser.newContext();
  const first = await context.newPage();
  await openSample(first, "Normal notice", "normal.pdf");
  const url = first.url();
  await waitForPdf(first);

  const second = await context.newPage();
  await second.goto(url);
  await expect(second.getByRole("heading", { name: "normal.pdf" })).toBeVisible();

  // Window one moves the document to version 2.
  await tick(first, "Fund name");
  await expect(first.getByText("Version 2", { exact: true })).toBeVisible();

  // Window two still holds version 1 and tries to save.
  await field(second, "Fund name").fill("Late Edit Fund");
  await second.getByRole("textbox", { name: "Reason for change" }).fill("Renaming.");
  await second.getByRole("button", { name: "Save changes" }).click();
  await expect(second.getByRole("alert")).toContainText("changed in another window");
  await expect(field(second, "Fund name")).toHaveValue("Late Edit Fund");

  // The server kept window one's state.
  await first.reload();
  await expect(field(first, "Fund name")).toHaveValue("Example Growth Fund I");
  await expect(check(first, "Fund name")).toBeChecked();

  // Only an explicit reload, then a deliberate save, gets the edit in.
  await second.getByRole("button", { name: "Reload latest" }).click();
  await expect(check(second, "Fund name")).toBeChecked();
  await expect(field(second, "Fund name")).toHaveValue("Late Edit Fund");
  await second.getByRole("button", { name: "Save changes" }).click();
  await expect(second.getByText("Version 3", { exact: true })).toBeVisible();
  await expect(check(second, "Fund name")).not.toBeChecked(); // an edit clears the checks
  await context.close();
});

test("a missing extraction is filled in from the PDF; the evidence box stays on target", async ({ page }) => {
  await openSample(page, "Preset missing due date", "missing-extraction.pdf");
  await waitForPdf(page);
  await expect(field(page, "Payment due date")).toHaveValue("");
  await expect(check(page, "Payment due date")).toBeDisabled(); // nothing to check yet

  await field(page, "Payment due date").click();
  await expectMarqueeOnValue(page); // the value is in the PDF even though extraction dropped it
  await field(page, "Payment due date").fill("2026-11-24");
  await page.getByRole("textbox", { name: "Reason for change" }).fill("Read from the PDF.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
  await expect(check(page, "Payment due date")).toBeEnabled();

  // Keyboard only: Tab from a field's input to its check box, Space to tick it, Tab onwards.
  // Focus must survive the save round trip so the next Tab continues from the same place.
  await field(page, "Fund name").focus();
  for (const [index, name] of FIELDS.entries()) {
    await page.keyboard.press("Tab");
    await expect(check(page, name)).toBeFocused();
    await page.keyboard.press("Space");
    await expect(check(page, name)).toBeChecked();
    await expect(check(page, name)).toBeFocused();
    await expect(page.getByText(`${index + 1} of 6 fields checked`)).toBeVisible();
    await page.keyboard.press("Tab");
  }
});

test("a value with no source cannot be located, checked or confirmed", async ({ page }) => {
  await openSample(page, "Missing source value", "missing-source.pdf");
  await waitForPdf(page);
  const row = page.getByTestId("field-due_date");
  await expect(row.getByText("No source location")).toBeVisible();
  await expect(row.getByRole("checkbox")).toBeDisabled();
  await field(page, "Payment due date").click();
  await expect(page.getByText(/could not be located uniquely/)).toBeVisible();
  await expect(page.getByTestId("evidence-box")).toHaveCount(0);

  await field(page, "Payment due date").fill("2026-11-30");
  await page.getByRole("textbox", { name: "Reason for change" }).fill("Value supplied by reviewer.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
  await expect(page.getByTestId("evidence-box")).toHaveCount(0); // typing a value does not invent a location
  await expect(row.getByRole("checkbox")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Confirm review" })).toBeDisabled();
});

test("importing the same file again opens the existing record", async ({ page }) => {
  await page.goto("/");
  const card = page.getByRole("listitem").filter({ hasText: "Normal notice" });
  await card.getByRole("button", { name: "Import sample" }).click();
  await expect(page.getByRole("alert")).toContainText("already been imported");
  await page.getByRole("link", { name: "Open the existing record" }).click();
  await expect(page.getByRole("heading", { name: "normal.pdf" })).toBeVisible();
  // The earlier edit and version are still there: nothing was overwritten or re-imported.
  await expect(field(page, "Fund name")).toHaveValue("Late Edit Fund");
  await expect(page.getByText("Version 3", { exact: true })).toBeVisible();
});

test("leaving with a draft asks first, and uploading a bad file explains why", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "normal.pdf" }).click();
  await field(page, "Fund name").fill("Changed but unsaved");
  await page.getByRole("link", { name: "All documents" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("unsaved changes");
  await page.getByRole("button", { name: "Keep editing" }).click();
  await expect(field(page, "Fund name")).toHaveValue("Changed but unsaved");
  await page.getByRole("button", { name: "Discard changes" }).click();
  await page.getByRole("link", { name: "All documents" }).click();

  await page.getByLabel(/Choose a PDF/).setInputFiles({
    name: "notes.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("this is not a pdf"),
  });
  await expect(page.getByRole("alert")).toContainText("could not be read as a PDF");
});
