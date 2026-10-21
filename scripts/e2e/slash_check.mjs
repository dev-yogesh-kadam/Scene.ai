// The browser check of /skill commands typed anywhere in the Agent box: mid-sentence, and straight after an attached
// file. Start server.py first (fresh), then: node scripts/e2e/slash_check.mjs
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
const project = await call('/api/projects', { method: 'POST', json: { name: 'Slash' } });
const form = new FormData();
form.append('file', new Blob([fs.readFileSync(`${OUT}/e2e_files/dog.png`)], { type: 'image/png' }), 'dog.png');
form.append('project_id', String(project.id));
const dog = await call('/api/library/upload', { method: 'POST', form });
const skills = (await call('/api/skills')).skills.map((s) => s.id);
const target = skills.includes('short-film') ? 'short-film' : skills[0];

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'], defaultViewport: { width: 1440, height: 900 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const sent = [];
page.on('request', (r) => { if (r.url().endsWith('/api/agent/plan')) sent.push(JSON.parse(r.postData() || '{}')); });
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument((pid) => { localStorage.setItem('scene.project', String(pid)); localStorage.setItem('scene.panel.tab', 'agent'); }, project.id);
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(1500);
const box = '.agent-input, [contenteditable="true"]';
await page.click(box);

// "@" is only a character: nothing opens (files are attached with + or from the canvas)
await page.keyboard.type('@do');
await wait(500);
check('typing @ opens no list of frames', !(await page.$('.agent-mentionmenu')) && !(await page.$('.agent-skillmenu')));
for (let i = 0; i < 3; i += 1) await page.keyboard.press('Backspace');

// mid-sentence
await page.keyboard.type('a short film about a dog /' + target.slice(0, 4));
await wait(500);
const shown = await page.$$eval('.agent-skillmenu .skillmenu-item code', (c) => c.map((x) => x.textContent));
check('the menu opens mid-sentence, the closest match first', shown[0] === '/' + target, shown.join(' '));
await page.keyboard.press('Enter');
await wait(300);
const text = await page.$eval(box, (n) => n.textContent);
check('the skill goes where it was typed', text.replace(/\u00a0/g, ' ').startsWith('a short film about a dog /' + target), JSON.stringify(text));
check('the menu closes', !(await page.$('.agent-skillmenu')));

// straight after an attached file: a chip, then "/"
await page.evaluate((id) => {
  const input = document.querySelector('.agent-input, [contenteditable="true"]');
  input.replaceChildren();
  const chip = document.createElement('span');
  chip.className = 'attach'; chip.dataset.id = String(id); chip.dataset.name = 'dog'; chip.dataset.kind = 'image'; chip.contentEditable = 'false'; chip.textContent = 'dog';
  input.append(chip, document.createTextNode(''));
  const range = document.createRange(); range.setStart(input.lastChild, 0); range.collapse(true);
  const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
}, dog.id);
await page.keyboard.type('/');
await wait(500);
check('the menu opens right after an attached file', !!(await page.$('.agent-skillmenu')));
await page.keyboard.press('Enter');
await wait(300);
await page.keyboard.press('Enter');   // send
await wait(2500);
check('the message sends the file and the skill', sent.length === 1 && /^@1 \/[a-z0-9-]+/.test(sent[0].instruction.replace(/\u00a0/g, ' ')) && sent[0].selection.includes(dog.id),
  sent[0] ? JSON.stringify({ instruction: sent[0].instruction, selection: sent[0].selection }) : 'nothing sent');
check('no page errors', errors.length === 0, errors.join(' | '));
await browser.close();
console.log(report.join('\n'));
process.exit(report.some((l) => l.startsWith('FAIL')) ? 1 : 0);
