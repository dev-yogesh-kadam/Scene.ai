// The kit of a project: everything it is made from, by name (characters, locations, props, outfits, voices, styles and
// scripts). The agent knows each entry by its name and what it shows; an entry that is "always on" goes into every shot
// that has a slot for it (what the cast was). One panel for what the Cast box and the Shared memory tab were.

import { api } from '../api.js';
import { ago, ask, el, field, icon } from '../dom.js';
import { addMenu } from './agent.js';

export const KIT = 'NeuralCore';   // what the feature is called wherever the user reads it
export const KIT_TYPES = [
  { id: 'character', label: 'Character' }, { id: 'location', label: 'Location' }, { id: 'prop', label: 'Prop' },
  { id: 'outfit', label: 'Outfit' }, { id: 'voice', label: 'Voice' }, { id: 'style', label: 'Style' },
  { id: 'script', label: 'Script' }, { id: 'other', label: 'Other' },
];
const FIND_KEY = 'scene.kit.type';
const LOOK_AGAIN = 15000;   // while pictures wait to be described, the panel looks again this often (a few times)

export const kitUrl = (entry) => `/api/assets/${entry.id}/file`;

// The type of an entry made from a file dropped into a reference slot with this label (as the server reads it).
const SLOT_TYPES = [['character', /character|main character|second person|\bperson\b/i], ['location', /background|location/i],
  ['outfit', /outfit|costume|clothing/i], ['prop', /\bprop\b|product/i], ['voice', /voice/i], ['style', /\bstyle\b/i]];
export const typeForSlot = (label) => (SLOT_TYPES.find(([, words]) => words.test(label || '')) || ['other'])[0];

export function kitThumb(entry) {
  if (entry.kind === 'image') return el('img', { src: kitUrl(entry), alt: '', loading: 'lazy', draggable: 'false' });
  if (entry.kind === 'video') return el('video', { src: kitUrl(entry) + '#t=0.1', preload: 'metadata', muted: true });
  return el('span', { class: 'kit-glyph' }, icon(entry.kind === 'audio' ? 'audio' : 'book'));
}

function openDialog(...content) {
  const dialog = el('dialog', {}, ...content);
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

const typeSelect = (current, onChange) => el('select', { class: 'kit-type', 'aria-label': 'Type', onchange: (e) => onChange(e.target.value) },
  KIT_TYPES.map((t) => el('option', { value: t.id, selected: t.id === current }, t.label)));

// Add a file, a canvas item or a script to a project's kit. file / item: what is added (a script has neither).
// Resolves with the new entry, or null if the dialog is closed.
export function addToKitDialog({ project = 0, file = null, item = null, script = false, type = '' } = {}) {
  if (!project) {   // a NeuralCore belongs to a project: there is none for all work
    alert(`The ${KIT} belongs to a project. Open a project from All projects and keep its characters, places and props there; every module of it shares them.`);
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    let made = null;
    const guess = type || (script ? 'script' : file && /^audio\//.test(file.type) ? 'voice' : 'character');
    const name = el('input', { type: 'text', maxlength: 60, value: (file ? file.name.replace(/\.[^.]+$/, '') : item ? item.name : '').slice(0, 60),
      placeholder: script ? 'Ep 135' : 'Violet' });
    const kind = typeSelect(guess, () => {});
    const always = el('input', { type: 'checkbox' });
    const words = script && el('textarea', { rows: 10, placeholder: 'Paste the script here.' });
    const error = el('p', { class: 'error notice' });
    const save = async () => {
      if (!name.value.trim()) { error.textContent = 'Give it a name: the agent finds it by this name.'; name.focus(); return; }
      try {
        if (file) {
          const data = new FormData();
          data.append('file', file, file.name);
          data.append('name', name.value);
          data.append('type', kind.value);
          data.append('project_id', String(project || ''));
          if (always.checked) data.append('always', '1');
          made = await api('/api/kit', { method: 'POST', body: data });
        } else {
          made = await api('/api/kit', { method: 'POST', json: { project_id: project || null, name: name.value, type: kind.value, always: always.checked,
            ...(item ? { item: item.id } : { text: words.value }) } });
        }
        dialog.close();
      } catch (e) { error.textContent = e.message; }
    };
    const dialog = openDialog(
      el('h2', {}, script ? `Add a script to the ${KIT}` : `Add to the ${KIT}`),
      el('p', { class: 'muted' }, `The agent finds it by its name in every tab of this project, and Quick actions offers it in the slots it fits.`),
      field('Name', name), field('Type', kind), words && field('Script', words),
      !script && el('label', { class: 'check' }, always, el('span', {}, 'Always on: put it into every shot that has a place for it')),
      error,
      el('div', { class: 'dialog-buttons' },
        el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
        el('button', { class: 'btn primary', onclick: save }, 'Add')));
    dialog.addEventListener('close', () => resolve(made));
    name.focus();
    name.select();
  });
}

// "Keep the result in the Kit as …": a name and a type given before Generate, so what is made goes into the project's
// kit under that name when it is done (a character sheet made by hand, a location plate). A picture can be kept as any
// type but a voice; a sound only as a voice. show(kind): shown for the kind the workflow makes, hidden for the rest.
export function keepField() {
  const on = el('input', { type: 'checkbox', onchange: () => draw() });
  const name = el('input', { type: 'text', class: 'keep-name', maxlength: 60, placeholder: 'Name, e.g. Maya', 'aria-label': `Name in the ${KIT}` });
  const kind = el('select', { class: 'keep-type', 'aria-label': 'Type' });
  const row = el('div', { class: 'keep-row hidden' }, name, kind);
  const node = el('div', { class: 'keep-field hidden' }, el('label', { class: 'check keep-check' }, on, el('span', {}, `Keep the result in the ${KIT}`)), row);
  let makes = '';
  function draw() { row.classList.toggle('hidden', !on.checked); if (on.checked) name.focus(); }
  return {
    node,
    // inProject: whether the job is in a project; outside one there is no NeuralCore to keep it in
    show(kindMade, inProject = true) {
      makes = inProject ? kindMade : '';
      const types = !makes ? [] : kindMade === 'audio' ? ['voice'] : kindMade === 'image' ? ['character', 'location', 'prop', 'outfit', 'style'] : [];
      node.classList.toggle('hidden', !types.length);
      kind.replaceChildren(...types.map((t) => el('option', { value: t }, KIT_TYPES.find((x) => x.id === t).label)));
    },
    // what the job keeps ({"as", "name"}), or undefined when it keeps nothing
    value: () => (on.checked && name.value.trim() && makes ? { as: kind.value, name: name.value.trim() } : undefined),
    reset() { on.checked = false; name.value = ''; draw(); },
  };
}

// Pick an entry of the project's kit for a reference slot that takes `kind` (image, video or audio). Resolves with
// the entry, or null.
export function pickFromKit(kind, project = 0) {
  const fits = { image: ['image', 'video'], video: ['video'], audio: ['audio', 'video'] }[kind] || [kind];
  return new Promise(async (resolve) => {
    let entries = [];
    try { entries = (await api('/api/kit?project=' + (project || 0))).entries.filter((e) => fits.includes(e.kind)); } catch (e) { alert(e.message); return resolve(null); }
    let chosen = null;
    const dialog = openDialog(
      el('h2', {}, `From the ${KIT}`),
      entries.length
        ? el('div', { class: 'asset-grid' }, entries.map((entry) =>
          el('button', { type: 'button', class: 'asset', onclick: () => { chosen = entry; dialog.close(); } },
            el('div', { class: 'asset-thumb' }, kitThumb(entry)),
            el('div', { class: 'asset-name' }, entry.name),
            el('div', { class: 'muted' }, entry.type))))
        : el('p', { class: 'muted' }, `Nothing in this project's ${KIT} fits here yet. Add characters, locations and voices in the ${KIT} tab of the canvas.`),
      el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', onclick: () => dialog.close() }, 'Close')));
    dialog.addEventListener('close', () => resolve(chosen));
  });
}

// The card of an entry: what it shows (the model's words, or the user's) and how to use it.
function cardDialog(entry, onSaved) {
  const about = el('textarea', { rows: 5, maxlength: 600 }, entry.about || '');
  const use = el('textarea', { rows: 3, maxlength: 600, placeholder: 'When and how to use it, e.g. "only in the night scenes".' }, entry.use_note || '');
  const error = el('p', { class: 'error notice' });
  const dialog = openDialog(
    el('h2', {}, entry.name),
    el('p', { class: 'muted' }, 'What it shows is written by the agent\'s model when it is added. Correct it here: your words win.'),
    field('What it shows', about), field('How to use it', use), error,
    el('div', { class: 'dialog-buttons' },
      el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
      el('button', { class: 'btn primary', onclick: async () => {
        try { await api('/api/kit/' + entry.id, { method: 'PUT', json: { about: about.value, use_note: use.value } }); dialog.close(); onSaved(); } catch (e) { error.textContent = e.message; }
      } }, 'Save')));
}

// projectId(): the current project or 0. selected(): the one canvas item selected, or null. onChange(): the kit changed.
export function kitPanel({ projectId = () => 0, selected = () => null, onChange = () => {} } = {}) {
  let found = null;            // what /api/kit gave, or null while it loads
  let loadedAt = 0;
  let looks = 0;               // how many times it looked again for descriptions
  let lookTimer = null;
  let dragged = null;          // the entry being dragged to a new place
  let filter = localStorage.getItem(FIND_KEY) || '';
  const stamp = el('span', { class: 'slate-text' });
  const search = el('input', { type: 'search', class: 'kit-search', placeholder: 'Search by name or what it shows', 'aria-label': `Search the ${KIT}`, oninput: () => draw() });
  const kinds = el('select', { class: 'kit-filter', 'aria-label': 'Type', onchange: (e) => { filter = e.target.value; localStorage.setItem(FIND_KEY, filter); draw(); } },
    el('option', { value: '' }, 'All types'), KIT_TYPES.map((t) => el('option', { value: t.id, selected: t.id === filter }, t.label)));
  const upload = el('input', { type: 'file', hidden: true, accept: 'image/*,video/*,audio/*,.txt,.md,.docx,.srt,.json',
    onchange: async (e) => { const file = e.target.files[0]; e.target.value = ''; if (file && await addToKitDialog({ project: projectId(), file })) changed(); } });
  const addButton = el('button', { class: 'btn small primary', type: 'button', onclick: (e) => openAdd(e.currentTarget) }, icon('plus'), 'Add');
  const body = el('div', { class: 'kit-body' });
  const node = el('div', { class: 'kit-panel memory-panel' },
    el('div', { class: 'memory-head' }, el('b', {}, KIT), el('span', { class: 'slate-text kit-count' }), el('span', { style: 'flex:1' }), stamp,
      el('button', { class: 'icon-btn', title: 'Refresh', 'aria-label': 'Refresh', onclick: () => load() }, '↻'), addButton, upload),
    el('p', { class: 'small muted memory-lead' }, `Everything this project is made from. The agent knows each by its name and what it shows. Always on goes into every shot that has a place for it.`),
    el('div', { class: 'kit-tools' }, search, kinds),
    body);

  function openAdd(anchor) {
    const one = selected();
    addMenu(anchor, [
      { icon: 'upload', label: 'Upload a file', hint: 'picture, video, sound or script', run: () => upload.click() },
      { icon: 'grid', label: one ? `“${one.name}” from the canvas` : 'Select an item on the canvas first', run: async () => {
        if (!one) return;
        if (await addToKitDialog({ project: projectId(), item: one })) changed();
      } },
      { icon: 'book', label: 'Paste a script', run: async () => { if (await addToKitDialog({ project: projectId(), script: true })) changed(); } },
    ]);
  }

  async function change(entry, json) {
    try { Object.assign(entry, await api('/api/kit/' + entry.id, { method: 'PUT', json })); } catch (e) { alert(e.message); }
    changed(false);
  }

  async function remove(entry) {
    if (!await ask({ title: `Take “${entry.name}” out of the ${KIT}?`, danger: true, confirm: 'Take it out',
      message: 'The agent will no longer know it by this name.' })) return;
    try { await api('/api/kit/' + entry.id, { method: 'DELETE' }); } catch (e) { alert(e.message); }
    changed();
  }

  // Drop an entry before another: the whole kit is saved in its new order.
  async function moveBefore(entry, target) {
    const list = found.entries.filter((e) => e.id !== entry.id);
    const at = target ? list.findIndex((e) => e.id === target.id) : list.length;
    list.splice(at < 0 ? list.length : at, 0, entry);
    found.entries = list;
    draw();
    try { found.entries = (await api('/api/kit/order', { method: 'POST', json: { project_id: projectId() || null, ids: list.map((e) => e.id) } })).entries; } catch (e) { alert(e.message); }
    changed(false);
  }

  function changed(reload = true) { onChange(); if (reload) load(); else draw(); }

  function row(entry) {
    const name = el('input', { class: 'kit-name', value: entry.name, maxlength: 60, 'aria-label': 'Name',
      onchange: (e) => { if (e.target.value.trim()) change(entry, { name: e.target.value }); } });
    return el('div', { class: 'kit-row' + (entry.named ? '' : ' unnamed') + (entry.always ? ' always' : ''), draggable: 'true',
      ondragstart: (e) => { dragged = entry; e.dataTransfer.effectAllowed = 'move'; e.currentTarget.classList.add('dragging'); },
      ondragend: (e) => { dragged = null; e.currentTarget.classList.remove('dragging'); },
      ondragover: (e) => { if (dragged && dragged !== entry) { e.preventDefault(); e.currentTarget.classList.add('drop-before'); } },
      ondragleave: (e) => e.currentTarget.classList.remove('drop-before'),
      ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove('drop-before'); if (dragged && dragged !== entry) moveBefore(dragged, entry); } },
      el('span', { class: 'kit-grip', title: 'Drag to change the order', 'aria-hidden': 'true' }, '⋮⋮'),
      el('span', { class: 'memory-thumb kit-thumb' }, kitThumb(entry)),
      el('div', { class: 'kit-main' },
        el('div', { class: 'kit-line' }, name, !entry.named && el('span', { class: 'kit-flag', title: 'The agent will ask who or what this is' }, 'needs a name')),
        el('div', { class: 'kit-line' }, typeSelect(entry.type, (type) => change(entry, { type })),
          entry.kind !== 'text' && el('label', { class: 'kit-always', title: 'Put it into every shot that has a place for it' },
            el('input', { type: 'checkbox', checked: entry.always, onchange: (e) => change(entry, { always: e.target.checked }) }), el('span', {}, 'Always on'))),
        el('button', { type: 'button', class: 'kit-about small muted', title: 'What it shows, and how to use it', onclick: () => cardDialog(entry, load) },
          entry.use_note || entry.about || (entry.kind === 'image' || entry.kind === 'video' ? 'Being looked at…' : 'Add what it is'))),
      el('button', { class: 'icon-btn kit-remove', title: `Take it out of the ${KIT}`, 'aria-label': `Take ${entry.name} out of the ${KIT}`, onclick: () => remove(entry) }, '×'));
  }

  function draw() {
    stamp.textContent = loadedAt ? ago(loadedAt / 1000) : '';
    addButton.classList.toggle('hidden', !projectId());
    if (!projectId()) {   // all work, in no project: there is no NeuralCore here
      node.querySelector('.kit-count').textContent = '';
      body.replaceChildren(el('div', { class: 'kit-empty' }, el('p', {}, `The ${KIT} belongs to a project. Open a project from All projects and keep its characters, places and props there; every module of it shares them.`)));
      return;
    }
    if (!found) { body.replaceChildren(el('p', { class: 'small muted' }, 'Loading…')); return; }
    node.querySelector('.kit-count').textContent = `· ${found.entries.length}`;
    const words = search.value.trim().toLowerCase();
    const shown = found.entries.filter((e) => (!filter || e.type === filter)
      && (!words || `${e.name} ${e.about} ${e.use_note}`.toLowerCase().includes(words)));
    const on = shown.filter((e) => e.always);
    const rest = shown.filter((e) => !e.always);
    body.replaceChildren(...[
      !found.entries.length && el('div', { class: 'kit-empty' },
        el('p', {}, `Nothing in this project's ${KIT} yet.`),
        el('p', { class: 'small muted' }, 'Add your characters, locations, props and voices with Add, or name them in a message to the agent: "Maya - @1".')),
      on.length > 0 && el('section', { class: 'kit-group' }, el('h3', {}, 'Always on', el('span', { class: 'slate-text' }, ' · in every shot, in this order')), ...on.map(row)),
      rest.length > 0 && el('section', { class: 'kit-group' }, el('h3', {}, on.length ? 'Also in this project' : 'In this project'), ...rest.map(row)),
      found.entries.length > 0 && !shown.length && el('p', { class: 'small muted' }, 'Nothing matches.')].filter(Boolean));
  }

  async function load() {
    if (!projectId()) { found = null; draw(); return; }
    try {
      found = await api('/api/kit?project=' + projectId());
      loadedAt = Date.now();
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error small' }, e.message));
      return;
    }
    draw();
    // pictures are described in the background as they come in: look again a few times while some wait
    clearTimeout(lookTimer);
    const waiting = found.entries.some((e) => !e.about && (e.kind === 'image' || e.kind === 'video'));
    if (waiting && looks < 4) { looks += 1; lookTimer = setTimeout(() => { if (node.isConnected) load(); }, LOOK_AGAIN); } else if (!waiting) looks = 0;
  }

  draw();
  return { node, load, reload: () => { found = null; draw(); return load(); }, focus: () => search.focus(),
    count: () => (found ? found.entries.length : null), destroy: () => clearTimeout(lookTimer) };
}
