// The browser check of a long skill's run going on by itself: once every step of its newest plan is made, the Agent
// tab tells the agent what each made. A free film operation stands in for a generated step (there is no render server).
// Start server.py first, then: node scripts/e2e/continue_check.mjs
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
const project = await call('/api/projects', { method: 'POST', json: { name: 'Run' } });
const form = new FormData();
form.append('file', new Blob([fs.readFileSync(`${OUT}/e2e_files/dog.png`)], { type: 'image/png' }), 'dog.png');
form.append('project_id', String(project.id));
const dog = await call('/api/library/upload', { method: 'POST', form });

const now = Date.now();
const runs = [{ instruction: 'go', parts: [{ text: 'go' }], reply: 'Making the references.', chips: {}, activity: [], seconds: 2, total: 0,
  state: 'proposed', ui: {}, at: now, continues: true,
  steps: [{ name: 'Dog reference', workflow_title: 'Film', kind: 'image', credits: 0, settings: null, prompt: '', facts: '1500 px', time: 'a few seconds' }] }];
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
await wait(2000);
check('nothing is sent before the plan is approved', sent.length === 0);

// Approve: the step is queued as a free film job (the plan's own step has no settings, so it is queued here by hand,
// the way approve() queues a local edit), then its result comes in and the run goes on.
const queued = await page.evaluate(async (pid, image) => {
  const r = await fetch('/api/edit/film', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'reference', image, project_id: pid }) });
  return (await r.json()).job;
}, project.id, dog.id);
const board = await call(`/api/boards/agent-t1?project=${project.id}`);
board.data.runs[0].state = 'approved';
board.data.runs[0].steps[0].job = queued;
await call('/api/boards/agent-t1', { method: 'PUT', json: { project: project.id, data: board.data } });
await page.reload({ waitUntil: 'networkidle2' });
for (let i = 0; i < 30 && !sent.length; i += 1) await wait(1000);
await page.$('.side-panel').then((p) => p && p.screenshot({ path: `${OUT}/continue_1.png` }));
const text = sent[0] ? sent[0].instruction : '';
check('the run went on by itself, once', sent.length === 1, `${sent.length} sent`);
check('it names what the step made, by library id', /“Dog reference”: item \d+ \(image, 1500×1500\)/.test(text) || /“Dog reference”: item \d+/.test(text), text.slice(0, 160));
check('it carries the run', sent[0] && sent[0].run === 't1');
await wait(4000);
check('and only once', sent.length === 1, `${sent.length} sent`);
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
process.exit(report.some((l) => l.startsWith('FAIL')) ? 1 : 0);
