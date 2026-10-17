// Imports each page module in Chrome against server.py on :8099 and prints any that fail to load. A broken module
// can pass `node --check` and still stop the page in the browser.
import { createRequire } from 'module';
const require = createRequire('C:/Scene/Scene.ai/motion/package.json');
const puppeteer = require('puppeteer-core');
const BASE = 'http://127.0.0.1:8099';
const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.goto(BASE + '/assets/img/logo.svg');
for (const f of ['dom.js', 'api.js', 'store.js', 'components/conversation.js', 'components/media.js', 'components/agent.js', 'components/agent-tabs.js', 'components/quick.js', 'components/memory.js', 'components/cast.js', 'pages/canvas.js', 'main.js']) {
  const out = await page.evaluate(async (u) => { try { await import(u); return 'ok'; } catch (e) { return e.message; } }, BASE + '/assets/js/' + f);
  console.log(f, '->', out);
}
await browser.close();
