import { defineConfig } from "@playwright/test";
const port = Number(process.env.HH_UI_PORT || 4173);
const url = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: "./qa",
  testMatch: "ui.spec.ts",
  fullyParallel: false,
  use: { baseURL: url, headless: true },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url,
    reuseExistingServer: false,
  },
  reporter: "list",
  outputDir: process.env.HH_UI_OUTPUT || "test-results",
});
