import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { "/api": backend } },
  preview: { port: 5173, strictPort: true, proxy: { "/api": backend } },
  test: {
    environment: "jsdom",
    globals: true,
    css: false,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
