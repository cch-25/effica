import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const base = process.argv[2] ?? 'http://127.0.0.1:3220';
const output = path.resolve('../output/playwright/article-map-live');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const results = [];
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 960 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    const articleLink = page.locator('main a[href^="/articles/"]').first();
    await articleLink.waitFor({ timeout: 30000 });
    const articlePath = await articleLink.getAttribute('href');
    const articleId = articlePath.split('/').at(-1);
    const articleResponse = await page.request.get(`${base}/api/v1/articles/${articleId}`);
    assert.equal(articleResponse.status(), 200);
    const article = await articleResponse.json();
    const issueResponse = await page.request.get(`${base}/api/v1/issues/${article.issue_id}/articles`);
    assert.equal(issueResponse.status(), 200);
    const issueArticles = (await issueResponse.json()).items;
    await articleLink.click();
    const map = page.locator('#perspective-map');
    await map.locator('.graph-3d[data-status="ready"]').waitFor({ timeout: 30000 });
    const choices = map.getByRole('group', { name: '같은 이슈에서 비교할 기사' }).getByRole('button');
    const expected = issueArticles.filter(item => item.analysis_status === 'READY');
    await page.waitForFunction(count => document.querySelectorAll('.article-perspective-map__articles > button').length === count, expected.length);
    const graphMarkers = map.locator('.graph-3d__marker');
    assert.equal(await graphMarkers.count(), expected.length);
    const identities = await choices.evaluateAll(buttons => buttons.map(button => ({
      number: button.querySelector('.article-map-marker').textContent,
      color: button.querySelector('.article-map-marker').style.getPropertyValue('--article-marker-color'),
    })));
    const plotted = await graphMarkers.evaluateAll(markers => markers.map(marker => ({ number: marker.textContent, color: marker.style.getPropertyValue('--article-marker-color') })));
    assert.deepEqual(plotted, identities);
    assert.ok(await map.getByRole('heading', { name: '지도 속 기사' }).isVisible());
    assert.ok(await map.getByText('빈 원과 점선: 좌표 보조 표시').isVisible());
    if (expected.length > 1) {
      const labels = await choices.allTextContents();
      for (const item of expected) assert.ok(labels.some(label => label.includes(item.title)), `missing related article ${item.id}`);
      assert.equal(await choices.first().getAttribute('aria-pressed'), 'true');
      await choices.nth(1).click();
      assert.equal(await graphMarkers.filter({ hasText: /^2$/ }).getAttribute('data-selected'), 'true');
      assert.equal(await graphMarkers.filter({ hasText: /^2$/ }).evaluate(marker => marker.style.getPropertyValue('--article-marker-color')), identities[1].color);
      assert.ok(await map.getByRole('link', { name: '이 기사 분석 보기' }).isVisible());
      await map.getByRole('button', { name: '읽고 있는 기사로 돌아가기' }).click();
    }
    assert.equal(await page.locator('nav a[href="/visualization"]').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(() => document.fonts.ready);
    await map.screenshot({ path: path.join(output, `map-${width}.png`) });
    await page.screenshot({ path: path.join(output, `article-${width}.png`), fullPage: true });
    assert.deepEqual(errors, []);
    results.push({ width, articleId, issueId: article.issue_id, articleCount: expected.length, status: 'passed' });
    console.log(`${width}px: same-issue scope, current selection, links, layout and runtime passed`);
    await page.close();
  }
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ base, results }, null, 2));
  await browser.close();
}
