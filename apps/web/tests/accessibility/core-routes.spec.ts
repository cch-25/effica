import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = [
  "/login",
  "/admin",
  "/onboarding/consent",
  "/",
  "/issues",
  "/articles/article-01",
  "/visualization",
  "/admin/runtime",
  "/admin/weights",
];

for (const route of routes) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    if (route.startsWith("/admin/")) {
      await page.context().addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]);
    }
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious")).toEqual([]);
  });
}

test("vote controls and the coordinate plot are keyboard accessible", async ({ page }) => {
  await page.goto("/articles/article-01");
  const perspectiveChoice = page.getByRole("button", { name: "약간 우편향 +33" });
  await perspectiveChoice.focus(); await page.keyboard.press("Enter"); await expect(perspectiveChoice).toHaveAttribute("aria-pressed", "true");
  await page.goto("/visualization");
  await expect(page.getByRole("region", { name: "나의 편향 기준으로 읽는 기사 좌표" })).toBeVisible();
  await expect(page.getByRole("img", { name: /나의 편향 기준과 기사 편향성·과장성 좌표 분포/ })).toBeVisible();
});
