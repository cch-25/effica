import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const output = path.resolve(process.argv[2] ?? '../output/playwright/newspaper');
const base = process.env.NEWSPAPER_BASE_URL ?? 'http://127.0.0.1:3210';
await fs.mkdir(output, { recursive: true });
const routes = ['/', '/issues', '/issues/issue-housing', '/issues/issue-ai', '/articles/article-01', '/articles/article-03', '/visualization', '/progress', '/login', '/onboarding/consent', '/onboarding/questionnaire', '/onboarding/demographics', '/efficacy', '/settings/privacy', '/share/new', '/share/card-ready', '/share/card-queued', '/share/card-rendering', '/share/card-failed', '/share/card-revoked', '/share/p/mock-public-token', '/missing-page', '/admin', ...['runtime', 'sources', 'crawls', 'issues', 'models', 'weights', 'autopilot', 'jobs', 'audit', 'metrics/efficacy'].map(s => '/admin/' + s)];
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const recheck = process.env.NEWSPAPER_RECHECK?.split(",");
const resume = process.env.NEWSPAPER_RESUME === "1";
const results = recheck || resume ? JSON.parse(await fs.readFile(path.join(output, 'audit.json'), 'utf8')) : [];
try {
  for (const [device, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }], ['narrow', { width: 320, height: 740 }], ['tablet', { width: 768, height: 1024 }]]) {
    const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
    const page = await context.newPage();
    let errors = [];
    page.on('pageerror', e => errors.push(e.message));
    for (const route of routes.filter(route => (!recheck || recheck.includes(route)) && (!resume || !results.some(record => record.device === device && record.route === route)))) {
      errors = [];
      await context.clearCookies();
      if (route.startsWith('/admin/')) await context.addCookies([{ name: 'mock-role', value: 'admin', url: base }]);
      const response = await page.goto(base + route, { waitUntil: 'networkidle' });
      const fontLoad = await page.evaluate(async () => {
        await document.fonts.ready;
        const family = getComputedStyle(document.body).fontFamily.split(",")[0];
        try {
          const regular = await document.fonts.load(`400 16px ${family}`, "에피카 가나다 ABC");
          const bold = await document.fonts.load(`700 16px ${family}`, "에피카 가나다 ABC");
          const editorialFamily = getComputedStyle(document.documentElement).getPropertyValue("--font-newspaper").split(",")[0].trim();
          const editorial = await Promise.all([400, 700].map(weight => document.fonts.load(`${weight} 16px ${editorialFamily}`, "에피카 가나다")));
          const editorialReady = editorial.every(faces => faces.length > 0 && faces.every(face => face.status === "loaded"));
          return { ready: editorialReady && document.fonts.check(`400 16px ${family}`) && document.fonts.check(`700 16px ${family}`) && [...regular, ...bold].every(face => face.status === "loaded"), family };
        } catch (error) { return { ready: false, family, error: String(error) }; }
      });
      if (route === '/visualization') await page.locator('.article-space .graph-3d[data-status="ready"]').waitFor({ timeout: 10000 }).catch(() => {});
      const name = route === '/' ? 'home' : route.slice(1).replaceAll('/', '-');
      await page.screenshot({ path: path.join(output, `${device}-${name}.png`), fullPage: true });
      const metrics = await page.evaluate(() => {
        const visible = el => el.getBoundingClientRect().width && el.getBoundingClientRect().height;
        const overflow = [...document.querySelectorAll('body *')].filter(el => visible(el) && el.getBoundingClientRect().right > innerWidth + 1 && getComputedStyle(el).position !== 'fixed').slice(0, 12).map(el => ({ tag: el.tagName, class: el.className, text: el.textContent?.slice(0, 60) }));
        const color = value => {
          const m = value.match(/^rgba?\((\d+), (\d+), (\d+)/);
          return m && Math.max(...m.slice(1).map(Number)) - Math.min(...m.slice(1).map(Number)) > 14;
        };
        const colored = [...document.querySelectorAll('main *')].filter(el => visible(el) && [getComputedStyle(el).color, getComputedStyle(el).backgroundColor].some(color)).slice(0, 8).map(el => ({ tag: el.tagName, class: el.className }));
        return { overflow: document.documentElement.scrollWidth > innerWidth, offenders: overflow, colored, whiteBackground: getComputedStyle(document.body).backgroundColor === "rgb(255, 255, 255)" && getComputedStyle(document.documentElement).backgroundColor === "rgb(255, 255, 255)", font: getComputedStyle(document.body).fontFamily, headings: [...document.querySelectorAll('h1')].map(el => el.textContent), width: innerWidth };
      });
      const record = { device, route, status: response.status(), errors: [...errors], fontLoad, ...metrics };
      const existing = results.findIndex(r => r.device === device && r.route === route);
      if (existing < 0) results.push(record); else results[existing] = record;
      console.log(device, route, response.status(), metrics.overflow ? 'OVERFLOW' : 'fit', metrics.colored.length ? 'COLOR' : 'ink', errors.length ? 'ERROR' : 'ok');
      await fs.writeFile(path.join(output, 'audit.json'), JSON.stringify(results, null, 2));
    }
    await context.close();
  }
} finally { await browser.close(); }
// Semantic blue and red are expected; font loading, overflow and runtime errors remain failures.
if (results.some(r => !r.fontLoad?.ready || !r.whiteBackground || r.overflow || r.errors.length || (r.status !== 200 && r.route !== '/missing-page'))) process.exitCode = 1;
