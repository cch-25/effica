import { expect, test } from "@playwright/test";

for (const width of [1280, 375]) {
  test(`ID login retains a populated member session at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login?returnTo=%2Fprogress");
    await expect(page.getByRole("link", { name: "아이디 로그인", exact: true })).toBeVisible();
    await page.screenshot({ path: `../output/login-options-${width}.png`, fullPage: true });
    await page.getByRole("link", { name: "아이디 로그인", exact: true }).click();
    await expect(page.getByRole("heading", { name: "아이디 로그인", exact: true })).toBeVisible();
    await page.getByLabel("아이디", { exact: true }).fill("user");
    await page.getByLabel("비밀번호", { exact: true }).fill("wrong");
    await page.getByRole("button", { name: "접속하기" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "아이디 또는 비밀번호" })).toBeVisible();
    await page.getByLabel("비밀번호", { exact: true }).fill("1234");
    await page.screenshot({ path: `../output/login-id-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "접속하기" }).click();
    await expect(page).toHaveURL(/\/progress$/);
    await expect(page.getByRole("heading", { name: "읽고 비교한 기록", exact: true })).toBeVisible();
    await expect.poll(async () => (await (await page.request.get("/api/v1/me")).json()).role).toBe("MEMBER");
    const progress = await (await page.request.get("/api/v1/me/progress")).json();
    expect(progress.ideology.x).toBe(65);
    expect(progress.credit_total).toBeGreaterThanOrEqual(576);
    expect(progress.compared_issue_count).toBeGreaterThan(0);
    expect((await page.request.get("/api/v1/admin/audit")).status()).toBe(403);
    await page.screenshot({ path: `../output/demo-progress-${width}.png`, fullPage: true });
    await page.reload();
    await expect(page.getByRole("heading", { name: "읽고 비교한 기록", exact: true })).toBeVisible();
    await page.goto("/efficacy");
    await expect(page.getByRole("heading", { name: "정치 이슈 이해 자신감 변화", exact: true })).toBeVisible();
    await expect(page.getByText("84", { exact: true })).toBeVisible();
    await page.screenshot({ path: `../output/demo-efficacy-${width}.png`, fullPage: true });
    await page.goto("/share/new");
    await expect(page.getByRole("heading", { name: "공유 카드 만들기", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "공유 카드 만들기", exact: true })).toBeEnabled();
    await page.screenshot({ path: `../output/demo-share-${width}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "csrf")!.value;
    expect((await page.request.post("/api/v1/auth/logout", { headers: { "X-CSRF-Token": csrf } })).status()).toBe(204);
    expect((await page.request.get("/api/v1/me")).status()).toBe(401);
  });
}

test("restored admin credentials reach the admin UI", async ({ page }) => {
  await page.goto("/admin");
  await page.getByLabel("아이디", { exact: true }).fill("dev");
  await page.getByLabel("비밀번호", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "접속하기" }).click();
  await expect(page).toHaveURL(/\/admin\/runtime$/);
  await expect.poll(async () => (await (await page.request.get("/api/v1/me")).json()).role).toBe("ADMIN");
  await page.screenshot({ path: "../output/admin-login-restored.png", fullPage: true });
});
