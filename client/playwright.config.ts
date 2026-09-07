import { defineConfig, devices } from "@playwright/test";

const webPort = process.env.PLAYWRIGHT_PORT ?? "3200";
const webBaseUrl = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./tests",
  timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT_MS ?? "30000"),
  expect: { timeout: Number(process.env.PLAYWRIGHT_EXPECT_TIMEOUT_MS ?? "5000") },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  use: {
    baseURL: webBaseUrl,
    headless: true,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `NEXT_DIST_DIR=.next-playwright-${webPort} NEXT_PUBLIC_API_MODE=mock npm run dev -- --hostname 127.0.0.1 --port ${webPort}`,
    url: webBaseUrl,
    reuseExistingServer: false,
  },
});
