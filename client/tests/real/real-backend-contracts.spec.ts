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
  await expect(page.locator(".ux-comparison")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const mobile = await new AxeBuilder({ page }).analyze();
  expect(mobile.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
});

test("published issue membership governs feed and retired content returns to current issues", async ({ page }) => {
  const response = await page.request.get("/api/v1/issues");
  const issues = (await response.json()).items as Array<{ id: string; kind: string; topic: string; source_count: number; article_ids: string[] }>;
  expect(issues.length).toBeGreaterThan(0);
  expect(issues.length).toBeLessThanOrEqual(5);
  for (const issue of issues) {
    expect(issue.kind).toBe("EVENT");
    expect(["정치", "경제", "사회"]).toContain(issue.topic);
    expect(issue.source_count).toBeGreaterThanOrEqual(3);
    const members = await (await page.request.get(`/api/v1/issues/${issue.id}/articles`)).json();
    expect(members.items.map((article: { id: string }) => article.id).sort()).toEqual([...issue.article_ids].sort());
  }
  const publicIds = new Set(issues.flatMap((issue) => issue.article_ids));
  const feed = await (await page.request.get("/api/v1/feed")).json();
  expect(feed.items.length).toBeGreaterThan(0);
  for (const article of feed.items) expect(publicIds.has(article.article_id)).toBe(true);

  await page.goto("/issues/00000000000000000000000000");
  await expect(page.getByRole("heading", { name: "현재 발행 목록에 없는 이슈입니다." })).toBeVisible();
  await page.getByRole("link", { name: "현재 이슈 보기", exact: true }).click();
  await expect(page).toHaveURL(/\/issues$/);
  await page.goto("/articles/00000000000000000000000000");
  await expect(page.getByRole("heading", { name: "현재 공개되지 않는 기사입니다." })).toBeVisible();
});

test("real OAuth callback restores returnTo without requiring the optional ideology test", async ({ page }) => {
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
  const firstDestination = new URL(callback.headers().location);
  expect(firstDestination.pathname).toBe("/onboarding/consent");
  expect(firstDestination.searchParams.get("returnTo")).toBe("/issues?source=oauth");

  const me = await page.request.get("/api/v1/me");
  expect(me.status()).toBe(200);
  expect((await me.json()).role).toBe("MEMBER");

  const replay = await page.request.get(
    `/api/v1/auth/mock/callback?state=${encodeURIComponent(state!)}&code=mock-real-e2e-replay`,
    { maxRedirects: 0 },
  );
  expect(replay.status()).toBe(400);

  await page.goto(firstDestination.toString());
  const boxes = page.getByRole("checkbox");
  await expect(boxes.first()).toBeVisible();
  for (const box of await boxes.all()) await box.check();
  await page.getByRole("button", { name: "동의하고 계속하기" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3100/issues?source=oauth");
  const afterConsent = await (await page.request.get("/api/v1/me")).json();
  expect(afterConsent.consent_complete).toBe(true);
  expect(afterConsent.onboarding_complete).toBe(false);
  const again = await page.request.get(
    `/api/v1/auth/mock/start?redirect_uri=${encodeURIComponent(callbackUri)}&returnTo=${encodeURIComponent("/issues?source=oauth")}`,
    { maxRedirects: 0 },
  );
  const nextState = new URL(again.headers().location).searchParams.get("state")!;
  const returning = await page.request.get(
    `/api/v1/auth/mock/callback?state=${encodeURIComponent(nextState)}&code=mock-real-e2e`,
    { maxRedirects: 0 },
  );
  expect(returning.status()).toBe(302);
  expect(returning.headers().location).toBe("http://127.0.0.1:3100/issues?source=oauth");
});

test("a questionnaire saved in a separate tab refreshes the original consumption card", async ({ page, context }) => {
  await context.setExtraHTTPHeaders(memberHeaders);
  const consents = await (await page.request.get("/api/v1/consents", { headers: memberHeaders })).json();
  for (const consent of consents) {
    await page.request.post("/api/v1/me/consents", { headers: memberHeaders, data: { consent_version_id: consent.id, granted: true } });
  }
  const versions = await (await page.request.get("/api/v1/questionnaires?kind=onboarding")).json();
  const version = versions.find((item: { version: string }) => item.version === "2.0-beta");
  expect(version).toBeTruthy();
  const answers = Object.fromEntries(version.schema_json.questions.map((question: { id: string }) => [question.id, 3]));
  const saved = await page.request.post("/api/v1/me/questionnaire-responses", { headers: memberHeaders, data: { questionnaire_version_id: version.id, answers } });
  expect(saved.ok()).toBeTruthy();
  await page.goto("/share/new");
  await expect(page.getByRole("img", { name: "좌우 성향과 권위 / 자유: 좌우 0, 세로 0", exact: true })).toBeVisible();
  const questionnaire = await context.newPage();
  await questionnaire.goto(await page.getByRole("link", { name: "정치 이념 검사 다시 하기" }).getAttribute("href") ?? "/onboarding/questionnaire");
  for (let step = 0; step < 3; step++) {
    const groups = questionnaire.getByRole("radiogroup");
    await expect(groups).toHaveCount(10);
    for (let index = 0; index < 10; index++) {
      await groups.nth(index).getByRole("radio", { name: step === 0 && index === 0 ? "5" : "3", exact: true }).check();
    }
    await questionnaire.getByRole("button", { name: step < 2 ? "다음 문항" : "저장하고 결과 확인", exact: true }).click();
  }
  await expect(questionnaire).toHaveURL(/\/share\/new$/);
  // Do not reload or synthesize focus: the real cross-tab notification must update it.
  await expect(page.getByRole("img", { name: "좌우 성향과 권위 / 자유: 좌우 -10, 세로 0", exact: true })).toBeVisible();
  const marker = await page.evaluate(() => localStorage.getItem("effica:profile-updated"));
  expect(marker).toMatch(/^\d+$/);
  await questionnaire.close();
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
    onboardingVersion.keys.map((key) => [key, 3]),
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
