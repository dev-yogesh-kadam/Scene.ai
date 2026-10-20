// The browser check of the turn being answered: it is built once and changed in place (the rows that are new fade in,
// the clock and the word change their text), so nothing blinks; a plain "Working…" wait shows the feel-good words.
// The plan is streamed slowly by a stand-in for fetch, as a long run's would be.
// Start server.py first, then: node scripts/e2e/live_check.mjs
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
const project = await call('/api/projects', { method: 'POST', json: { name: 'Live' } });

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument((pid) => {
  localStorage.setItem('scene.project', String(pid));
  localStorage.setItem('scene.panel.tab', 'agent');
  // The plan, streamed slowly: "Working…" every second, a row of work every two, the answer after nine.
  const real = window.fetch;
  window.fetch = (url, options) => {
    if (!String(url).endsWith('/api/agent/plan')) return real(url, options);
    const enc = new TextEncoder();
    const line = (o) => enc.encode(JSON.stringify(o) + '\n');
    const body = new ReadableStream({ async start(c) {
      const rows = ['Read what you attached: episode, script', 'Read the skill “Pocket Motion”', 'Opened the asset book: 9 entries', 'Wrote /motion/decisions of the run'];
      for (let s = 0; s < 9; s += 1) {
        c.enqueue(line({ type: 'status', text: 'Working…' }));
        if (s % 2 === 1 && rows.length) c.enqueue(line({ type: 'activity', icon: 'book', text: rows.shift(), at: s }));
        await new Promise((r) => setTimeout(r, 1000));
      }
      c.enqueue(line({ type: 'plan', reply: 'Done.', steps: [], total: 0, chips: {}, activity: [] }));
      c.close();
    } });
    return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
  };
}, project.id);
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(1500);
await page.click('.agent-input, [contenteditable="true"]');
await page.keyboard.type('go');
await page.keyboard.press('Enter');
await wait(1200);

// Mark the live turn, its dots and its first row: in place, they are the same elements seconds later.
await page.evaluate(() => {
  const live = document.querySelector('.turn.live');
  window.__live = live;
  window.__dots = live && live.querySelector('.thinking-dots');
  window.__words = new Set();
  window.__timer = setInterval(() => { const w = document.querySelector('.turn.live .thinking-word'); if (w) window.__words.add(w.textContent); }, 200);
});
await wait(3500);
const early = await page.evaluate(() => ({ rows: document.querySelectorAll('.turn.live .work-row').length,
  first: document.querySelector('.turn.live .work-row') }));
await page.evaluate(() => { window.__row = document.querySelector('.turn.live .work-row'); });
await wait(3000);
const later = await page.evaluate(() => {
  const live = document.querySelector('.turn.live');
  const rows = [...document.querySelectorAll('.turn.live .work-row')];
  return {
    same: live === window.__live, dots: live && live.querySelector('.thinking-dots') === window.__dots,
    row: rows[0] === window.__row, rows: rows.length, fading: rows.filter((r) => r.classList.contains('row-in')).length,
    clock: live && live.querySelector('.fold-sub') && live.querySelector('.fold-sub').textContent,
    words: [...window.__words],
  };
});
await page.screenshot({ path: path.join(OUT, 'live_check.png') });
check('the turn being answered is the same element seconds later', later.same);
check('its dots keep running (the same element)', later.dots);
check('a row already shown is kept, not drawn again', later.row);
check('new rows are added as they come', later.rows > early.rows, `${early.rows} then ${later.rows}`);
check('the clock counts', /\d/.test(later.clock || ''), later.clock);
check('a "Working…" wait shows the feel-good words, never "Working"', later.words.length >= 2 && !later.words.includes('Working'), later.words.join(' | '));
await wait(4000);
const done = await page.evaluate(() => !document.querySelector('.turn.live'));
check('the answer replaces the turn being answered', done);
check('no page errors', errors.length === 0, errors.join(' | '));
await browser.close();
console.log(report.join('\n'));
