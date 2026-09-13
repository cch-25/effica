import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

test("guestbook supports anonymous posting, limits, reloads and mobile navigation", async ({ page }) => {
  await mkdir("../output/feedback", { recursive: true });
  await page.goto("/feedback");
  const nav = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
  await expect(nav.getByRole("link", { name: "피드백", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "피드백", exact: true })).toBeVisible();
  await expect(page.getByText("첫 이야기를 기다리고 있어요.")).toBeVisible();
  await page.screenshot({ path: "../output/feedback/desktop-empty.png", fullPage: true });
  const name = page.getByRole("textbox", { name: "이름" });
  const content = page.getByRole("textbox", { name: "피드백 내용" });
  const submit = page.getByRole("button", { name: "피드백 남기기" });
  await expect(submit).toBeDisabled();
  await name.fill("에피카 독자");
  await content.fill("가".repeat(201));
  await expect(submit).toBeDisabled();
  await expect(page.getByText("200자 이내로 줄여 주세요.")).toBeVisible();
  await content.fill("가".repeat(200));
  await expect(submit).toBeEnabled();
  await content.fill("같은 뉴스를 여러 관점에서 읽을 수 있어 좋았어요.\n다음에는 관심 있는 이슈를 모아보는 기능도 있으면 좋겠습니다.");
  await submit.click();
  await expect(page.getByRole("status")).toContainText("피드백을 남겼어요");
  await expect(page.getByRole("list").getByText("에피카 독자", { exact: true })).toBeVisible();
  await expect(content).toHaveValue("");
  await page.reload();
  await expect(page.getByRole("list").getByText("에피카 독자", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../output/feedback/desktop.png", fullPage: true });
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = page.getByRole("navigation", { name: "모바일 주요 메뉴" });
  await expect(mobile.getByRole("link", { name: "피드백" })).toBeVisible();
  await expect(mobile.getByRole("link", { name: "내 활동" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/feedback/mobile.png", fullPage: true });
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.setViewportSize({ width: 320, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/feedback/mobile-small.png", fullPage: true });
});

test("failed posting keeps the draft and recovers without duplicate entries", async ({ page }) => {
  await page.goto("/feedback");
  await page.getByRole("textbox", { name: "이름" }).fill("다시 온 독자");
  await page.getByRole("textbox", { name: "피드백 내용" }).fill("읽기 편한 화면이 마음에 들어요.");
  let lostResponse = false;
  await page.route("**/api/v1/feedback", async (route) => {
    if (route.request().method() === "POST" && !lostResponse) {
      lostResponse = true;
      await route.fetch();
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "피드백 남기기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "작성한 내용은 그대로" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "피드백 내용" })).toHaveValue("읽기 편한 화면이 마음에 들어요.");
  await page.getByRole("button", { name: "피드백 남기기" }).click();
  await expect(page.getByRole("status")).toContainText("피드백을 남겼어요");
  await page.reload();
  await expect(page.getByRole("list").getByText("다시 온 독자", { exact: true })).toHaveCount(1);
});
