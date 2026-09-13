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

async function installFixture(page: Page, empty = false, distinct = false) {
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
  }, { rows: distinct ? rows.map((row) => ({ ...row, coverage_group_id: row.id, coverage_group_title: row.title })) : rows, sources, empty });
}

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`readers can choose a distinct event and a related angle at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installFixture(page);
    await page.goto("/");
    const menu = page.getByRole("navigation", { name: "이 지면의 이슈" });
    const lead = page.locator(".home-spread--lead");
    await expect(menu.getByRole("link")).toHaveCount(2);
    await expect(menu.locator('[data-content-type="issue"]')).toHaveText(["이슈 A", "이슈 B"]);
    const labelsAligned = await page.locator(".home-index [data-content-type-line], .home-related [data-content-type-line]").evaluateAll((lines) => lines.every((line) => {
      const badge = line.querySelector<HTMLElement>('[data-content-type="issue"]')?.getBoundingClientRect();
      const copy = line.querySelector<HTMLElement>("[data-content-type-copy]")?.getBoundingClientRect();
      return Boolean(badge && copy && Math.abs(badge.top - copy.top) <= 2 && copy.left > badge.right);
    }));
    expect(labelsAligned).toBe(true);
    await expect(page.locator(".home-spread")).toHaveCount(2);
    await expect(lead.locator(".home-reading")).toHaveAttribute("data-issue-id", "kim");
    await expect(lead.locator(".home-selected-context")).toContainText("이슈 A");
    await expect(lead.locator(".home-article-list > li")).toHaveCount(3);
    await expect(lead.locator(".home-article").first().locator('[data-content-type="article"]')).toHaveText("기사");
    await expect(lead.locator(".home-coverage")).toContainText("발행 시각순");
    await expect(lead.locator(".home-article").first()).toContainText("12:00 발행");
    await expect(lead.getByRole("link", { name: "이 쟁점의 보도 비교하기" })).toHaveAttribute("href", "/issues/kim");
    await expect(page.locator(".front-chart, .edition-articles, .headline-band")).toHaveCount(0);
    await lead.getByRole("button", { name: "이 쟁점의 기사 4개 모두 보기" }).click();
    await expect(lead.locator(".home-article-list > li")).toHaveCount(4);
    await lead.getByRole("button", { name: "언론사별 기사 3개만 보기" }).click();
    await expect(lead.locator(".home-article-list > li")).toHaveCount(3);

    await page.locator(".home-angle-picker summary").click();
    await page.getByRole("button", { name: new RegExp(titles[1]) }).click();
    await expect(lead.locator("h1")).toHaveText(titles[1]);
    await expect(lead.locator(".home-selected-context")).toContainText("이슈 A");
    await expect(lead.locator(".home-reading")).toHaveAttribute("data-issue-id", "yong");
    await expect(lead.locator(".home-article").first()).toContainText(titles[1]);
    await expect(lead.locator(".home-article-list")).not.toContainText(titles[0]);
    await expect(page.locator(".home-angle-picker summary")).toBeFocused();

    await menu.getByRole("link", { name: new RegExp(titles[3]) }).click();
    const other = page.locator("#home-issue-hormuz");
    await expect(other).toBeInViewport();
    await expect(other.locator("h2")).toHaveText(titles[3]);
    await expect(other.locator(".home-selected-context")).toContainText("이슈 B");
    await expect(other.locator(".home-reading")).toHaveAttribute("data-issue-id", "hormuz");
    await expect(other.locator(".home-angle-picker")).toHaveCount(0);
    await expect(other.locator(".home-article-list > li")).toHaveCount(3);
    await expect(other.locator(".home-article-list")).not.toContainText("용혜인");
    await expect(other.locator(".home-compare-link")).toHaveAttribute("href", "/issues/hormuz");
    await expect(other.locator(".home-article__links").first().getByRole("link", { name: "분석 근거 읽기" })).toHaveAttribute("href", "/articles/hormuz-0");

    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    const directory = path.resolve("../output/playwright/home-newspaper-fixtures");
    await mkdir(directory, { recursive: true });
    await page.screenshot({ path: path.join(directory, `${width}-${testInfo.project.name}.png`), fullPage: true });
    if (width === 390 || width === 1440) expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  });
}

test("a selected unready angle is not presented as ready to compare", async ({ page }) => {
  await installFixture(page);
  await page.goto("/");
  await expect(page.locator(".home-angle-picker")).toBeVisible();
  await page.locator(".home-angle-picker summary").click();
  await page.getByRole("button", { name: new RegExp(titles[2]) }).click();
  await expect(page.getByRole("link", { name: "이 쟁점의 기사와 준비 상태 보기" })).toHaveAttribute("href", "/issues/witness");
  await expect(page.locator(".home-spread--lead .home-article").first()).toContainText("분석을 준비하고 있습니다.");
  await expect(page.locator(".home-spread--lead").getByRole("link", { name: "이 쟁점의 보도 비교하기" })).toHaveCount(0);
});

test("an empty edition does not show fallback stories or fabricated counts", async ({ page }) => {
  await installFixture(page, true);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "비교할 이슈를 준비하고 있습니다." })).toBeVisible();
  await expect(page.locator(".home-spreads")).toHaveCount(0);
});

test("five issue groups form newspaper columns and reflow on mobile", async ({ page }) => {
  await installFixture(page, false, true);
  await page.goto("/");
  await expect(page.locator(".home-spread")).toHaveCount(5);
  await expect(page.locator('.home-spread .home-selected-context [data-content-type="issue"]')).toHaveText(["이슈 A", "이슈 B", "이슈 C", "이슈 D", "이슈 E"]);
  const directory = path.resolve("../output/playwright/home-newspaper-fixtures");
  await mkdir(directory, { recursive: true });
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => document.fonts.ready);
    const positions = await page.locator(".home-secondary__columns > .home-spread").evaluateAll(elements => elements.map(element => {
      const { x, y, width } = element.getBoundingClientRect();
      return { x, y, width };
    }));
    if (width > 760) {
      expect(positions[0].y).toBe(positions[1].y);
      expect(positions[1].x).toBeGreaterThanOrEqual(positions[0].x + positions[0].width);
    } else {
      expect(positions[0].x).toBe(positions[1].x);
      expect(positions[1].y).toBeGreaterThan(positions[0].y);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: path.join(directory, `five-groups-${width}.png`), fullPage: true });
  }
});
