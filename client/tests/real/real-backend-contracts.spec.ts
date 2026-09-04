import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const memberHeaders = { "X-Debug-Role": "MEMBER", "X-CSRF-Token": "local-csrf" };

test("public issue comparison is accessible and does not overflow on mobile", async ({ page }) => {
  const issues = await page.request.get("/api/v1/issues");
  expect(issues.status()).toBe(200);
  const issueId = ((await issues.json()) as { items: Array<{ id: string }> }).items[0].id;

  await page.goto(`/issues/${issueId}`);
  await expect(page.getByRole("heading", { name: "공통으로 확인된 사실" })).toBeVisible();
  const desktop = await new AxeBuilder({ page }).analyze();
  expect(desktop.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("region", { name: "선택한 기사 비교" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const mobile = await new AxeBuilder({ page }).analyze();
  expect(mobile.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
});

test("real OAuth challenge callback creates a session and restores returnTo", async ({ page }) => {
  const callbackUri = "http://127.0.0.1:3100/api/v1/auth/mock/callback";
  const start = await page.request.get(
    `/api/v1/auth/mock/start?redirect_uri=${encodeURIComponent(callbackUri)}&returnTo=${encodeURIComponent("/issues?source=oauth")}`,
    { maxRedirects: 0 },
  );
  expect(start.status()).toBe(302);
  const providerLocation = new URL(start.headers().location);
  const state = providerLocation.searchParams.get("state");
  expect(state).toBeTruthy();

  const callback = await page.request.get(
    `/api/v1/auth/mock/callback?state=${encodeURIComponent(state!)}&code=mock-real-e2e`,
    { maxRedirects: 0 },
  );
  expect(callback.status()).toBe(302);
  expect(callback.headers().location).toBe("http://127.0.0.1:3100/issues?source=oauth");

  const me = await page.request.get("/api/v1/me");
  expect(me.status()).toBe(200);
  expect((await me.json()).role).toBe("MEMBER");

  const replay = await page.request.get(
    `/api/v1/auth/mock/callback?state=${encodeURIComponent(state!)}&code=mock-real-e2e-replay`,
    { maxRedirects: 0 },
  );
  expect(replay.status()).toBe(400);
});

test("real API persists onboarding, vote, read-session, and privacy mutations", async ({ page }) => {
  const me = await page.request.get("/api/v1/me", { headers: memberHeaders });
  expect(me.status()).toBe(200);
  expect((await me.json()).role).toBe("MEMBER");

  const consentsResponse = await page.request.get("/api/v1/consents", { headers: memberHeaders });
  expect(consentsResponse.status()).toBe(200);
  const consents = await consentsResponse.json() as Array<{ id: string }>;
  expect(consents.length).toBeGreaterThan(0);
  for (const consent of consents) {
    const submission = await page.request.post("/api/v1/me/consents", {
      data: { consent_version_id: consent.id, granted: true },
      headers: memberHeaders,
    });
    expect(submission.status()).toBe(200);
    expect((await submission.json()).granted).toBe(true);
  }

  const onboardingVersionsResponse = await page.request.get(
    "/api/v1/questionnaires?kind=onboarding",
    { headers: memberHeaders },
  );
  expect(onboardingVersionsResponse.status()).toBe(200);
  const onboardingVersions = await onboardingVersionsResponse.json() as Array<{
    id: string;
    keys: string[];
  }>;
  expect(onboardingVersions.length).toBeGreaterThan(0);
  const onboardingVersion = onboardingVersions[0];
  const onboardingAnswers = Object.fromEntries(
    onboardingVersion.keys.map((key, index) => [key, [-20, 10, 5][index] ?? 0]),
  );
  const onboarding = await page.request.post("/api/v1/me/questionnaire-responses", {
    data: {
      questionnaire_version_id: onboardingVersion.id,
      answers: onboardingAnswers,
    },
    headers: memberHeaders,
  });
  expect(onboarding.status()).toBe(200);
  expect((await onboarding.json()).kind).toBe("SELF_REPORTED");

  const demographics = await page.request.patch("/api/v1/me/demographics", {
    data: { age_band: "30-39", gender_response: "PREFER_NOT_TO_SAY" },
    headers: memberHeaders,
  });
  expect(demographics.status()).toBe(200);

  const efficacyVersionsResponse = await page.request.get(
    "/api/v1/questionnaires?kind=efficacy",
    { headers: memberHeaders },
  );
  expect(efficacyVersionsResponse.status()).toBe(200);
  const efficacyVersions = await efficacyVersionsResponse.json() as Array<{
    id: string;
    keys: string[];
  }>;
  expect(efficacyVersions.length).toBeGreaterThan(0);
  const efficacyVersion = efficacyVersions[0];
  const efficacyAnswers = Object.fromEntries(
    efficacyVersion.keys.map((key, index) => [key, [68, 76][index] ?? 72]),
  );
  const efficacy = await page.request.post("/api/v1/me/efficacy-responses", {
    data: { questionnaire_version_id: efficacyVersion.id, answers: efficacyAnswers },
    headers: memberHeaders,
  });
  expect(efficacy.status()).toBe(200);
  expect((await efficacy.json()).normalized_score).toBe(72);

  const feed = await page.request.get("/api/v1/feed");
  expect(feed.status()).toBe(200);
  const feedBody = await feed.json() as { items: Array<{ article_id: string }> };
  expect(feedBody.items.length).toBeGreaterThan(0);
  const articleId = feedBody.items[0].article_id;

  const vote = await page.request.put(`/api/v1/articles/${articleId}/vote`, {
    data: { x: -20, y: 10, z: 5, sensationalism: 25 },
    headers: memberHeaders,
  });
  expect(vote.status()).toBe(200);
  const deleteVote = await page.request.delete(`/api/v1/articles/${articleId}/vote`, {
    headers: memberHeaders,
  });
  expect(deleteVote.status()).toBe(204);

  const readSession = await page.request.post(`/api/v1/articles/${articleId}/read-sessions`, {
    data: { return_path: `/articles/${articleId}` },
    headers: memberHeaders,
  });
  expect(readSession.status()).toBe(200);
  const sessionBody = await readSession.json() as { read_session_id: string; redirect_url: string };
  const redirectPath = new URL(sessionBody.redirect_url).pathname;
  const redirect = await page.request.get(redirectPath, { headers: memberHeaders, maxRedirects: 0 });
  expect(redirect.status()).toBe(302);

  const returned = await page.request.post(
    `/api/v1/read-sessions/${sessionBody.read_session_id}/return`,
    { data: { client_elapsed_ms: 0 }, headers: memberHeaders },
  );
  expect(returned.status()).toBe(200);
  expect((await returned.json()).credit_delta).toBe(0);

  const exportJob = await page.request.post("/api/v1/me/export", { headers: memberHeaders });
  expect(exportJob.status()).toBe(202);
  const exportBody = await exportJob.json() as { job_id: string; status: string };
  expect(exportBody.job_id).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
  expect(exportBody.status).toBe("PENDING");

  const share = await page.request.post("/api/v1/share-cards", {
    data: {
      template: "perspective",
      display_name: "real-e2e",
      political_data_publication_confirmed: true,
    },
    headers: memberHeaders,
  });
  expect(share.status()).toBe(202);
  const shareJob = await share.json() as { job_id: string; share_card_id: string };
  expect(shareJob.job_id).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
  expect(shareJob.share_card_id).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
  const card = await page.request.get(`/api/v1/share-cards/${shareJob.share_card_id}`, {
    headers: memberHeaders,
  });
  expect(card.status()).toBe(200);
  expect((await card.json()).snapshot.publication_consent.confirmation_version).toBe(
    "share-card-publication-v1",
  );
  const revokeCard = await page.request.delete(`/api/v1/share-cards/${shareJob.share_card_id}`, {
    headers: memberHeaders,
  });
  expect(revokeCard.status()).toBe(204);

  const invalidDelete = await page.request.delete("/api/v1/me", {
    data: { confirmation: "delete" },
    headers: memberHeaders,
  });
  expect(invalidDelete.status()).toBe(422);
  const deleteAccount = await page.request.delete("/api/v1/me", {
    data: { confirmation: "DELETE MY ACCOUNT" },
    headers: memberHeaders,
  });
  expect(deleteAccount.status()).toBe(202);
  expect((await deleteAccount.json()).job_id).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
  expect((await page.request.get("/api/v1/me")).status()).toBe(401);
});

test("real admin mutation enqueues an observable job", async ({ page }) => {
  const adminHeaders = {
    "X-Debug-Role": "ADMIN",
    "X-CSRF-Token": "local-csrf",
    "Idempotency-Key": "real-admin-crawl-0001",
  };
  const sources = await page.request.get("/api/v1/admin/sources", { headers: adminHeaders });
  expect(sources.status()).toBe(200);
  const sourceId = (await sources.json()).items[0].id as string;
  const crawl = await page.request.post(`/api/v1/admin/sources/${sourceId}/crawl`, {
    headers: adminHeaders,
    data: { reason: "real backend crawl contract" },
  });
  expect(crawl.status()).toBe(202);
  const accepted = await crawl.json() as { job_id: string; status: string };
  expect(accepted.status).toBe("PENDING");
  const jobs = await page.request.get("/api/v1/admin/jobs?job_type=crawl", {
    headers: adminHeaders,
  });
  expect(jobs.status()).toBe(200);
  expect((await jobs.json()).items).toEqual(
    expect.arrayContaining([expect.objectContaining({ id: accepted.job_id, job_type: "crawl" })]),
  );
});

test("real browser requests reach the API without starting mock handlers", async ({ page }) => {
  const intercepted: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/mock")) intercepted.push(request.url());
  });

  await page.goto("/");
  const response = await page.evaluate(async () => {
    const result = await fetch("/api/v1/issues");
    return { status: result.status, body: await result.json() };
  });
  expect(response.status).toBe(200);
  expect(response.body).toHaveProperty("items");
  expect(intercepted).toEqual([]);
  const favicon = await page.request.get("/favicon.ico");
  expect(favicon.status()).toBe(200);
  expect(favicon.headers()["content-type"]).toContain("image/x-icon");
});
