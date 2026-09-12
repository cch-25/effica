import { expect, test } from "@playwright/test";
import type { components } from "../../src/lib/api/generated/schema";

test("homepage reading sections follow live backend groups and exact article memberships", async ({ page }) => {
  const response = await page.request.get("/api/v1/issues?limit=250");
  expect(response.ok()).toBe(true);
  const { items } = await response.json() as components["schemas"]["IssuePage"];
  expect(items.length).toBeGreaterThan(0);
  for (const issue of items) {
    expect(issue.coverage_group_id).toBeTruthy();
    expect(issue.coverage_group_title).toBeTruthy();
    const detail = await (await page.request.get(`/api/v1/issues/${issue.id}`)).json();
    expect(detail.coverage_group_id).toBe(issue.coverage_group_id);
    expect(detail.article_ids).toEqual(issue.article_ids);
  }
  await page.goto("/");
  await expect(page.locator(".ux-issue-list > li")).toHaveCount(items.length);
  for (const issue of items) {
    await expect(page.locator(`.ux-issue-list a[href="/issues/${issue.id}"]`)).toContainText(issue.title);
  }
  const total = new Set(items.flatMap((issue) => issue.article_ids)).size;
  await expect(page.getByText(`${items.length}개 이슈 / ${total}개 기사`)).toBeVisible();
});
