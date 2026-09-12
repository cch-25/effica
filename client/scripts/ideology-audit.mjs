import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const output = path.resolve(process.argv[2]);
const base = process.env.GRAPH_BASE_URL ?? 'http://127.0.0.1:3240';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const results = [];
try {
  for (const [device, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['narrow', 320, 740]].filter(([device]) => !process.env.IDEOLOGY_DEVICE || process.env.IDEOLOGY_DEVICE === device)) {
    const context = await browser.newContext({ viewport: { width, height }, isMobile: device !== 'desktop', hasTouch: device !== 'desktop', reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        const input = args[0];
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
        if (!url.includes('/me/progress') || !response.ok) return response;
        const body = await response.clone().json();
        body.ideology = { completed: true, x: -24, y: 37, z: 12 };
        return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
      };
    });
    await page.goto(base + '/progress', { waitUntil: 'networkidle' });
    const ideology = page.locator('.ideology-graph');
    const graph = ideology.locator('.graph-3d');
    await page.locator('.graph-3d[data-status="ready"]').waitFor();
    await ideology.scrollIntoViewIfNeeded();
    assert.match(await ideology.locator('.ideology-graph__result').textContent(), /자유주의 좌파 성향/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const poles = graph.locator('.graph-3d__pole');
    for (const label of ['좌파', '우파', '권위주의', '자유주의', '주권주의', '국제주의']) {
      assert.equal(await poles.filter({ hasText: new RegExp(`^${label}$`) }).isVisible(), true, `${device}: ${label} pole visible`);
    }
    await ideology.screenshot({ path: path.join(output, `${device}-ideology.png`) });
    await graph.getByRole('button', { name: '정면', exact: true }).click();
    const position = async label => poles.filter({ hasText: new RegExp(`^${label}$`) }).boundingBox();
    const left = await position('좌파'), right = await position('우파');
    const authority = await position('권위주의'), liberty = await position('자유주의');
    assert.ok(left && right && left.x < right.x, `${device}: left/right positions`);
    assert.ok(authority && liberty && authority.y < liberty.y, `${device}: authority above liberty`);
    assert.equal(await poles.filter({ hasText: '국제주의' }).isVisible(), false, 'depth hidden in front view');
    await ideology.screenshot({ path: path.join(output, `${device}-ideology-front.png`) });
    await ideology.getByText('이념 지도 읽는 법', { exact: true }).click();
    assert.equal(await ideology.getByText(/국제관은 좌우 판정에 합산하지 않습니다/).isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await graph.locator('canvas').evaluate(element => element.dispatchEvent(new Event('webglcontextlost', { cancelable: true, bubbles: true })));
    await graph.locator('.graph-3d__fallback').waitFor();
    assert.equal(await graph.getAttribute('data-status'), 'unavailable');
    assert.equal(await ideology.locator('.ideology-graph__result').isVisible(), true, 'interpretation survives WebGL loss');
    assert.match(await ideology.locator('.ideology-coordinates').textContent(), /좌파.*-24.*자유주의.*\+37.*국제주의.*\+12/);
    assert.deepEqual(errors, []);
    results.push({ device, poles: 'passed', frontAxes: 'passed', overflow: 'passed', fallback: 'passed' });
    console.log(`${device}: ideology labels, axes, layout and fallback passed`);
    await context.close();
  }
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
} finally {
  await browser.close();
}
