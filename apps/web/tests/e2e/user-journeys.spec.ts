import { test, expect } from "@playwright/test";

test("Google login facade, separate consent, questionnaire, demographics, home", async ({ page }) => {
  await page.goto("/login"); await page.getByRole("button", { name: /Google로 계속하기/ }).click();
  await expect(page).toHaveURL(/\/onboarding\/consent/);
  const consentBoxes = page.getByRole("checkbox");
  await expect(consentBoxes.first()).toBeVisible();
  for (let index = 0; index < await consentBoxes.count(); index += 1) {
    await consentBoxes.nth(index).check();
    await expect(consentBoxes.nth(index)).toBeChecked();
  }
  await page.getByRole("button", { name: "동의하고 설문 시작" }).click();
  await expect(page).toHaveURL(/\/onboarding\/questionnaire/);
  const neutralAnswers = page.getByRole("radio", { name: "3" });
  await expect(neutralAnswers.first()).toBeVisible();
  for (let index = 0; index < await neutralAnswers.count(); index += 1) await neutralAnswers.nth(index).click();
  await page.getByRole("button", { name: "응답 결과 확인" }).click();
  await expect(page).toHaveURL(/\/onboarding\/demographics/);
  await page.getByRole("button", { name: "건너뛰고 홈으로" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Political efficacy" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/데모 데이터 기준 8월 16일/)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "이슈" })).toHaveCount(0);
});

test("issue, article analysis, and passive dwell tracking", async ({ page }) => {
  await page.goto("/issues/issue-housing");
  const started = page.waitForResponse((response) => response.url().includes("/articles/article-01/read-sessions") && response.request().method() === "POST");
  await page.getByRole("link", { name: /도심 주택 공급, 속도보다/ }).first().click();
  await expect(page.getByText("Mock 전용 데이터")).toBeVisible();
  await expect(page.getByRole("heading", { name: "준비 중입니다" })).toBeVisible();
  await expect((await started).status()).toBe(200);
  await expect(page.getByRole("button", { name: "원문 읽기 세션 시작" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "원문에서 돌아왔어요" })).toHaveCount(0);
  const returned = page.waitForResponse((response) => response.url().includes("/read-sessions/") && response.url().endsWith("/return"));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide")));
  const returnResponse = await returned;
  await expect(returnResponse.status()).toBe(200);
  expect(returnResponse.request().postDataJSON()).toEqual({ client_elapsed_ms: expect.any(Number) });
});

test("vote can be submitted, revised and deleted", async ({ page }) => {
  await page.goto("/articles/article-01"); await page.getByRole("button", { name: "약간 우편향 +33" }).click(); await page.getByRole("button", { name: "투표 저장·수정" }).click(); await expect(page.getByText(/revision 2/)).toBeVisible(); await page.getByRole("button", { name: "우편향 +67" }).click(); await page.getByRole("button", { name: "투표 저장·수정" }).click(); await page.getByRole("button", { name: "내 투표 삭제" }).click(); await expect(page.getByText(/활성 투표가 삭제/)).toBeVisible();
});

test("efficacy follow-up connects to progress", async ({ page }) => { await page.goto("/efficacy"); await page.getByRole("button", { name: "후속 설문 저장" }).click(); await expect(page.getByText(/정규화 점수/)).toBeVisible(); await page.goto("/progress"); await expect(page.getByText("immutable ledger").first()).toBeVisible(); });

test("share card create, ready, public actions and revoke", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  await page.goto("/share/new");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "공유 카드 생성" }).click();
  await expect(page.getByText("생성 완료", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "즉시 폐기" }).click();
  await expect(page.getByText("폐기됨", { exact: true })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("admin is fail-closed without a server session or explicit mock role", async ({ page }) => { await page.goto("/admin/sources"); await expect(page).toHaveURL(/\/login\?returnTo=/); });

test("analyst and admin action permissions differ", async ({ context, page }) => { await context.addCookies([{ name: "mock-role", value: "analyst", domain: "127.0.0.1", path: "/" }]); await page.goto("/admin/weights"); await expect(page.getByRole("button", { name: /Publish/ }).first()).toBeDisabled(); await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]); await page.reload(); await expect(page.getByRole("button", { name: "Publish" }).first()).toBeEnabled(); });

test("weight publish sends a real mutation with reason", async ({ context, page }) => { await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]); await page.goto("/admin/weights"); await page.getByRole("button", { name: "Publish" }).first().click(); await page.getByLabel("변경 사유 (필수)").fill("7일·30일 guardrail 통과"); await page.getByRole("button", { name: "사유와 함께 실행" }).click(); await expect(page.getByText(/Publish 요청이 서버에 반영/)).toBeVisible(); });

test("mock analysis is labelled, complete and a populated topic remains usable", async ({ page }) => {
  const mockWorkerReady = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/articles/article-01/vote") && response.status() === 404,
  );
  await page.goto("/articles/article-01");
  await mockWorkerReady;
  await expect(page.getByText("Mock 전용 데이터")).toBeVisible();
  await expect(page.getByText(/실제 모델 provenance나 독자 집계를 표시하지 않습니다/)).toBeVisible();
  await expect(page.getByText("공급 시차를 줄이려면 인허가 병목 해소가 우선이다.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "점수 정정·버전 이력" })).toBeVisible();
  const analysisStatuses = await page.evaluate(async () => Promise.all([
    "/api/v1/articles/article-01/assessments",
    "/api/v1/articles/article-01/score-history",
  ].map(async (path) => (await fetch(path)).status)));
  expect(analysisStatuses).toEqual([200, 200]);
  await page.goto("/issues/issue-diplomacy");
  await expect(page.getByText("준비 중입니다")).not.toBeVisible();
  await expect(page.getByRole("link", { name: "다자 협력과 공급망 안보 사이, 새 통상 전략의 선택지", exact: true })).toBeVisible();
});

test("guest vote lookup 401 keeps the public article visible", async ({ page }) => { await page.goto("/articles/article-05"); await expect(page.getByRole("heading", { name: "주택 공급 대책에서 세입자 보호가 빠지지 않으려면" })).toBeVisible(); await expect(page.getByRole("link", { name: "로그인 후 평가하기" })).toBeVisible(); await expect(page).toHaveURL(/\/articles\/article-05$/); });
