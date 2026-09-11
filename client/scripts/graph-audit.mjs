import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const output = path.resolve(process.argv[2]);
const base = process.env.GRAPH_BASE_URL ?? 'http://127.0.0.1:3230';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const results = [];
try {
  for (const [device, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['narrow', 320, 740]].filter(([device]) => !process.env.GRAPH_DEVICE || process.env.GRAPH_DEVICE === device)) {
    const context = await browser.newContext({ viewport: { width, height }, isMobile: device !== 'desktop', hasTouch: device !== 'desktop', reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const [name, route] of [['articles', '/visualization'], ['ideology-empty', '/share/new'], ['ideology', '/progress']]) {
      if (name === 'ideology') await page.addInitScript(() => {
        const original = window.fetch;
        window.fetch = async (...args) => {
          const response = await original(...args);
          const request = args[0];
          const url = typeof request === 'string' ? request : request instanceof Request ? request.url : request.toString();
          if (!url.includes('/me/progress') || !response.ok) return response;
          const body = await response.clone().json();
          body.ideology = { completed: true, x: -24, y: 37, z: 12 };
          return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
        };
      });
      const response = await page.goto(base + route, { waitUntil: 'networkidle' });
      assert.equal(response.status(), 200);
      const graph = page.locator('.graph-3d');
      await graph.locator('canvas').waitFor();
      await page.locator('.graph-3d[data-status="ready"]').waitFor({ timeout: 15000 });
      await graph.scrollIntoViewIfNeeded();
      await fs.writeFile(path.join(output, `${device}-${name}-labels.json`), JSON.stringify(await graph.locator('.graph-3d__labels > span').evaluateAll(labels => labels.map(label => ({ text: label.textContent, rect: label.getBoundingClientRect().toJSON(), css: label.style.cssText, display: getComputedStyle(label).display }))), null, 2));
      await page.screenshot({ path: path.join(output, `${device}-${name}-page.png`), fullPage: true });
      await graph.screenshot({ path: path.join(output, `${device}-${name}.png`) });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${device}/${name}: horizontal overflow`);
      const canvas = graph.locator('.graph-3d__canvas');
      const initial = await canvas.getAttribute('data-camera');
      await graph.getByRole('button', { name: '확대', exact: true }).click();
      assert.notEqual(await canvas.getAttribute('data-camera'), initial);
      await graph.getByRole('button', { name: '처음 시점으로' }).click();
      assert.equal(await canvas.getAttribute('data-camera'), initial);
      await graph.getByRole('button', { name: '정면', exact: true }).click();
      assert.equal(await graph.getAttribute('data-view'), 'front');
      await graph.screenshot({ path: path.join(output, `${device}-${name}-front.png`) });
      await graph.getByRole('button', { name: '위에서', exact: true }).click();
      assert.equal(await graph.getAttribute('data-view'), 'top');
      await graph.getByRole('button', { name: '처음 시점으로' }).click();
      await canvas.focus();
      await canvas.press('ArrowRight');
      assert.notEqual(await canvas.getAttribute('data-camera'), initial);
      await canvas.press('Home');
      assert.equal(await canvas.getAttribute('data-camera'), initial);
      if (name === 'articles') {
        const heading = page.locator('.space-inspector__title');
        const before = await heading.textContent();
        await page.getByRole('button', { name: '다음 자료', exact: true }).click();
        assert.notEqual(await heading.textContent(), before);
        await page.getByRole('button', { name: '이전 자료', exact: true }).click();
        assert.equal(await heading.textContent(), before);
        await page.getByRole('button', { name: /^출처 평균/ }).click();
        assert.match(await heading.textContent(), /서울데일리/);
        await page.getByRole('button', { name: /^기사 \d/ }).click();
      }
      if (name === 'ideology-empty') assert.match(await page.locator('.ideology-graph__note').textContent(), /중도를 뜻하지 않습니다/);
      if (name === 'ideology') assert.match(await canvas.getAttribute('aria-label'), /경제 -24, 사회문화 37, 국제 12/);
      results.push({ device, graph: name, status: 'passed', errors: [...errors] });
      assert.deepEqual(errors, []);
      console.log(`${device} ${name}: rendering, camera, keyboard, fit passed`);
    }
    // Coincident points must remain individually selectable with real pointer
    // events, including native touch taps. Fixtures affect this browser only.
    await page.addInitScript(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        const input = args[0];
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
        if (!url.includes('/visualization/points') || !response.ok) return response;
        const body = await response.clone().json();
        body.items = body.items.filter(item => item.entity_type === 'article').slice(0, 3).map(item => ({ ...item, x: 0, sensationalism: 30, confidence: .8 }));
        return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
      };
    });
    await page.goto(base + '/visualization', { waitUntil: 'networkidle' });
    const graph = page.locator('.graph-3d');
    await page.locator('.graph-3d[data-status="ready"]').waitFor();
    const cluster = graph.locator('.graph-3d__count');
    await cluster.waitFor();
    assert.equal(await cluster.textContent(), '3');
    await graph.scrollIntoViewIfNeeded();
    const titles = [];
    for (let index = 0; index < 3; index++) {
      titles.push(await page.locator('.space-inspector__title').textContent());
      const box = await cluster.boundingBox();
      if (device === 'desktop') await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      else await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    }
    assert.equal(new Set(titles).size, 3, 'all coincident articles can be selected');
    assert.equal(await page.locator('.space-inspector__title').textContent(), titles[0]);
    const canvas = graph.locator('.graph-3d__canvas');
    const rotation = graph.getByRole('button', { name: '마우스와 터치로 회전' });
    if (await rotation.getAttribute('aria-pressed') === 'false') await rotation.click();
    const beforeDrag = await canvas.getAttribute('data-camera');
    const box = await canvas.boundingBox();
    if (device === 'desktop') {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 55, box.y + box.height / 2 + 25, { steps: 8 });
      await page.mouse.up();
    } else {
      const cdp = await context.newCDPSession(page);
      const x = box.x + box.width / 2, y = box.y + box.height / 2;
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
      for (let step = 1; step <= 5; step++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + step * 10, y: y + step * 4 }] });
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await cdp.detach();
    }
    assert.notEqual(await canvas.getAttribute('data-camera'), beforeDrag, 'drag rotates graph');
    assert.equal(await page.locator('.space-inspector__title').textContent(), titles[0], 'drag does not select an article');
    await graph.screenshot({ path: path.join(output, `${device}-cluster-rotated.png`) });
    // Losing WebGL must leave exact values and article navigation available.
    await canvas.locator('canvas').evaluate(element => element.dispatchEvent(new Event('webglcontextlost', { cancelable: true, bubbles: true })));
    assert.equal(await graph.getAttribute('data-status'), 'unavailable');
    assert.equal(await graph.getByRole('button', { name: '확대', exact: true }).isDisabled(), true);
    assert.match(await page.locator('.article-space__readout').textContent(), /80%/);
    assert.deepEqual(errors, []);
    results.push({ device, graph: 'coincident-points', status: 'passed', selectedArticles: titles.length, drag: 'passed', fallback: 'passed' });
    console.log(`${device}: coincident point selection, drag and WebGL fallback passed`);
    await context.close();
  }
  const motionContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const motionPage = await motionContext.newPage();
  await motionPage.goto(base + '/visualization', { waitUntil: 'networkidle' });
  await motionPage.locator('.graph-3d[data-status="ready"]').waitFor();
  await motionPage.getByRole('button', { name: '정면', exact: true }).click();
  await motionPage.waitForFunction(() => document.querySelector('.graph-3d__canvas')?.getAttribute('data-camera') === '0.000,0.000,6.000,1.00');
  await motionPage.getByRole('button', { name: '처음 시점으로' }).click();
  await motionPage.waitForFunction(() => document.querySelector('.graph-3d__canvas')?.getAttribute('data-camera') === '2.600,1.900,5.400,1.00');
  await motionContext.close();
  results.push({ graph: 'camera-transition', status: 'passed', reducedMotion: false });
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  await browser.close();
}
