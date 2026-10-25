// The browser check: drives the canvas and the agent's conversation in headless Chrome against server.py on :8099.
// Start server.py first (fresh, so the account made here is the first one, an admin), then: node scripts/e2e/check.mjs
import { createRequire } from 'module';
import fs from 'fs';
import os from 'os';
import path from 'path';

const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const BASE = 'http://127.0.0.1:8099';
const OUT = path.join(os.tmpdir(), 'scene-e2e');   // where server.py put the test files; screenshots go here too
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const report = [];
const check = (label, ok, extra = '') => report.push(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  (' + extra + ')' : ''}`);

let cookie = '';
async function call(path, { method = 'GET', json, form } = {}) {
  const headers = { cookie };
  let body;
  if (json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  if (form) body = form;
  const r = await fetch(BASE + path, { method, headers, body });
  const set = r.headers.get('set-cookie');
  if (set) cookie = set.split(';')[0];
  const text = await r.text();
  if (!r.ok) throw new Error(`${path} ${r.status} ${text}`);
  try { return JSON.parse(text); } catch { return text; }
}

const CONSOLE = 'http://127.0.0.1:8098';
const EMAIL = 'tester' + Date.now() + '@example.com';
const PASSWORD = 'correct horse battery staple';
await call('/api/auth/register', { method: 'POST', json: { name: 'Tester', email: EMAIL, password: PASSWORD } });
const project = await call('/api/projects', { method: 'POST', json: { name: 'E2E' } });
async function upload(file, type) {
  const form = new FormData();
  form.append('file', new Blob([fs.readFileSync(file)], { type }), file.split(/[\\/]/).pop());
  form.append('project_id', String(project.id));
  return call('/api/library/upload', { method: 'POST', form });
}
const clip = await upload(`${OUT}/e2e_files/clip.mp4`, 'video/mp4');
const dog = await upload(`${OUT}/e2e_files/dog.png`, 'image/png');
const cat = await upload(`${OUT}/e2e_files/cat.png`, 'image/png');

const now = Date.now();
const settings = { workflow: 'video/h3_master', clips: 1, options: { quality: 'medium' } };
const runs = [
  { instruction: 'make a clip from [clip]', parts: [{ text: 'make a short clip from ' }, { id: clip.id, name: clip.name, kind: 'video' }],
    reply: `Here is **the clip**, made from [[item:${clip.id}]].\n- 3 seconds\n- landscape`, chips: { [`item:${clip.id}`]: { name: clip.name, kind: 'video' } },
    thought: 'They attached a clip and want a short shot from it. One 3 s landscape clip on MiniMax H3.',
    activity: [{ type: 'activity', icon: 'attach', text: 'Read what you attached: clip', at: 0.1 },
      { type: 'activity', icon: 'skill', text: 'Read the skill “Social video”', at: 0.2 },
      { type: 'thought', text: 'They attached a clip and want a short shot from it. One 3 s landscape clip on MiniMax H3.', seconds: 4.2, at: 4.4 },
      { type: 'activity', icon: 'plan', text: 'Checked and priced 1 step', at: 4.5 }],
    seconds: 4.6, total: 40, state: 'approved', approvedAt: now - 60000, ui: {},
    work: [{ icon: 'queue', text: 'Queued “Clip of the dog”', at: now - 60000 }, { icon: 'ready', text: '“Clip of the dog” is ready', at: now - 20000 },
      { icon: 'check', text: 'Checked “Clip of the dog”: it is what was asked for', at: now - 10000 }],
    steps: [{ name: 'Clip of the dog', workflow_title: 'MiniMax H3', kind: 'video', credits: 40, settings, job: 'fake-job-1',
      prompt: 'SCENE CONTEXT: a brown dog runs across a sunny park.\nREFERENCES: clip reference — take only the light for the park.\nACTION: the dog chases a red ball.\nCAMERA: tracking shot at dog height.\nLIGHT AND LOOK: warm late afternoon.\nAUDIO: birds, paws on grass.',
      current: { orientation: 'portrait', resolution: 480, duration: 3 }, shape: [360, 640], why: '3 s for one run; portrait for Reels',
      made: clip.id, madeInfo: { duration: 3, width: 360, height: 640 }, review: { passed: true, checks: [] } }] },
  { instruction: 'two pictures: a dog and a cat', parts: [{ text: 'two pictures: a dog and a cat' }], reply: 'Two pictures, side by side.',
    thought: 'Two stills on Z-Image Turbo, square for the feed.', activity: [{ type: 'thought', text: 'Two stills on Z-Image Turbo, square for the feed.', seconds: 2.1, at: 2.1 }],
    seconds: 2.2, total: 4, state: 'approved', approvedAt: now - 30000, ui: {},
    steps: [{ name: 'Dog portrait', workflow_title: 'FLUX.2 Klein 9B (distilled)', kind: 'image', credits: 2, settings: { workflow: 'image/image_t2i_flux2_klein_9b', clips: 1 }, job: 'fake-job-2',
      prompt: 'SCENE CONTEXT: a dog on a sofa.', current: {}, shape: [1, 1], made: dog.id, madeInfo: { width: 512, height: 512 }, review: { passed: false, problem: 'The dog has five legs.', checks: [] } },
    { name: 'Cat portrait', workflow_title: 'FLUX.2 Klein 9B (distilled)', kind: 'image', credits: 2, settings: { workflow: 'image/image_t2i_flux2_klein_9b', clips: 1 }, job: 'fake-job-3',
      prompt: 'SCENE CONTEXT: a cat on a windowsill.', current: {}, shape: [1, 1], made: cat.id, madeInfo: { width: 512, height: 512 } }] },
  { instruction: 'a kitchen scene', parts: [{ text: 'a kitchen scene. ' + 'The cook drops a pan, the servers run past, steam rises from every pot. '.repeat(8) }], reply: 'One shot of the kitchen at night.', total: 40, state: 'dismissed', ui: {},
    activity: [{ type: 'thought', text: 'A kitchen at night.', seconds: 1.4, at: 1.4 }], seconds: 1.5,
    steps: [{ name: 'Kitchen at night', workflow_title: 'MiniMax H3', kind: 'video', credits: 40, settings, prompt: 'SCENE CONTEXT: a kitchen at night.',
      current: { orientation: 'portrait', resolution: 480, duration: 5 } }] },
];
await call('/api/boards/agent', { method: 'PUT', json: { project: project.id, data: { tabs: [{ id: 't1', name: 'Agent 1', created: now, updated: now }], open: ['t1'], active: 't1' } } });
await call('/api/boards/agent-t1', { method: 'PUT', json: { project: project.id, data: { runs } } });

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'], defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
const [name, value] = cookie.split('=');
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument((pid) => {
  localStorage.setItem('scene.project', String(pid));
  localStorage.setItem('scene.panel.tab', 'agent');
  localStorage.setItem('scene.panel.width', '520');
}, project.id);
await page.goto(BASE + '/#/canvas', { waitUntil: 'networkidle2' });
await wait(1500);
const panel = await page.$('.side-panel');
if (!panel) {
  await page.screenshot({ path: `${OUT}/e2e_debug.png` });
  console.log('NO PANEL', JSON.stringify(errors), (await page.evaluate(() => document.body.innerText)).slice(0, 300));
  process.exit(1);
}
await panel.screenshot({ path: `${OUT}/e2e_1_conversation.png` });

check('three turns drawn', (await page.$$('.turn')).length === 3, `${(await page.$$('.turn')).length}`);
check('user bubble has a picture chip', !!(await page.$('.agent-said .md-chip')));
check('reply markdown: bold and list', !!(await page.$('.turn-reply .md b')) && !!(await page.$('.turn-reply .md ul li')));
check('reply chip for the clip', !!(await page.$('.turn-reply .md-chip')));
check('Worked fold present', (await page.$$eval('.fold.work .fold-head', (n) => n.map((x) => x.textContent))).some((t) => t.includes('Worked')));
check('Thought fold present', (await page.$$eval('.fold.thought .fold-head', (n) => n.map((x) => x.textContent))).some((t) => t.includes('Thought for 4s')));
check('cancelled plan folded', (await page.$$eval('.fold.cancelled .fold-head', (n) => n.map((x) => x.textContent))).some((t) => t.includes('Cancelled')));
check('no video plays in the panel: a still with its length', !(await page.$('.side-panel video')) && !!(await page.$('.result-media .clip-badge')));
const clipBox = await page.$eval('.result-media', (n) => { const r = n.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; });
check('a portrait clip keeps its shape, not stretched across the panel', clipBox.h <= 302 && clipBox.w < clipBox.h, JSON.stringify(clipBox));
check('a long message folds in its bubble', !!(await page.$('.agent-said p.clamped')) && !!(await page.$('.agent-said .more-btn')));
check('no credits in the conversation', !(await page.$('.turn-cost')));
check('image grid with 2 tiles', (await page.$$('.result-grid .res-tile')).length === 2);
check('failed check shown under the grid', !!(await page.$('.grid-review .agent-review.failed')));
await wait(800);
const frames = await page.$$eval('.keyframe img', (n) => n.map((img) => ({ ok: img.complete && img.naturalWidth > 0, src: img.getAttribute('src') })));
check('keyframes load', frames.length >= 2 && frames.every((f) => f.ok), JSON.stringify(frames.map((f) => f.ok)));
const crumbText = await page.$eval('.crumb', (n) => n.textContent).catch(() => '');
check('crumb names the shot', /Shot \d+ › Take \d+/.test(crumbText), crumbText);

// open the folds
for (const sel of ['.turn:nth-child(1) .fold.work > .fold-head', '.turn:nth-child(1) .fold.thought > .fold-head', '.turn:nth-child(1) .fold.info > .fold-head']) {
  const head = await page.$(sel);
  if (head) await head.click();
  await wait(150);
}
check('worked fold opens with rows', (await page.$$('.turn:nth-child(1) .fold.work .work-row')).length >= 3);
check('thought text shows', !!(await page.$('.turn:nth-child(1) .fold.thought .fold-text')));
check('generation information opens', !!(await page.$('.turn:nth-child(1) .fold.info .fold-body .step-tags')));
await panel.screenshot({ path: `${OUT}/e2e_2_folds_open.png` });

// scrolling stays where it is when a fold opens (the bug fixed earlier)
const before = await page.$eval('.agent-log', (n) => n.scrollTop);
await page.$eval('.agent-log', (n) => { n.scrollTop = 200; });
const atBefore = await page.$eval('.agent-log', (n) => n.scrollTop);
await page.$eval('.turn:nth-child(2) .fold.thought > .fold-head', (h) => h.click());   // a click that does not scroll first
await wait(200);
const atAfter = await page.$eval('.agent-log', (n) => n.scrollTop);
check('opening a fold keeps the scroll', Math.abs(atAfter - atBefore) < 2, `${atBefore} -> ${atAfter} (start ${before})`);

// a click on the clip shows it on the canvas
await page.$eval('.result-media', (n) => n.scrollIntoView({ block: 'center' }));
await page.click('.result-media', { offset: { x: 30, y: 30 } });
await wait(900);
const focus = await page.evaluate((id) => {
  const frame = document.querySelector('.frame.selected');
  const world = document.querySelector('.canvas-world');
  return { selected: !!frame, spot: !!document.querySelector('.frame.spotlight'), title: frame && frame.title, transform: world.style.transform };
}, clip.id);
check('clip selected and ringed on the canvas', focus.selected && focus.spot, JSON.stringify(focus));
await page.screenshot({ path: `${OUT}/e2e_3_canvas_focus.png` });

// thumbs on a tile
await page.$eval('.result-grid .res-tile', (n) => n.scrollIntoView({ block: 'center' }));
await page.hover('.result-grid .res-tile');
await page.click('.result-grid .res-tile .tile-rate .icon-btn');
await wait(500);
const rated = await call(`/api/library?project=${project.id}`);
check('thumbs up saved on the item', rated.items.find((i) => i.id === dog.id).rating === 1);

// live progress while the agent works, then the approval card
await page.click('.agent-input');
await page.keyboard.type('a dog in a park');
await page.keyboard.press('Enter');
await wait(700);
const live = await page.evaluate(() => ({ live: !!document.querySelector('.turn.live'), status: (document.querySelector('.turn.live .thinking-word') || {}).textContent,
  rows: [...document.querySelectorAll('.turn.live .work-row')].map((r) => r.textContent) }));
check('the message shows at once, with live work', live.live && !!live.status, JSON.stringify(live));
await panel.screenshot({ path: `${OUT}/e2e_4_live.png` });
await wait(2600);
const answered = await page.evaluate(() => ({ turns: document.querySelectorAll('.turn').length, live: !!document.querySelector('.turn.live'),
  card: !!document.querySelector('.step-card'), approve: [...document.querySelectorAll('.agent-approve button')].map((b) => b.textContent),
  thought: [...document.querySelectorAll('.fold.thought .fold-head')].map((h) => h.textContent).pop() }));
check('the plan arrives as an approval card', answered.turns === 4 && !answered.live && answered.card && answered.approve.includes('Approve'), JSON.stringify(answered));
await page.$eval('.agent-log', (n) => { n.scrollTop = n.scrollHeight; });
await wait(200);
await panel.screenshot({ path: `${OUT}/e2e_5_plan.png` });

// approving: the work is logged and the result block shows where the job is
await page.$$eval('.agent-approve button', (bs) => bs.find((b) => b.textContent === 'Approve').click());
await wait(2500);
const approved = await page.evaluate(() => {
  const turns = [...document.querySelectorAll('.turn')];
  const last = turns[turns.length - 1];
  return { result: !!last.querySelector('.result'), wait: (last.querySelector('.result-wait span') || {}).textContent || '',
    worked: [...last.querySelectorAll('.fold.work .fold-head')].map((h) => h.textContent).pop() || '' };
});
check('approved: a result block and the work log', approved.result && /Worked/.test(approved.worked), JSON.stringify(approved));
const retry = await page.evaluate(() => [...document.querySelectorAll('.turn:last-child .result button')].map((b) => b.textContent));
check('a failed job offers Try again', retry.includes('Try again'), retry.join(','));

// the history menu of the tabs, with the breakdown of what a conversation spent
await page.click('.agent-history-btn');
await wait(300);
const rows = await page.$$eval('.agent-history-row', (n) => n.map((r) => r.textContent));
check('history menu lists the conversation', rows.length === 1 && rows[0].includes('Agent 1'), rows.join(' | '));
await page.hover('.agent-history-row .agent-spend');
await wait(200);
const tabCard = await page.$$eval('.agent-spend-card div', (n) => n.map((x) => x.textContent));
check('history breakdown shows the four kinds', tabCard.length === 4 && tabCard[0].startsWith('Video'), tabCard.join(' | '));
check('a refunded job is not counted', tabCard[0] === 'Video40 cr' && tabCard[1] === 'Image4 cr', tabCard.join(' | '));
await page.screenshot({ path: `${OUT}/e2e_6_history.png` });

// the model under the message box: a quiet button with each model's price in its menu
await page.goto(BASE + '/#/canvas', { waitUntil: 'networkidle2' });
await wait(1200);
const lane = await page.$eval('.lane', (n) => getComputedStyle(n).backgroundImage).catch(() => 'no lane');
check('shot lanes have no dotted lines', lane === 'none', lane);
const picker = await page.$eval('.agent-model-btn', (b) => ({ shown: !b.classList.contains('hidden'), text: b.textContent, tag: b.tagName }));
check('model picker is a button with the model name', picker.shown && picker.tag === 'BUTTON' && picker.text.includes('gemini-3.6-flash'), JSON.stringify(picker));
await page.click('.agent-model-btn');
await wait(250);
const items = await page.$$eval('.pop .pop-item', (n) => n.map((x) => x.textContent));
check('the menu prices each model', items.some((t) => t.includes('2 cr a message')) && items.some((t) => t.includes('Free')), items.join(' | '));
const composer = await page.$('.agent-composer');
await page.screenshot({ path: `${OUT}/e2e_8_models.png`, clip: await (async () => { const b = await composer.boundingBox(); return { x: b.x - 10, y: b.y - 200, width: b.width + 20, height: b.height + 210 }; })() });
await page.keyboard.press('Escape');

// the canvas bar names its one project, with no way to switch to another
const bar = await page.$eval('.canvas-bar', (b) => ({ name: (b.querySelector('.canvas-project') || {}).textContent, select: !!b.querySelector('select') }));
check('canvas bar shows only this project', bar.name === 'E2E' && !bar.select, JSON.stringify(bar));
// Quick actions: Generate video has no "Continue from the end of" line
await page.$$eval('.panel-head .seg button', (bs) => bs[0].click());
await wait(300);
await page.$$eval('.quick-action', (bs) => bs.find((b) => b.textContent.includes('Generate video')).click());
await wait(800);
const quick = await page.evaluate(() => document.querySelector('.side-panel').innerText);
check('no Continue from the end of in Quick actions', !/Continue from the end of|Start on /.test(quick), quick.slice(0, 120).replace(/\s+/g, ' '));
// the admin console's Pricing section loads, with its Agent models card (the console is on its own port and sign-in)
await page.goto(CONSOLE + '/pricing', { waitUntil: 'networkidle2' });
await page.type('input[type=email]', EMAIL);
await page.type('input[type=password]', PASSWORD);
await Promise.all([page.waitForSelector('.sidebar'), page.click('button[type=submit]')]);
await wait(800);
const pricingText = await page.evaluate(() => document.querySelector('main').innerText);
check('Pricing tab loads with Agent models', pricingText.includes('Agent models') && !pricingText.includes('Not Found'), pricingText.slice(0, 80).replace(/\s+/g, ' '));

// the library shows the thumbs too: a mark on the card, and the buttons in the viewer
await page.goto(BASE + '/#/library', { waitUntil: 'networkidle2' });
await wait(800);
check('library card shows the thumbs up', !!(await page.$('.media .rated')));
await page.click('.media .rated');
await wait(500);
check('viewer has the thumbs, pressed', !!(await page.$('.viewer .viewer-rate .icon-btn.on')));
await page.screenshot({ path: `${OUT}/e2e_7_library.png` });

check('no page errors', errors.length === 0, errors.slice(0, 5).join(' || '));
console.log(report.join('\n'));
await browser.close();
