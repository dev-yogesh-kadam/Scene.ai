// The console's Agent section: how the agent's models did (by model, by what they were asked for), its latest runs
// with every call and its words, a replay with another model, and the models of its roles. See backend/scene/traces.py.

import { api } from '../api.js';
import { el, field, segmented } from '../dom.js';
import { number, span, ago, stamp, tile, table, drawer, section, facts, person } from './shared.js';

const ROLES = [
  { id: 'main', label: 'Main model', hint: 'Plans and answers when the user picks none.', none: 'the first one there is' },
  { id: 'fast', label: 'Fast model', hint: 'The small jobs: image captions, notes, the check of a skill.', none: 'the model in use' },
  { id: 'vision', label: 'Vision model', hint: 'Looks at pictures for a model that can\'t.', none: 'the first local model that can see' },
];
const speed = (r) => (r.tokens_per_second ? `${r.tokens_per_second} tok/s` : '');
const tokens = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : number(n));

// A list of models to pick from, kept as typed text so a model can be named while the model server is off.
function modelList(id, models) {
  return el('datalist', { id }, models.map((m) => el('option', { value: m })));
}

function statsTable(rows, first) {
  return table([first, 'Calls', 'Failed', 'Average', 'Speed', 'Read', 'Written'], rows.map((r) => [
    r.model || r.purpose || '(none)', number(r.calls), r.errors ? el('span', { class: 'error' }, number(r.errors)) : '0',
    span(r.avg_seconds), speed(r), tokens(r.prompt_tokens), tokens(r.answer_tokens)]), { empty: 'No calls in this period.' });
}

function rolesCard(report, ctx) {
  const inputs = {};
  const notice = el('p', { class: 'notice' });
  const save = el('button', { class: 'btn primary', onclick: async () => {
    save.disabled = true;
    try {
      await api('/api/admin/agent/roles', { method: 'PUT', json: Object.fromEntries(ROLES.map((r) => [r.id, inputs[r.id].value])) });
      notice.className = 'notice ok';
      notice.textContent = 'Saved. The agent uses them from its next call.';
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
    save.disabled = false;
  } }, 'Save');
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Models for each role')),
    el('p', { class: 'muted small' }, report.models.length
      ? `Any of the ${report.models.length} models the model server and the hosted services have now. Empty follows config.json.`
      : 'The model server does not answer now, so no list: a model can still be named. Empty follows config.json.'),
    modelList('agent-models', report.models),
    ROLES.map((r) => {
      inputs[r.id] = el('input', { type: 'text', list: 'agent-models', value: report.roles[r.id], placeholder: `config.json: ${report.configured[r.id] || r.none}` });
      return field(r.label, inputs[r.id], el('div', { class: 'muted small' }, r.hint));
    }),
    notice, el('div', { class: 'row', style: 'margin-top:12px' }, save));
}

async function openCall(call, models, holder) {
  const kept = await api(`/api/admin/agent/calls/${call.id}`);
  const words = kept.exchange;
  const model = el('input', { type: 'text', list: 'agent-models-drawer', placeholder: call.model || 'the main model' });
  const out = el('div');
  const replay = el('button', { class: 'btn small', disabled: !words, onclick: async () => {
    replay.disabled = true;
    replay.textContent = 'Asking…';
    try {
      const r = await api(`/api/admin/agent/calls/${call.id}/replay`, { method: 'POST', json: { model: model.value } });
      out.replaceChildren(el('p', { class: 'muted small' }, `${r.model} · ${span(r.seconds)} · read ${tokens(r.usage.prompt)}, wrote ${tokens(r.usage.answer)}`
        + (r.pictures_left_out ? ` · its ${r.pictures_left_out} picture${r.pictures_left_out === 1 ? ' was' : 's were'} not kept, so not sent` : '')),
      el('pre', { class: 'words' }, JSON.stringify(r.answer, null, 2)));
    } catch (e) { out.replaceChildren(el('p', { class: 'error' }, e.message)); }
    replay.disabled = false;
    replay.textContent = 'Replay';
  } }, 'Replay');
  holder.replaceChildren(
    words
      ? el('div', {},
        words.messages.map((m) => el('details', { class: 'words-part' },
          el('summary', {}, `${m.role}${m.images ? ` · ${m.images} picture${m.images === 1 ? '' : 's'}` : ''} · ${number(String(m.content || '').length)} characters`),
          el('pre', { class: 'words' }, String(m.content || '')))),
        el('details', { class: 'words-part', open: true }, el('summary', {}, 'answer'), el('pre', { class: 'words' }, JSON.stringify(words.answer, null, 2))))
      : el('p', { class: 'muted small' }, 'Its words are no longer kept: they are kept for a week.'),
    words && el('div', { class: 'row', style: 'margin-top:8px' }, modelList('agent-models-drawer', models), model, replay),
    out);
}

async function openRun(run, models) {
  const panel = drawer('Agent run', el('p', { class: 'muted' }, 'Loading…'));
  const found = await api('/api/admin/agent/runs/' + encodeURIComponent(run.run));
  panel.replace(
    section('Run', facts([['Who', found.user ? `${found.user.name} (${found.user.email})` : 'The studio itself (a job, a check)'], ['Started', stamp(run.started)],
      ['Calls', number(found.calls.length)], ['Time', span(run.seconds)], ['Tokens', tokens(run.tokens)]])),
    section('Calls, in order', found.calls.map((c, i) => {
      const holder = el('div');
      return el('div', { class: 'version' },
        el('div', { class: 'row' }, el('b', {}, `${i + 1}. ${c.purpose}`), c.tool && el('span', { class: 'pill running' }, c.tool),
          el('span', { class: 'muted small' }, `${c.model || c.asked || '?'} · ${span(c.seconds)} · read ${tokens(c.prompt_tokens)}, wrote ${tokens(c.answer_tokens)}`),
          el('button', { class: 'btn small quiet', onclick: (e) => { e.currentTarget.remove(); openCall(c, models, holder); } }, 'Words and replay')),
        c.error && el('p', { class: 'error small' }, c.error), holder);
    })));
}

export async function agent(ctx) {
  const s = ctx.state.agent;
  const report = await api('/api/admin/agent?days=' + s.days);
  const t = report.totals;
  return [
    el('div', { class: 'row', style: 'margin-bottom:12px' }, el('span', { class: 'muted' }, 'Period'),
      segmented([{ id: 1, label: 'Today' }, { id: 7, label: '7 days' }, { id: 30, label: '30 days' }], report.days, (d) => { s.days = d; ctx.draw(); })),
    el('div', { class: 'tiles kpis' },
      tile('Calls to the models', number(t.calls || 0)),
      tile('Failed', number(t.errors || 0), t.calls ? Math.round((100 * (t.errors || 0)) / t.calls) + '% of them' : ''),
      tile('Average answer', span(t.avg_seconds) || '–'),
      tile('Writing speed', t.tokens_per_second ? `${t.tokens_per_second}` : '–', 'tokens a second'),
      tile('Tokens', tokens((t.prompt_tokens || 0) + (t.answer_tokens || 0)), `read ${tokens(t.prompt_tokens || 0)} · wrote ${tokens(t.answer_tokens || 0)}`)),
    el('div', { class: 'grid-2' },
      el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'By model')), statsTable(report.by_model, 'Model')),
      el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'By what it was asked')), statsTable(report.by_purpose, 'For'))),
    el('div', { class: 'grid-2' },
      el('div', { class: 'card' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Latest runs'), el('span', { class: 'muted small' }, 'a run: the calls of one request')),
        table(['When', 'Who', 'For', 'Model', 'Tools', 'Calls', 'Time'], report.runs.map((r) => [
          ago(r.started), r.user_name ? person(r.user_name, r.user_email) : el('span', { class: 'muted' }, 'the studio'),
          r.purposes.join(', '), el('span', { class: 'small' }, r.models.join(', ')), el('span', { class: 'small' }, r.tools.join(', ')),
          r.errors ? el('span', { class: 'error' }, `${r.calls} (${r.errors} failed)`) : number(r.calls), span(r.seconds)]),
        { onRow: (i) => openRun(report.runs[i], report.models), empty: 'No calls yet. They appear as people use the agent.' }),
        el('p', { class: 'muted small', style: 'margin-top:10px' }, 'Each call is kept for 30 days; its words (what was sent and the answer) for a week, to read them again or replay them with another model.')),
      rolesCard(report, ctx)),
  ];
}
