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
  await expect(page.getByRole("heading", { name: "POLITICAL EFFICACY" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "이슈" })).toHaveCount(0);
});

test("issue, article analysis, outbound return and credit", async ({ page }) => {
  await page.goto("/issues/issue-housing"); await page.getByRole("link", { name: /도심 주택 공급, 속도보다/ }).first().click();
  await expect(page.getByText("MODEL_SCHEMA_REJECTED")).toBeVisible(); await page.getByRole("button", { name: "원문 읽기 세션 시작" }).click(); await page.getByRole("button", { name: "원문에서 돌아왔어요" }).click();
  await expect(page.getByText(/활동 크레딧 \+12/)).toBeVisible();
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

test("partial LLM failure and populated issue remain usable", async ({ page }) => { await page.goto("/articles/article-01"); await expect(page.getByText("model-c · 부분 실패")).toBeVisible(); await expect(page.getByText("model-a · 성공")).toBeVisible(); await page.goto("/issues/issue-diplomacy"); await expect(page.getByText("준비 중입니다")).not.toBeVisible(); await expect(page.getByRole("link", { name: "다자 협력과 공급망 안보 사이, 새 통상 전략의 선택지", exact: true })).toBeVisible(); });
