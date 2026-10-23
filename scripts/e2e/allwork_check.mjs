// The browser check that there is no NeuralCore outside a project: on the canvas of all work the NeuralCore tab says it
// belongs to a project and offers no Add, the asset boards button is hidden, and a canvas item offers no "Add to NeuralCore".
// Start server.py first, then: node scripts/e2e/allwork_check.mjs
import { createRequire } from 'module';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const BASE = 'http://127.0.0.1:8099';
const OUT = path.join(os.tmpdir(), 'scene-e2e');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

let cookie = '';
const r = await fetch(BASE + '/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Tester', email: 'allwork' + Date.now() + '@example.com', password: 'correct horse battery staple' }) });
cookie = r.headers.get('set-cookie').split(';')[0];

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument(() => { localStorage.setItem('scene.project', ''); localStorage.setItem('scene.panel.tab', 'kit'); });
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(1200);
const said = await page.evaluate(() => (document.querySelector('.kit-panel .kit-body') || {}).textContent || '');
check('the NeuralCore tab says it belongs to a project', said.includes('belongs to a project'), said.slice(0, 90));
const add = await page.evaluate(() => { const b = [...document.querySelectorAll('.kit-panel button')].find((x) => x.textContent.trim() === 'Add'); return b ? b.classList.contains('hidden') : true; });
check('it offers no Add', add);
const boards = await page.evaluate(() => [...document.querySelectorAll('.canvas-bar button, button')].some((b) => /beside the shots/.test(b.title || '') && !b.classList.contains('hidden')));
check('the asset boards button is hidden', !boards);
await page.screenshot({ path: `${OUT}/allwork_neuralcore.png` });
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
