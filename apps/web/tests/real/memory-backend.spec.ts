import { expect, test } from "@playwright/test";

const debugMember = { "X-Debug-Role": "MEMBER", "X-CSRF-Token": "local-csrf" };

test("same-origin web reads and vote authorization flows use the memory backend", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Fixture policy report 1" })).toBeVisible({ timeout: 15_000 });

  const issuesResponse = await page.request.get("/api/v1/issues");
  expect(issuesResponse.ok()).toBeTruthy();
  const issues = await issuesResponse.json() as { items: Array<{ id: string; title: string }> };
  await page.goto(`/issues/${issues.items[0].id}`);
  await expect(page.getByRole("heading", { name: issues.items[0].title })).toBeVisible();

  const feedResponse = await page.request.get("/api/v1/feed");
  const feed = await feedResponse.json() as { items: Array<{ article_id: string; title: string }> };
  const article = feed.items[0];
  await page.goto(`/articles/${article.article_id}`);
  await expect(page.getByRole("heading", { name: article.title })).toBeVisible();

  const vote = { x: -20, y: 10, z: 5, sensationalism: 25 };
  const unauthorized = await page.request.put(`/api/v1/articles/${article.article_id}/vote`, {
    data: vote,
    headers: { "X-CSRF-Token": "local-csrf" },
  });
  expect(unauthorized.status()).toBe(401);
  expect((await unauthorized.json()).error.code).toBe("AUTH_REQUIRED");

  const success = await page.request.put(`/api/v1/articles/${article.article_id}/vote`, { data: vote, headers: debugMember });
  expect(success.ok()).toBeTruthy();

  const consentsResponse = await page.request.get("/api/v1/consents", { headers: { "X-Debug-Role": "MEMBER" } });
  const consents = await consentsResponse.json() as Array<{ id: string; sensitive: boolean }>;
  const politicalConsent = consents.find((consent) => consent.sensitive);
  expect(politicalConsent).toBeTruthy();
  await page.request.post("/api/v1/me/consents", {
    data: { consent_version_id: politicalConsent!.id, granted: false },
    headers: debugMember,
  });
  const consentRequired = await page.request.put(`/api/v1/articles/${article.article_id}/vote`, { data: vote, headers: debugMember });
  expect(consentRequired.status()).toBe(403);
  expect((await consentRequired.json()).error.code).toBe("CONSENT_REQUIRED");
});
