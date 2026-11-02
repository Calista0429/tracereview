import { expect, type Locator, type Page } from "@playwright/test";

/** Open a sample's record, importing it first if this database has not seen it yet. */
export async function openSample(page: Page, title: string, filename: string) {
  await page.goto("/");
  const existing = page.getByRole("link", { name: filename, exact: true });
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.getByText("Loading documents…")).toHaveCount(0);
  if (await existing.count()) {
    await existing.click();
  } else {
    const card = page.getByRole("listitem").filter({ hasText: title });
    await card.getByRole("button", { name: "Import sample" }).click();
  }
  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: filename })).toBeVisible();
}

/** Opaque dark pixels in a canvas region. Unpainted canvas pixels are transparent, not ink. */
const COUNT_INK = `
  (data) => {
    let ink = 0;
    for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 200 && data[i] < 128) ink++;
    return ink;
  }
`;

/** Wait until PDF.js has finished painting at the page's current CSS size. */
export async function waitForPdf(page: Page) {
  await expect(page.getByTestId("pdf-canvas")).toBeVisible();
  await expect
    .poll(
      () =>
        page.evaluate((countSource) => {
          const count = eval(countSource) as (d: Uint8ClampedArray) => number;
          const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="pdf-canvas"]')!;
          const sheet = document.querySelector<HTMLElement>('[data-testid="pdf-page"]')!;
          const expectedWidth = Math.round(sheet.getBoundingClientRect().width * window.devicePixelRatio);
          if (Math.abs(canvas.width - expectedWidth) > 1) return 0; // not re-rendered at this size yet
          const ctx = canvas.getContext("2d");
          if (!ctx) return 0;
          return count(ctx.getImageData(0, 0, canvas.width, canvas.height).data);
        }, COUNT_INK),
      { message: "PDF.js should paint the page at its current size" },
    )
    .toBeGreaterThan(200);
}

export interface InkReading {
  ink: number;
  total: number;
}

/**
 * Dark pixels of the rendered PDF under the evidence box, offset by dyCss CSS pixels.
 * Measures the real canvas bitmap, so it proves the box is over the printed value.
 */
export async function inkUnderMarquee(page: Page, dyCss = 0): Promise<InkReading> {
  return page.evaluate(
    ({ dy, countSource }) => {
      const count = eval(countSource) as (d: Uint8ClampedArray) => number;
      const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="pdf-canvas"]')!;
      const box = document.querySelector<HTMLElement>('[data-testid="evidence-box"]')!;
      const c = canvas.getBoundingClientRect();
      const b = box.getBoundingClientRect();
      const sx = canvas.width / c.width;
      const sy = canvas.height / c.height;
      const x = Math.max(0, Math.round((b.left - c.left) * sx));
      const y = Math.max(0, Math.round((b.top - c.top + dy) * sy));
      const w = Math.max(1, Math.min(Math.round(b.width * sx), canvas.width - x));
      const h = Math.max(1, Math.min(Math.round(b.height * sy), canvas.height - y));
      const { data } = canvas.getContext("2d")!.getImageData(x, y, w, h);
      return { ink: count(data), total: data.length / 4 };
    },
    { dy: dyCss, countSource: COUNT_INK },
  );
}

export async function expectMarqueeOnValue(page: Page) {
  await expect(page.getByTestId("evidence-box")).toBeVisible();
  await waitForPdf(page);
  // Scrolling and a re-render can still be settling: wait for the box to sit on ink.
  await expect
    .poll(async () => {
      const r = await inkUnderMarquee(page);
      return r.ink / r.total;
    }, { message: "ink inside the highlighted box" })
    .toBeGreaterThan(0.04);
  const on = await inkUnderMarquee(page);
  // Control: rows are 32pt apart and text is 11pt tall, so a box shifted down by 16pt (1.45
  // box heights, at any zoom) sits in blank paper. A drifting overlay would be caught here.
  const marquee = await page.getByTestId("evidence-box").boundingBox();
  const between = await inkUnderMarquee(page, (marquee?.height ?? 12) * 1.45);
  expect(between.ink / between.total, "ink in the gap below").toBeLessThan(on.ink / on.total / 2);
}

export function field(page: Page, name: string): Locator {
  return page.getByRole("textbox", { name, exact: true });
}

export function check(page: Page, name: string): Locator {
  return page.getByRole("checkbox", { name: new RegExp(name) });
}

/** Select a field row by its label, which works whether or not the input is editable. */
export async function selectField(page: Page, name: string) {
  await page.locator(".field__label", { hasText: new RegExp(`^${name}$`) }).click();
}

/** Tick a "checked against PDF" box. It flips only once the server has accepted the change. */
export async function tick(page: Page, name: string) {
  await check(page, name).click();
  await expect(check(page, name)).toBeChecked();
}
