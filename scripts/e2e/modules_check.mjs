// The browser check of modules: All projects lists projects only, a project opens on its page (kit and modules), Add
// module makes one and opens its canvas, the canvas names it "Project › Module" and leads back to the project's page.
// Start server.py first, then: node scripts/e2e/modules_check.mjs
import { createRequire } from 'module';
import fs from 'fs';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const BASE = 'http://127.0.0.1:8099';
const OUT = path.join(os.tmpdir(), 'scene-e2e');
fs.mkdirSync(OUT, { recursive: true });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

let cookie = '';
async function call(where, { method = 'GET', json } = {}) {
  const headers = { cookie };
  if (json) headers['Content-Type'] = 'application/json';
  const r = await fetch(BASE + where, { method, headers, body: json ? JSON.stringify(json) : undefined });
  const set = r.headers.get('set-cookie');
  if (set) cookie = set.split(';')[0];
  const text = await r.text();
  if (!r.ok) throw new Error(`${where} ${r.status} ${text}`);
  try { return JSON.parse(text); } catch { return text; }
}

await call('/api/auth/register', { method: 'POST', json: { name: 'Tester', email: 'modules' + Date.now() + '@example.com', password: 'correct horse battery staple' } });
const project = await call('/api/projects', { method: 'POST', json: { name: 'Pocket motions' } });
await call('/api/projects', { method: 'POST', json: { name: 'Episode 1', parent_id: project.id } });

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('dialog', (d) => d.accept());
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });

await page.goto(BASE + '/projects', { waitUntil: 'networkidle2' });
await wait(500);
const cards = await page.$$eval('.pcard-info b', (b) => b.map((x) => x.textContent));
check('All projects lists the project, not its module', cards.includes('Pocket motions') && !cards.includes('Episode 1'), cards.join(', '));
const sub = await page.$$eval('.pcard-info span', (s) => s.map((x) => x.textContent).join(' | '));
check('its card counts the modules', sub.includes('2 modules'), sub);
await page.click('.pcard');
await wait(900);
check('a project opens on its page', page.url().includes('/project?id=' + project.id), page.url());
const modules = await page.$$eval('.proj-modules .pcard-info b', (b) => b.map((x) => x.textContent));
check('the page shows the main canvas and the module', modules.join(',') === 'Main canvas,Episode 1', modules.join(','));
check('the page shows the project kit', !!(await page.$('.proj-section h2')), '');
await page.screenshot({ path: `${OUT}/modules_page.png`, fullPage: true });

// Add module: the dialog, then its canvas
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Add module')).click());
await wait(400);
const field = await page.$('dialog input');
check('Add module opens the dialog with a name', !!field && (await field.evaluate((i) => i.value)) === 'Module 3', field ? await field.evaluate((i) => i.value) : 'no dialog');
await page.evaluate(() => { document.querySelector('dialog input').value = 'Episode 2'; });
await page.click('dialog button[type=submit]');
await wait(1500);
check('a new module opens on its canvas', page.url().endsWith('/canvas'), page.url());
const picker = await page.$eval('.canvas-project', (b) => b.textContent).catch(() => '');
check('the canvas names it with its project', picker === 'Pocket motions › Episode 2', picker);
await page.screenshot({ path: `${OUT}/modules_canvas.png` });
await page.click('.canvas-project');
await wait(900);
check('the name leads back to the project page', page.url().includes('/project?id=' + project.id), page.url());
const after = await page.$$eval('.proj-modules .pcard-info b', (b) => b.map((x) => x.textContent));
check('the new module is listed', after.includes('Episode 2'), after.join(','));

// Library → Projects: projects only
await page.goto(BASE + '/library', { waitUntil: 'networkidle2' });
await page.evaluate(() => [...document.querySelectorAll('.seg button')].find((b) => b.textContent === 'Projects').click());
await wait(600);
const folders = await page.$$eval('.project b', (b) => b.map((x) => x.textContent));
check('Library → Projects shows projects only', folders.join(',') === 'Pocket motions', folders.join(','));
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
