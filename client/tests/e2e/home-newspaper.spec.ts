import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";

const titles = [
  "김승원 법무부 장관 후보자 신약 청탁 의혹과 인사청문 검증 공방",
  "용혜인 성평등가족부 장관 후보자의 국회의원 겸직 및 공직 적격성 논란",
  "김승원 용혜인 강신철 장관 후보자 인사청문회 증인 채택 무산",
  "호르무즈 해협 파병과 안보 지원을 둘러싼 정부 국회 공방",
  "김승원 용혜인 장관 후보자 인사청문회와 각종 의혹 검증",
];
const ids = ["kim", "yong", "witness", "hormuz", "hearing"];
const sources = ["세계일보", "동아일보", "뉴시스", "경향신문"];
const rows = ids.map((id, index) => ({
  id, title: titles[index], topic: "정치", kind: "EVENT", status: "active",
  summary: index === 3 ? "해협 파병과 안보 지원 여부를 두고 정부와 국회가 입장을 내놨습니다. 국회 동의와 안전 대책이 주요 쟁점입니다." : "후보자 검증을 두고 여야의 입장이 엇갈립니다. 제기된 의혹과 후보자의 해명을 같은 쟁점을 다룬 기사에서 확인할 수 있습니다.",
  source_count: 4, analysis_status: index === 2 ? "PARTIAL" : "READY", freshness_status: "CURRENT",
  editorial_priority: index + 1, data_as_of: "2026-09-11T03:00:00Z", last_activity_at: "2026-09-11T03:00:00Z",
  coverage_group_id: index === 3 ? "hormuz" : "kim",
  coverage_group_title: index === 3 ? titles[index] : "장관 후보자 인사청문회",
  opened_at: "2026-09-10T00:00:00Z", article_ids: sources.map((_, source) => `${id}-${source}`),
}));

async function installFixture(page: Page, empty = false) {
  await page.addInitScript(({ rows, sources, empty }) => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.origin);
      const respond = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } }));
      if (url.pathname === "/api/v1/issues") return respond({ items: empty ? [] : rows, next_cursor: null });
      const match = url.pathname.match(/^\/api\/v1\/issues\/([^/]+)\/articles$/);
      if (match) {
        const issue = rows.find((item) => item.id === match[1]);
        if (issue) return respond({ items: issue.article_ids.map((id, index) => ({
          id, issue_id: issue.id, source_id: `source-${index}`, source: sources[index],
          title: `${issue.title}: ${sources[index]}의 보도`, summary: "기사가 강조하는 주장과 인용 근거를 살펴봅니다.",
          published_at: `2026-09-11T0${3 - index}:00:00Z`, canonical_url: `https://source-${index}.example/${id}`,
          current_version_id: `version-${id}`, analysis_status: issue.analysis_status === "PARTIAL" ? "PROCESSING" : "READY", status: "active",
          coordinate: { x: index * 10, y: 0, z: 0, sensationalism: 20, confidence: .9 },
        })), next_cursor: null });
      }
      return original(input, init);
    };
  }, { rows, sources, empty });
}

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`one issue list stays readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installFixture(page);
    await page.goto("/");
    await expect(page.locator(".ux-issue-list > li")).toHaveCount(5);
    await expect(page.getByText("5개 이슈 / 20개 기사")).toBeVisible();
    for (let index = 0; index < ids.length; index++) {
      await expect(page.locator(`.ux-issue-list a[href="/issues/${ids[index]}"]`)).toContainText(titles[index]);
    }
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    const directory = path.resolve("../output/playwright/home-newspaper-fixtures");
    await mkdir(directory, { recursive: true });
    await page.screenshot({ path: path.join(directory, `${width}-${testInfo.project.name}.png`), fullPage: true });
    if (width === 390 || width === 1440) expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  });
}

test("an empty list does not show fallback stories or fabricated counts", async ({ page }) => {
  await installFixture(page, true);
  await page.goto("/");
  await expect(page.getByText("현재 표시할 이슈가 없습니다.")).toBeVisible();
  await expect(page.locator(".ux-issue-list")).toHaveCount(0);
});
