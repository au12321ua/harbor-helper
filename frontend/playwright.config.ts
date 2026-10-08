import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./qa",
  testMatch: "ui.spec.ts",
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:4173", headless: true },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
  },
  reporter: "list",
  outputDir: "/tmp/harbor-helper-web-ui-results",
});
