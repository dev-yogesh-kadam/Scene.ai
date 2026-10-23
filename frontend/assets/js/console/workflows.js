// The console's Workflows section: what the render PC changed lately, who each workflow is offered to, what it needs
// that the render server lacks, its versions and what changed in each, and a test run. See backend/scene/versions.py.

import { api } from '../api.js';
import { el, segmented } from '../dom.js';
import { number, span, ago, stamp, table, drawer, section, facts } from './shared.js';

const AUDIENCE = [{ id: 'everyone', label: 'Everyone' }, { id: 'admins', label: 'Admins only' }, { id: 'off', label: 'Off' }];
const PILL = { everyone: ['done', 'Everyone'], admins: ['running', 'Admins only'], off: ['cancelled', 'Off'] };
const CHANGE = { first: ['done', 'On record'], new: ['running', 'New'], updated: ['running', 'Updated'], removed: ['cancelled', 'Removed'] };
const pill = ([kind, label]) => el('span', { class: 'pill ' + kind }, label);

// What a workflow needs that the render server lacked, in one short phrase ('' when nothing).
function lacking(w) {
  if (!w.missing) return '';
  const parts = [];
  if (w.missing.files.length) parts.push(`${w.missing.files.length} model file${w.missing.files.length === 1 ? '' : 's'}`);
  if (w.missing.nodes.length) parts.push(`${w.missing.nodes.length} node type${w.missing.nodes.length === 1 ? '' : 's'}`);
  return parts.length ? parts.join(' and ') + ' missing' : '';
}

function health(w) {
  if (w.error) return el('div', {}, el('span', { class: 'pill failed' }, 'Can\'t be read'), el('div', { class: 'error small' }, w.error));
  const lack = lacking(w);
  return lack ? el('span', { class: 'pill failed' }, lack) : el('span', { class: 'pill done' }, 'Ready');
}

const needsAttention = (w) => w.error || lacking(w) || !w.example;

async function openWorkflow(ctx, w, report) {
  const panel = drawer(w.title, el('p', { class: 'muted' }, 'Loading…'));
  const notice = el('p', { class: 'notice' });
  let audience = w.audience;
  const audienceBox = el('div');
  const drawAudience = () => audienceBox.replaceChildren(segmented(AUDIENCE, audience, async (v) => {
    try {
      await api('/api/admin/workflows/audience', { method: 'PUT', json: { workflow: w.id, audience: v } });
      audience = w.audience = v;
      drawAudience();
      ctx.draw();
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  }));
  drawAudience();
  const test = el('button', { class: 'btn primary', disabled: !!w.error, onclick: async () => {
    test.disabled = true;
    try {
      const job = await api('/api/admin/workflows/test', { method: 'POST', json: { workflow: w.id } });
      notice.className = 'notice ok';
      notice.textContent = `"${job.name}" is first in the queue, free. It runs once the render server answers, and the result goes to your library.`;
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
    test.disabled = false;
  } }, 'Test run');

  let history = [];
  try { history = (await api('/api/admin/workflows/history?workflow=' + encodeURIComponent(w.id))).versions; } catch (e) { /* shown empty */ }
  const lines = (changes) => (changes.length > 12
    ? el('details', {}, el('summary', { class: 'small' }, `${changes.length} changes`), el('ul', { class: 'small' }, changes.map((c) => el('li', {}, c))))
    : el('ul', { class: 'small' }, changes.map((c) => el('li', {}, c))));
  panel.replace(
    section('Offered to', audienceBox, el('p', { class: 'muted small' }, 'Admins only: you and the other admins see it on Create and the agent can use it for you; users don\'t, until you offer it to everyone.')),
    section('Try it', el('p', { class: 'muted small' }, 'Runs it once with its own settings and a sample prompt, as you: free, first in the queue, and even under maintenance.'), test, notice),
    w.missing && (w.missing.files.length || w.missing.nodes.length) && section('Missing on the render server',
      el('p', { class: 'muted small' }, `As its node list said ${report.nodes_saved ? ago(report.nodes_saved) : 'last time'}. A job would fail with "value not in list" or an unknown node.`),
      w.missing.files.length > 0 && table(['Model file', 'Node', 'Input'], w.missing.files.map((f) => [f.file, `${f.node} · ${f.type}`, f.input])),
      w.missing.nodes.length > 0 && el('p', {}, 'Node types not installed: ', w.missing.nodes.join(', '))),
    section('About it', facts([['File', w.file], ['Type', w.kind], ['Presets file', w.presets ? 'Yes' : 'No'], ['Price', w.example ? `${number(w.example)} credits ${w.kind === 'image' ? 'an image' : 'for 5 s'}` : 'Free'],
      ['Jobs', number(w.jobs)], ['Succeeded', w.done + w.failed ? Math.round((100 * w.done) / (w.done + w.failed)) + '%' : ''], ['Average time', span(w.avg_seconds)], ['Last used', w.last_used && ago(w.last_used)]])),
    section(`Versions (${history.length})`, history.length
      ? history.map((v) => el('div', { class: 'version' },
        el('div', { class: 'row' }, pill(CHANGE[v.change] || ['done', v.change]), el('span', { class: 'muted small' }, stamp(v.seen)), v.file && el('span', { class: 'muted small' }, v.file)),
        v.changes.length ? lines(v.changes) : el('p', { class: 'muted small' }, v.change === 'first' ? 'As it was when the record began.' : v.change === 'updated' ? 'Only spacing or order changed.' : '')))
      : el('p', { class: 'muted' }, 'None kept yet.')));
}

export async function workflows(ctx) {
  const report = await api('/api/admin/workflows');
  const s = ctx.state.workflows;
  const byId = Object.fromEntries(report.workflows.map((w) => [w.id, w]));
  const name = (id) => (byId[id] ? el('button', { class: 'link-button', onclick: () => openWorkflow(ctx, byId[id], report) }, byId[id].title) : el('span', { class: 'muted' }, id));

  const hold = el('input', { type: 'checkbox', checked: report.new_admins_only, onchange: async (e) => {
    try { await api('/api/admin/workflows/settings', { method: 'PUT', json: { new_admins_only: e.target.checked } }); } catch (err) { alert(err.message); e.target.checked = !e.target.checked; }
  } });
  const changes = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Changes from the render PC')),
    report.drops.length
      ? report.drops.map((d) => el('div', { class: 'drop' },
        el('div', { class: 'row' }, el('b', {}, stamp(d.seen)), el('span', { class: 'muted small' },
          [d.new.length && `${d.new.length} new`, d.updated.length && `${d.updated.length} updated`, d.removed.length && `${d.removed.length} removed`].filter(Boolean).join(' · '))),
        el('div', { class: 'drop-names' }, [...d.new.map((id) => ['new', id]), ...d.updated.map((id) => ['updated', id]), ...d.removed.map((id) => ['removed', id])]
          .map(([kind, id]) => el('span', { class: 'drop-name' }, pill(CHANGE[kind]), name(id))))))
      : el('p', { class: 'muted' }, report.since ? `No changes since the record began, ${stamp(report.since)}.` : 'No record yet.'),
    el('label', { class: 'check' }, hold, 'New workflows start for admins only, until you offer them to everyone'));

  const refresh = el('button', { class: 'btn small', onclick: async () => {
    refresh.disabled = true;
    refresh.textContent = 'Asking…';
    try { await api('/api/admin/workflows/nodes', { method: 'POST' }); ctx.draw(); } catch (e) { alert(e.message); refresh.disabled = false; refresh.textContent = 'Refresh now'; }
  } }, 'Refresh now');
  const attention = report.workflows.filter(needsAttention);
  const nodes = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Compared with the render server'), refresh),
    el('p', { class: 'muted small' }, report.nodes_saved
      ? `What each workflow needs is checked against the render server's node list from ${stamp(report.nodes_saved)} (${ago(report.nodes_saved)}). It is fetched again by itself when the server answers and the list is over 6 hours old.`
      : 'There is no node list from the render server yet: it is fetched once the server answers.'),
    report.nodes_saved && Date.now() / 1000 - report.nodes_saved > 3 * 86400 && el('p', { class: 'notice error' },
      'This list is old. Models and nodes installed on the render PC since then show as missing here until it is fetched again: start the render server and press Refresh now.'),
    facts([['Workflows', number(report.workflows.length)], ['Need attention', number(attention.length)],
      ['Offered to admins only', number(report.workflows.filter((w) => w.audience === 'admins').length)], ['Switched off', number(report.workflows.filter((w) => w.audience === 'off').length)]]));

  const shown = report.workflows.filter((w) => (s.show === 'attention' ? needsAttention(w) : s.show ? w.audience === s.show : true));
  const list = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Workflows'),
      segmented([{ id: '', label: 'All' }, { id: 'attention', label: 'Need attention' }, { id: 'admins', label: 'Admins only' }, { id: 'off', label: 'Off' }],
        s.show, (v) => { s.show = v; ctx.draw(); })),
    table(['Workflow', 'Type', 'Offered to', 'Health', 'Price', 'Jobs', 'Succeeded', 'Changed'],
      shown.map((w) => [
        el('div', {}, w.title, el('div', { class: 'muted small' }, w.file)), w.kind, pill(PILL[w.audience]), health(w),
        w.example ? number(w.example) + ' cr' : el('span', { class: 'pill failed' }, 'Free'), number(w.jobs),
        w.done + w.failed ? Math.round((100 * w.done) / (w.done + w.failed)) + '%' : '', w.changed ? ago(w.changed) : '']),
      { onRow: (i) => openWorkflow(ctx, shown[i], report), empty: 'None.' }),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, `Workflow files are read from ${report.folder}. Price: an image, or 5 seconds of video or sound. Select a workflow for its versions, a test run and who it is offered to.`));
  return [el('div', { class: 'grid-2' }, changes, nodes), list];
}
