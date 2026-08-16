import { test, expect } from "@playwright/test";

test("mock login, separate consent, questionnaire, demographics, home", async ({ page }) => {
  await page.goto("/login"); await page.getByRole("link", { name: /로컬 mock/ }).click();
  const consentBoxes = page.getByRole("checkbox");
  for (let index = 0; index < await consentBoxes.count(); index += 1) {
    await consentBoxes.nth(index).check();
    await expect(consentBoxes.nth(index)).toBeChecked();
  }
  await page.getByRole("button", { name: "동의하고 설문 시작" }).click();
  await expect(page).toHaveURL(/\/onboarding\/questionnaire/);
  for (const name of ["economy", "culture", "foreign"]) await page.locator(`input[name="${name}"][value="3"]`).check();
  await page.getByRole("button", { name: "응답 결과 확인" }).click();
  await expect(page).toHaveURL(/\/onboarding\/demographics/);
  await page.getByRole("button", { name: "건너뛰고 홈으로" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: /뉴스의 결론보다/ })).toBeVisible();
});

test("issue, article analysis, outbound return and credit", async ({ page }) => {
  await page.goto("/issues/issue-housing"); await page.getByRole("link", { name: /도심 주택 공급, 속도보다/ }).first().click();
  await expect(page.getByText("MODEL_SCHEMA_REJECTED")).toBeVisible(); await page.getByRole("button", { name: "원문에서 돌아왔어요" }).click();
  await expect(page.getByText(/활동 크레딧 \+12/)).toBeVisible();
});

test("vote can be submitted, revised and deleted", async ({ page }) => {
  await page.goto("/articles/article-01"); const number = page.getByLabel("경제 숫자 입력"); await number.fill("24"); await page.getByRole("button", { name: "투표 저장·수정" }).click(); await expect(page.getByText(/revision 2/)).toBeVisible(); await number.fill("18"); await page.getByRole("button", { name: "투표 저장·수정" }).click(); await page.getByRole("button", { name: "내 투표 삭제" }).click(); await expect(page.getByText(/활성 투표가 삭제/)).toBeVisible();
});

test("efficacy follow-up connects to progress", async ({ page }) => { await page.goto("/efficacy"); await page.getByRole("button", { name: "후속 설문 저장" }).click(); await expect(page.getByText(/정규화 점수/)).toBeVisible(); await page.goto("/progress"); await expect(page.getByText("immutable ledger")).toBeVisible(); });

test("share card create, ready, public actions and revoke", async ({ page }) => { await page.goto("/share/new"); await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "공유 카드 생성" }).click(); await expect(page.getByText("ready", { exact: true })).toBeVisible(); await page.getByRole("button", { name: "즉시 폐기" }).click(); await expect(page.getByText("revoked", { exact: true })).toBeVisible(); });

test("analyst and admin action permissions differ", async ({ context, page }) => { await context.addCookies([{ name: "mock-role", value: "analyst", domain: "127.0.0.1", path: "/" }]); await page.goto("/admin/weights"); await expect(page.getByRole("button", { name: /Publish/ }).first()).toBeDisabled(); await context.addCookies([{ name: "mock-role", value: "admin", domain: "127.0.0.1", path: "/" }]); await page.reload(); await expect(page.getByRole("button", { name: "Publish" }).first()).toBeEnabled(); });

test("weight publish preserves reason across version conflict review", async ({ page }) => { await page.goto("/admin/weights"); await page.getByRole("button", { name: "Publish" }).first().click(); await page.getByLabel("변경 사유 (필수)").fill("7일·30일 guardrail 통과"); await page.getByRole("button", { name: "사유와 함께 실행" }).click(); await expect(page.getByText("다른 변경이 먼저 반영됐습니다")).toBeVisible(); await page.getByRole("button", { name: "최신 데이터 불러와 재검토" }).click(); await expect(page.getByLabel("변경 사유 (필수)")).toHaveValue("7일·30일 guardrail 통과"); await page.getByRole("button", { name: "사유와 함께 실행" }).click(); await expect(page.getByText(/Publish 요청이 접수/)).toBeVisible(); });

test("partial LLM failure and preparing issue remain usable", async ({ page }) => { await page.goto("/articles/article-01"); await expect(page.getByText("model-c · 부분 실패")).toBeVisible(); await expect(page.getByText("model-a · 성공")).toBeVisible(); await page.goto("/issues/issue-diplomacy"); await expect(page.getByText("준비 중입니다")).toBeVisible(); });
