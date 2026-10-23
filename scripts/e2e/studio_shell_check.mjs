// The studio's top bar, project page, analytics and Guide in headless Chrome, against server.py (the studio on :8099).
// Start server.py, then: node scripts/e2e/studio_shell_check.mjs
import { createRequire } from 'module';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const STUDIO = 'http://127.0.0.1:8099';
const OUT = path.join(os.tmpdir(), 'scene-e2e');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error' && !/401|403|404|Failed to load resource/.test(m.text())) errors.push(m.text()); });
const json = (method, url, body) => page.evaluate(async (a) => (await fetch(a.url, { method: a.method, headers: { 'Content-Type': 'application/json' }, body: a.body && JSON.stringify(a.body) })).json(), { method, url, body });

await page.goto(STUDIO + '/signup', { waitUntil: 'networkidle2' });
await json('POST', '/api/auth/register', { name: 'Yogesh', email: 'y' + Date.now() + '@example.com', password: 'correct horse battery staple' });
const film = await json('POST', '/api/projects', { name: 'Ai Influencer' });
await json('POST', '/api/projects', { name: 'Episode 1', parent_id: film.id });

await page.goto(STUDIO + '/project?id=' + film.id, { waitUntil: 'networkidle2' });
await page.waitForSelector('.proj-analytics', { timeout: 15000 }).catch(() => {});
await wait(500);
const shell = await page.evaluate(() => ({
  sidebar: !!document.querySelector('.sidebar') && getComputedStyle(document.querySelector('.sidebar')).display !== 'none',
  crumbs: document.querySelector('.crumbs').innerText.replace(/\s+/g, ' '),
  guide: !!document.querySelector('.topbar-right .top-btn'), who: (document.querySelector('.who-name') || {}).textContent,
  references: /Project (References|NeuralCore)/.test(document.querySelector('main').innerText),
  library: [...document.querySelectorAll('main a')].some((a) => a.getAttribute('href') === '/library'),
  modules: document.querySelectorAll('.proj-modules .pcard').length }));
check('no sidebar; the breadcrumb says where you are', !shell.sidebar && shell.crumbs === 'Projects › Ai Influencer', shell.crumbs);
check('the top right has the Guide and your name', shell.guide && shell.who === 'Yogesh', String(shell.who));
check('the project page has no references or library links', !shell.references && !shell.library);
check('the project page shows its modules', shell.modules === 2, String(shell.modules));
await page.screenshot({ path: `${OUT}/studio_1_project.png` });

await page.click('.app-menu-button');
await wait(300);
const menu = await page.$eval('.app-menu:not(.hidden)', (m) => m.innerText.replace(/\s+/g, ' ')).catch(() => '');
check('the logo opens the pages in a dropdown', /All projects/.test(menu) && /Library/.test(menu) && /Guide/.test(menu), menu.slice(0, 80));
await page.keyboard.press('Escape');
await page.click('.who-chip');
await wait(300);
const account = await page.$eval('.account-menu:not(.hidden)', (m) => m.innerText.replace(/\s+/g, ' ')).catch(() => '');
check('your name opens the account dropdown', /Settings/.test(account) && /Sign out/.test(account), account.slice(0, 80));
await page.keyboard.press('Escape');

await page.click('.proj-analytics');
await page.waitForSelector('.an-tiles', { timeout: 15000 }).catch(() => {});
await wait(400);
const an = await page.evaluate(() => ({ crumbs: document.querySelector('.crumbs').innerText.replace(/\s+/g, ' '), tiles: document.querySelectorAll('.an-tile').length,
  rows: document.querySelectorAll('.an-module').length, back: (document.querySelector('.an-back') || {}).getAttribute && document.querySelector('.an-back').getAttribute('href') }));
check('analytics: tiles, daily spend and every module', an.tiles === 3 && an.rows === 2 && /Analytics$/.test(an.crumbs), JSON.stringify(an));
await page.$$eval('.an-tools .seg button', (bs) => bs.find((b) => b.textContent === 'Last 30 days').click());
await wait(800);
check('a period can be chosen', await page.evaluate(() => /–/.test(document.querySelector('.an-showing').innerText)));
await page.click('.an-row');
await wait(200);
check('a module opens to what it spent on', await page.evaluate(() => !document.querySelector('.an-detail').classList.contains('hidden')));
await page.screenshot({ path: `${OUT}/studio_2_analytics.png` });

await page.click('.topbar-right .top-btn');
await page.waitForSelector('.guide-section', { timeout: 10000 }).catch(() => {});
const guide = await page.evaluate(() => ({ sections: document.querySelectorAll('.guide-section').length, path: location.pathname, crumbs: document.querySelector('.crumbs').innerText }));
check('the Guide opens from the top bar', guide.path === '/guide' && guide.sections >= 8 && /Guide/.test(guide.crumbs), JSON.stringify(guide));
await page.screenshot({ path: `${OUT}/studio_3_guide.png` });

await page.evaluate((id) => localStorage.setItem('scene.project', id), film.id);
await page.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await wait(1200);
const canvas = await page.evaluate(() => ({ guide: !!document.querySelector('.topbar-right') && getComputedStyle(document.querySelector('.topbar-right')).display !== 'none',
  logo: !!document.querySelector('.app-menu-button') }));
check('the canvas has no Guide, only the logo menu', !canvas.guide && canvas.logo, JSON.stringify(canvas));
await page.screenshot({ path: `${OUT}/studio_4_canvas.png` });

await page.setViewport({ width: 390, height: 844 });
await page.goto(STUDIO + '/project?id=' + film.id, { waitUntil: 'networkidle2' });
await wait(600);
check('no sideways scrolling on a phone', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
await page.screenshot({ path: `${OUT}/studio_5_phone.png` });

check('no page errors', errors.length === 0, errors.slice(0, 5).join(' || '));
console.log(report.join('\n'));
await browser.close();
