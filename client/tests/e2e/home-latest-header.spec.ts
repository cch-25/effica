import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";

const output = path.resolve("../output/playwright/home-latest-header");

test("latest articles paginate independently of issue coverage without duplicates", async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.origin);
      if (url.pathname !== "/api/v1/articles") return original(input, init);
      const offset = url.searchParams.get("cursor") ? 11 : 0;
      const items = Array.from({ length: offset ? 3 : 12 }, (_, index) => ({
        id: `latest-${offset + index}`, source_id: "independent", source: "독립 보도",
        title: `지역 교통 정책의 변화와 시민 의견 ${offset + index + 1}`,
        summary: "지역 주민들이 교통 정책에 관해 제시한 의견과 관련 자료를 살펴봅니다.",
        published_at: new Date(Date.UTC(2026, 8, 13, 12) - (offset + index) * 3600000).toISOString(),
        canonical_url: `https://publisher.example/${offset + index}`, current_version_id: `version-${offset + index}`,
        analysis_status: "READY", status: "active", coordinate: null,
      }));
      return Promise.resolve(new Response(JSON.stringify({ items, next_cursor: offset ? null : "page-two" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    };
  });
  await page.goto("/");
  const latest = page.getByRole("region", { name: "최신 기사" });
  await expect(latest.locator("li")).toHaveCount(12);
  await expect(latest.locator("h3 a").first()).toHaveAttribute("href", "/articles/latest-0");
  await expect(page.locator(".home-spreads")).not.toContainText("독립 보도");
  await latest.getByRole("button", { name: "기사 더 보기", exact: true }).click();
  await expect(latest.locator("li")).toHaveCount(14);
  await expect(latest.locator("h3 a").last()).toHaveAttribute("href", "/articles/latest-13");
  await expect(latest.getByRole("button", { name: "기사 더 보기", exact: true })).toHaveCount(0);
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await latest.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  }
  expect((await new AxeBuilder({ page }).include(".home-latest").analyze()).violations).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`shared header retains the home dimensions across routes at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mkdir(output, { recursive: true });
    let expected: unknown;
    for (const route of ["/", "/articles", "/issues", "/algo", "/progress", "/login", "/admin"]) {
      await page.goto(route);
      await page.evaluate(() => document.fonts.ready);
      const dimensions = await page.locator(".site-header").evaluate(header => [".newspaper-masthead", ".newspaper-masthead__name", ".site-nav"].map(selector => {
        const element = header.querySelector(selector)!;
        const { x, y, width, height } = element.getBoundingClientRect();
        return { x, y, width, height, font: getComputedStyle(element).fontSize };
      }));
      expected ??= dimensions;
      expect(dimensions, route).toEqual(expected);
      await expect(page.locator(".headline-band")).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      if (route === "/") {
        await expect(page.locator(".shell--frontpage")).toHaveCSS("background-color", "rgb(255, 255, 255)");
        await expect(page.locator(".home-latest li").first()).toBeVisible();
        await page.screenshot({ path: path.join(output, `home-${width}.png`), fullPage: true });
      }
      if (["/articles", "/login"].includes(route)) await page.screenshot({ path: path.join(output, `${route.slice(1)}-${width}.png`) });
    }
  });
}
