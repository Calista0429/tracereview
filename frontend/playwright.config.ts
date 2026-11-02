import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// One fresh data directory per run, shared by the config evaluated in every process.
process.env.E2E_DATA_DIR ??= mkdtempSync(path.join(tmpdir(), "tracereview-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    // Uses the Chrome already on the machine, so no browser download is needed. To use
    // Playwright's own Chromium instead: `npx playwright install chromium`, then run with PW_CHANNEL= (empty).
    channel: process.env.PW_CHANNEL === undefined ? "chrome" : process.env.PW_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "../.venv/bin/python -m app",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/openapi.json",
      env: { TRACEREVIEW_DATA_DIR: process.env.E2E_DATA_DIR },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
