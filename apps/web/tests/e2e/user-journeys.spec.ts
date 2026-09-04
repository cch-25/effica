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
  const primaryNav = page.getByRole("navigation", { name: /빠른 이동|모바일 주요 메뉴/ });
  await expect(primaryNav.getByRole("link", { name: /^(오늘의 )?이슈$/ })).toBeVisible();
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

test("today's issues keeps top stories above broad topic sections without horizontal overflow", async ({ page }) => {
  await page.goto("/issues");
  await expect(page.getByRole("heading", { name: "주요 이슈 TOP 10" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "대주제별 이슈" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "경제" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "국제" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "산업" })).toBeVisible();
  await expect(page.locator(".issue-rank-list > li")).toHaveCount(1);
  await expect(page.locator(".issue-rank-list")).not.toContainText("AI 기본법 시행 준비");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
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

test("admin is fail-closed and accepts the dedicated credentials", async ({ page }) => {
  await page.goto("/admin/sources");
  await expect(page).toHaveURL(/\/admin\?returnTo=/);
  await expect(page.getByRole("heading", { name: "관리자 로그인" })).toBeVisible();

  await page.getByLabel("아이디").fill("dev");
  await page.getByLabel("비밀번호").fill("wrong");
  await page.getByRole("button", { name: "접속하기" }).click();
  await expect(page.getByText("아이디 또는 비밀번호가 올바르지 않습니다.", { exact: true })).toBeVisible();

  await page.getByLabel("비밀번호").fill("1234");
  await page.getByRole("button", { name: "접속하기" }).click();
  await expect(page).toHaveURL(/\/admin\/sources$/);
  await expect(page.getByRole("heading", { name: /출처/ })).toBeVisible();
});

test("analyst and admin action permissions differ", async ({ context, page }) => { await context.addCookies([{ name: "mock-role", value: "analyst", domain: "127.0.0.1", path: "/" }]); await page.goto("/admin/weights"); await expect(page.getByRole("button", { name: /Publish/ }).first()).toBeDisabled(); await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]); await page.reload(); await expect(page.getByRole("button", { name: "Publish" }).first()).toBeEnabled(); });

test("weight publish sends a real mutation with reason", async ({ context, page }) => { await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]); await page.goto("/admin/weights"); await page.getByRole("button", { name: "Publish" }).first().click(); await page.getByLabel("변경 사유 (필수)").fill("7일·30일 guardrail 통과"); await page.getByRole("button", { name: "사유와 함께 실행" }).click(); await expect(page.getByText(/Publish 요청이 서버에 반영/)).toBeVisible(); });

test("admin can start and stop the persisted LLM runtime", async ({ context, page }) => {
  await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]);
  await page.goto("/admin/runtime");
  const control = page.getByRole("switch", { name: "LLM 사용" });
  await expect(control).not.toBeChecked();
  await control.click();
  await page.getByLabel("변경 사유 (필수)").fill("운영자가 직접 실행");
  await page.getByRole("button", { name: "실행 시작" }).click();
  await expect(control).toBeChecked();
  await expect(page.getByText("RUNNING", { exact: true })).toBeVisible();
  await control.click();
  await page.getByLabel("변경 사유 (필수)").fill("운영자가 직접 중지");
  await page.getByRole("button", { name: "전체 중지" }).click();
  await expect(control).not.toBeChecked();
  await expect(page.getByText("STOPPED", { exact: true })).toBeVisible();
});

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

test("page transitions and browser history always start at the top", async ({ page }) => {
  const viewport = page.viewportSize();
  await page.setViewportSize({ width: viewport?.width ?? 1280, height: 320 });
  const scrollAwayFromTop = async () => expect.poll(() => page.evaluate(() => {
    let spacer = document.querySelector<HTMLElement>("[data-test-scroll-spacer]");
    if (!spacer) {
      spacer = document.createElement("div");
      spacer.dataset.testScrollSpacer = "";
      spacer.style.height = "1200px";
      spacer.setAttribute("aria-hidden", "true");
      document.body.append(spacer);
    }
    const root = document.documentElement;
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, root.scrollHeight);
    root.style.scrollBehavior = "";
    return window.scrollY;
  })).toBeGreaterThan(0);
  await page.goto("/issues");
  await expect.poll(() => page.evaluate(() => window.history.scrollRestoration)).toBe("manual");
  await scrollAwayFromTop();

  await page.getByRole("link", { name: "홈", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

  await scrollAwayFromTop();
  await page.goBack();
  await expect(page).toHaveURL(/\/issues$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});
