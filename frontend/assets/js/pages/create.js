// The Create page: pick a workflow, fill its form, queue a generation.

import { api } from '../api.js';
import { el, field, segmented } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';
import { jobList } from '../components/jobs.js';
import { mediaCard } from '../components/media.js';
import { pickAsset, saveAssetDialog } from '../components/assets.js';

const ACCEPT = { image: 'image/*', video: 'video/*', audio: 'audio/*,video/*' };
const KIND_LABEL = { video: 'Video', image: 'Image' };

export function render(view) {
  const form = {
    kind: localStorage.getItem('scene.kind') || 'video',
    catalog: [], kinds: ['video', 'image'], fallback: '',
    wf: null, values: {}, options: {}, resolution: null, orientation: null, seedMode: 'fixed', name: '',
    clips: 1,        // more than 1 = a long video made of chained clips
    projectId: Number(localStorage.getItem('scene.project')) || null, projects: [],
    refs: {},        // slot id -> {file}, {existing: name on the render server} or {assetId}, plus {name, url}
    estimate: '', cost: null,
  };

  const tabs = el('div');
  const picker = el('select', { 'aria-label': 'Workflow', style: 'max-width:320px',
    onchange: (e) => selectWorkflow(e.target.value).catch(showError) });
  const note = el('p', { class: 'muted' });
  const fields = el('div');
  const estimate = el('div', { class: 'estimate' });
  const refsBlock = el('div');
  const tips = el('details', { class: 'tips' });
  const error = el('p', { class: 'error notice' });
  const generateLabel = el('span', {}, 'Generate');
  const cost = el('span', { class: 'cost' });
  const generateButton = el('button', { class: 'btn generate', onclick: () => generate(false) }, generateLabel, cost);
  const body = el('div', {}, fields, refsBlock, tips, error, el('div', { class: 'generate-bar' }, estimate, generateButton));
  const queue = el('div');
  const recent = el('div', { class: 'media-grid compact' });

  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Create'), tabs),
    el('div', { class: 'create' },
      el('div', { class: 'card create-form' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Workflow'), picker,
          el('button', { class: 'btn small quiet', title: 'Look for new workflow files', onclick: () => loadCatalog().catch(showError) }, 'Refresh')),
        note, body),
      el('div', {},
        el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Queue'),
          el('a', { class: 'btn small quiet', href: '#/queue' }, 'View all')), queue),
        el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Latest'),
          el('a', { class: 'btn small quiet', href: '#/library' }, 'Open library')), recent))));

  const byRole = (role) => form.wf.controls.find((c) => c.role === role);
  const showError = (e) => { error.textContent = e.message || String(e); };

  // ------------------------------------------------------------ workflows

  async function loadCatalog(wanted, saved) {
    const [list, projects] = await Promise.all([api('/api/workflows'), api('/api/projects')]);
    form.catalog = list.workflows;
    form.kinds = list.kinds;
    form.fallback = list.default;
    form.projects = projects.projects;
    if (!form.projects.some((p) => p.id === form.projectId)) form.projectId = null;
    drawCatalog(wanted, saved);
  }

  function drawCatalog(wanted, saved) {
    tabs.replaceChildren(segmented(form.kinds.map((k) => ({ id: k, label: KIND_LABEL[k] || k })), form.kind, (k) => {
      form.kind = k;
      localStorage.setItem('scene.kind', k);
      drawCatalog();
    }));
    const items = form.catalog.filter((w) => w.kind === form.kind);
    const usable = items.filter((w) => !w.error);
    picker.replaceChildren(...items.map((w) =>
      el('option', { value: w.id, disabled: !!w.error }, w.title + (w.error ? ' (not readable yet)' : ''))));
    picker.classList.toggle('hidden', !items.length);
    if (!usable.length) {
      form.wf = null;
      body.classList.add('hidden');
      note.textContent = items.length ? items[0].error
        : `No ${form.kind} workflows yet. Save a ComfyUI workflow into the workflows/${form.kind} folder, then press Refresh.`;
      return;
    }
    body.classList.remove('hidden');
    wanted = wanted || localStorage.getItem('scene.workflow.' + form.kind) || form.fallback;
    const pick = usable.find((w) => w.id === wanted) || usable[0];
    picker.value = pick.id;
    selectWorkflow(pick.id, pick.id === wanted ? saved : undefined).catch(showError);
  }

  async function selectWorkflow(id, saved) {
    const wf = await api('/api/workflows/' + id);
    form.wf = wf;
    localStorage.setItem('scene.workflow.' + form.kind, id);
    form.values = Object.fromEntries(wf.controls.map((c) => [c.id, c.default]));
    form.options = Object.fromEntries(wf.options.map((o) => [o.id, o.default]));
    form.resolution = wf.size && wf.size.resolution;
    form.orientation = wf.size && wf.size.orientation;
    form.seedMode = 'fixed';
    form.name = id.split('/')[1];
    form.clips = 1;
    form.refs = {};
    if (saved) {   // re-run from the library
      for (const c of wf.controls) if (saved.values && c.id in saved.values) form.values[c.id] = saved.values[c.id];
      for (const o of wf.options) if (saved.options && o.id in saved.options) form.options[o.id] = saved.options[o.id];
      if (wf.size) {
        form.resolution = saved.resolution || form.resolution;
        form.orientation = saved.orientation || form.orientation;
      }
      form.seedMode = saved.seed_mode || 'fixed';
      form.name = saved.name || form.name;
      form.clips = wf.chain ? Number(saved.clips) || 1 : 1;
      for (const r of wf.refs) {
        const old = saved.refs && saved.refs[r.id];
        if (old) form.refs[r.id] = existingRef(old);
      }
    }
    error.textContent = '';
    // A library item sent here with "Use as first frame".
    if (store.prefill) {
      const slot = wf.refs.find((r) => r.id === wf.slots[store.prefill.slot]);
      if (slot) form.refs[slot.id] = existingRef(store.prefill.ref);
      else showError(new Error('This workflow has no first-frame slot. Pick one that has, such as H3 Director.'));
      store.prefill = null;
    }
    note.textContent = wf.description + (wf.approximate ? ' Some node settings were guessed because the render server is offline.' : '');
    tips.classList.toggle('hidden', !wf.hints.length);
    tips.replaceChildren(el('summary', {}, 'Tips'), el('ul', {}, wf.hints.map((h) => el('li', {}, h))));
    drawForm();
    drawRefs();
  }

  const existingRef = (ref) => ({ existing: ref.comfy_name, name: ref.name,
    url: '/api/ref-preview?name=' + encodeURIComponent(ref.comfy_name) });

  // ------------------------------------------------------------ the form

  const seg = (choices, current, onPick) => segmented(choices, current, (id) => { onPick(id); drawForm(); });

  function numberInput(control, extra = {}) {
    return el('input', { type: 'number', value: form.values[control.id], step: control.type === 'int' ? 1 : 'any', ...extra,
      oninput: (e) => { form.values[control.id] = e.target.value; refreshEstimate(); } });
  }

  function projectField() {
    const select = el('select', { onchange: async (e) => {
      if (e.target.value === 'new') {
        const name = prompt('Name of the new project');
        if (name && name.trim()) {
          try {
            const created = await api('/api/projects', { method: 'POST', json: { name } });
            form.projects.push(created);
            form.projectId = created.id;
          } catch (err) { showError(err); }
        }
        drawForm();
        return;
      }
      form.projectId = Number(e.target.value) || null;
      localStorage.setItem('scene.project', form.projectId || '');
    } },
      el('option', { value: '' }, 'No project'),
      form.projects.map((p) => el('option', { value: p.id, selected: p.id === form.projectId }, p.name)),
      el('option', { value: 'new' }, 'New project…'));
    return field('Project', select);
  }

  function drawForm() {
    const wf = form.wf;
    const parts = [];
    const special = new Set();
    const promptControl = byRole('prompt');
    if (promptControl) {
      special.add(promptControl.id);
      const file = el('input', { type: 'file', accept: '.txt,text/plain', hidden: true, onchange: async (e) => {
        if (e.target.files[0]) { form.values[promptControl.id] = (await e.target.files[0].text()).trim(); drawForm(); }
      } });
      parts.push(el('div', { class: 'field' },
        el('div', { class: 'label' }, 'Prompt', el('button', { type: 'button', class: 'btn small quiet', onclick: () => file.click() }, 'Load .txt'), file),
        el('textarea', { placeholder: promptControl.label, oninput: (e) => { form.values[promptControl.id] = e.target.value; } }, form.values[promptControl.id] || ''),
        form.clips > 1 && el('div', { class: 'hint' }, 'One prompt is used for every clip. To give each clip its own prompt, separate them with a line containing only ---')));
    }

    const groups = wf.options.map((o) => field(o.label,
      seg(o.choices, form.options[o.id], (id) => { form.options[o.id] = id; }),
      el('div', { class: 'hint' }, (o.choices.find((c) => c.id === form.options[o.id]) || {}).hint || '')));
    const sizes = wf.resolutions.map((r) => ({ id: r, label: String(r) }));
    if (wf.size) {
      special.add(byRole('width').id).add(byRole('height').id);
      groups.push(field('Resolution', seg(sizes, form.resolution, (r) => { form.resolution = r; })));
      groups.push(field('Orientation', seg(['landscape', 'portrait', 'square'].map((o) => ({ id: o, label: o[0].toUpperCase() + o.slice(1) })),
        form.orientation, (o) => { form.orientation = o; })));
    }
    const res = byRole('resolution');
    if (res) {
      special.add(res.id);
      groups.push(field('Resolution (short edge)', el('div', { class: 'row' },
        seg(sizes, form.values[res.id], (r) => { form.values[res.id] = r; }), numberInput(res, { style: 'width:90px' }))));
    }
    const dur = byRole('duration');
    if (dur) {
      special.add(dur.id);
      groups.push(field(form.clips > 1 ? 'Length of each clip' : 'Duration', el('div', { class: 'row' },
        seg([5, 10, 15].map((d) => ({ id: d, label: d + ' s' })), Number(form.values[dur.id]), (d) => { form.values[dur.id] = d; }),
        numberInput(dur, { min: 1, style: 'width:80px', onchange: drawForm }))));
    }
    if (wf.chain) {
      const total = form.clips * Number(form.values[dur.id]);
      groups.push(field('Long video (number of clips)',
        seg([1, 2, 3, 4, 6].map((n) => ({ id: n, label: n === 1 ? 'Off' : '× ' + n })), form.clips, (n) => { form.clips = n; }),
        el('div', { class: 'hint' }, form.clips > 1
          ? `${form.clips} clips are made one after another, each starting on the last frame of the one before, then joined: about ${total} s in total.`
          : 'Make a longer video as several chained clips. Faster and steadier than one long clip.')));
    }
    const seed = byRole('seed');
    if (seed) {
      special.add(seed.id);
      groups.push(field('Seed', el('div', { class: 'row' },
        seg([{ id: 'random', label: 'Random' }, { id: 'fixed', label: 'Fixed' }], form.seedMode, (m) => { form.seedMode = m; }),
        form.seedMode === 'fixed' && numberInput(seed))));
    }
    parts.push(el('div', { class: 'grid2' }, groups));

    // Everything else the workflow exposes, labelled with the node's own title.
    const extra = [];
    const main = [];   // controls a presets file marks as primary stay in view
    for (const c of wf.controls.filter((x) => !special.has(x.id))) {
      const shelf = c.primary ? main : extra;
      if (c.type === 'bool') {
        shelf.push(el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!form.values[c.id],
          onchange: (e) => { form.values[c.id] = e.target.checked; } }), c.label));
      } else if (c.choices && c.choices.length > 4) {
        shelf.push(field(c.label, el('select', { onchange: (e) => { form.values[c.id] = e.target.value; refreshEstimate(); } },
          c.choices.map((x) => el('option', { value: x, selected: x === form.values[c.id] }, x)))));
      } else if (c.choices) {
        shelf.push(field(c.label, seg(c.choices.map((x) => ({ id: x, label: String(x) })), form.values[c.id], (x) => { form.values[c.id] = x; })));
      } else if (c.type === 'text') {
        shelf.push(field(c.label, el('textarea', { oninput: (e) => { form.values[c.id] = e.target.value; } }, form.values[c.id] || '')));
      } else if (c.type === 'string') {
        shelf.push(field(c.label, el('input', { type: 'text', value: form.values[c.id], oninput: (e) => { form.values[c.id] = e.target.value; } })));
      } else {
        shelf.push(field(c.label, numberInput(c)));
      }
    }
    if (main.length) parts.push(el('div', { class: 'grid2' }, main));
    parts.push(el('div', { class: 'grid2' },
      field('Name', el('input', { type: 'text', value: form.name, oninput: (e) => { form.name = e.target.value; } })), projectField()));
    // Settings most people leave alone stay folded away.
    if (extra.length) {
      const more = el('details', { class: 'more', ontoggle: (e) => { form.moreOpen = e.target.open; } }, el('summary', {}, `More settings (${extra.length})`), el('div', { class: 'grid2' }, extra));
      more.open = !!form.moreOpen;
      parts.push(more);
    }
    fields.replaceChildren(...parts);
    refreshEstimate();
  }

  // ------------------------------------------------------------ references

  function setRef(slot, value) {
    const old = form.refs[slot.id];
    if (old && old.file) URL.revokeObjectURL(old.url);
    if (value instanceof File) form.refs[slot.id] = { file: value, name: value.name, url: URL.createObjectURL(value) };
    else if (value) form.refs[slot.id] = value;
    else delete form.refs[slot.id];
    drawRefs();
  }

  async function chooseSaved(slot) {
    const asset = await pickAsset(slot.kind);
    if (asset) setRef(slot, { assetId: asset.id, name: asset.name, kind: asset.kind, url: `/api/assets/${asset.id}/file` });
  }

  function drawRefs() {
    const wf = form.wf;
    if (!wf.refs.length) { refsBlock.className = ''; return refsBlock.replaceChildren(); }
    refsBlock.className = 'form-section';
    refsBlock.replaceChildren(
      el('h2', {}, 'References'),
      el('p', { class: 'muted' }, 'All optional unless marked with *. Drop a file on a box, click it, or pick one of your saved assets.'),
      el('div', { class: 'refs' }, wf.refs.map((slot) => {
        const current = form.refs[slot.id];
        const file = el('input', { type: 'file', accept: ACCEPT[slot.kind], hidden: true,
          onchange: (e) => e.target.files[0] && setRef(slot, e.target.files[0]) });
        const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
        let content;
        if (!current) {
          content = slot.default ? `Uses ${slot.default} unless you add a file`
            : { image: 'Drop an image', video: 'Drop a video', audio: 'Drop audio or video' }[slot.kind];
        } else if (slot.kind === 'image') {
          content = el('img', { src: current.url, alt: '' });
        } else if (slot.kind === 'video') {
          content = el('video', { src: current.url, muted: true, preload: 'metadata' });
        } else {
          content = el('span', { class: 'note' }, '♪');
        }
        return el('div', {
          class: 'ref' + (current ? ' filled' : ''), title: slot.label,
          onclick: () => file.click(),
          ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('over'); },
          ondragleave: (e) => e.currentTarget.classList.remove('over'),
          ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove('over'); if (e.dataTransfer.files[0]) setRef(slot, e.dataTransfer.files[0]); },
        },
          el('div', { class: 'ref-label' }, slot.label + (slot.optional ? '' : ' *')),
          el('div', { class: 'ref-body' }, content),
          current && el('div', { class: 'ref-name' }, current.name),
          el('div', { class: 'ref-actions' },
            !current && el('button', { type: 'button', class: 'btn small quiet', title: 'Pick one of your saved assets', onclick: stop(() => chooseSaved(slot)) }, 'Saved'),
            current && current.file && el('button', { type: 'button', class: 'btn small quiet', title: 'Keep this file in your assets to reuse it',
              onclick: stop(() => saveAssetDialog({ file: current.file })) }, 'Save')),
          current && el('button', { type: 'button', class: 'remove', title: 'Remove', onclick: stop(() => setRef(slot, null)) }, '×'),
          file);
      })));
  }

  // ------------------------------------------------------------ estimate, warnings, generate

  function settings() {
    const refs = {};
    for (const [id, r] of Object.entries(form.refs)) {
      if (r.existing) refs[id] = { comfy_name: r.existing, name: r.name };
      else if (r.assetId) refs[id] = { asset_id: r.assetId };
    }
    return { workflow: form.wf.id, name: form.name, values: form.values, options: form.options,
      resolution: form.resolution, orientation: form.orientation, seed_mode: form.seedMode,
      clips: form.wf.chain ? form.clips : 1, project_id: form.projectId, refs };
  }

  let estimateTimer;
  function refreshEstimate() {
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      if (!form.wf) return;
      try {
        const quote = await api('/api/estimate', { method: 'POST', json: settings() });
        form.estimate = quote.text;
        form.cost = quote.credits;
        const short = quote.credits > quote.balance;
        cost.textContent = quote.credits + ' cr';
        estimate.replaceChildren(el('b', {}, quote.text),
          el('span', { class: short ? 'error' : '' }, short ? ` · this needs ${quote.credits} cr and you have ${quote.balance} cr` : ` · you have ${quote.balance} cr`));
      } catch (e) { estimate.textContent = e.message; }
    }, 150);
  }

  function warnings() {
    const dur = byRole('duration');
    const ctx = { ...form.options, resolution: form.resolution, orientation: form.orientation, clips: form.clips,
      duration: dur ? Number(form.values[dur.id]) : undefined };
    return form.wf.confirm.filter((c) => Object.entries(c.when).every(([k, v]) => [].concat(v).some((x) => x === ctx[k])));
  }

  function applyAlternative(set) {
    for (const [key, value] of Object.entries(set)) {
      if (key in form.options) form.options[key] = value;
      else if (byRole(key)) form.values[byRole(key).id] = value;
      else if (key !== 'clips' || form.wf.chain) form[key] = value;
    }
    drawForm();
  }

  function askToConfirm(hits) {
    const dialog = el('dialog', {},
      el('h2', {}, 'Before you start'),
      el('ul', {}, hits.map((h) => el('li', {}, h.message))),
      el('p', { class: 'muted', style: 'margin-top:10px' }, 'Estimated time: ' + (form.estimate || 'unknown')),
      el('div', { class: 'dialog-buttons' },
        el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
        hits.filter((h) => h.alt).map((h) => el('button', { class: 'btn', onclick: () => { dialog.close(); applyAlternative(h.alt.set); } }, h.alt.label)),
        el('button', { class: 'btn generate', onclick: () => { dialog.close(); generate(true); } }, 'Generate anyway')));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
  }

  async function generate(confirmed) {
    error.textContent = '';
    if (!form.wf) return;
    const promptControl = byRole('prompt');
    if (promptControl && !String(form.values[promptControl.id] || '').trim()) return showError(new Error('Write a prompt first.'));
    const hits = warnings();
    if (hits.length && !confirmed) return askToConfirm(hits);
    const data = new FormData();
    data.append('settings', JSON.stringify(settings()));
    for (const [id, r] of Object.entries(form.refs)) if (r.file) data.append('ref:' + id, r.file, r.name);
    generateButton.disabled = true;
    generateLabel.textContent = 'Uploading…';
    try {
      await api('/api/jobs', { method: 'POST', body: data });
      refreshJobs();
    } catch (e) { showError(e); }
    generateButton.disabled = false;
    generateLabel.textContent = 'Generate';
    refreshEstimate();
  }

  // ------------------------------------------------------------ side panels

  const drawQueue = () => queue.replaceChildren(jobList(store.jobs, { limit: 5 }));
  async function drawRecent() {
    const items = (await api('/api/library')).items.slice(0, 4);
    recent.replaceChildren(...(items.length ? items.map((i) => mediaCard(i)) : [el('div', { class: 'empty', style: 'grid-column:1/-1' }, 'Your finished work shows up here.')]));
  }

  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') drawQueue();
    if (change === 'library') { drawRecent().catch(() => {}); refreshEstimate(); }
    if (change === 'credits') refreshEstimate();
  });

  // ------------------------------------------------------------ start

  const rerun = store.rerun;
  store.rerun = null;
  if (rerun) form.kind = rerun.workflow.split('/')[0];
  if (store.prefill) form.kind = 'video';
  loadCatalog(rerun && rerun.workflow, rerun && rerun.settings).catch(showError);
  drawQueue();
  drawRecent().catch(() => {});
  return unsubscribe;
}
