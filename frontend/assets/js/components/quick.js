// The Quick actions tab of the Canvas panel: pick what to make, then fill a short form for it.
// Images, videos and audio each open the same form, built from the workflows of that kind.

import { api } from '../api.js';
import { el, icon } from '../dom.js';
import { subscribe, refreshJobs } from '../store.js';
import { pickAsset } from './assets.js';
import { motionForm, sequenceForm } from './motion.js';

const ACCEPT = { image: 'image/*', video: 'video/*', audio: 'audio/*,video/*' };
const ACTIONS = [
  { id: 'image', label: 'Generate image', icon: 'image' },
  { id: 'video', label: 'Generate video', icon: 'video' },
  { id: 'audio', label: 'Generate audio', icon: 'audio' },
  { id: 'upscaler', label: 'Upscale video', icon: 'upscale' },   // takes the video selected on the canvas; no prompt
];
const ORIENTATIONS = ['landscape', 'portrait', 'square'];
const SHOWN = 3;   // reference boxes in view before "More references" is pressed

const capital = (text) => text[0].toUpperCase() + text.slice(1);
const short = (label) => label.split(' (')[0];   // "First frame (the video starts on this image)" -> "First frame"

// startFrom(): the library item a new video should start on (the canvas selection), or null.
// projectId(): the project new work is filed under, or null.
export function quickActions({ startFrom = () => null, projectId = () => null } = {}) {
  const form = { catalog: [], wf: null, values: {}, options: {}, resolution: null, orientation: null, useStart: true,
    kind: 'video', refs: {}, allRefs: false };   // refs: slot id -> {file}, {assetId} or {itemId} (a library item, as the cast is), plus {name, url}
  let page = 'home';
  const node = el('div', { class: 'quick' });

  // ------------------------------------------------------------ the list of actions

  // Motion graphics: titles and overlays drawn from templates. They are rendered on this machine and cost nothing.
  let motion = null;         // {ready, detail, templates}, once it has been asked for
  let motionPage = null;     // the open template's form
  let sequencePage = null;   // the form of a whole motion video
  const motionCards = el('div');

  function drawMotion() {
    if (!motion) return motionCards.replaceChildren(el('p', { class: 'muted small' }, 'Loading…'));
    motionCards.replaceChildren(
      ...(motion.ready ? [] : [el('p', { class: 'muted small' }, motion.detail)]),
      el('div', { class: 'quick-actions' },
        el('button', { class: 'quick-action', disabled: !motion.ready, title: 'A whole video of animated words, written from what it is about', onclick: openSequence },
          icon('play'), el('b', {}, 'Motion video'), el('span', { class: 'slate-text' }, 'A whole video')),
        motion.templates.map((t) =>
          el('button', { class: 'quick-action', disabled: !motion.ready, title: t.description, onclick: () => openMotion(t) },
            icon(t.needs === 'video' ? 'video' : 'title'), el('b', {}, t.title), el('span', { class: 'slate-text' }, t.needs === 'video' ? 'Over a video' : 'On its own')))));
  }

  // The form of a whole motion video is kept, so its scenes are still there after a look at the other actions.
  function openSequence() {
    page = 'motion';
    sequencePage = sequencePage || sequenceForm({ projectId, onBack: () => show('home') });
    motionPage = sequencePage;
    node.replaceChildren(motionPage.node);
  }

  function openMotion(template) {
    page = 'motion';
    motionPage = motionForm({ template, source: () => { const item = startFrom(); return item && item.kind === 'video' ? item : null; },
      projectId, onBack: () => show('home') });
    node.replaceChildren(motionPage.node);
  }

  function drawHome() {
    motionPage = null;
    drawMotion();
    node.replaceChildren(el('div', { class: 'quick-body' },
      el('h3', {}, 'Create'),
      el('p', { class: 'muted small' }, 'Make something new from a prompt and references.'),
      el('div', { class: 'quick-actions' }, ACTIONS.map((a) =>
        el('button', { class: 'quick-action', disabled: !!a.soon, onclick: () => show(a.id) },
          icon(a.icon), el('b', {}, a.label), a.soon && el('span', { class: 'slate-text' }, 'Coming soon')))),
      el('h3', { style: 'margin-top:24px' }, 'Motion graphics'),
      el('p', { class: 'muted small' }, 'Whole videos of animated words, titles and overlays, drawn and rendered here. Priced by the second.'),
      motionCards));
    if (!motion) api('/api/motion/templates').then((found) => { motion = found; drawMotion(); })
      .catch((e) => motionCards.replaceChildren(el('p', { class: 'error small' }, e.message)));
  }

  function show(next) {
    page = next;
    if (page === 'home') return drawHome();
    const changed = form.kind !== page;   // the form is shared: another kind means another list of workflows
    form.kind = page;
    title.textContent = label.textContent = action().label;
    node.replaceChildren(
      el('div', { class: 'quick-head' },
        el('button', { class: 'icon-btn', title: 'Back to quick actions', 'aria-label': 'Back to quick actions', onclick: () => show('home') }, icon('back')),
        title),
      el('div', { class: 'quick-body' }, model, about, start, source,
promptField, texts, note),
      el('div', { class: 'quick-foot' }, pills, button));
    if (form.wf && !changed) draw(); else loadCatalog().catch(showError);
  }

  // ------------------------------------------------------------ the form of one action

  const action = () => ACTIONS.find((a) => a.id === form.kind);
  const title = el('b');
  const model = el('div', { class: 'field' });
  const about = el('p', { class: 'muted small' });
  const start = el('div', { class: 'composer-start' });
  const source = el('div', { class: 'field' });
  const prompt = el('textarea', { rows: 5, 'aria-label': 'Prompt', placeholder: 'Describe the shot',
    oninput: (e) => { setPrompt(e.target.value); original = null; drawImprove(); },
    onkeydown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate(); } });
  const texts = el('div');   // further text boxes a presets file keeps in view, such as the lyrics of a song
  const note = el('p', { class: 'error notice' });
  // The agent rewrites the prompt into a fuller one; Undo brings back what was typed, until the prompt is edited again.
  let original = null;
  const improveButton = el('button', { type: 'button', class: 'btn small agent', onclick: () => (original === null ? improve() : undo()) });
  const drawImprove = () => {
    improveButton.replaceChildren(original === null ? 'Improve prompt' : 'Undo');
    improveButton.title = original === null ? 'Have the agent rewrite this prompt with more detail. Costs nothing.' : 'Bring back the prompt you wrote';
  };
  const setPrompt = (text) => { const c = byRole('prompt'); if (c) form.values[c.id] = text; };
  const undo = () => { prompt.value = original; setPrompt(original); original = null; drawImprove(); };
  async function improve() {
    note.textContent = '';
    const typed = prompt.value.trim();
    if (!typed) return showError(new Error('Write a prompt first, then improve it.'));
    improveButton.disabled = true;
    improveButton.replaceChildren(el('i', { class: 'cell-mark stepping' }), 'Improving');
    try {
      const better = await api('/api/agent/improve', { method: 'POST', json: { prompt: typed, kind: form.kind, project_id: projectId(), workflow: form.wf ? form.wf.id : null,
          model: localStorage.getItem('scene.agent.model') || null } });
      if (prompt.value.trim() === typed) {   // left alone if the prompt was edited while the agent worked
        original = prompt.value;
        prompt.value = better.prompt;
        setPrompt(better.prompt);
      }
    } catch (e) { showError(e); }
    improveButton.disabled = false;
    drawImprove();
  }
  drawImprove();
  const promptField = el('div', { class: 'field' }, el('div', { class: 'label' }, 'Prompt', el('span', { style: 'flex:1' }), improveButton), prompt);
  const pills = el('div', { class: 'quick-pills' });
  const label = el('span');
  const cost = el('span', { class: 'cost' });
  const time = el('span', { class: 'slate-text' });
  const button = el('button', { class: 'btn generate', title: 'Generate (Ctrl or ⌘ + Enter)', onclick: () => generate() }, label, cost);

  const byRole = (role) => form.wf && form.wf.controls.find((c) => c.role === role);
  const firstFrame = () => form.wf && form.wf.refs.find((r) => r.id === form.wf.slots.first_frame);
  const showError = (e) => { note.textContent = e.message || String(e); };

  async function loadCatalog() {
    const list = await api('/api/workflows');
    form.catalog = list.workflows.filter((w) => !w.error && w.kind === form.kind);
    form.wf = null;
    button.disabled = !form.catalog.length;
    if (!form.catalog.length) {
      for (const part of [model, about, start, source, pills]) part.replaceChildren();
      return showError(new Error(`No ${form.kind} workflows yet. Save a ComfyUI workflow into the workflows/${form.kind} folder, then reload.`));
    }
    const wanted = localStorage.getItem('scene.workflow.' + form.kind) || list.default;
    await selectWorkflow((form.catalog.find((w) => w.id === wanted) || form.catalog[0]).id);
  }

  async function selectWorkflow(id) {
    const wf = await api('/api/workflows/' + id);
    const text = prompt.value;
    for (const ref of Object.values(form.refs)) if (ref.file) URL.revokeObjectURL(ref.url);
    form.wf = wf;
    form.refs = {};
    form.allRefs = false;
    form.values = Object.fromEntries(wf.controls.map((c) => [c.id, c.default]));
    form.options = Object.fromEntries(wf.options.map((o) => [o.id, o.default]));
    form.resolution = wf.size && wf.size.resolution;
    form.orientation = wf.size && wf.size.orientation;
    if (byRole('prompt')) form.values[byRole('prompt').id] = text;   // keep what was typed when the workflow changes
    localStorage.setItem('scene.workflow.' + form.kind, id);
    note.textContent = '';
    follow();
    draw();
    recast();
  }

  // An upscale works on the video selected on the canvas: it fills the workflow's video slot, and follows the
  // selection until a file is put there by hand.
  const upscaled = () => form.kind === 'upscaler' && form.wf && form.wf.refs.find((r) => r.kind === 'video');
  function takeSelection() {
    const slot = upscaled();
    if (!slot || (form.refs[slot.id] && !form.refs[slot.id].selection)) return;
    const item = startFrom();
    if (item && item.kind === 'video') {
      form.refs[slot.id] = { itemId: item.id, name: item.name, takes: 'video', shown: 'image', url: `/api/library/${item.id}/poster`, selection: true };
    } else delete form.refs[slot.id];
  }

  // A video that starts on a frame takes that frame's shape: a portrait picture in a landscape video comes out squashed.
  function follow() {
    const item = form.wf && firstFrame() && !form.refs[firstFrame().id] ? startFrom() : null;
    const made = item && item.context;
    if (!made || !made.width || !made.height) return;
    const ratio = made.width / made.height;
    if (form.wf.size) form.orientation = ratio > 1.15 ? 'landscape' : ratio < 0.87 ? 'portrait' : 'square';
    const of = (choice) => { const m = /^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)/.exec(String(choice)); return m ? m[1] / m[2] : null; };
    const aspect = form.wf.controls.find((c) => c.input === 'aspect_ratio' && c.choices);
    const fits = aspect ? aspect.choices.filter(of) : [];
    if (fits.length) form.values[aspect.id] = fits.reduce((best, c) => (Math.abs(Math.log(of(c) / ratio)) < Math.abs(Math.log(of(best) / ratio)) ? c : best));
  }

  // Put the project's cast into the slots this workflow has for it. A slot the user filled is left alone.
  async function recast() {
    const wf = form.wf;
    if (!wf) return;
    let fills = [];
    try { fills = (await api(`/api/cast?project=${projectId() || 0}&workflow=${encodeURIComponent(wf.id)}`)).fills; } catch (e) { /* no cast, then */ }
    if (form.wf !== wf) return;
    for (const [slot, ref] of Object.entries(form.refs)) if (ref.cast) delete form.refs[slot];
    for (const f of fills) {
      if (!form.refs[f.slot]) form.refs[f.slot] = { itemId: f.id, name: f.name, takes: f.kind, shown: f.item_kind, url: `/api/library/${f.id}/file`, cast: true };
    }
    if (page !== 'home' && page !== 'motion') drawSource();
  }

  const pill = (name, choices, current, onPick) => el('select', { class: 'opt', title: name, 'aria-label': name,
    onchange: (e) => { onPick(e.target.value); refreshEstimate(); } },
    choices.map((c) => el('option', { value: c.id, selected: String(c.id) === String(current) }, c.label)));

  function draw() {
    const wf = form.wf;
    takeSelection();
    model.replaceChildren(el('div', { class: 'label' }, 'Model', el('span', { style: 'flex:1' }), time),
      el('select', { 'aria-label': 'Model', onchange: (e) => selectWorkflow(e.target.value).catch(showError) },
        form.catalog.map((w) => el('option', { value: w.id, selected: w.id === wf.id }, w.title))));
    about.textContent = wf.description;
    promptField.classList.toggle('hidden', !byRole('prompt'));
    drawSource();
    texts.replaceChildren(...wf.controls.filter((c) => c.primary && c.type === 'text' && !c.role).map((c) =>
      el('div', { class: 'field' }, el('div', { class: 'label' }, short(c.label)),
        el('textarea', { rows: 5, 'aria-label': short(c.label), placeholder: c.label, oninput: (e) => { form.values[c.id] = e.target.value; } }, form.values[c.id] || ''))));

    const sizes = wf.resolutions.map((r) => ({ id: r, label: r + 'p' }));
    const set = [];
    const dur = byRole('duration');
    if (dur) {
      const lengths = [...new Set([5, 10, 15, Number(form.values[dur.id])])].sort((a, b) => a - b);
      set.push(pill('Length', lengths.map((d) => ({ id: d, label: d + ' s' })), form.values[dur.id], (d) => { form.values[dur.id] = Number(d); }));
    }
    if (wf.size) {
      set.push(pill('Resolution', sizes, form.resolution, (r) => { form.resolution = Number(r); }));
      set.push(pill('Orientation', ORIENTATIONS.map((o) => ({ id: o, label: capital(o) })), form.orientation, (o) => { form.orientation = o; }));
    }
    const res = byRole('resolution');
    if (res) set.push(pill('Resolution', sizes, form.values[res.id], (r) => { form.values[res.id] = Number(r); }));
    // Choices a presets file keeps in view, such as the aspect ratio of a workflow that has no orientation.
    for (const c of wf.controls.filter((x) => x.primary && x.choices && !x.role)) {
      set.push(pill(c.label, c.choices.map((x) => ({ id: x, label: c.choices.every((y) => typeof y === 'string') ? x : `${short(c.label)}: ${x}` })),
        form.values[c.id], (x) => { form.values[c.id] = typeof c.default === 'number' ? Number(x) : x; }));
    }
    for (const o of wf.options) {
      set.push(pill(o.label, o.choices.map((c) => ({ id: c.id, label: `${o.label}: ${c.label}` })), form.options[o.id], (id) => { form.options[o.id] = id; }));
    }
    if (form.kind !== 'upscaler') set.push(el('a', { class: 'opt', href: '#/create', title: 'Open the full form on the Create page' }, 'All settings'));
    pills.replaceChildren(...set);
    refreshEstimate();
  }

  // ------------------------------------------------------------ references

  function setRef(slot, value) {
    const old = form.refs[slot.id];
    if (old && old.file) URL.revokeObjectURL(old.url);
    if (value instanceof File) {
      const ref = form.refs[slot.id] = { file: value, name: value.name, url: URL.createObjectURL(value) };
      if (upscaled() && upscaled().id === slot.id) {   // the price follows the video's length, which the browser can read
        const reader = el('video', { preload: 'metadata', src: ref.url });
        reader.onloadedmetadata = () => { if (Number.isFinite(reader.duration)) { ref.seconds = reader.duration; refreshEstimate(); } };
      }
    }
    else if (value) form.refs[slot.id] = value;
    else delete form.refs[slot.id];
    drawSource();
    if (upscaled()) refreshEstimate();   // an upscale is priced by the video in its slot
  }

  async function chooseSaved(slot) {
    const asset = await pickAsset(slot.kind);
    if (asset) setRef(slot, { assetId: asset.id, name: asset.name, url: `/api/assets/${asset.id}/file` });
  }

  function slotBox(slot) {
    const current = form.refs[slot.id];
    const file = el('input', { type: 'file', accept: ACCEPT[slot.kind], hidden: true,
      onchange: (e) => e.target.files[0] && setRef(slot, e.target.files[0]) });
    const shown = current && (current.shown || slot.kind);   // a cast item can be a video standing in for a picture
    const preview = !current ? icon('plus')
      : shown === 'image' ? el('img', { src: current.url, alt: '' })
      : shown === 'video' ? el('video', { src: current.url + '#t=0.1', muted: true, preload: 'metadata' })
      : el('span', {}, '♪');
    return el('div', { class: 'slot' },
      el('div', { class: 'slot-label', title: slot.label }, short(slot.label) + (slot.optional ? '' : ' *')),
      el('button', { type: 'button', class: 'slot-box' + (current ? ' filled' : '') + (current && current.cast ? ' cast' : ''),
        title: current ? current.name + (current.cast ? ', from the project\'s cast' : '') : 'Click to choose a file, or drop one here',
        onclick: () => file.click(),
        ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('over'); },
        ondragleave: (e) => e.currentTarget.classList.remove('over'),
        ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove('over'); if (e.dataTransfer.files[0]) setRef(slot, e.dataTransfer.files[0]); },
      }, preview),
      current
        ? el('button', { type: 'button', class: 'btn small quiet', onclick: () => setRef(slot, null) }, 'Remove')
        : el('button', { type: 'button', class: 'btn small quiet', title: 'Pick one of your saved assets', onclick: () => chooseSaved(slot) }, 'Saved'),
      file);
  }

  function drawSource() {
    const wf = form.wf;
    const item = startFrom();
    if (item && firstFrame() && !form.refs[firstFrame().id]) {
      start.replaceChildren(el('label', { class: 'check' },
        el('input', { type: 'checkbox', checked: form.useStart, onchange: (e) => { form.useStart = e.target.checked; } }),
        (item.kind === 'video' ? 'Continue from the end of ' : 'Start on ') + item.name));
    } else start.replaceChildren();
    source.classList.toggle('hidden', !wf.refs.length);
    prompt.placeholder = { image: 'Describe the image', audio: 'Describe the music' }[form.kind] || 'Describe the shot';
    // A workflow can have many optional slots; the first few, the required ones and the filled ones stay in view.
    const shown = wf.refs.filter((r, i) => form.allRefs || i < SHOWN || !r.optional || form.refs[r.id]);
    const more = wf.refs.length - shown.length;
    source.replaceChildren(...[el('div', { class: 'label' }, 'Source'), el('div', { class: 'slots' }, shown.map(slotBox)),
      (more > 0 || form.allRefs) && wf.refs.length > SHOWN && el('button', { type: 'button', class: 'btn small quiet', style: 'margin-top:6px',
        onclick: () => { form.allRefs = !form.allRefs; drawSource(); } }, form.allRefs ? 'Fewer references' : `More references (${more})`)].filter(Boolean));
  }

  // ------------------------------------------------------------ estimate and generate

  // parent: the frame this is made from, so the result joins that frame's row on the canvas.
  function settings(extra = {}, parent = null) {
    const refs = { ...extra };
    const source = upscaled() && form.refs[upscaled().id];   // the result is named after the video it is made from
    for (const [id, r] of Object.entries(form.refs)) if (r.assetId) refs[id] = { asset_id: r.assetId };
    return { workflow: form.wf.id, name: source ? `${source.name} upscaled` : form.wf.id.split('/')[1], values: form.values, options: form.options,
      resolution: form.resolution, orientation: form.orientation, seed_mode: 'random', clips: 1, project_id: projectId(), parent, refs,
      source_seconds: (source && source.seconds) || undefined };
  }

  let estimateTimer;
  function refreshEstimate() {
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      if (!form.wf) return;
      try {
        // An upscale is priced by the length of the video it is made from, so the estimate names that video.
        const made = upscaled() && form.refs[upscaled().id];
        const quote = await api('/api/estimate', { method: 'POST', json: settings({}, made && made.itemId ? made.itemId : null) });
        const lacking = quote.credits > quote.balance;
        cost.textContent = quote.credits + ' cr';
        time.textContent = quote.text;
        button.disabled = lacking;
        note.textContent = lacking ? `You have ${quote.balance} cr. This needs ${quote.credits} cr.` : '';
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
    const first = firstFrame();
    const item = form.useStart && first && !form.refs[first.id] ? startFrom() : null;
    const missing = form.wf.refs.find((r) => !r.optional && !form.refs[r.id] && !(item && r.id === first.id));
    if (missing) return showError(new Error(`Add a file for "${short(missing.label)}".`));
    const hits = warnings();
    if (hits.length && !confirm(hits.map((h) => h.message).join('\n') + '\n\nGenerate anyway?')) return;
    button.disabled = true;
    label.textContent = 'Sending…';
    try {
      const extra = {};
      if (item) {
        const ref = await api(`/api/library/${item.id}/reference`, { method: 'POST' });
        extra[first.id] = { comfy_name: ref.comfy_name, name: ref.name };
      }
      for (const [slot, r] of Object.entries(form.refs)) {   // library items, such as the cast, are sent to the render server now
        if (!r.itemId) continue;
        const ref = await api(`/api/library/${r.itemId}/reference?kind=${r.takes}`, { method: 'POST' });
        extra[slot] = { comfy_name: ref.comfy_name, name: ref.name };
      }
      const data = new FormData();
      const made = upscaled() && form.refs[upscaled().id];   // an upscaled video joins the row of the video it is made from
      data.append('settings', JSON.stringify(settings(extra, item ? item.id : made && made.itemId ? made.itemId : null)));
      for (const [id, r] of Object.entries(form.refs)) if (r.file) data.append('ref:' + id, r.file, r.name);
      await api('/api/jobs', { method: 'POST', body: data });
      refreshJobs();
      refreshEstimate();   // the balance changed. After a failure it is left alone: it would clear the message
    } catch (e) { showError(e); }
    button.disabled = false;
    label.textContent = action().label;
  }

  drawHome();
  const unsubscribe = subscribe((change) => { if (change === 'credits' && page !== 'home' && page !== 'motion') refreshEstimate(); });
  return {
    node,
    // refresh(): call when the selection changes, so the "start on" line follows it.
    recast,   // the project's cast changed
    refresh: () => {
      form.useStart = true;
      if (page === 'motion') motionPage.refresh();
      else if (form.wf && page !== 'home') { follow(); draw(); }
    },
    focus: () => { if (page !== 'home' && page !== 'motion') prompt.focus(); },
    destroy: () => { unsubscribe(); for (const ref of Object.values(form.refs)) if (ref.file) URL.revokeObjectURL(ref.url); },
  };
}
