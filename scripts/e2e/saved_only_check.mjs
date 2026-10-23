// The browser check of a long run's planning stages: a turn that saved its work and planned nothing to make goes on
// by itself, and after SAVED_ONLY such turns in a row the run waits for the user, so it cannot loop.
// Start server.py first, then: node scripts/e2e/saved_only_check.mjs
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
async function call(where, { method = 'GET', json } = {}) {
  const headers = { cookie };
  let body;
  if (json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  const r = await fetch(BASE + where, { method, headers, body });
  const set = r.headers.get('set-cookie');
  if (set) cookie = set.split(';')[0];
  const text = await r.text();
  if (!r.ok) throw new Error(`${where} ${r.status} ${text}`);
  try { return JSON.parse(text); } catch { return text; }
}

await call('/api/auth/register', { method: 'POST', json: { name: 'Tester', email: 'tester' + Date.now() + '@example.com', password: 'correct horse battery staple' } });
const project = await call('/api/projects', { method: 'POST', json: { name: 'Plan' } });
const turn = (instruction, extra = {}) => ({ instruction, parts: [{ text: instruction }], reply: 'Planned the units.', chips: {}, activity: [],
  seconds: 2, total: 0, state: 'answered', ui: {}, at: Date.now(), steps: [], continues: true, ...extra });

async function open(runs) {
  const now = Date.now();
  await call('/api/boards/agent', { method: 'PUT', json: { project: project.id, data: { tabs: [{ id: 't1', name: 'Agent 1', created: now, updated: now }], open: ['t1'], active: 't1' } } });
  await call('/api/boards/agent-t1', { method: 'PUT', json: { project: project.id, data: { runs } } });
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
    args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  const sent = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/agent/plan')) sent.push(JSON.parse(r.postData() || '{}')); });
  const [name, value] = cookie.split('=');
  await page.setCookie({ name, value, url: BASE });
  await page.evaluateOnNewDocument((pid) => {
    localStorage.setItem('scene.project', String(pid));
    localStorage.setItem('scene.panel.tab', 'agent');
  }, project.id);
  await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
  for (let i = 0; i < 10 && !sent.length; i += 1) await wait(1000);
  return { browser, page, sent, errors };
}

// One planning turn that saved its work: the run goes on.
let s = await open([turn('Looks good, next step')]);
check('a turn that saved its work goes on by itself', s.sent.length === 1 && /saved your work/.test(s.sent[0].instruction), `${s.sent.length} sent`);
check('it carries the run', s.sent[0] && s.sent[0].run === 't1');
check('no page errors', s.errors.length === 0, s.errors.join(' | ').slice(0, 200));
await s.browser.close();

// Four such turns in a row (the user's, then three it went on by itself): it waits for the user.
s = await open([turn('go'), turn('Continue the run', { auto: true, continued: true }), turn('Continue the run', { auto: true, continued: true }),
  turn('Continue the run', { auto: true })]);
check('after three in a row it waits for the user', s.sent.length === 0, `${s.sent.length} sent`);
const notes = await s.page.evaluate(() => [...document.querySelectorAll('.agent-auto')].map((n) => n.textContent.trim()));
check('the turns it went on by itself show as notes', notes.length === 3 && notes.every((n) => n === 'Carried on by itself'), notes.join(' | '));
await s.browser.close();

// A turn with a question waits for the answer.
s = await open([turn('go', { continues: false, question: { text: 'Which take?', options: ['A', 'B'] } })]);
check('a turn that asks waits for the answer', s.sent.length === 0, `${s.sent.length} sent`);
await s.browser.close();
console.log(report.join('\n'));
