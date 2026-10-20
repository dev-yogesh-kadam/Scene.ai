// The browser check of a skill's review turn: a reply with a ```csv table of library links (drawn as pictures) and a
// question with buttons. Start server.py first (fresh), then: node scripts/e2e/review_check.mjs
import { createRequire } from 'module';
import fs from 'fs';
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
async function call(where, { method = 'GET', json, form } = {}) {
  const headers = { cookie };
  let body;
  if (json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  if (form) body = form;
  const r = await fetch(BASE + where, { method, headers, body });
  const set = r.headers.get('set-cookie');
  if (set) cookie = set.split(';')[0];
  const text = await r.text();
  if (!r.ok) throw new Error(`${where} ${r.status} ${text}`);
  try { return JSON.parse(text); } catch { return text; }
}

await call('/api/auth/register', { method: 'POST', json: { name: 'Tester', email: 'tester' + Date.now() + '@example.com', password: 'correct horse battery staple' } });
const project = await call('/api/projects', { method: 'POST', json: { name: 'Review' } });
async function upload(file, type) {
  const form = new FormData();
  form.append('file', new Blob([fs.readFileSync(file)], { type }), file.split(/[\\/]/).pop());
  form.append('project_id', String(project.id));
  return call('/api/library/upload', { method: 'POST', form });
}
const clip = await upload(`${OUT}/e2e_files/clip.mp4`, 'video/mp4');
const dog = await upload(`${OUT}/e2e_files/dog.png`, 'image/png');

const now = Date.now();
const reply = [
  'Here are the anchors.',
  '',
  '```csv',
  'time,scene,image',
  `00:00.000 - 00:41.320,"The suite at night: Emma at the cabinet, Robert at the window, she pours, he will not turn",/api/library/${dog.id}/file`,
  `00:41.320 - 01:10.000,"Emma crosses to the table and sets the plate down",/api/library/${clip.id}/file`,
  '00:41.320 - 01:10.000,"An outside link stays text",https://example.com/x.png',
  '```',
].join('\n');
const runs = [{ instruction: 'pocket motion seedance v2', parts: [{ text: 'pocket motion seedance v2' }], reply, chips: {},
  question: { text: 'Review the anchors — any corrections?', options: ['I have corrections in the anchors', 'Looks good, next step'] },
  budget: { credits: null, spent: 0 }, activity: [], seconds: 3, total: 0, state: 'answered', ui: {}, steps: [], at: now }];
await call('/api/boards/agent', { method: 'PUT', json: { project: project.id, data: { tabs: [{ id: 't1', name: 'Agent 1', created: now, updated: now }], open: ['t1'], active: 't1' } } });
await call('/api/boards/agent-t1', { method: 'PUT', json: { project: project.id, data: { runs } } });

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error' && !/404|Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
const sent = [];
page.on('request', (r) => { if (r.url().endsWith('/api/agent/plan')) sent.push(JSON.parse(r.postData() || '{}')); });
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument((pid) => {
  localStorage.setItem('scene.project', String(pid));
  localStorage.setItem('scene.panel.tab', 'agent');
  localStorage.setItem('scene.panel.width', '620');
}, project.id);
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(2500);
const panel = await page.$('.side-panel');
if (!panel) { await page.screenshot({ path: `${OUT}/review_debug.png` }); console.log('NO PANEL', errors.join(' | '), (await page.evaluate(() => document.body.innerText)).slice(0, 300)); process.exit(1); }
await panel.screenshot({ path: `${OUT}/review_1_table.png` });

const cells = await page.$$eval('.md-table tbody tr', (rows) => rows.map((r) => [...r.children].map((c) => (c.querySelector('img') ? 'IMG' : c.textContent))));
check('the csv is a table of three rows', cells.length === 3, JSON.stringify(cells).slice(0, 200));
check('a quoted cell keeps its commas', cells[0] && cells[0][1].includes('Emma at the cabinet, Robert'));
check('library links are pictures', cells[0] && cells[0][2] === 'IMG' && cells[1][2] === 'IMG');
check('an outside link stays text', cells[2] && cells[2][2] === 'https://example.com/x.png');
const loaded = await page.$$eval('.md-cell-media img', (imgs) => imgs.map((i) => i.complete && i.naturalWidth > 0));
check('the picture and the video poster load', loaded.length === 2 && loaded.every(Boolean), JSON.stringify(loaded));
const options = await page.$$eval('.turn-question-options button', (b) => b.map((x) => x.textContent));
check('the question has its two buttons', options.length === 2 && options[1] === 'Looks good, next step', JSON.stringify(options));

const shown = await page.$eval('.turn-budget', (n) => n.textContent).catch(() => '');
check('the run budget is shown', shown.includes('no limit'), shown);
await page.evaluate(() => [...document.querySelectorAll('.turn-budget button')].find((b) => b.textContent === 'Set a budget').click());
await wait(300);
await page.type('.turn-budget .budget-field', '500');
await page.evaluate(() => [...document.querySelectorAll('.turn-budget button')].find((b) => b.textContent === 'Save').click());
await wait(800);
const stored = await call('/api/runs/t1/budget');
check('the budget is set on the server', stored.credits === 500, JSON.stringify(stored));
const line = await page.$eval('.turn-budget', (n) => n.textContent).catch(() => '');
check('and shown as spent of the budget', line.includes('0 of 500 cr spent'), line);
await panel.screenshot({ path: `${OUT}/review_3_budget.png` });

await page.evaluate(() => [...document.querySelectorAll('.turn-question-options button')][1].click());
await wait(3500);
await panel.screenshot({ path: `${OUT}/review_2_answered.png` });
check('a click sends the option as the next message', sent.length === 1 && sent[0].instruction === 'Looks good, next step', JSON.stringify(sent.map((s) => s.instruction)));
check('the message carries the run', sent[0] && sent[0].run === 't1', sent[0] && sent[0].run);
const after = await page.$$eval('.turn-question-options button', (b) => b.map((x) => [x.disabled, x.getAttribute('aria-pressed')]));
check('once answered the buttons stand as a record', after.length === 2 && after.every(([d]) => d) && after[1][1] === 'true', JSON.stringify(after));
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));

await browser.close();
console.log(report.join('\n'));
console.log('screenshots in', OUT);
process.exit(report.some((l) => l.startsWith('FAIL')) ? 1 : 0);
