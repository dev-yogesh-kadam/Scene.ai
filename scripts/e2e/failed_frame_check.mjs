// A job that fails stays on the canvas, saying why. Against server.py (no render server
// there, so every render fails). Start server.py, then: node scripts/e2e/failed_frame_check.mjs
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
await page.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
await page.evaluate(async () => fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Ada', email: 'f' + Date.now() + '@example.com', password: 'correct horse battery staple' }) }));
const project = await page.evaluate(async () => (await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'testing' }) })).json());
await page.evaluate((id) => localStorage.setItem('scene.project', id), project.id);
const post = () => page.evaluate(async (id) => {
  const form = new FormData();
  form.append('settings', JSON.stringify({ workflow: 'video/h3_master', name: 'Dancing girl', values: { '100:value': 'a girl is dancing inside a bar' }, options: { mode: 'fast', quality: 'low' }, project_id: id, seed_mode: 'random' }));
  return (await fetch('/api/jobs', { method: 'POST', body: form })).json();
}, project.id);
await post();
await page.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await page.waitForSelector('.frame.failed', { timeout: 60000 }).catch(() => {});
const shown = await page.$eval('.frame.failed', (f) => f.innerText.replace(/\s+/g, ' ')).catch(() => '');
check('a failed job stays on the canvas, saying why', /Didn't work/.test(shown) && /render server/i.test(shown) && /credits came back/.test(shown), shown.slice(0, 160));
await page.screenshot({ path: `${OUT}/failed_1_canvas.png` });

check('a failed frame has no buttons', await page.evaluate(() => !document.querySelector('.frame.failed button')));
check('no page errors', errors.length === 0, errors.slice(0, 3).join(' || '));
console.log(report.join('\n'));
await browser.close();
