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
  await expect(page.locator(".home-spread")).toHaveCount(new Set(items.map((item) => item.coverage_group_id)).size);
  for (const spread of await page.locator(".home-spread").all()) {
    const reading = spread.locator(".home-reading");
    const id = await reading.getAttribute("data-issue-id");
    const issue = items.find((item) => item.id === id)!;
    expect(issue).toBeTruthy();
    await expect(spread).toHaveAttribute("id", `home-issue-${issue.coverage_group_id}`);
    await expect(reading.locator(".home-article")).toHaveCount(3);
    for (const link of await reading.locator(".home-article__links a[href^='/articles/']").all()) {
      const articleId = (await link.getAttribute("href"))!.split("/").pop();
      expect(issue.article_ids).toContain(articleId);
    }
  }
});
