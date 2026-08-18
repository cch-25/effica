import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = ["/login", "/onboarding/consent", "/", "/issues", "/articles/article-01", "/visualization?webgl-off=1", "/admin/weights"];

for (const route of routes) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    if (route.startsWith("/admin")) {
      await page.context().addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]);
    }
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious")).toEqual([]);
  });
}

test("vote controls and fallback are keyboard accessible", async ({ page }) => {
  await page.goto("/articles/article-01");
  const perspectiveChoice = page.getByRole("button", { name: "약간 우편향 +33" });
  await perspectiveChoice.focus(); await page.keyboard.press("Enter"); await expect(perspectiveChoice).toHaveAttribute("aria-pressed", "true");
  await page.goto("/visualization?webgl-off=1");
  await expect(page.getByRole("region", { name: "두 기준으로 읽는 현재 관점" })).toBeVisible();
  await expect(page.getByRole("img", { name: /현재 관점의 편향성과 과장성/ })).toBeVisible();
});
