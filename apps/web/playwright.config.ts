import { defineConfig, devices } from "@playwright/test";

const webPort = process.env.PLAYWRIGHT_PORT ?? "3000";
const webBaseUrl = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./tests",
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
    reuseExistingServer: !process.env.CI,
  },
});
