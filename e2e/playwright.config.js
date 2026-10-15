// Requires backend on :8000 and frontend on :5173 (see README).
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
});
