import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/real",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "cd ../.. && APP_ENV=test APP_BACKEND=memory LLM_PROVIDER_MODE=stub uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8100",
      url: "http://127.0.0.1:8100/health/ready",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "NEXT_DIST_DIR=.next-real NEXT_PUBLIC_API_MODE=real API_BACKEND_URL=http://127.0.0.1:8100 npm run dev -- --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
