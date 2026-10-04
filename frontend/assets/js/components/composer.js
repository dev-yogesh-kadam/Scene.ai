// The quick composer docked on the Canvas: a prompt, the few settings that matter most, and Generate.
// Everything else uses the workflow's own defaults; the Create page has the full form.

import { api } from '../api.js';
import { el } from '../dom.js';
import { subscribe, refreshJobs } from '../store.js';

const KIND_LABEL = { video: 'Video', image: 'Image' };

// startFrom(): the library item a new video should start on (the canvas selection), or null.
// projectId(): the project new work is filed under, or null.
export function composer({ startFrom = () => null, projectId = () => null } = {}) {
  const form = { catalog: [], wf: null, values: {}, options: {}, resolution: null, orientation: null, useStart: true };
  const start = el('div', { class: 'composer-start' });
  const prompt = el('textarea', { rows: 2, 'aria-label': 'Prompt', placeholder: 'Describe the shot',
    oninput: (e) => { const c = byRole('prompt'); if (c) form.values[c.id] = e.target.value; },
    onkeydown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate(); } });
  const readout = el('div', { class: 'readout' });
  const label = el('span', {}, 'Generate');
  const cost = el('span', { class: 'cost' });
  const button = el('button', { class: 'btn generate', title: 'Generate (Ctrl or ⌘ + Enter)', onclick: () => generate() }, label, cost);
  const note = el('p', { class: 'error notice' });
  const node = el('div', { class: 'composer' }, start, prompt, el('div', { class: 'composer-foot' }, readout, button), note);

  const byRole = (role) => form.wf && form.wf.controls.find((c) => c.role === role);
  const firstFrame = () => form.wf && form.wf.refs.find((r) => r.id === form.wf.slots.first_frame);
  const showError = (e) => { note.textContent = e.message || String(e); };

  async function loadCatalog() {
    const list = await api('/api/workflows');
    form.catalog = list.workflows.filter((w) => !w.error);
    if (!form.catalog.length) {
      node.classList.add('off');
      return showError(new Error('No workflows yet. Save a ComfyUI workflow into the workflows folder, then reload.'));
    }
    const kind = localStorage.getItem('scene.kind') || 'video';
    const wanted = localStorage.getItem('scene.workflow.' + kind) || list.default;
    await selectWorkflow((form.catalog.find((w) => w.id === wanted) || form.catalog[0]).id);
  }

  async function selectWorkflow(id) {
    const wf = await api('/api/workflows/' + id);
    const text = prompt.value;
    form.wf = wf;
    form.values = Object.fromEntries(wf.controls.map((c) => [c.id, c.default]));
    form.options = Object.fromEntries(wf.options.map((o) => [o.id, o.default]));
    form.resolution = wf.size && wf.size.resolution;
    form.orientation = wf.size && wf.size.orientation;
    if (byRole('prompt')) form.values[byRole('prompt').id] = text;   // keep what was typed when the workflow changes
    note.textContent = '';
    draw();
  }

  const cell = (name, choices, current, onPick) => el('label', { class: 'cell' }, el('span', {}, name),
    el('select', { onchange: (e) => { onPick(e.target.value); refreshEstimate(); } },
      choices.map((c) => el('option', { value: c.id, selected: String(c.id) === String(current) }, c.label))));

  function draw() {
    const wf = form.wf;
    const item = startFrom();
    if (item && firstFrame()) {
      start.replaceChildren(el('label', { class: 'check' },
        el('input', { type: 'checkbox', checked: form.useStart, onchange: (e) => { form.useStart = e.target.checked; } }),
        (item.kind === 'video' ? 'Continue from the end of ' : 'Start on ') + item.name));
    } else start.replaceChildren();

    const cells = [cell('Workflow', form.catalog.map((w) => ({ id: w.id, label: `${KIND_LABEL[w.kind] || w.kind} · ${w.title}` })), wf.id,
      (id) => selectWorkflow(id).catch(showError))];
    const sizes = wf.resolutions.map((r) => ({ id: r, label: String(r) }));
    if (wf.size) {
      cells.push(cell('Resolution', sizes, form.resolution, (r) => { form.resolution = Number(r); }));
      cells.push(cell('Orientation', ['landscape', 'portrait', 'square'].map((o) => ({ id: o, label: o[0].toUpperCase() + o.slice(1) })),
        form.orientation, (o) => { form.orientation = o; }));
    }
    const res = byRole('resolution');
    if (res) cells.push(cell('Resolution', sizes, form.values[res.id], (r) => { form.values[res.id] = Number(r); }));
    const dur = byRole('duration');
    if (dur) {
      const lengths = [...new Set([5, 10, 15, Number(form.values[dur.id])])].sort((a, b) => a - b);
      cells.push(cell('Length', lengths.map((d) => ({ id: d, label: d + ' s' })), form.values[dur.id], (d) => { form.values[dur.id] = Number(d); }));
    }
    for (const o of wf.options) cells.push(cell(o.label, o.choices, form.options[o.id], (id) => { form.options[o.id] = id; }));
    cells.push(el('a', { class: 'cell link', href: '#/create', title: 'Open the full form on the Create page' }, el('span', {}, 'More'), 'All settings'));
    readout.replaceChildren(...cells);
    refreshEstimate();
  }

  function settings(refs = {}) {
    return { workflow: form.wf.id, name: form.wf.id.split('/')[1], values: form.values, options: form.options,
      resolution: form.resolution, orientation: form.orientation, seed_mode: 'random', clips: 1, project_id: projectId(), refs };
  }

  let estimateTimer;
  function refreshEstimate() {
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      if (!form.wf) return;
      try {
        const quote = await api('/api/estimate', { method: 'POST', json: settings() });
        const short = quote.credits > quote.balance;
        cost.textContent = quote.credits + ' cr';
        button.disabled = short;
        button.title = `${quote.text} · Generate (Ctrl or ⌘ + Enter)`;
        note.textContent = short ? `You have ${quote.balance} cr. This needs ${quote.credits} cr.` : '';
      } catch (e) { showError(e); }
    }, 150);
  }

  function warnings() {
    const dur = byRole('duration');
    const ctx = { ...form.options, resolution: form.resolution, orientation: form.orientation, clips: 1,
      duration: dur ? Number(form.values[dur.id]) : undefined };
    return form.wf.confirm.filter((c) => Object.entries(c.when).every(([k, v]) => [].concat(v).some((x) => x === ctx[k])));
  }

  async function generate() {
    note.textContent = '';
    if (!form.wf || button.disabled) return;
    if (byRole('prompt') && !prompt.value.trim()) return showError(new Error('Write a prompt first.'));
    const item = form.useStart && firstFrame() ? startFrom() : null;
    if (form.wf.refs.some((r) => !r.optional && !(item && r.id === firstFrame().id))) {
      return showError(new Error('This workflow needs reference files. Add them on the Create page.'));
    }
    const hits = warnings();
    if (hits.length && !confirm(hits.map((h) => h.message).join('\n') + '\n\nGenerate anyway?')) return;
    button.disabled = true;
    label.textContent = 'Sending…';
    try {
      const refs = {};
      if (item) {
        const ref = await api(`/api/library/${item.id}/reference`, { method: 'POST' });
        refs[firstFrame().id] = { comfy_name: ref.comfy_name, name: ref.name };
      }
      const data = new FormData();
      data.append('settings', JSON.stringify(settings(refs)));
      await api('/api/jobs', { method: 'POST', body: data });
      refreshJobs();
    } catch (e) { showError(e); }
    button.disabled = false;
    label.textContent = 'Generate';
    refreshEstimate();
  }

  loadCatalog().catch(showError);
  const unsubscribe = subscribe((change) => { if (change === 'credits') refreshEstimate(); });
  // refresh(): call when the selection changes, so the "start on" line follows it.
  return { node, refresh: () => { form.useStart = true; if (form.wf) draw(); }, destroy: unsubscribe };
}
