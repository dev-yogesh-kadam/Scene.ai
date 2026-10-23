// The admin console in headless Chrome, against server.py (the studio on :8099, the console on :8098). Start server.py
// fresh, so the account made here is the first one, an admin; then: node scripts/e2e/console_check.mjs
// Checks: the studio's link to the console, the console's own sign-in, every section, the live count, signing out.
import { createRequire } from 'module';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const STUDIO = 'http://127.0.0.1:8099';
const CONSOLE = 'http://127.0.0.1:8098';
const OUT = path.join(os.tmpdir(), 'scene-e2e');
const SECTIONS = ['overview', 'jobs', 'system', 'users', 'credits', 'library', 'projects', 'moderation', 'pricing', 'economics', 'workflows', 'agent', 'skills', 'audit', 'settings'];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error' && !/401|403|Failed to load resource/.test(m.text())) errors.push(m.text()); });

// The admin, made in the studio (the first account).
const email = 'ada' + Date.now() + '@example.com';
const password = 'correct horse battery staple';
await page.goto(STUDIO + '/signup', { waitUntil: 'networkidle2' });
const made = await page.evaluate(async (body) => (await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json(),
  { name: 'Ada', email, password });
check('the first account is an admin and is told where the console is', made.role === 'admin' && made.console && made.console.port === 8098, JSON.stringify(made.console));
await page.goto(STUDIO + '/settings', { waitUntil: 'networkidle2' });
await wait(600);
const link = await page.$$eval('a', (as) => as.filter((a) => a.textContent.includes('Admin console')).map((a) => a.href));
check('the studio links to the console on its own port', link.length > 0 && link.every((h) => h.startsWith(CONSOLE)), link.join(' '));
const blocked = await page.evaluate(async () => (await fetch('/assets/js/console/main.js')).status);
check('the studio does not serve the console\'s scripts', blocked === 404, String(blocked));

// The studio's sign-in does not open the console: it asks for its own.
await page.goto(CONSOLE + '/users', { waitUntil: 'networkidle2' });
await page.waitForSelector('input[type=password]');
check('the console asks for its own sign-in', (await page.evaluate(() => location.pathname)) === '/signin');
await page.screenshot({ path: `${OUT}/console_1_signin.png` });
await page.type('input[type=email]', email);
await page.type('input[type=password]', 'wrong password');
await page.click('button[type=submit]');
await wait(800);
const wrong = await page.$eval('.auth-card .error', (e) => e.textContent);
check('a wrong password is refused', /Wrong email or password/.test(wrong), wrong);
await page.$eval('input[type=password]', (i) => { i.value = ''; });
await page.type('input[type=password]', password);
await Promise.all([page.waitForSelector('.sidebar .nav'), page.click('button[type=submit]')]);
await wait(800);
check('signing in lands on the section asked for', (await page.evaluate(() => location.pathname)) === '/users');

// Every section loads without an error, from its own address and from the sidebar.
for (const id of SECTIONS) {
  await page.click(`.sidebar .nav a[href="/${id}"]`);
  await wait(900);
  const state = await page.evaluate(() => ({ path: location.pathname, h1: document.querySelector('.page-head h1').textContent,
    error: (document.querySelector('main .error') || {}).textContent || '', lit: (document.querySelector('.nav a.on') || {}).textContent }));
  check(`section ${id}`, state.path === '/' + id && !state.error && state.lit === state.h1, JSON.stringify(state));
}
await page.goto(CONSOLE + '/overview', { waitUntil: 'networkidle2' });
const cards = await page.waitForSelector('main .card', { timeout: 15000 }).then(() => true, () => false);
check('the overview shows its cards', cards);
await wait(600);
const people = await page.$eval('.live-count b', (b) => b.textContent);
check('the live count arrives over the console\'s own connection', /^\d+$/.test(people), people);
await page.screenshot({ path: `${OUT}/console_2_overview.png` });
await page.setViewport({ width: 390, height: 844 });
await wait(400);
const wide = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
check('no sideways scrolling on a phone', wide);
await page.screenshot({ path: `${OUT}/console_3_phone.png` });
await page.setViewport({ width: 1400, height: 900 });

// Live operations: the health cards, maintenance mode end to end, and the phone alerts card.
await page.goto(CONSOLE + '/system', { waitUntil: 'networkidle2' });
await page.waitForSelector('main .card', { timeout: 15000 });
const titles = await page.$$eval('main .card h2', (hs) => hs.map((h) => h.textContent));
check('System shows alerts, maintenance and both servers', ['Alerts', 'Maintenance', 'Render server', 'Model server'].every((c) => titles.includes(c)), titles.join(', '));
await page.$eval('main textarea', (t) => { t.value = ''; });
await page.type('main textarea', 'Back at 6 pm.');
await page.$$eval('main button', (bs) => bs.find((b) => b.textContent === 'Turn on').click());
await page.waitForFunction(() => /On since/.test(document.querySelector('main').innerText), { timeout: 15000 }).catch(() => {});
const on = await page.evaluate(() => [...document.querySelectorAll('main .card')].find((c) => c.querySelector('h2').textContent === 'Maintenance').innerText);
check('maintenance turns on and says what is left', /On since/.test(on) && /safe to restart/.test(on), on.slice(0, 120).replace(/\s+/g, ' '));
const blocked503 = await (async () => {
  const studioPage = await browser.newPage();
  await studioPage.goto(STUDIO + '/projects', { waitUntil: 'networkidle2' });
  await wait(1500);
  const banner = await studioPage.$eval('.announce', (b) => b.textContent).catch(() => '');
  const job = await studioPage.evaluate(async () => (await fetch('/api/jobs', { method: 'POST', body: new URLSearchParams({ settings: JSON.stringify({ workflow: 'video/h3_master', values: { '100:value': 'She waves.' }, options: { mode: 'fast', quality: 'low' } }) }) })).status);
  await studioPage.close();
  return { banner, job };
})();
check('the studio shows the message and refuses new jobs', blocked503.banner.includes('Back at 6 pm.') && blocked503.job === 503, JSON.stringify(blocked503));
await page.screenshot({ path: `${OUT}/console_4_system.png`, fullPage: true });
await page.$$eval('main button', (bs) => bs.find((b) => b.textContent === 'Turn off').click());
await page.waitForFunction(() => [...document.querySelectorAll('main button')].some((b) => b.textContent === 'Turn on'), { timeout: 15000 }).catch(() => {});
check('maintenance turns off', await page.evaluate(() => !![...document.querySelectorAll('main button')].find((b) => b.textContent === 'Turn on')));
await page.click('.sidebar .nav a[href="/settings"]');
await page.waitForSelector('main .card', { timeout: 15000 });
// .invalid never resolves: the watcher's alerts during the check go nowhere.
await page.type('main input[placeholder^="https://ntfy.sh/"]', 'https://ntfy.invalid/scene-e2e-check');
await page.$$eval('main button', (bs) => bs.find((b) => b.textContent === 'Save' && b.closest('.card').querySelector('h2').textContent === 'Phone alerts').click());
await wait(1200);
const phoneCard = await page.evaluate(() => [...document.querySelectorAll('main .card')].find((c) => c.querySelector('h2').textContent === 'Phone alerts').innerText);
check('phone alerts save and turn on', /\bOn\b/.test(phoneCard), phoneCard.slice(0, 60).replace(/\s+/g, ' '));
await page.screenshot({ path: `${OUT}/console_5_settings.png`, fullPage: true });

// Workflows: the record of versions, a workflow's panel, offering it to admins only, and a test run.
await page.click('.sidebar .nav a[href="/workflows"]');
await page.waitForSelector('main table tr.clickable', { timeout: 20000 });
const wfCards = await page.$$eval('main .card h2', (hs) => hs.map((h) => h.textContent));
check('Workflows shows changes, the comparison and the list', ['Changes from the render PC', 'Compared with the render server', 'Workflows'].every((c) => wfCards.includes(c)), wfCards.join(', '));
await page.screenshot({ path: `${OUT}/console_6_workflows.png`, fullPage: true });
await page.click('main table tr.clickable');
await page.waitForFunction(() => /Versions \(\d+\)/.test((document.querySelector('.drawer') || {}).innerText || ''), { timeout: 15000 }).catch(() => {});
const drawerText = await page.$eval('.drawer', (d) => d.innerText);
check('a workflow\'s panel shows its versions', /Versions \(1\)/.test(drawerText) && /On record/.test(drawerText), drawerText.slice(0, 80).replace(/\s+/g, ' '));
await page.$$eval('.drawer .seg button', (bs) => bs.find((b) => b.textContent === 'Admins only').click());
await page.waitForFunction(() => [...document.querySelectorAll('main table .pill')].some((p) => p.textContent === 'Admins only'), { timeout: 15000 }).catch(() => {});
check('it can be offered to admins only', await page.evaluate(() => [...document.querySelectorAll('main table .pill')].some((p) => p.textContent === 'Admins only')));
await page.$$eval('.drawer button', (bs) => bs.find((b) => b.textContent === 'Test run').click());
await page.waitForFunction(() => /first in the queue|needs a file/.test((document.querySelector('.drawer .notice') || {}).textContent || ''), { timeout: 15000 }).catch(() => {});
const tested = await page.$eval('.drawer .notice', (n) => n.textContent);
check('a test run is queued, or says what file it needs', /first in the queue|needs a file/.test(tested), tested.slice(0, 90));
await page.screenshot({ path: `${OUT}/console_7_workflow.png` });
await page.$$eval('.drawer .seg button', (bs) => bs.find((b) => b.textContent === 'Everyone').click());
await wait(800);
await page.keyboard.press('Escape');

// The health strip, search (Ctrl+K), a person's panel with where they are signed in, the audit seals.
await page.goto(CONSOLE + '/overview', { waitUntil: 'networkidle2' });
await page.waitForSelector('.health-strip', { timeout: 20000 }).catch(() => {});
const chips = await page.$$eval('.health-chip', (cs) => cs.map((c) => c.innerText.replace(/\s+/g, ' ')));
check('the overview starts with the health strip', chips.length >= 6 && chips.some((c) => /Render server Offline/.test(c)), chips.join(' | '));
await page.keyboard.down('Control');
await page.keyboard.press('k');
await page.keyboard.up('Control');
await page.waitForSelector('.palette-input', { timeout: 5000 }).catch(() => {});
await page.type('.palette-input', 'ada');
await page.waitForFunction(() => [...document.querySelectorAll('.palette-item')].some((i) => /Person/i.test(i.innerText)), { timeout: 10000 }).catch(() => {});
const hits = await page.$$eval('.palette-item', (is) => is.map((i) => i.innerText.replace(/\s+/g, ' ')));
check('Ctrl+K finds people', hits.some((h) => /person/i.test(h) && /Ada/.test(h)), hits.join(' | '));
await page.screenshot({ path: `${OUT}/console_8_search.png` });
await page.keyboard.press('Enter');
await page.waitForFunction(() => location.pathname === '/users', { timeout: 10000 }).catch(() => {});
await page.waitForSelector('main table tr.clickable', { timeout: 15000 }).catch(() => {});
await page.click('main table tr.clickable');
await page.waitForFunction(() => /Signed in \(\d+\)/.test((document.querySelector('.drawer') || {}).innerText || ''), { timeout: 15000 }).catch(() => {});
const userPanel = await page.$eval('.drawer', (d) => d.innerText).catch(() => '');
check('a person\'s panel says where they are signed in', /Signed in \(2\)/.test(userPanel) && /You, here/.test(userPanel) && /Chrome|A browser/.test(userPanel), (userPanel.match(/Signed in[\s\S]{0,160}/) || [''])[0].replace(/\s+/g, ' '));
await page.keyboard.press('Escape');
await page.click('.sidebar .nav a[href="/audit"]');
await page.waitForSelector('main table', { timeout: 15000 });
await page.$$eval('main button', (bs) => bs.find((b) => b.textContent === 'Check the seals').click());
await page.waitForFunction(() => /sealed entries hold/.test(document.querySelector('main').innerText), { timeout: 10000 }).catch(() => {});
check('the audit log\'s seals hold', await page.evaluate(() => /sealed entries hold/.test(document.querySelector('main').innerText)));
await page.click('.sidebar .nav a[href="/agent"]');
await page.waitForSelector('main .tiles', { timeout: 15000 }).catch(() => {});
const agentCards = await page.$$eval('main .card h2', (hs) => hs.map((h) => h.textContent));
check('the Agent section shows its parts', ['By model', 'By what it was asked', 'Latest runs', 'Models for each role'].every((c) => agentCards.includes(c)), agentCards.join(', '));
await page.screenshot({ path: `${OUT}/console_9_agent.png`, fullPage: true });

// Staff roles: Bob, made support staff, sees only his part of the console. Then the admin views the studio as Bob.
const other = await browser.createBrowserContext();
const bobPage = await other.newPage();
await bobPage.setViewport({ width: 1400, height: 900 });
bobPage.on('pageerror', (e) => errors.push('bob: ' + e.message));
const bobEmail = 'bob' + Date.now() + '@example.com';
await bobPage.goto(STUDIO + '/signup', { waitUntil: 'networkidle2' });
const bob = await bobPage.evaluate(async (body) => (await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json(),
  { name: 'Bob', email: bobEmail, password });
await page.goto(CONSOLE + '/users', { waitUntil: 'networkidle2' });
const promoted = await page.evaluate(async (id) => (await fetch('/api/admin/users/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: 'support' }) })).status, bob.id);
await bobPage.goto(CONSOLE + '/overview', { waitUntil: 'networkidle2' });
await bobPage.waitForSelector('input[type=password]');
await bobPage.type('input[type=email]', bobEmail);
await bobPage.type('input[type=password]', password);
await Promise.all([bobPage.waitForSelector('.sidebar .nav'), bobPage.click('button[type=submit]')]);
await wait(800);
const bobNav = await bobPage.$$eval('.sidebar .nav a', (as) => as.map((a) => a.getAttribute('href').slice(1)));
const tag = await bobPage.$eval('.console-tag', (t) => t.textContent);
check('support staff see only their sections', promoted === 200 && tag === 'Support' && bobNav.includes('users') && !bobNav.includes('settings') && !bobNav.includes('pricing'), `${tag}: ${bobNav.join(', ')}`);
await bobPage.goto(CONSOLE + '/settings', { waitUntil: 'networkidle2' });
await wait(600);
check('a section outside the role leads back to their first', await bobPage.evaluate(() => location.pathname) === '/overview');
const view = await page.evaluate(async (id) => (await fetch('/api/admin/users/' + id + '/view', { method: 'POST' })).json(), bob.id);
const viewer = await browser.newPage();
await viewer.goto(`${STUDIO}${view.path}`, { waitUntil: 'networkidle2' });
await viewer.waitForSelector('.viewing-bar', { timeout: 15000 }).catch(() => {});
const bar = await viewer.$eval('.viewing-bar', (b) => b.innerText).catch(() => '');
const write = await viewer.evaluate(async () => (await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'x' }) })).status);
check('viewing the studio as Bob says so and changes nothing', /Viewing as Bob/.test(bar) && /read only/.test(bar) && write === 403, `${bar.replace(/\s+/g, ' ')} · write ${write}`);
await viewer.screenshot({ path: `${OUT}/console_10_viewing.png` });
await viewer.$$eval('.viewing-bar button', (bs) => bs[0].click());
await wait(800);
await viewer.close();
await other.close();
await page.goto(CONSOLE + '/moderation', { waitUntil: 'networkidle2' });
await page.waitForSelector('main .card', { timeout: 15000 });
const modCards = await page.$$eval('main .card h2', (hs) => hs.map((h) => h.textContent));
check('Moderation shows its queue and its words', modCards.some((c) => /To review/.test(c)) && modCards.includes('Words'), modCards.join(', '));
await page.screenshot({ path: `${OUT}/console_11_moderation.png` });
// The admin's own studio sign-in in this browser was replaced by the view; sign in to the studio again for the last check.
await page.goto(STUDIO + '/signin', { waitUntil: 'networkidle2' });
await page.evaluate(async (body) => fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { email, password });
await page.goto(CONSOLE + '/overview', { waitUntil: 'networkidle2' });
await page.waitForSelector('.sidebar .menu-item');

// Signing out of the console leaves the studio signed in.
await page.$$eval('.sidebar .menu-item', (bs) => bs.find((b) => b.textContent.includes('Sign out')).click());
await page.waitForSelector('input[type=password]');
const me = await page.evaluate(async () => (await fetch('/api/console/me')).status);
check('signing out ends the console\'s session', me === 401, String(me));
await page.goto(STUDIO + '/projects', { waitUntil: 'networkidle2' });
const studio = await page.evaluate(async () => (await fetch('/api/auth/me')).status);
check('the studio stays signed in', studio === 200, String(studio));

check('no page errors', errors.length === 0, errors.slice(0, 5).join(' || '));
console.log(report.join('\n'));
await browser.close();
