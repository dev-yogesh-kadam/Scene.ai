// The console's Servers & APIs section: the ComfyUI servers the renders run on, the Ollama servers of the agent's local
// models, and hosted APIs that speak the OpenAI chat API. Each can be added, switched off or removed while the studio
// runs. A waiting render goes to the first ComfyUI server that is free; a call to a local model goes to the Ollama
// server that has it and is answering the fewest calls. See backend/scene/endpoints.py.

import { api } from '../api.js';
import { el, field } from '../dom.js';

const ABOUT = {
  comfy: 'Renders go to the first one that answers and is not rendering. The first is the main one: uploaded files are kept there and copied to the others when a render needs them.',
  ollama: 'The agent\'s local models. Every model these servers have is offered; each call goes to the server that has the model and is least busy.',
  openai: 'Hosted models through the OpenAI chat API (Kimi, Gemini, an Ollama behind /v1...). Its models show in the agent\'s model picker as "<name>/<model>".',
};
const PLACEHOLDER = { comfy: 'http://100.123.221.34:8188', ollama: 'https://name.trycloudflare.com', openai: 'https://api.moonshot.ai/v1' };

// The form for one: a new one (`row` without an id) or an existing one.
function form(kinds, row, ctx, close) {
  const kind = el('select', {}, Object.entries(kinds).map(([id, label]) => el('option', { value: id, selected: id === row.kind }, label)));
  // No autofill: a browser would put the console's sign-in email and password in the address and the key.
  const name = el('input', { type: 'text', autocomplete: 'off', maxlength: 60, value: row.name || '', placeholder: 'Zoro, Kaggle…' });
  const url = el('input', { type: 'text', autocomplete: 'off', value: row.url || '', placeholder: PLACEHOLDER[row.kind] });
  const key = el('input', { type: 'password', autocomplete: 'new-password', placeholder: row.has_key ? 'Kept; type to replace it' : 'Only for an API' });
  const models = el('input', { type: 'text', autocomplete: 'off', value: row.models || '', placeholder: 'Empty: all it has. Or qwen3:14b, kimi-k2.6' });
  const active = el('input', { type: 'checkbox', checked: row.active !== 0 });
  const notice = el('p', { class: 'notice' });
  kind.onchange = () => { url.placeholder = PLACEHOLDER[kind.value]; };
  const submit = el('button', { class: 'btn primary' }, row.id ? 'Save' : 'Add');
  const save = async () => {
    if (submit.disabled) return;   // one click, one server: a second click while it saves does nothing
    submit.disabled = true;
    submit.textContent = row.id ? 'Saving…' : 'Adding…';
    const body = { kind: kind.value, name: name.value, url: url.value, api_key: key.value, models: models.value, active: active.checked };
    try {
      await api('/api/admin/endpoints' + (row.id ? '/' + row.id : ''), { method: row.id ? 'PUT' : 'POST', json: body });
      ctx.draw();
    } catch (e) {
      notice.className = 'notice error'; notice.textContent = e.message;
      submit.disabled = false; submit.textContent = row.id ? 'Save' : 'Add';
    }
  };
  submit.onclick = save;
  return el('div', { class: 'card' },
    el('div', { class: 'grid2' }, field('What it is', kind), field('Name', name), field('Address', url), field('API key', key),
      field('Models', models)),
    el('label', { class: 'check' }, active, 'In use'),
    notice,
    el('div', { class: 'row', style: 'margin-top:12px' },
      submit,
      el('button', { class: 'btn quiet', onclick: close }, 'Cancel')));
}

const dot = (e) => el('span', { class: 'dot ' + (e.active && e.online ? 'online' : e.active ? 'offline' : '') });
// The address in full, to read and copy at a glance.
const address = (url) => !url ? el('p', { class: 'muted small' }, 'No address yet. Edit to add one.') : el('div', { class: 'endpoint-url' }, el('code', {}, url),
  el('button', { class: 'btn small quiet', onclick: () => navigator.clipboard.writeText(url) }, 'Copy'));

function line(e, kinds, ctx) {
  const slot = el('div');
  const remove = async () => {
    if (!confirm(`Remove ${e.name}?`)) return;
    try { await api('/api/admin/endpoints/' + e.id, { method: 'DELETE' }); ctx.draw(); } catch (err) { alert(err.message); }
  };
  const toggle = async () => {
    try { await api('/api/admin/endpoints/' + e.id, { method: 'PUT', json: { active: !e.active } }); ctx.draw(); } catch (err) { alert(err.message); }
  };
  const state = !e.active ? 'Off' : !e.online ? 'Not answering'
    : e.kind === 'comfy' ? (e.running ? 'Rendering' : 'Free') + (e.detail ? ' · ' + e.detail : '')
      : e.kind === 'ollama' ? `${e.calls ? e.calls + ' calls now' : 'Free'} · ${(e.found || []).join(', ') || 'no models'}`
        : 'Answers';
  const row = el('div', { class: 'card' },
    el('div', { class: 'card-head', style: 'justify-content:flex-start;gap:10px' },
      dot(e), el('h2', {}, e.name)),
    address(e.url),
    el('p', { class: 'muted small' }, state, e.models ? ` · offered: ${e.models}` : ''),
    el('div', { class: 'row' },
      el('button', { class: 'btn small', onclick: () => slot.replaceChildren(form(kinds, e, ctx, () => slot.replaceChildren())) }, 'Edit'),
      el('button', { class: 'btn small', onclick: toggle }, e.active ? 'Switch off' : 'Switch on'),
      el('button', { class: 'btn small quiet danger', onclick: remove }, 'Remove')),
    slot);
  return row;
}

let checkNow = false;   // Check again: every server is asked now, not what was found a few seconds ago

export async function servers(ctx) {
  const d = await api('/api/admin/endpoints' + (checkNow ? '?fresh=1' : ''));
  checkNow = false;
  // A new one is added in its own group: the form opens under that group's heading.
  const slots = Object.fromEntries(Object.keys(d.kinds).map((kind) => [kind, el('div')]));
  const add = (kind) => {
    Object.values(slots).forEach((slot) => slot.replaceChildren());
    slots[kind].replaceChildren(form(d.kinds, { kind, active: 1 }, ctx, () => slots[kind].replaceChildren()));
    slots[kind].querySelector('input').focus();
  };
  return [
    el('div', { class: 'row' },
      el('p', { class: 'muted', style: 'flex:1' }, 'Add a server or an API here and the studio uses it at once, no restart.'),
      el('button', { class: 'btn small', onclick: () => { checkNow = true; ctx.draw(); } }, 'Check again')),
    ...Object.entries(d.kinds).flatMap(([kind, label]) => [
      el('div', { class: 'card-head', style: 'margin-top:18px' }, el('h2', {}, label),
        el('button', { class: 'btn small primary', onclick: () => add(kind) }, 'Add')),
      el('p', { class: 'muted small' }, ABOUT[kind]),
      slots[kind],
      ...d.endpoints.filter((e) => e.kind === kind).map((e) => line(e, d.kinds, ctx)),
      d.endpoints.some((e) => e.kind === kind) ? null : el('p', { class: 'muted small' }, 'None yet.'),
    ]),
  ];
}
