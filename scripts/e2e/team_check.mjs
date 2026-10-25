// Sharing a project, the Library's sidebar, the canvas's Share button and running frame, and the console's Roles and
// Bulk generation sections, in headless Chrome against server.py (the studio on :8099, the console on :8098).
// Restart server.py first: the first account made here must be the admin.
import { createRequire } from 'module';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const STUDIO = 'http://127.0.0.1:8099';
const CONSOLE = 'http://127.0.0.1:8098';
const SHOTS = path.join(os.tmpdir(), 'scene-e2e');
const ADA = { name: 'Ada', email: 'ada@example.com', password: 'correct horse battery' };
const BOB = { name: 'Bob', email: 'bob@example.com', password: 'correct horse battery 2' };
let failed = 0;
const check = (what, ok, more = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${what}${ok || !more ? '' : '  ' + more}`); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
const fresh = async () => {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 1360, height: 860 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  return page;
};
const call = (page, url, json, method = 'POST') => page.evaluate(async (u, j, m) => {
  const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: j ? JSON.stringify(j) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, url, json, method);

// Ada (the admin) and Bob each have an account.
const ada = await fresh();
await ada.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
check('Ada signs up (the admin)', (await call(ada, '/api/auth/register', ADA)).status === 200);
const bob = await fresh();
await bob.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
check('Bob signs up', (await call(bob, '/api/auth/register', BOB)).status === 200);

// Ada shares a project with Bob from its page.
const film = (await call(ada, '/api/projects', { name: 'Coca Cola' })).body.id;
await ada.goto(`${STUDIO}/project?id=${film}`, { waitUntil: 'networkidle2' });
await ada.waitForSelector('.proj-members-head button');
check('the project page shows its members, the owner first', (await ada.$eval('.proj-owner', (n) => n.textContent)).includes('Members · 1'));
await ada.click('.proj-members-head button');
await ada.waitForSelector('dialog.share-dialog input');
check('the share dialog is titled with the project', (await ada.$eval('dialog.share-dialog h2', (h) => h.textContent)) === 'Add to Coca Cola');
await ada.type('dialog.share-dialog input', BOB.email);
await ada.keyboard.press('Enter');
await ada.waitForSelector('.share-pending .share-row select');
await ada.select('.share-pending .share-row select', 'creator');
await ada.screenshot({ path: path.join(SHOTS, 'team_1_share.png') });
await ada.evaluate(() => [...document.querySelectorAll('dialog.share-dialog button')].find((b) => /^Add/.test(b.textContent)).click());
await wait(800);
const listed = await ada.$$eval('.share-people .share-row', (rows) => rows.map((r) => r.textContent));
check('Bob is in the project as a creator', listed.some((t) => t.includes(BOB.email) && t.includes('Creator')), JSON.stringify(listed));
await ada.screenshot({ path: path.join(SHOTS, 'team_2_shared.png') });
await ada.keyboard.press('Escape');
await wait(600);
check('the page lists two members once the dialog closes', (await ada.$eval('.proj-owner', (n) => n.textContent)).includes('Members · 2'));

// Bob sees it shared with him, opens it, and has no owner's buttons.
await bob.goto(STUDIO + '/projects', { waitUntil: 'networkidle2' });
await bob.waitForSelector('.pcard');
const card = await bob.$eval('.pcard', (c) => c.textContent);
check('Bob\'s Projects show it as shared by Ada', card.includes('Shared') && card.includes("Ada's"), card);
await bob.screenshot({ path: path.join(SHOTS, 'team_3_bob_projects.png') });
await bob.goto(`${STUDIO}/project?id=${film}`, { waitUntil: 'networkidle2' });
await bob.waitForSelector('.proj-side-actions');
check('Bob, a creator, has no Delete or Edit details on it', (await bob.$$('.proj-side-actions button')).length === 0);

// The Library has the full sidebar; the canvas has the Share button and the running frame.
await ada.goto(STUDIO + '/library', { waitUntil: 'networkidle2' });
await wait(500);
check('the Library shows the full sidebar', await ada.evaluate(() => !!document.querySelector('.rail, .sidebar, nav.side') &&
  getComputedStyle(document.querySelector('.rail, .sidebar, nav.side')).display !== 'none'));
await ada.screenshot({ path: path.join(SHOTS, 'team_4_library.png') });
await ada.evaluate((id) => localStorage.setItem('scene.project', id), film);
await ada.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await wait(800);
check('the canvas has a Share button', await ada.evaluate(() => [...document.querySelectorAll('.canvas-bar button')].some((b) => b.textContent.includes('Share') && !b.classList.contains('hidden'))));
const kept = await ada.evaluate(async () => {
  const { runningGate } = await import(document.querySelector('script[type=module]').src.replace('main.js', 'dom.js'));
  const shot = document.createElement('div');
  shot.className = 'shot';
  shot.style.cssText = 'position:fixed;left:200px;top:200px;width:360px;height:200px;z-index:999';
  const frame = document.createElement('div');
  frame.className = 'frame developing';
  frame.appendChild(shot);
  shot.appendChild(runningGate());
  document.body.appendChild(frame);
  return getComputedStyle(shot.querySelector('.run'), '::before').animationName;
});
check('a running frame has the drifting sheen, not the circling light', kept === 'run-sheen', kept);
await wait(900);
await ada.screenshot({ path: path.join(SHOTS, 'team_5_running.png'), clip: { x: 180, y: 180, width: 400, height: 240 } });

// The console: Roles and Bulk generation.
const desk = await fresh();
await desk.goto(CONSOLE + '/', { waitUntil: 'networkidle2' });
await desk.waitForSelector('input[type=email]');
await desk.type('input[type=email]', ADA.email);
await desk.type('input[type=password]', ADA.password);
await desk.keyboard.press('Enter');
await desk.waitForSelector('.page-head h1', { timeout: 15000 });
await desk.goto(CONSOLE + '/roles', { waitUntil: 'networkidle2' });
await desk.waitForSelector('.role-card');
const roleNames = await desk.$$eval('.role-card summary h2', (h) => h.map((x) => x.textContent));
check('Roles lists the built-in roles and a new one to make', ['Admin', 'Support', 'Finance', 'Moderator', 'New role'].every((r) => roleNames.includes(r)), JSON.stringify(roleNames));
await desk.screenshot({ path: path.join(SHOTS, 'team_6_roles.png'), fullPage: true });

// Bulk generation: a tab of the canvas panel for the admin, not for Bob.
await ada.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await wait(800);
await ada.evaluate(() => document.querySelector('.side-panel .segmented button[title="Bulk generation"], .side-panel [aria-label="Bulk generation"]')?.click());
await wait(400);
if (!(await ada.$('.panel-bulk:not(.hidden) textarea'))) {   // the tab's button, found by its hint
  await ada.evaluate(() => [...document.querySelectorAll('.side-panel .panel-head button')].find((b) => (b.title || b.getAttribute('aria-label') || '').includes('Bulk'))?.click());
}
await ada.waitForSelector('.panel-bulk:not(.hidden) textarea', { timeout: 10000 });
await ada.type('.panel-bulk textarea', 'a red fox in snow');
await wait(300);
const label = await ada.$eval('.panel-bulk button.primary', (b) => b.textContent);
check('the admin canvas has a Bulk tab that picks every image workflow', /Generate with (1[6-9]|2\d) workflows/.test(label), label);
await ada.screenshot({ path: path.join(SHOTS, 'team_7_bulk_panel.png') });
await ada.click('.panel-bulk button.primary');
await wait(2500);
const frames = await ada.$$eval('.frame.developing', (f) => f.length);
check('the bulk jobs come onto the canvas as frames', frames > 15, String(frames));
await ada.screenshot({ path: path.join(SHOTS, 'team_8_bulk_canvas.png') });
await bob.evaluate((id) => localStorage.setItem('scene.project', id), film);
await bob.goto(STUDIO + '/canvas', { waitUntil: 'networkidle2' });
await wait(800);
check('Bob has no Bulk tab', await bob.evaluate(() => ![...document.querySelectorAll('.side-panel .panel-head button')].some((b) => (b.title || b.getAttribute('aria-label') || '').includes('Bulk'))));

for (const [who, page] of [['studio (Ada)', ada], ['studio (Bob)', bob], ['console', desk]]) check(`no script errors in the ${who}`, page.errors.length === 0, page.errors.join(' | '));
console.log(failed ? `${failed} failed` : 'all passed');
await browser.close();
process.exit(failed ? 1 : 0);
