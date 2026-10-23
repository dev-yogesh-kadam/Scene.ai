// The browser check of a project's kit: the Kit tab lists what the project is made from (always on first), an entry is
// renamed, switched on and taken out in the panel, and Quick actions offers the kit in its reference slots.
// Start server.py first, then: node scripts/e2e/kit_check.mjs
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
const project = await call('/api/projects', { method: 'POST', json: { name: 'Kit' } });
const add = (file, name, type, always) => {
  const form = new FormData();
  form.append('file', new Blob([fs.readFileSync(`${OUT}/e2e_files/${file}`)], { type: 'image/png' }), file);
  form.append('name', name);
  form.append('type', type);
  form.append('project_id', String(project.id));
  if (always) form.append('always', '1');
  return call('/api/kit', { method: 'POST', form });
};
const violet = await add('dog.png', 'Violet', 'character', true);
const clearing = await add('cat.png', 'Clearing', 'location', false);

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('dialog', (d) => d.accept());   // "Take it out of the Kit?"
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument((pid) => {
  localStorage.setItem('scene.project', String(pid));
  localStorage.setItem('scene.panel.tab', 'kit');
}, project.id);
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(2000);
const rows = () => page.evaluate(() => [...document.querySelectorAll('.kit-row')].map((r) => ({
  name: r.querySelector('.kit-name').value, always: r.classList.contains('always'), group: r.closest('.kit-group').querySelector('h3').textContent })));
let shown = await rows();
check('the Kit tab lists the project\'s entries, always on first', shown.length === 2 && shown[0].name === 'Violet' && shown[0].always
  && /Always on/.test(shown[0].group) && shown[1].name === 'Clearing', JSON.stringify(shown));
check('the panel is titled with the kit\'s name', await page.evaluate(() => document.querySelector('.panel-title').textContent) === 'NeuralCore');
await page.$('.side-panel').then((p) => p && p.screenshot({ path: `${OUT}/kit_1.png` }));

// rename the location and switch it on
await page.evaluate(() => {
  const row = [...document.querySelectorAll('.kit-row')].find((r) => r.querySelector('.kit-name').value === 'Clearing');
  const input = row.querySelector('.kit-name');
  input.value = 'Bonfire Clearing';
  input.dispatchEvent(new Event('change'));
});
await wait(800);
await page.evaluate(() => {
  const row = [...document.querySelectorAll('.kit-row')].find((r) => r.querySelector('.kit-name').value === 'Bonfire Clearing');
  row.querySelector('.kit-always input').click();
});
await wait(1200);
const saved = (await call(`/api/kit?project=${project.id}`)).entries;
check('a name changed in the panel is saved', saved.some((e) => e.id === clearing.id && e.name === 'Bonfire Clearing'));
check('Always on switched in the panel is saved', saved.some((e) => e.id === clearing.id && e.always));
shown = await rows();
check('both are always on now', shown.length === 2 && shown.every((r) => r.always), JSON.stringify(shown));

// Quick actions offers the kit in a reference slot
await page.evaluate(() => [...document.querySelectorAll('.panel-head [role="radio"], .panel-head button')].find((b) => /Quick actions/.test(b.title || b.getAttribute('aria-label') || b.textContent))?.click());
await wait(800);
await page.evaluate(() => [...document.querySelectorAll('.panel-quick button')].find((b) => b.textContent.trim().startsWith('Generate video'))?.click());
await wait(1500);
const slot = await page.$('.slot-box');
if (slot) {
  await slot.click();
  await wait(400);
}
const menu = await page.evaluate(() => [...document.querySelectorAll('.pop .add-menu-item')].map((b) => b.textContent.trim()));
check('a reference slot offers "From the NeuralCore"', menu.some((t) => t.startsWith('From the NeuralCore')), menu.join(' | '));
await page.keyboard.press('Escape');
const keepOnVideo = await page.evaluate(() => { const k = document.querySelector('.panel-quick .keep-field'); return !!k && !k.classList.contains('hidden'); });
check('a video is not offered to be kept (only pictures and voices are)', !keepOnVideo);
await page.evaluate(() => document.querySelector('.panel-quick .quick-head .icon-btn')?.click());   // back to the tiles
await wait(500);
await page.evaluate(() => [...document.querySelectorAll('.panel-quick button')].find((b) => b.textContent.trim().startsWith('Generate image'))?.click());
await wait(1500);
const keepOnImage = await page.evaluate(() => {
  const k = document.querySelector('.panel-quick .keep-field');
  if (!k || k.classList.contains('hidden')) return null;
  k.querySelector('input[type=checkbox]').click();
  return [...k.querySelectorAll('.keep-type option')].map((o) => o.textContent);
});
check('a picture can be kept in the Kit under a name, as a character, location, prop, outfit or style', Array.isArray(keepOnImage)
  && keepOnImage.join(',') === 'Character,Location,Prop,Outfit,Style', String(keepOnImage));

// take one out
await page.evaluate(() => [...document.querySelectorAll('.panel-head [role="radio"], .panel-head button')].find((b) => /Kit/.test(b.title || b.getAttribute('aria-label') || b.textContent))?.click());
await wait(800);
await page.evaluate(() => {
  const row = [...document.querySelectorAll('.kit-row')].find((r) => r.querySelector('.kit-name').value === 'Violet');
  row.querySelector('.kit-remove').click();
});
await wait(1200);
const left = (await call(`/api/kit?project=${project.id}`)).entries;
check('× takes an entry out of the kit', left.length === 1 && left[0].id === clearing.id, left.map((e) => e.name).join(', '));
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
