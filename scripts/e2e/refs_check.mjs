// The browser check of picture references in Quick actions → Generate image, for every model that takes them:
// 1) no references (the job carries none), 2) one, 3) the most the model takes, 4) REF 1 removed after two were added
// (the rest renumbered, and so are their names in the prompt). Then: switching to a model that takes fewer keeps what
// fits and says how many went; a required REF 1 keeps Generate off; a words-only model offers models with references.
// Generate is caught in the browser: nothing is queued. Start server.py first, then: node scripts/e2e/refs_check.mjs
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
const MODELS = [   // id, most references, a required first one, the name REF 1 and REF 2 have in a prompt
  ['image_t2i_flux2_klein_4b', 4, false, ['image 1', 'image 2']], ['image_t2i_flux2_klein_9b', 4, false, ['image 1', 'image 2']],
  ['image_t2i_flux2_dev', 4, false, ['image 1', 'image 2']], ['image_t2i_flux3_klein', 4, false, ['<ref_image_0>', '<ref_image_1>']],
  ['image_t2i_hidream_o1', 4, false, ['image 1', 'image 2']], ['image_t2i_qwen_image_21', 4, false, ['<image1>', '<image2>']],
  ['image_t2i_krea2_turbo', 1, false, ['the reference']], ['image_ref_edit', 6, true, ['Picture 1', 'Picture 2', 'Picture 2']],
  ['image_location_rebuild', 1, true, []],
];
const pictures = ['a', 'b', 'c', 'd', 'e', 'f'].map((n) => {   // six files, told apart by their names
  const file = path.join(OUT, `ref_${n}.png`);
  fs.copyFileSync(path.join(OUT, 'e2e_files', n.charCodeAt(0) % 2 ? 'dog.png' : 'cat.png'), file);
  return file;
});

const res = await fetch(BASE + '/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Refs', email: 'refs' + Date.now() + '@example.com', password: 'correct horse battery staple' }) });
const [name, value] = res.headers.get('set-cookie').split(';')[0].split('=');
const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--no-sandbox'], defaultViewport: { width: 1500, height: 1000 } });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const sent = [];
await page.setRequestInterception(true);
page.on('request', async (req) => {
  if (req.url().endsWith('/api/jobs') && req.method() === 'POST') {
    const body = req.postData() || (req.hasPostData() ? await req.fetchPostData() : '') || '';
    const refs = [...body.matchAll(/name="ref:([^"]+)"; filename="([^"]+)"/g)].map((m) => [m[1], m[2]]);
    const settings = JSON.parse((body.match(/name="settings"\r\n\r\n([\s\S]*?)\r\n--/) || [null, '{}'])[1]);
    sent.push({ refs, settings });
    return req.respond({ status: 200, contentType: 'application/json', body: '{"id":"caught","credits":0}' });
  }
  req.continue();
});
await page.setCookie({ name, value, url: BASE });
await page.evaluateOnNewDocument(() => localStorage.setItem('scene.panel.tab', 'quick'));
await page.goto(BASE + '/canvas', { waitUntil: 'networkidle2' });
await wait(1200);
await page.evaluate(() => [...document.querySelectorAll('.panel-quick button')].find((x) => x.textContent.trim().startsWith('Generate image'))?.click());
await wait(1500);

const pick = async (id) => {
  await page.evaluate((v) => { const s = document.querySelector('.panel-quick select[aria-label="Model"]'); s.value = v; s.dispatchEvent(new Event('change')); }, 'image/' + id);
  await wait(900);
};
const strip = () => page.evaluate(() => ({
  labels: [...document.querySelectorAll('.panel-quick .ref-slot .slot-label')].map((n) => n.textContent),
  empty: document.querySelectorAll('.panel-quick .ref-slot .slot-box:not(.filled)').length,
  offer: !!document.querySelector('.panel-quick .ref-offer'),
  note: document.querySelector('.panel-quick .ref-note')?.textContent || '',
  chips: [...document.querySelectorAll('.panel-quick .ref-chip')].map((c) => c.textContent),
  disabled: document.querySelector('.panel-quick .btn.generate').disabled,
  error: document.querySelector('.panel-quick .notice')?.textContent || '',
  prompt: document.querySelector('.panel-quick textarea[aria-label="Prompt"]').value }));
const add = async (file) => {   // the empty box's own file input
  const inputs = await page.$$('.panel-quick .ref-slot input[type=file]');
  const empty = await page.evaluateHandle(() => [...document.querySelectorAll('.panel-quick .ref-slot')].find((s) => !s.querySelector('.slot-box.filled'))?.querySelector('input[type=file]'));
  await (empty.asElement() || inputs[inputs.length - 1]).uploadFile(file);
  await wait(500);
};
const clearAll = async () => {
  for (let i = 0; i < 8; i += 1) {
    const gone = await page.evaluate(() => { const x = document.querySelector('.panel-quick .ref-slot .slot-clear'); if (x) x.click(); return !!x; });
    if (!gone) break;
    await wait(200);
  }
};
const setPrompt = (text) => page.evaluate((t) => { const p = document.querySelector('.panel-quick textarea[aria-label="Prompt"]'); p.value = t; p.dispatchEvent(new Event('input')); }, text);
const generate = async () => {
  const before = sent.length;
  await page.evaluate(() => document.querySelector('.panel-quick .btn.generate').click());
  for (let i = 0; i < 20 && sent.length === before; i += 1) await wait(200);
  return sent.length > before ? sent[sent.length - 1] : null;
};
const waitEnabled = async () => { for (let i = 0; i < 25; i += 1) { if (!(await strip()).disabled) return true; await wait(200); } return false; };

const only = process.env.ONLY ? process.env.ONLY.split(',') : null;
for (const [id, most, required, tokens] of MODELS.filter(([m]) => !only || only.includes(m))) {
  await wait(6000);   // the studio takes 120 price estimates a minute; this check makes many
  await pick(id);
  await clearAll();
  await setPrompt('a test');
  // 1) no references
  let s = await strip();
  if (required) {
    await wait(800);
    s = await strip();
    check(`${id}: REF 1 is required, Generate stays off without it`, s.disabled && s.empty === 1 && /\*/.test(s.labels[0]), JSON.stringify(s.labels));
  } else {
    await waitEnabled();
    const job = await generate();
    check(`${id}: 1) no references: one empty REFERENCE box, the job carries none`, s.labels.join() === 'REFERENCE' && job && job.refs.length === 0,
      job ? JSON.stringify(job.refs) : 'not sent');
  }
  // 2) one reference
  await add(pictures[0]);
  s = await strip();
  await waitEnabled();
  let job = await generate();
  check(`${id}: 2) one reference: REF 1 ${most > 1 ? 'and a new empty box' : 'and no more boxes'}, sent as REF 1`,
    s.labels[0] === 'REF 1' + (required ? ' *' : '') && s.empty === (most > 1 ? 1 : 0) && job && job.refs.length === 1 && job.refs[0][1] === 'ref_a.png',
    `${JSON.stringify(s.labels)} sent ${job ? JSON.stringify(job.refs) : 'nothing'} ${s.disabled ? 'button off' : ''} ${s.error}`);
  // 3) the most it takes
  for (let i = 1; i < most; i += 1) await add(pictures[i]);
  s = await strip();
  job = await generate();
  check(`${id}: 3) ${most} reference${most > 1 ? 's' : ''}: no empty box left, all sent in order`,
    s.empty === 0 && s.labels.length === most && job && job.refs.length === most && job.refs.every(([, f], i) => f === `ref_${'abcdef'[i]}.png`),
    job ? JSON.stringify(job.refs.map((r) => r[1])) : 'nothing');
  // 4) two references, named in the prompt; REF 1 removed: the second is REF 1 now, and so is its name
  if (most >= 2) {
    await clearAll();
    await add(pictures[0]);
    await add(pictures[1]);
    await setPrompt('');
    await page.evaluate(() => { for (const c of document.querySelectorAll('.panel-quick .ref-chip')) c.click(); });
    s = await strip();
    const named = s.prompt;
    await page.evaluate(() => document.querySelector('.panel-quick .ref-slot .slot-clear').click());
    await wait(400);
    s = await strip();
    job = await generate();
    const unique = new Set(tokens).size === tokens.length;
    check(`${id}: 4) REF 1 removed: REF 2 is REF 1 now${unique ? ', and so is its name in the prompt' : ''}`,
      s.labels.filter((l) => /^REF \d/.test(l)).length === 1 && job && job.refs.length === 1 && job.refs[0][1] === 'ref_b.png'
        && named.includes(tokens[0]) && named.includes(tokens[1])
        && (!unique || s.prompt === `[removed] ${tokens[0]}`) && (unique || s.prompt === named),
      `prompt "${named}" -> "${s.prompt}" labels ${JSON.stringify(s.labels)} sent ${job ? JSON.stringify(job.refs) : 'nothing'} ${s.error}`);
  }
}

// switching to a model that takes fewer
await pick('image_t2i_flux2_klein_4b');
await clearAll();
for (const f of pictures.slice(0, 3)) await add(f);
await pick('image_t2i_krea2_turbo');
let s = await strip();
check('switching from 3 references to a model that takes 1 keeps the first, and says 2 went', s.labels.join() === 'REF 1' && /takes 1 reference; 2 removed/.test(s.note), s.note);
// a model that makes pictures from words only
await pick('image_t2i_sdxl');
s = await strip();
check('a words-only model shows no boxes, and says the reference went', s.labels.length === 0 && s.offer && /words only; 1 reference removed/.test(s.note), s.note);
await page.evaluate(() => document.querySelector('.panel-quick .ref-offer').click());
await wait(300);
const offered = await page.evaluate(() => [...document.querySelectorAll('.pop .add-menu-item')].map((b) => b.textContent.trim()));
check('it offers every model that takes references, FLUX.2 Klein 4B and Reference Image Edit first',
  offered.length === 9 && offered[0].startsWith('Switch to FLUX.2 Klein 4B') && offered[1].startsWith('Switch to Reference Image Edit')
    && offered.some((t) => t.startsWith('Switch to HiDream-O1') && t.endsWith('up to 4 references')) && offered.some((t) => /Krea 2 Turbo.*up to 1 reference$/.test(t)),
  offered.join(' | '));
await page.evaluate(() => [...document.querySelectorAll('.pop .add-menu-item')].find((b) => b.textContent.includes('FLUX.2 Klein 4B')).click());
await wait(900);
s = await strip();
check('choosing it shows the reference boxes', s.labels.join() === 'REFERENCE', JSON.stringify(s.labels));
await pick('image_t2i_qwen_image_21');
const license = await page.evaluate(() => document.querySelector('.panel-quick .ref-license')?.textContent || '');
check('Qwen Image 2.1 says it is not for monetized content', /not for monetized/.test(license), license);
await page.$('.side-panel').then((p) => p && p.screenshot({ path: `${OUT}/refs_check.png` }));
check('no page errors', errors.length === 0, errors.join(' | ').slice(0, 300));
await browser.close();
console.log(report.join('\n'));
