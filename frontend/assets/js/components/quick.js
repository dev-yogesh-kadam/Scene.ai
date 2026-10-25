// The Quick actions tab of the Canvas panel: pick what to make, then fill a short form for it.
// Images, videos and audio each open the same form, built from the workflows of that kind.

import { api } from '../api.js';
import { ask, el, icon, segmented } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';
import { KIT, keepField, pickFromKit } from './kit.js';
import { addMenu } from './agent.js';
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

// startFrom(): the item selected on the canvas, or null. An upscale takes it; a title laid over a video goes on it.
// projectId(): the project new work is filed under, or null.
// What a reference slot takes, in a word, for its + menu.
const KIND_WORD = { image: 'Image', video: 'Video', audio: 'Audio' };

export function quickActions({ startFrom = () => null, projectId = () => null, pick = null } = {}) {
  const form = { catalog: [], wf: null, values: {}, options: {}, resolution: null, orientation: null,
    kind: 'video', refs: {}, allRefs: false };   // refs: slot id -> {file}, {assetId} (a kit entry) or {itemId} (a library item), plus {name, url}
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
      el('div', { class: 'quick-body' }, model, about, modes, source,
promptField, texts, keep.node, note),
      el('div', { class: 'quick-foot' }, pills, button));
    if (form.wf && !changed) draw(); else loadCatalog().catch(showError);
  }

  // ------------------------------------------------------------ the form of one action

  const action = () => ACTIONS.find((a) => a.id === form.kind);
  const title = el('b');
  const model = el('div', { class: 'field' });
  const about = el('p', { class: 'muted small' });
  const modes = el('div');   // the choices a presets file puts first, such as which of a workflow's two modes to use
  const source = el('div', { class: 'field' });
  const prompt = el('textarea', { rows: 5, 'aria-label': 'Prompt', placeholder: 'Describe the shot',
    oninput: (e) => setPrompt(e.target.value),
    onkeydown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate(); } });
  const texts = el('div');   // further text boxes a presets file keeps in view, such as the lyrics of a song
  const note = el('p', { class: 'error notice' });
  const setPrompt = (text) => { const c = byRole('prompt'); if (c) form.values[c.id] = text; };
  const refHint = el('div', { class: 'ref-hint hidden' });   // how this model's prompt names the references, and chips that type it
  const promptField = el('div', { class: 'field' }, el('div', { class: 'label' }, 'Prompt'), prompt, refHint);
  const pills = el('div', { class: 'quick-pills' });
  const label = el('span');
  const cost = el('span', { class: 'cost' });
  const time = el('span', { class: 'slate-text' });
  const button = el('button', { class: 'btn generate', title: 'Generate (Ctrl or ⌘ + Enter)', onclick: () => generate() }, label, cost);
  const keep = keepField();   // what is made can go into the project's kit under a name

  const byRole = (role) => form.wf && form.wf.controls.find((c) => c.role === role);
  // Whether the workflow reads this slot with the choices made: some belong to one mode only. A file left in a slot
  // that is out of use stays there for when the mode is switched back, and is not sent.
  const inUse = (slot) => Object.entries(slot.when || {}).every(([k, v]) => [].concat(v).includes(form.options[k]));
  const used = () => new Set(form.wf.refs.filter(inUse).map((slot) => slot.id));
  const showError = (e) => { note.textContent = e.message || String(e); };

  async function loadCatalog() {
    const list = await api('/api/workflows');
    form.catalog = list.workflows.filter((w) => !w.error && w.kind === form.kind);
    form.wf = null;
    button.disabled = !form.catalog.length;
    if (!form.catalog.length) {
      for (const part of [model, about, modes, source, pills]) part.replaceChildren();
      return showError(new Error(`No ${form.kind} workflows yet. Save a ComfyUI workflow into the workflows/${form.kind} folder, then reload.`));
    }
    const wanted = localStorage.getItem('scene.workflow.' + form.kind) || list.default;
    await selectWorkflow((form.catalog.find((w) => w.id === wanted) || form.catalog[0]).id);
  }

  async function selectWorkflow(id) {
    const wf = await api('/api/workflows/' + id);
    let text = prompt.value;
    // The picture references the user gave, in order, go with them to the new model, as many as it takes.
    const carried = form.wf && form.kind === 'image' ? refSlots().map((s) => form.refs[s.id]).filter((r) => r && !r.cast) : [];
    const said = form.wf ? form.wf.ref_naming || {} : {};
    const before = form.refs;
    form.wf = wf;
    form.refs = {};
    const room = refSlots();
    carried.slice(0, room.length).forEach((ref, i) => { form.refs[room[i].id] = ref; });
    // Each model names its references its own way ("image 1", <ref_image_0>, <image1>): the prompt is rewritten in the
    // new one's words, and a reference it has no room for is [removed].
    const saying = wf.ref_naming || {};
    if (carried.length && said.unique && (said.tokens || []).length && saying.unique && (saying.tokens || []).length) {
      const marks = carried.map((_, i) => `\u0000${i}\u0000`);
      carried.forEach((_, i) => { if (said.tokens[i]) text = text.replace(tokenRe(said.tokens[i]), marks[i]); });
      marks.forEach((mark, i) => { text = text.split(mark).join(i < room.length && saying.tokens[i] ? saying.tokens[i] : REMOVED); });
      if (text !== prompt.value) prompt.value = text;
    }
    const kept = new Set(Object.values(form.refs));
    for (const ref of Object.values(before)) if (ref.file && !kept.has(ref)) URL.revokeObjectURL(ref.url);
    const dropped = carried.length - Math.min(carried.length, room.length);
    form.refNote = !dropped ? '' : room.length
      ? `This model takes ${room.length} reference${room.length === 1 ? '' : 's'}; ${dropped} removed.`
      : `This model makes pictures from words only; ${dropped} reference${dropped === 1 ? '' : 's'} removed.`;
    form.allRefs = false;
    form.values = Object.fromEntries(wf.controls.map((c) => [c.id, c.default]));
    form.options = Object.fromEntries(wf.options.map((o) => [o.id, o.default]));
    form.resolution = wf.size && wf.size.resolution;
    form.orientation = wf.size && wf.size.orientation;
    if (byRole('prompt')) form.values[byRole('prompt').id] = text;   // keep what was typed when the workflow changes
    localStorage.setItem('scene.workflow.' + form.kind, id);
    note.textContent = '';
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

  // Put the project's always-on kit entries into the slots this workflow has for them. A slot the user filled is left alone.
  async function recast() {
    const wf = form.wf;
    if (!wf) return;
    let fills = [];
    try { fills = (await api(`/api/cast?project=${projectId() || 0}&workflow=${encodeURIComponent(wf.id)}`)).fills; } catch (e) { /* no cast, then */ }
    if (form.wf !== wf) return;
    for (const [slot, ref] of Object.entries(form.refs)) if (ref.cast) delete form.refs[slot];
    for (const f of fills) {
      if (!form.refs[f.slot]) form.refs[f.slot] = { assetId: f.asset, name: f.name, takes: f.kind, shown: f.item_kind, url: `/api/assets/${f.asset}/file`, cast: true };
    }
    if (page !== 'home' && page !== 'motion') drawSource();
  }

  // `priced`: "resolution" or "quality", for a choice that changes the price: each option then says what it costs.
  const pill = (name, choices, current, onPick, priced) => el('select', { class: 'opt', title: name, 'aria-label': name, 'data-priced': priced || null,
    onchange: (e) => { onPick(e.target.value); refreshEstimate(); } },
    choices.map((c) => el('option', { value: c.id, selected: String(c.id) === String(current), 'data-label': c.label }, c.label)));
  // "1080p · 200 cr", from what the estimate says each choice would cost.
  const priceChoices = (choices) => {
    for (const select of pills.querySelectorAll('select[data-priced]')) {
      const prices = (choices || {})[select.dataset.priced] || {};
      for (const option of select.options) {
        const price = prices[option.value];
        option.textContent = option.dataset.label + (price != null ? ` · ${price} cr` : '');
      }
    }
  };

  function draw() {
    const wf = form.wf;
    takeSelection();
    model.replaceChildren(el('div', { class: 'label' }, 'Model', el('span', { style: 'flex:1' }), time),
      el('select', { 'aria-label': 'Model', onchange: (e) => selectWorkflow(e.target.value).catch(showError) },
        form.catalog.map((w) => el('option', { value: w.id, selected: w.id === wf.id }, w.title.replace(/^Text to Image:\s*/i, '')))),
      wf.ref_naming && wf.ref_naming.license && el('div', { class: 'ref-license' }, wf.ref_naming.license));
    about.textContent = wf.description;
    modes.replaceChildren(...wf.options.filter((o) => o.top).map((o) => el('div', { class: 'field' }, el('div', { class: 'label' }, o.label),
      segmented(o.choices, form.options[o.id], (id) => { form.options[o.id] = id; draw(); }),
      el('div', { class: 'hint' }, (o.choices.find((c) => c.id === form.options[o.id]) || {}).hint || ''))));
    promptField.classList.toggle('hidden', !byRole('prompt'));
    keep.show(wf.id.split('/')[0], !!projectId());
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
      set.push(pill('Resolution', sizes, form.resolution, (r) => { form.resolution = Number(r); }, 'resolution'));
      set.push(pill('Orientation', ORIENTATIONS.map((o) => ({ id: o, label: capital(o) })), form.orientation, (o) => { form.orientation = o; }));
    }
    const res = byRole('resolution');
    if (res) set.push(pill('Resolution', sizes, form.values[res.id], (r) => { form.values[res.id] = Number(r); }, 'resolution'));
    // Choices a presets file keeps in view, such as the aspect ratio of a workflow that has no orientation.
    for (const c of wf.controls.filter((x) => x.primary && x.choices && !x.role)) {
      set.push(pill(c.label, c.choices.map((x) => ({ id: x, label: c.choices.every((y) => typeof y === 'string') ? x : `${short(c.label)}: ${x}` })),
        form.values[c.id], (x) => { form.values[c.id] = typeof c.default === 'number' ? Number(x) : x; }));
    }
    for (const o of wf.options.filter((x) => !x.top)) {
      set.push(pill(o.label, o.choices.map((c) => ({ id: c.id, label: `${o.label}: ${c.label}` })), form.options[o.id], (id) => { form.options[o.id] = id; },
        o.id === 'quality' ? 'quality' : null));
    }
    if (form.kind !== 'upscaler') set.push(el('a', { class: 'opt', href: '/create', title: 'Open the full form on the Create page', onclick: () => { store.from = '/canvas'; } }, 'All settings'));
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

  // A frame dragged from the canvas onto a slot: the item goes in as it is, a video in a picture slot as its last
  // frame, a video in a sound slot as its sound. False when the slot can't take it.
  function dropItem(slotId, item) {
    const slot = form.wf && form.wf.refs.find((r) => r.id === slotId);
    if (!slot || !item) return false;
    const fits = item.kind === slot.kind || (slot.kind === 'image' && item.kind === 'video') || (slot.kind === 'audio' && item.kind === 'video');
    if (!fits) return false;
    const picture = slot.kind === 'image' && item.kind === 'video';
    setRef(slot, { itemId: item.id, name: picture ? 'End of ' + item.name : item.name, takes: slot.kind,
      shown: picture ? 'image' : item.kind === 'video' && slot.kind === 'audio' ? 'audio' : item.kind,
      url: picture ? `/api/library/${item.id}/poster` : `/api/library/${item.id}/file` });
    return true;
  }

  async function chooseSaved(slot) {
    const asset = await pickFromKit(slot.kind, projectId());
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
      el('div', { class: 'slot-frame' },
      el('button', { type: 'button', class: 'slot-box' + (current ? ' filled' : '') + (current && current.cast ? ' cast' : ''), 'data-slot': slot.id,
        title: current ? current.name + (current.cast ? `, always on in this project's ${KIT}` : '') : `Add a file: upload, from the ${KIT} or from the canvas`, 'aria-haspopup': 'menu',
        // Where the file comes from: the computer, the project's kit, or what is selected on the canvas.
        onclick: (e) => addMenu(e.currentTarget, [
          { icon: 'upload', label: 'Upload', hint: KIND_WORD[slot.kind] || 'File', run: () => file.click() },
          { icon: 'memory', label: `From the ${KIT}`, hint: 'By name', run: () => chooseSaved(slot) },
          ...(pick ? [{ icon: 'target', label: 'From canvas', hint: 'Selected item', run: () => pick((list) => {
            if (!dropItem(slot.id, list[0])) showError(new Error(`${list[0].name} can't go in "${short(slot.label)}": it takes another kind of file.`));
          }) }] : []),
        ]),
        ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('over'); },
        ondragleave: (e) => e.currentTarget.classList.remove('over'),
        ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove('over'); if (e.dataTransfer.files[0]) setRef(slot, e.dataTransfer.files[0]); },
      }, preview),
      // A filled slot is emptied with the × in its corner.
      current && el('button', { type: 'button', class: 'slot-clear', title: 'Remove', 'aria-label': `Remove ${current.name}`,
        onclick: () => setRef(slot, null) }, '×')),
      file);
  }

  // ------------------------------------------------------------ picture references (Generate image)

  // The picture reference slots of the model, in order (REF 1 first), when the action makes pictures; else [].
  function refSlots() {
    if (form.kind !== 'image' || !form.wf) return [];
    const place = (r) => (r.order ? 1e9 + r.order : Number.parseFloat(r.node) || 0);   // a list of references (ref_1, ref_2 ...) in its order
    return form.wf.refs.filter((r) => r.kind === 'image' && inUse(r)).sort((a, b) => place(a) - place(b));
  }
  const filledRefs = () => refSlots().filter((s) => form.refs[s.id]);
  // "REF 1 (the base image)" when a required reference is missing, else ''.
  function missingRef() {
    const slots = refSlots();
    const at = slots.findIndex((s) => s.required && !form.refs[s.id]);
    return at < 0 ? '' : `REF ${at + 1}`;
  }
  const tokenOf = (n) => ((form.wf.ref_naming || {}).tokens || [])[n] || '';
  const REMOVED = '[removed]';
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const tokenRe = (token) => new RegExp(escapeRe(token) + '(?![\\w>])', 'g');

  // Put a picture into the next free reference: REF n is always the n-th slot.
  function addRef(value) {
    const slot = refSlots()[filledRefs().length];
    if (!slot) return;
    form.refNote = '';
    setRef(slot, value);
  }

  // Take REF n out: the ones after it move up one, and so do their names in the prompt ("image 3" becomes "image 2").
  // Where the prompt named the one taken out, it now says [removed], so no name points at the wrong picture.
  function removeRef(index) {
    const slots = refSlots();
    const refs = slots.map((s) => form.refs[s.id]).filter(Boolean);
    const [gone] = refs.splice(index, 1);
    if (gone && gone.file) URL.revokeObjectURL(gone.url);
    for (const s of slots) delete form.refs[s.id];
    refs.forEach((ref, i) => { form.refs[slots[i].id] = ref; });
    const naming = form.wf.ref_naming || {};
    const said = tokenOf(index) && tokenRe(tokenOf(index)).test(prompt.value);
    if (naming.unique && naming.tokens.length) {
      let text = prompt.value.replace(tokenRe(naming.tokens[index]), REMOVED);
      for (let n = index + 1; n < naming.tokens.length; n += 1) text = text.replace(tokenRe(naming.tokens[n]), naming.tokens[n - 1]);
      if (text !== prompt.value) { prompt.value = text; setPrompt(text); }
    }
    form.refNote = !said ? '' : naming.unique
      ? `REF ${index + 1} was removed and the others moved up. The prompt says ${REMOVED} where it named it.`
      : `REF ${index + 1} was removed and the others moved up: check where the prompt said "${tokenOf(index)}".`;
    drawSource();
    refreshEstimate();
  }

  // Type a reference's name into the prompt where the cursor is.
  function insertToken(token) {
    const at = prompt.selectionStart ?? prompt.value.length;
    const end = prompt.selectionEnd ?? at;
    const before = prompt.value.slice(0, at);
    const pad = before && !/\s$/.test(before) ? ' ' : '';
    prompt.value = before + pad + token + prompt.value.slice(end);
    setPrompt(prompt.value);
    prompt.focus();
    prompt.selectionStart = prompt.selectionEnd = at + pad.length + token.length;
  }


  function refBox(slot, index) {
    const current = form.refs[slot.id];
    const file = el('input', { type: 'file', accept: ACCEPT.image, hidden: true,
      onchange: (e) => { if (e.target.files[0]) (current ? setRef(slot, e.target.files[0]) : addRef(e.target.files[0])); } });
    const shown = current && (current.shown || 'image');
    const preview = !current ? icon('plus')
      : shown === 'video' ? el('video', { src: current.url + '#t=0.1', muted: true, preload: 'metadata' })
      : el('img', { src: current.url, alt: '' });
    const label = current ? `REF ${index + 1}` : 'REFERENCE';
    return el('div', { class: 'slot ref-slot' },
      el('div', { class: 'slot-label', title: slot.label }, label + (slot.required ? ' *' : '')),
      el('div', { class: 'slot-frame' },
        el('button', { type: 'button', class: 'slot-box' + (current ? ' filled' : ' ref-empty') + (current && current.cast ? ' cast' : ''), 'data-slot': slot.id,
          title: current ? current.name : `Add a reference picture: upload, from the ${KIT} or from the canvas`, 'aria-haspopup': 'menu',
          onclick: (e) => addMenu(e.currentTarget, [
            { icon: 'upload', label: 'Upload', hint: 'Image', run: () => file.click() },
            { icon: 'memory', label: `From the ${KIT}`, hint: 'By name', run: () => chooseSaved(slot) },
            ...(pick ? [{ icon: 'target', label: 'From canvas', hint: 'Selected item', run: () => pick((list) => {
              if (!dropItem(slot.id, list[0])) showError(new Error(`${list[0].name} can't be a reference: it is not a picture or a video.`));
            }) }] : []),
          ]),
          ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('over'); },
          ondragleave: (e) => e.currentTarget.classList.remove('over'),
          ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove('over'); if (e.dataTransfer.files[0]) (current ? setRef(slot, e.dataTransfer.files[0]) : addRef(e.dataTransfer.files[0])); },
        }, preview),
        current && el('button', { type: 'button', class: 'slot-clear', title: 'Remove', 'aria-label': `Remove REF ${index + 1}`,
          onclick: () => removeRef(index) }, '×')),
      // how the prompt names it, for a model that names each one
      slot.tag && el('div', { class: 'slot-tag' + (current ? '' : ' muted'), title: `The prompt calls this reference ${slot.tag}` }, slot.tag),
      file);
  }

  function drawRefs() {
    const slots = refSlots();
    const filled = filledRefs().length;
    if (missingRef()) {
      button.disabled = true;
      note.textContent = `Add ${missingRef()} to generate.`;
    }
    const naming = form.wf.ref_naming || {};
    source.classList.remove('hidden');
    const said = form.refNote && el('p', { class: 'small muted ref-note' }, form.refNote);
    if (!slots.length) {   // words only: no references; only the note that some were removed, if they were
      source.replaceChildren(...[said].filter(Boolean));
      source.classList.toggle('hidden', !said);
      refHint.classList.add('hidden');
      return;
    }
    const boxes = slots.slice(0, filled).map((s, i) => refBox(s, i));
    if (filled < slots.length) boxes.push(refBox(slots[filled], filled));   // one empty box, until the model's maximum
    source.replaceChildren(...[el('div', { class: 'label' }, 'References', el('span', { class: 'slate-text' }, ` · up to ${slots.length}`)),
      el('div', { class: 'slots ref-strip' }, boxes), said].filter(Boolean));
    // how the prompt names them, and a chip per reference that types its name
    const chips = naming.tokens && naming.tokens.length ? slots.slice(0, filled).map((s, i) => el('button', { type: 'button', class: 'ref-chip',
      title: `Type ${tokenOf(i)} into the prompt`, onclick: () => insertToken(tokenOf(i)) }, `+ REF ${i + 1}: ${tokenOf(i)}`)) : [];
    refHint.replaceChildren(...[naming.hint && el('span', { class: 'small muted' }, naming.hint), ...chips].filter(Boolean));
    refHint.classList.toggle('hidden', !naming.hint && !chips.length);
  }

  function drawSource() {
    const wf = form.wf;
    if (form.kind === 'image') { drawRefs(); refreshEstimate(); return; }
    const refs = wf.refs.filter(inUse);
    source.classList.toggle('hidden', !refs.length);
    prompt.placeholder = { image: 'Describe the image', audio: 'Describe the music' }[form.kind] || 'Describe the shot';
    // A workflow can have many optional slots; the first few, the required ones and the filled ones stay in view.
    const shown = refs.filter((r, i) => form.allRefs || i < SHOWN || !r.optional || form.refs[r.id]);
    const more = refs.length - shown.length;
    source.replaceChildren(...[el('div', { class: 'label' }, 'Source'), el('div', { class: 'slots' }, shown.map(slotBox)),
      (more > 0 || form.allRefs) && refs.length > SHOWN && el('button', { type: 'button', class: 'btn small quiet', style: 'margin-top:6px',
        onclick: () => { form.allRefs = !form.allRefs; drawSource(); } }, form.allRefs ? 'Fewer references' : `More references (${more})`)].filter(Boolean));
  }

  // ------------------------------------------------------------ estimate and generate

  // parent: the frame this is made from, so the result joins that frame's row on the canvas.
  function settings(extra = {}, parent = null) {
    const refs = { ...extra };
    const source = upscaled() && form.refs[upscaled().id];   // the result is named after the video it is made from
    for (const [id, r] of Object.entries(form.refs)) if (r.assetId && used().has(id)) refs[id] = { asset_id: r.assetId };
    return { workflow: form.wf.id, name: source ? `${source.name} upscaled` : form.wf.id.split('/')[1], values: form.values, options: form.options,
      resolution: form.resolution, orientation: form.orientation, seed_mode: 'random', clips: 1, project_id: projectId(), parent, refs,
      source_seconds: (source && source.seconds) || undefined, keep: keep.value() };
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
        const needed = missingRef();
        cost.textContent = quote.credits + ' cr';
        priceChoices(quote.choices);
        time.textContent = quote.text;
        button.disabled = lacking || !!needed;
        note.textContent = lacking ? `You have ${quote.balance} cr. This needs ${quote.credits} cr.` : needed ? `Add ${needed} to generate.` : '';
      } catch (e) {
        showError(e);
        button.disabled = !!missingRef();   // a price that could not be fetched does not stop Generate; a missing reference does
      }
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
    const missing = form.wf.refs.filter(inUse).find((r) => !r.optional && !form.refs[r.id]);
    if (missing) return showError(new Error(`Add a file for "${short(missing.label)}".`));
    const hits = warnings();
    if (hits.length && !await ask({ title: 'Generate anyway?', confirm: 'Generate',
      message: hits.map((h) => h.message).join('\n') + `\n\nEstimated time: ${time.textContent || 'unknown'}` })) return;
    button.disabled = true;
    label.textContent = 'Sending…';
    try {
      const extra = {};
      for (const [slot, r] of Object.entries(form.refs)) {   // library items are sent to the render server now
        if (!r.itemId || !used().has(slot)) continue;
        const ref = await api(`/api/library/${r.itemId}/reference?kind=${r.takes}`, { method: 'POST' });
        extra[slot] = { comfy_name: ref.comfy_name, name: ref.name };
      }
      const data = new FormData();
      const made = upscaled() && form.refs[upscaled().id];   // an upscaled video joins the row of the video it is made from
      data.append('settings', JSON.stringify(settings(extra, made && made.itemId ? made.itemId : null)));
      for (const [id, r] of Object.entries(form.refs)) if (r.file && used().has(id)) data.append('ref:' + id, r.file, r.name);
      await api('/api/jobs', { method: 'POST', body: data });
      keep.reset();   // kept once: the next one is not kept unless asked again
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
    // refresh(): call when the selection changes (an upscale takes the selected video; a motion overlay goes on it).
    recast,   // the project's cast changed
    dropItem,   // dropItem(slotId, item): a frame dragged from the canvas onto a reference slot
    refresh: () => {
      if (page === 'motion') motionPage.refresh();
      else if (form.wf && page !== 'home') draw();
    },
    focus: () => { if (page !== 'home' && page !== 'motion') prompt.focus(); },
    destroy: () => { unsubscribe(); for (const ref of Object.values(form.refs)) if (ref.file) URL.revokeObjectURL(ref.url); },
  };
}
