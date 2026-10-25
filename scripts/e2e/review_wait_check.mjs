// The browser check of a long run that waits for the user: a picture of the run failed its check and offers Retake or
// Keep it, so the run does not carry on by itself until the user chooses. Keep it lets it go on.
// Start server.py first, then: node scripts/e2e/review_wait_check.mjs
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
const project = await call('/api/projects', { method: 'POST', json: { name: 'Wait' } });
const form = new FormData();
form.append('file', new Blob([fs.readFileSync(`${OUT}/e2e_files/dog.png`)], { type: 'image/png' }), 'anchor.png');
form.append('project_id', String(project.id));
const anchor = await call('/api/library/upload', { method: 'POST', form });

// An approved plan of a long run whose one picture is made and failed its check, with a retake offered.
const now = Date.now();
const runs = [{ instruction: 'go', parts: [{ text: 'go' }], reply: 'Making the anchor.', chips: {}, activity: [], seconds: 2, total: 40,
  state: 'approved', ui: {}, at: now, continues: true,
  steps: [{ name: 'Anchor — clearing', workflow_title: 'FLUX.2 Klein 9B (distilled)', kind: 'image', credits: 40, prompt: 'Five women by a bonfire.',
    settings: { workflow: 'image/image_t2i_flux2_klein_9b', values: {} }, made: anchor.id, madeInfo: { width: 512, height: 512 },
    review: { passed: false, problem: 'The characters do not match the reference pictures.', checks: [] },
    retake: { credits: 40, prompt: 'Five women by a bonfire, faces as in the references.' } }] }];
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
await wait(6000);
check('the run waits while a failed picture waits for Retake or Keep it', sent.length === 0, `${sent.length} sent`);
const offered = await page.evaluate(() => [...document.querySelectorAll('.agent-review button')].map((b) => b.textContent.trim()));
check('Retake and Keep it are offered', offered.some((t) => t.startsWith('Retake')) && offered.includes('Keep it'), offered.join(' | '));
await page.evaluate(() => [...document.querySelectorAll('.agent-review button')].find((b) => b.textContent.trim() === 'Keep it').click());
for (let i = 0; i < 15 && !sent.length; i += 1) await wait(1000);
check('Keep it lets the run go on, once', sent.length === 1, `${sent.length} sent`);
check('it says the picture was made', sent[0] && /“Anchor — clearing”: item \d+/.test(sent[0].instruction), sent[0] ? sent[0].instruction.slice(0, 120) : '');
await page.$('.side-panel').then((p) => p && p.screenshot({ path: `${OUT}/review_wait.png` }));
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
