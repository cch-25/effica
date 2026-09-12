import { chromium } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const output = process.argv[2];
const base = process.argv[3] ?? 'http://localhost:3000';
const widths = (process.argv[4] ?? '1440,1024,768,390,320').split(',').map(Number);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const width of widths) {
    const context = await browser.newContext({ viewport: { width, height: 1050 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base, { waitUntil: 'domcontentloaded' });
    await page.locator('.home-spread--lead h1').waitFor({ timeout: 30000 });
    await page.locator('.home-spread--lead .home-article').first().waitFor({ timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    await page.locator('.home-issue-photo img').evaluateAll(images => Promise.all(images.map(img => img.complete ? Promise.resolve() : new Promise(resolve => {
      img.addEventListener('load', resolve, { once: true });
      img.addEventListener('error', resolve, { once: true });
      setTimeout(resolve, 5000);
    }))));
    const metrics = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      spreads: [...document.querySelectorAll('.home-spread')].map(section => ({
        title: section.querySelector('h1,h2')?.textContent,
        issueId: section.querySelector('.home-reading')?.getAttribute('data-issue-id'),
        articles: section.querySelectorAll('.home-article').length,
        articleIds: [...section.querySelectorAll('.home-article h3 a,.home-article h4 a')].map(a => a.getAttribute('href')?.split('/').at(-1)),
        columns: getComputedStyle(section.querySelector('.home-article-list')).gridTemplateColumns,
      })),
      index: [...document.querySelectorAll('.home-index li')].map(item => item.textContent),
      photos: [...document.querySelectorAll('.home-issue-photo img')].map(img => ({ loaded: img.complete && img.naturalWidth > 0, source: img.getAttribute('src') })),
    }));
    await page.screenshot({ path: path.join(output, `home-${width}.png`), fullPage: true });
    await page.screenshot({ path: path.join(output, `first-screen-${width}.png`) });
    const violations = (await new AxeBuilder({ page }).include('main').analyze()).violations.map(({ id, impact, description }) => ({ id, impact, description }));
    const switching = [];
    const picker = page.locator('.home-spread--lead .home-angle-picker');
    if (await picker.count()) {
      const count = await picker.locator('button').count();
      for (let index = 0; index < count; index++) {
        await picker.locator('summary').click();
        await picker.getByRole('button').nth(index).click();
        const lead = page.locator('.home-spread--lead');
        const id = await lead.locator('.home-reading').getAttribute('data-issue-id');
        await page.waitForFunction(id => {
          const root = document.querySelector('.home-spread--lead .home-reading');
          return root?.getAttribute('data-issue-id') === id && !root?.textContent.includes('기사를 불러오는 중');
        }, id);
        const response = await page.request.get(new URL(`/api/v1/issues/${encodeURIComponent(id)}/articles`, base).href);
        const data = await response.json();
        const members = new Set((data.items ?? []).map(article => article.id));
        const displayed = await lead.locator('.home-article h3 a').evaluateAll(links => links.map(link => link.getAttribute('href').split('/').at(-1)));
        switching.push({ id, displayed: displayed.length, membershipMatches: displayed.length > 0 && displayed.every(id => members.has(id)) });
      }
    }
    const result = { width, base, ...metrics, switching, violations, errors };
    results.push(result);
    await writeFile(path.join(output, 'audit.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(result));
    await context.close();
  }
} finally { await browser.close(); }
if (results.some(result => result.overflow || result.errors.length || result.violations.length || result.switching.some(item => !item.membershipMatches))) process.exitCode = 1;
