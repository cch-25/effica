import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = [
  "/login",
  "/admin",
  "/onboarding/consent",
  "/onboarding/questionnaire",
  "/onboarding/demographics",
  "/",
  "/issues",
  "/issues/issue-housing",
  "/articles/article-01",
  "/visualization",
  "/progress",
  "/efficacy",
  "/share/new",
  "/share/share-card-ready",
  "/share/p/mock-public-token",
  "/settings/privacy",
  "/admin/runtime",
  "/admin/weights",
];

const mobileRoutes = [
  "/login",
  "/onboarding/consent",
  "/onboarding/questionnaire",
  "/onboarding/demographics",
  "/",
  "/issues",
  "/issues/issue-housing",
  "/articles/article-01",
  "/visualization",
  "/progress",
  "/efficacy",
  "/share/new",
  "/share/share-card-ready",
  "/share/p/mock-public-token",
  "/settings/privacy",
];

for (const route of routes) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    if (route.startsWith("/admin/")) {
      await page.context().addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]);
    }
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious")).toEqual([]);
  });
}

for (const route of mobileRoutes) {
  test(`${route} fits a 390px viewport without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });

    await expect.poll(() => page.evaluate(() => (
      document.documentElement.scrollWidth <= document.documentElement.clientWidth
      && document.body.scrollWidth <= document.documentElement.clientWidth
    ))).toBe(true);
  });
}

test("vote controls and the coordinate plot are keyboard accessible", async ({ page }) => {
  await page.goto("/articles/article-01");
  const perspectiveChoice = page.getByRole("button", { name: "약간 우편향 +33" });
  await perspectiveChoice.focus(); await page.keyboard.press("Enter"); await expect(perspectiveChoice).toHaveAttribute("aria-pressed", "true");
  await page.goto("/visualization");
  await expect(page.getByRole("region", { name: "나의 편향 기준으로 읽는 기사 좌표" })).toBeVisible();
  await expect(page.getByRole("img", { name: /나의 편향 기준과 기사 편향성과 과장성 좌표 분포/ })).toBeVisible();
});
