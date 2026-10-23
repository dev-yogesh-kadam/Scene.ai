// The studio's health in the admin console: the agent's model server, maintenance mode, the watcher's alerts, and
// where alerts are sent (Telegram, ntfy). See backend/scene/health.py and phone.py.

import { api } from '../api.js';
import { el, field } from '../dom.js';
import { span, stamp, ago, table, facts } from './shared.js';

const LEVEL = { critical: 'Critical', serious: 'Serious', warning: 'Warning' };
const gb = (v) => (v / 1024 ** 3).toFixed(1) + ' GB';

// The agent's model server (Ollama): whether it answers, and the models it holds in memory now.
export function modelServerCard(m) {
  if (!m.url) {
    return el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Model server')),
      el('p', { class: 'muted' }, 'No local model server is set (ollama_url is empty in config.json). The agent uses hosted models only.'));
  }
  const until = (when) => { const left = (Date.parse(when) - Date.now()) / 1000; return left > 0 ? `unloads in ${span(left)}` : 'unloading'; };
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Model server'), el('span', { class: 'pill ' + (m.online ? 'done' : 'failed') }, m.online ? 'Online' : 'Offline')),
    facts([[m.online ? 'Online since' : 'Offline since', stamp(m.since)], ['Address', m.url], ['Ollama', m.version]]),
    !m.online && el('p', { class: 'muted' }, 'It does not answer. Check that the machine is on, Tailscale is connected and Ollama is running, and that ollama_url in config.json is right.'),
    m.online && el('h3', {}, 'In memory now'),
    m.online && (m.loaded.length
      ? table(['Model', 'Video memory', 'Size', ''], m.loaded.map((x) => [x.name, gb(x.vram), gb(x.size), el('span', { class: 'muted small' }, until(x.until))]))
      : el('p', { class: 'muted' }, 'No model is loaded. The first message to the agent loads one, which takes a moment.')));
}

// Maintenance mode: new jobs are refused and their credits given back; the waiting ones still finish.
export function maintenanceCard(m, ctx) {
  const text = el('textarea', { rows: 2, maxlength: 300, placeholder: 'The studio is under maintenance. New jobs can start again soon.' }, m.text || '');
  const notice = el('p', { class: 'notice' });
  const set = async (on, button, working) => {
    button.disabled = true;
    button.textContent = working;   // the section takes a moment to redraw: it asks both servers again
    try { await api('/api/admin/maintenance', { method: 'PUT', json: { on, text: text.value } }); await ctx.draw(); } catch (e) {
      notice.className = 'notice error';
      notice.textContent = e.message;
      button.disabled = false;
    }
  };
  const button = (label, on, working, primary) => {
    const b = el('button', { class: primary ? 'btn primary' : 'btn', onclick: () => set(on, b, working) }, label);
    return b;
  };
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Maintenance'), el('span', { class: 'pill ' + (m.on ? 'running' : 'done') }, m.on ? 'On' : 'Off')),
    el('p', { class: 'muted small' }, 'For a restart, an update or work on the render PC. While it is on, nobody can start a new job: they are told your message, which also shows at the top of the studio, and get their credits back. Jobs already waiting or running still finish.'),
    m.on && facts([['On since', stamp(m.since)], ['Left to finish', m.left ? `${m.left} job${m.left === 1 ? '' : 's'}` : 'None: the queue is empty, it is safe to restart']]),
    field('Message to users', text),
    notice,
    el('div', { class: 'row', style: 'margin-top:12px' },
      m.on
        ? [button('Update message', true, 'Saving…'), button('Turn off', false, 'Turning off…', true)]
        : button('Turn on', true, 'Turning on…', true)));
}

// What the watcher found: open alerts first, then the latest ones and how long each lasted.
export function alertsCard(a, ctx) {
  const row = (x) => el('button', { class: 'alert ' + x.level, onclick: () => ctx.go(x.tab || 'system') },
    el('span', { class: 'alert-level' }, LEVEL[x.level] || x.level), el('span', { class: 'alert-text' }, x.text),
    el('span', { class: 'muted small' }, 'since ' + stamp(x.started)));
  const past = a.recent.filter((x) => x.ended);
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Alerts'), el('span', { class: 'pill ' + (a.open.length ? 'failed' : 'done') }, a.open.length ? `${a.open.length} open` : 'All well')),
    el('p', { class: 'muted small' }, `The studio checks its servers, disk, backups and queue every ${a.every} seconds, also while nobody has the console open. A problem found ${a.confirm} times in a row is an alert: it is sent to your phone ${a.phone.on ? '(set up in Settings)' : '(once Phone alerts are set up in Settings)'}, and so is its end.`),
    a.open.length ? el('div', { class: 'attention' }, a.open.map(row)) : el('p', { class: 'muted' }, 'Nothing is wrong right now.'),
    past.length > 0 && el('h3', {}, 'Earlier'),
    past.length > 0 && table(['', 'What', 'When', 'Lasted'], past.slice(0, 15).map((x) => [
      el('span', { class: 'alert ' + x.level + ' static', style: 'padding:0;border:0;margin:0;background:none' }, el('span', { class: 'alert-level' }, LEVEL[x.level] || x.level)),
      el('span', { class: 'small' }, x.text), ago(x.started), span(x.ended - x.started)])));
}

// Where alerts go: a Telegram bot of the admin's own, or an ntfy topic, or both.
export function phoneCard(phone, ctx) {
  const token = el('input', { type: 'password', autocomplete: 'off', placeholder: phone.telegram_token_end ? `Saved (ends in ${phone.telegram_token_end})` : '123456789:AAH…' });
  const chat = el('input', { type: 'text', value: phone.telegram_chat, placeholder: 'Found for you, or a number' });
  const topic = `https://ntfy.sh/scene-${Math.random().toString(36).slice(2, 10)}`;
  const ntfy = el('input', { type: 'text', value: phone.ntfy_url, placeholder: topic });
  const notice = el('p', { class: 'notice' });
  const say = (ok, text) => { notice.className = 'notice ' + (ok ? 'ok' : 'error'); notice.textContent = text; };
  const run = async (button, work) => {
    button.disabled = true;
    try { await work(); } catch (e) { say(false, e.message); }
    button.disabled = false;
  };
  const save = el('button', { class: 'btn primary', onclick: () => run(save, async () => {
    await api('/api/admin/alerts/phone', { method: 'PUT', json: { telegram_token: token.value, telegram_chat: chat.value, ntfy_url: ntfy.value } });
    ctx.draw();
  }) }, 'Save');
  const find = el('button', { class: 'btn small', onclick: () => run(find, async () => {
    if (token.value) await api('/api/admin/alerts/phone', { method: 'PUT', json: { telegram_token: token.value } });
    const found = await api('/api/admin/alerts/telegram-chat', { method: 'POST' });
    chat.value = found.telegram_chat;
    say(true, `Found your chat (${found.telegram_chat}) and saved it.`);
  }) }, 'Find my chat');
  const test = el('button', { class: 'btn', disabled: !phone.on, onclick: () => run(test, async () => {
    const { results } = await api('/api/admin/alerts/test', { method: 'POST' });
    const failed = Object.entries(results).filter(([, problem]) => problem);
    say(!failed.length, failed.length
      ? failed.map(([channel, problem]) => `${channel === 'ntfy' ? 'ntfy' : 'Telegram'}: ${problem}.`).join(' ')
      : `Sent to ${Object.keys(results).map((c) => (c === 'ntfy' ? 'ntfy' : 'Telegram')).join(' and ')}. Check your phone.`);
  }) }, 'Send a test');
  const removeTelegram = phone.telegram_token_end && el('button', { class: 'btn quiet danger', onclick: () => run(removeTelegram, async () => {
    await api('/api/admin/alerts/phone', { method: 'PUT', json: { telegram: false } });
    ctx.draw();
  }) }, 'Remove Telegram');
  return el('div', { class: 'card narrow' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Phone alerts'), el('span', { class: 'pill ' + (phone.on ? 'done' : 'failed') }, phone.on ? 'On' : 'Off')),
    el('p', { class: 'muted small' }, 'When the render server or the model server stops answering, the disk fills, backups stop, jobs fail one after another or wait too long, your phone hears of it, and again when it is over. Use either or both.'),
    el('h3', {}, 'Telegram'),
    el('ol', { class: 'steps' },
      el('li', {}, 'In Telegram, talk to @BotFather, send /newbot and follow it. It gives you a token.'),
      el('li', {}, 'Paste the token here, then open your new bot and press Start.'),
      el('li', {}, 'Press Find my chat.')),
    field('Bot token', token),
    field('Chat', el('div', { class: 'row' }, chat, find)),
    el('h3', {}, 'ntfy'),
    el('p', { class: 'muted small' }, `Install the ntfy app, subscribe to a topic of your own (a name nobody can guess, like the one suggested), and paste its address here.`),
    field('Topic address', ntfy),
    notice,
    el('div', { class: 'row', style: 'margin-top:12px' }, save, test, removeTelegram));
}
