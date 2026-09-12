import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { articles } from "../../src/mocks/fixtures/content";

// Reproduce the six long headlines in the reported layout without changing live data.
const headlines = [
  "‘잘못된 인선’ 용혜인 63%, 김승원 47%...부정 평가 압도적 [NBS]",
  "이 정부 장관 후보자 ‘낙마의 법칙’...청문회 고수하고, 3~4주 만에 결판",
  "청 “파병, 국익 국민 공감 기반돼야”",
  "“호르무즈 파병 명분 없어” “휘말리면 안 돼”...민주당 내 신중론 잇따라",
  "국회 법사위, 김승원 인사청문회 15일 개최키로...증인 채택은 불발",
  "美, 중간선거 맞춰 11월까지 파병 요청...정부, 내주 NSC 논의",
];

for (const count of [3, 6]) {
  for (const width of [1440, 1024, 768, 390, 320]) {
    test(`${count} long headlines align with their chart at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      const items = headlines.slice(0, count).map((title, index) => {
        const article = articles[index % articles.length];
        return {
          id: `layout-article-${index}`, issue_id: "issue-housing", source_id: article.sourceId,
          source: article.source, title, summary: article.dek, published_at: "2026-09-11T00:00:00Z",
          canonical_url: article.originalUrl, current_version_id: article.scoreVersion,
          analysis_status: "READY", status: "active",
          coordinate: { x: [-18, 0, -9, -18, -9, 8][index], y: 0, z: 0, sensationalism: [38, 17, 30, 22, 52, 27][index], confidence: .85 },
        };
      });
      await page.addInitScript((fixture) => {
        const originalFetch = window.fetch.bind(window);
        window.fetch = (input, init) => {
          const url = input instanceof Request ? input.url : String(input);
          if (url.includes("/api/v1/issues/issue-housing/articles")) {
            return Promise.resolve(new Response(JSON.stringify({ items: fixture, next_cursor: null }), {
              status: 200, headers: { "Content-Type": "application/json" },
            }));
          }
          return originalFetch(input, init);
        };
      }, items);
      await page.goto("/");
      const section = page.locator(".front-page__analysis");
      await expect(section.locator(".analysis-story-index > li")).toHaveCount(count);
      await expect(section.locator("figcaption")).toContainText(`공개 분석 ${count}건`);
      await page.evaluate(() => document.fonts.ready);
      const boxes = await section.evaluate((element) => {
        const rect = (selector: string) => {
          const box = element.querySelector(selector)!.getBoundingClientRect();
          return { top: box.top, bottom: box.bottom, left: box.left, right: box.right };
        };
        return { heading: rect(".front-page__analysis-heading"), list: rect(".analysis-story-index"), chart: rect(".front-chart"), footer: rect(".front-page__analysis-more"), overflow: document.documentElement.scrollWidth > innerWidth };
      });
      expect(boxes.overflow).toBe(false);
      expect(boxes.heading.bottom).toBeLessThanOrEqual(boxes.list.top);
      if (width > 900) {
        expect(Math.abs(boxes.list.top - boxes.chart.top)).toBeLessThan(1);
        expect(boxes.list.right).toBeLessThan(boxes.chart.left);
        expect(Math.abs(boxes.heading.right - boxes.chart.right)).toBeLessThan(1);
      } else {
        expect(boxes.chart.top).toBeGreaterThanOrEqual(boxes.list.bottom);
        expect(Math.abs(boxes.chart.left - boxes.heading.left)).toBeLessThan(1);
      }
      expect(boxes.footer.top).toBeGreaterThanOrEqual(Math.max(boxes.list.bottom, boxes.chart.bottom));
      expect(Math.abs(boxes.footer.left - boxes.heading.left)).toBeLessThan(1);
      const directory = path.resolve("../output/playwright/home-alignment");
      await mkdir(directory, { recursive: true });
      await section.screenshot({ path: path.join(directory, `${count}-articles-${width}-${testInfo.project.name}.png`) });
      await expect(section.getByRole("link", { name: "기사 안에서 관점 비교하기 →" })).toHaveAttribute("href", "/articles/layout-article-0#perspective-map");
    });
  }
}
