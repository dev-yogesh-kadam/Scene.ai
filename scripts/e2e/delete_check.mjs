// Deleting a module from a project's page: the studio's own confirmation (not the browser's), Cancel keeps it, Delete
// removes it and what was made in it. Against server.py (:8099). node scripts/e2e/delete_check.mjs
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
let native = 0;
page.on('pageerror', (e) => errors.push(e.message));
page.on('dialog', async (d) => { native += 1; await d.dismiss(); });   // the browser's own box: should never appear
await page.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
await page.evaluate(async () => fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Ada', email: 'd' + Date.now() + '@example.com', password: 'correct horse battery staple' }) }));
const film = await page.evaluate(async () => (await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'testing' }) })).json());
const mod = await page.evaluate(async (id) => (await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Module 2', parent_id: id }) })).json(), film.id);
await page.evaluate(async (id) => {
  const form = new FormData();
  form.append('file', new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, ...new Array(32).fill(48)])], { type: 'image/png' }), 'shot.png');
  form.append('project_id', String(id));
  return fetch('/api/library/upload', { method: 'POST', body: form });
}, mod.id);

await page.goto(`${STUDIO}/project?id=${film.id}`, { waitUntil: 'networkidle2' });
await page.waitForSelector('.pcard-actions', { timeout: 15000 });
const clickDelete = () => page.evaluate(() => [...document.querySelectorAll('.pcard-actions .icon-btn')].find((b) => /Delete/.test(b.title)).click());
await clickDelete();
await page.waitForSelector('dialog.ask-dialog[open]', { timeout: 5000 }).catch(() => {});
const text = await page.$eval('dialog.ask-dialog', (d) => d.innerText.replace(/\s+/g, ' ')).catch(() => '');
check('the studio asks in its own window', /Delete "Module 2"\?/.test(text) && /1 item is deleted with it/.test(text) && native === 0, text);
await page.screenshot({ path: `${OUT}/delete_1_ask.png` });
await page.$$eval('dialog.ask-dialog button', (bs) => bs.find((b) => b.textContent === 'Cancel').click());
await wait(500);
check('Cancel keeps the module', await page.evaluate(() => document.querySelectorAll('.proj-modules .pcard').length) === 2);
await clickDelete();
await page.waitForSelector('dialog.ask-dialog[open]', { timeout: 5000 }).catch(() => {});
await page.$$eval('dialog.ask-dialog button', (bs) => bs.find((b) => b.textContent === 'Delete module').click());
await wait(1500);
const left = await page.evaluate(async () => ({ cards: document.querySelectorAll('.proj-modules .pcard').length, items: (await (await fetch('/api/library')).json()).items.length }));
check('Delete removes the module and what was made in it', left.cards === 1 && left.items === 0, JSON.stringify(left));
check('no browser dialogs, no page errors', native === 0 && errors.length === 0, errors.slice(0, 3).join(' || '));
console.log(report.join('\n'));
await browser.close();
