import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = ["/login", "/onboarding/consent", "/", "/issues", "/articles/article-01", "/visualization?webgl-off=1", "/admin/weights"];

for (const route of routes) {
  test(`${route} has no critical accessibility violations`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => violation.impact === "critical")).toEqual([]);
  });
}

test("vote controls and fallback are keyboard accessible", async ({ page }) => {
  await page.goto("/articles/article-01");
  const slider = page.getByLabel("경제 (평등·재분배 ↔ 시장·경쟁)");
  await slider.focus(); await page.keyboard.press("ArrowRight"); await expect(slider).toHaveValue("1");
  await page.goto("/visualization?webgl-off=1"); await expect(page.getByRole("tab", { name: "2D 투영" })).toHaveAttribute("aria-selected", "true"); await expect(page.getByRole("tab", { name: "데이터 표" })).toBeEnabled();
});
