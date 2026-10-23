// Prices by resolution and quality, and a failed frame's details, in headless Chrome against server.py (studio :8099,
// console :8098). Start server.py fresh (the first account is the admin), then: node scripts/e2e/pricing_check.mjs
import { createRequire } from 'module';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const STUDIO = 'http://127.0.0.1:8099';
const CONSOLE = 'http://127.0.0.1:8098';
const OUT = path.join(os.tmpdir(), 'scene-e2e');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const email = 'p' + Date.now() + '@example.com';
const password = 'correct horse battery staple';
await page.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
await page.evaluate(async (body) => fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { name: 'Ada', email, password });

// The Home bar: each resolution and quality says its price.
await page.goto(STUDIO + '/home', { waitUntil: 'networkidle2' });
await page.waitForFunction(() => [...document.querySelectorAll('select[data-priced] option')].some((o) => / cr$/.test(o.textContent)), { timeout: 15000 }).catch(() => {});
const options = await page.$$eval('select[data-priced] option', (os) => os.map((o) => o.textContent));
check('the choices that change the price say what they cost', options.some((o) => /^1080 · \d+ cr$/.test(o)) && options.some((o) => / · \d+ cr$/.test(o)), options.slice(0, 8).join(' | '));
const price = await page.evaluate(() => document.querySelector('.composer .cost, [class*=cost]') && document.querySelector('[class*=cost]').textContent);
await page.select('select[data-priced="resolution"]', '480');
await wait(800);
const cheaper = await page.evaluate(() => document.querySelector('[class*=cost]').textContent);
check('the price changes with the resolution', price !== cheaper, `${price} -> ${cheaper}`);

// A failed frame opens to its details.
const project = await page.evaluate(async () => (await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'testing' }) })).json());
await page.evaluate((id) => localStorage.setItem('scene.project', id), project.id);
await page.evaluate(async (id) => {
  const form = new FormData();
  form.append('settings', JSON.stringify({ workflow: 'video/h3_master', name: 'Dancing girl', values: { '100:value': 'a girl is dancing inside a bar' }, options: { mode: 'fast', quality: 'high' }, project_id: id, seed_mode: 'random' }));
  return fetch('/api/jobs', { method: 'POST', body: form });
}, project.id);
await page.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await page.waitForSelector('.frame.failed', { timeout: 60000 }).catch(() => {});
await page.click('.frame.failed');
await page.waitForSelector('dialog.failed-dialog[open]', { timeout: 5000 }).catch(() => {});
const details = await page.$eval('dialog.failed-dialog', (d) => d.innerText.replace(/\s+/g, ' ')).catch(() => '');
check('a failed frame opens to its details', /Didn't work/.test(details) && /Prompt/.test(details) && /dancing/.test(details) && /given back/.test(details), details.slice(0, 200));
check('an admin also sees what the render server said', /What the render server said/.test(details));
await page.screenshot({ path: `${OUT}/pricing_1_failed_details.png` });
await page.keyboard.press('Escape');

// The console's Pricing: the factors, with what they come to.
await page.goto(CONSOLE + '/pricing', { waitUntil: 'networkidle2' });
await page.type('input[type=email]', email);
await page.type('input[type=password]', password);
await Promise.all([page.waitForSelector('.sidebar .nav'), page.click('button[type=submit]')]);
await page.waitForFunction(() => /Quality and size/.test(document.querySelector('main').innerText), { timeout: 15000 }).catch(() => {});
const card = await page.evaluate(() => [...document.querySelectorAll('main .card')].find((c) => /Quality and size/.test(c.innerText)).innerText.replace(/\s+/g, ' '));
check('Pricing shows the quality and size factors and what they come to', /1080p/.test(card) && /Draft/.test(card) && /200 cr/.test(card), card.slice(0, 160));
await page.screenshot({ path: `${OUT}/pricing_2_console.png`, fullPage: true });

check('no page errors', errors.length === 0, errors.slice(0, 3).join(' || '));
console.log(report.join('\n'));
await browser.close();
