// The Canvas page: every finished item as a frame on an endless board. A panel on the right makes new work,
// either directly (Quick action) or through the agent.
// Each row is a shot: new work starts a row, work made from a frame joins that frame's row. Frames can be
// dragged between rows, and the rows are remembered per project. Work in progress shows as a frame the Gate runs around.

import { api } from '../api.js';
import { creditMark, el, icon, phaseOf, reel, runningGate, segmented, still, tabTitle } from '../dom.js';
import { store, subscribe } from '../store.js';
import { openViewer } from '../components/media.js';
import { quickActions } from '../components/quick.js';
import { agentTabs } from '../components/agent-tabs.js';
import { KIT, addToKitDialog, kitPanel } from '../components/kit.js';
import { go } from '../nav.js';

const FRAME = 240;      // width of every frame, in canvas units
const SLATE = 24;       // room under a frame for its line of facts
const LABEL = 144;      // room left of a row for the name of its shot
const GAP = 48;
const SNAP = 8;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const ACTIVE = ['queued', 'running'];
const PANEL = 380;      // the width the panel starts with; its left edge can be dragged
const PANEL_MIN = 320;
const PANEL_MAX = 960;
const TABS = [{ id: 'quick', label: 'Quick actions', icon: 'bolt' }, { id: 'agent', label: 'Agent', icon: 'chat' },
  { id: 'kit', label: KIT, icon: 'memory' }];

// The asset boards: the project's kit to the left of the shots, one board per type.
const ASSET_TYPES = [
  { tag: 'character', label: 'Characters', glyph: 'C' }, { tag: 'background', label: 'Locations', glyph: 'L' },
  { tag: 'prop', label: 'Props', glyph: 'P' }, { tag: 'outfit', label: 'Outfits', glyph: 'O' },
  { tag: 'style', label: 'Style', glyph: 'S' }, { tag: 'voice', label: 'Voices', glyph: 'V' }, { tag: 'script', label: 'Scripts', glyph: '¶' },
  { tag: 'other', label: 'Other', glyph: '·' },
];
const BOARD_W = 236;      // width of one asset board, in canvas units
const BOARD_GAP = 32;
const CARD_H = 212;       // a card: its name and its picture
const BOARD_HEAD = 56;

const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
const heightOf = (item) => {
  const c = (item && item.context) || {};
  return Math.round(FRAME * (c.width && c.height ? c.height / c.width : 9 / 16));
};
// A frame's place in its shot, counted as takes from the left.
const take = (spot) => `Take ${Math.round(spot.x / (FRAME + GAP)) + 1}`;
const elapsed = (job) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - (job.started || Date.now() / 1000)));
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
};

export function render(view) {
  view.classList.add('full');
  let items = [];
  let projects = [];
  let project = Number(localStorage.getItem('scene.project')) || 0;   // 0 = everything
  // rows: [{id, name, keys}], one per shot, top to bottom. A key is a generation id, or 'job:<id>' while it is being made.
  let layout = { rows: [], count: 0 };
  let ready = false;              // false until the saved layout is loaded: nothing may be placed before that
  const cam = { x: 96, y: 96, k: 1 };
  const selected = new Set();     // generation ids
  const spots = new Map();        // key -> {x, y, h}: where its row puts each frame
  let bands = [];                 // the rows as drawn: {row, y, h}
  let boardBox = { left: 0, width: 0 };   // where the board of shots is across, for the line that marks a new shot
  const boxes = new Map();        // what is on the canvas now: key -> {key, x, y, h, node}
  const jobFrames = new Map();    // job id -> the parts of its frame that change while it runs
  let agentJobs = new Set();      // jobs the agent started: their frames are drawn in the agent's colour

  const itemLayer = el('div');
  const assetLayer = el('div');
  let assets = [];
  let assetBox = null;            // where the asset boards are, in canvas units, or null when none are shown
  let showAssets = localStorage.getItem('scene.canvas.assets') !== 'off';
  const jobLayer = el('div');
  const labelLayer = el('div');
  const world = el('div', { class: 'canvas-world' }, assetLayer, labelLayer, itemLayer, jobLayer);
  const stage = el('div', { class: 'canvas-stage' }, world);
  // The canvas shows one project, the one opened from All projects; its name is shown, and it does not switch.
  const picker = el('b', { class: 'canvas-project', title: 'This project. Open another from All projects.' });
  const count = el('span', { class: 'slate-text' });
  const context = el('div', { class: 'float canvas-context hidden' });
  const zoomLabel = el('button', { class: 'btn small quiet', title: 'Zoom to 100% (0)', onclick: () => zoomTo(1) });
  const map = el('div', { class: 'minimap hidden', 'aria-hidden': 'true' });
  const hint = el('p', { class: 'canvas-hint muted' }, 'Use the panel on the right to make a shot. Everything you make lands here.');
  // The balance, at the top right like on every page; here it leads the tool bar that is already there.
  const balance = el('span', { class: 'canvas-credits', title: 'Credits pay for generations. An admin can add more.' });
  const drawBalance = () => balance.replaceChildren(creditMark(''), el('b', {}, Number(store.user.credits ?? 0).toLocaleString()), Number(store.user.credits) === 1 ? ' credit' : ' credits');
  drawBalance();
  const leaveBalance = subscribe((change) => { if (change === 'credits') drawBalance(); });
  const dock = quickActions({
    pick: (onPick) => pickFromCanvas(onPick),   // "From canvas" in a reference slot's + menu
    startFrom: () => (selected.size === 1 ? items.find((i) => selected.has(i.id) && i.kind !== 'audio') : null),   // a sound is not a frame to start on
    projectId: () => project || null,
  });

  // The agent is open to admins and to users an admin has given it to. For the others its tab says so.
  const comingSoon = () => ({ node: el('div', { class: 'agent-panel soon' },
    el('div', { class: 'soon-box' }, icon('chat'), el('span', { class: 'soon-tag' }, 'Coming soon'), el('b', {}, 'The agent'),
      el('p', { class: 'muted small' }, 'Describe what you want and have it planned for you. It is not open on your account yet.'),
      el('button', { class: 'btn small', onclick: () => showPanel(true, 'quick') }, 'Use Quick actions'))),
    attach: () => {}, selectionChanged: () => {}, reload: () => {}, redraw: () => {}, focus: () => {}, destroy: () => {} });
  const agent = !store.user.agent ? comingSoon() : agentTabs({
    projectId: () => project,
    // What is selected on the canvas: offered to the message as one suggestion, and read when a message says "this".
    selection: () => items.filter((i) => selected.has(i.id)),
    items: () => items,   // the project's frames, for "@name" in the message
    pickCanvas: (onPick) => pickFromCanvas(onPick),   // "Select from canvas" in the + menu
    onUploaded: () => loadItems().then(draw),   // a file uploaded from the + menu joins the canvas
    onJobs: (ids) => { agentJobs = new Set(ids); for (const [id, frame] of jobFrames) frame.node.classList.toggle('by-agent', agentJobs.has(id)); },
    onMemory: () => showPanel(true, 'kit'),
    onFocus: (id) => focusItem(id),   // a result in the conversation shows that clip on the canvas
    locate: (id) => locate(id),
  });
  // The kit: everything the project is made from, by name; its always-on entries go into every shot (what the cast was).
  const shared = kitPanel({
    projectId: () => project,
    selected: () => (selected.size === 1 ? items.find((i) => selected.has(i.id)) || null : null),
    onChange: () => { dock.recast(); if (showAssets) loadAssets().then(() => { drawAssets(); fit(); }); },
  });
  // The panel is open every time the canvas is entered, and remembers which of its two tabs was showing.
  const savedTab = localStorage.getItem('scene.panel.tab');   // Quick actions unless the agent or the memory was chosen
  let tab = savedTab === 'agent' && store.user.agent ? 'agent' : savedTab === 'kit' || savedTab === 'memory' ? 'kit' : 'quick';
  const title = el('b', { class: 'panel-title' });
  const tabs = el('div');
  const quick = el('div', { class: 'panel-quick' }, dock.node);
  // The left edge of the panel is a grip: drag it to make the panel wider or narrower, double-click for the usual width.
  let panelWidth = PANEL;
  const setWidth = (width) => {
    panelWidth = clamp(Math.round(width) || PANEL, PANEL_MIN, Math.max(PANEL_MIN, Math.min(PANEL_MAX, (view.clientWidth || 9999) - 280)));
    view.style.setProperty('--panel-w', panelWidth + 'px');
  };
  const keepWidth = () => { localStorage.setItem('scene.panel.width', panelWidth); if (ready) fit(); };
  const grip = el('div', { class: 'panel-grip', title: 'Drag to resize. Double-click for the usual width.', role: 'separator', 'aria-orientation': 'vertical',
    ondblclick: () => { setWidth(PANEL); keepWidth(); },
    onpointerdown: (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const from = { x: e.clientX, width: panelWidth };
      view.classList.add('resizing');
      track((ev) => setWidth(from.width + from.x - ev.clientX), () => { view.classList.remove('resizing'); keepWidth(); });
    } });
  const panel = el('aside', { class: 'side-panel', 'aria-label': 'Make something' }, grip,
    el('div', { class: 'panel-head' }, title, el('span', { style: 'flex:1' }), tabs,
      el('button', { class: 'icon-btn', title: 'Close (Ctrl or ⌘ + J)', 'aria-label': 'Close the panel', onclick: () => showPanel(false) }, '×')),
    quick, agent.node, shared.node);
  const isOpen = () => view.classList.contains('with-panel');
  const panelButton = el('button', { class: 'btn small quiet', title: 'Show or hide Quick action and the Agent (Ctrl or ⌘ + J)', onclick: () => showPanel(!isOpen()) }, 'Panel');
  function showPanel(open, which = tab) {
    tab = which;
    view.classList.toggle('with-panel', open);
    panelButton.setAttribute('aria-pressed', String(open));
    localStorage.setItem('scene.panel.tab', tab);
    title.textContent = TABS.find((t) => t.id === tab).label;
    title.classList.toggle('agent-name', tab === 'agent');
    tabs.replaceChildren(segmented(TABS.map((t) => ({ id: t.id, label: icon(t.icon), hint: t.label })), tab, (id) => showPanel(true, id)));
    quick.classList.toggle('hidden', tab !== 'quick');
    agent.node.classList.toggle('hidden', tab !== 'agent');
    shared.node.classList.toggle('hidden', tab !== 'kit');
    if (open && tab === 'kit') shared.load();   // what the agent has just made or kept shows at once
    if (open) (tab === 'agent' ? agent : tab === 'kit' ? shared : dock).focus();
    if (ready) fit();
  }

  // ------------------------------------------------------------ asset boards

  const assetsButton = el('button', { class: 'btn small quiet', title: `Show or hide the project's ${KIT} beside the shots`,
    'aria-pressed': String(showAssets), onclick: async () => {
      showAssets = !showAssets;
      localStorage.setItem('scene.canvas.assets', showAssets ? 'on' : 'off');
      assetsButton.setAttribute('aria-pressed', String(showAssets));
      if (showAssets) await loadAssets();   // what was saved since the canvas opened shows too
      drawAssets();
      fit();
    } }, 'Assets');

  async function loadAssets() {
    try {
      assets = (await api('/api/kit?project=' + (project || 0))).entries;   // the project's kit
    } catch { assets = []; }
  }

  // One board per type that has assets, side by side to the left of the names of the shots.
  function drawAssets() {
    const groups = ASSET_TYPES.map((t) => ({ ...t, list: assets.filter((a) => (ASSET_TYPES.some((x) => x.tag === a.tag) ? a.tag : 'other') === t.tag) }))
      .filter((g) => g.list.length);
    if (!showAssets || !groups.length) {
      assetLayer.replaceChildren();
      assetBox = null;
      return;
    }
    const width = groups.length * BOARD_W + (groups.length - 1) * BOARD_GAP;
    const left = -LABEL - 96 - width;
    let tallest = 0;
    assetLayer.replaceChildren(...groups.map((group, i) => {
      const height = BOARD_HEAD + group.list.length * CARD_H + 12;
      tallest = Math.max(tallest, height);
      return el('section', { class: 'asset-board type-' + group.tag, style: `left:${left + i * (BOARD_W + BOARD_GAP)}px;top:0;width:${BOARD_W}px;height:${height}px`,
        'aria-label': group.label },
        el('header', { class: 'asset-board-head' }, el('span', { class: 'asset-glyph', 'aria-hidden': 'true' }, group.glyph),
          el('b', {}, group.label), el('span', { class: 'asset-count' }, String(group.list.length))),
        ...group.list.map((asset) => el('button', { type: 'button', class: 'asset-card',
          title: [asset.name, asset.use_note && 'Use: ' + asset.use_note, asset.about].filter(Boolean).join('\n'),
          onpointerdown: (e) => e.stopPropagation(), ondblclick: () => previewAsset(asset), onclick: (e) => {
            assetLayer.querySelectorAll('.asset-card.on').forEach((c) => c !== e.currentTarget && c.classList.remove('on'));
            e.currentTarget.classList.toggle('on');
          } },
          el('span', { class: 'asset-name' }, asset.name, asset.always && el('i', { class: 'asset-tag' }, 'always on')),
          el('span', { class: 'asset-picture' }, asset.kind === 'audio'
            ? el('span', { class: 'asset-sound' }, icon('audio'), 'Sound')
            : still(`/api/assets/${asset.id}/file`, asset.kind, asset.name)))));
    }));
    assetBox = { x: left, y: 0, right: left + width, bottom: tallest };
  }

  // A closer look at one asset: the file, what it shows and the note on when to use it.
  function previewAsset(asset) {
    const url = `/api/assets/${asset.id}/file`;
    const dialog = el('dialog', { class: 'asset-preview' },
      el('div', { class: 'asset-preview-media' }, asset.kind === 'image' ? el('img', { src: url, alt: asset.name })
        : el(asset.kind === 'video' ? 'video' : 'audio', { src: url, controls: true })),
      el('div', { class: 'asset-preview-words' },
        el('span', { class: 'asset-tag' }, (ASSET_TYPES.find((t) => t.tag === asset.tag) || ASSET_TYPES[6]).label.replace(/s$/, '')),
        el('h2', {}, asset.name),
        asset.about && el('p', { class: 'muted small' }, asset.about),
        asset.use_note && el('p', { class: 'small' }, el('b', {}, 'When to use: '), asset.use_note),
        el('div', { class: 'dialog-buttons' }, el('a', { class: 'btn small quiet', href: '/assets' }, 'Edit in Assets'),
          el('button', { class: 'btn small primary', onclick: () => dialog.close() }, 'Close'))));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
  }

  // ------------------------------------------------------------ tools: bring files in, and take work from the library

  const toolNote = el('div', { class: 'float canvas-tool-note hidden', role: 'status', 'aria-live': 'polite' });
  let noteTimer = null;
  const note = (text, { error = false, stay = false } = {}) => {
    clearTimeout(noteTimer);
    toolNote.textContent = text;
    toolNote.classList.toggle('error', error);
    toolNote.classList.toggle('hidden', !text);
    if (!stay) noteTimer = setTimeout(() => toolNote.classList.add('hidden'), error ? 6000 : 2500);
  };
  const filePicker = el('input', { type: 'file', accept: 'image/*,video/*,audio/*,.docx,.txt,.md,.srt,.json', multiple: true, hidden: true,
    onchange: (e) => { uploadFiles([...e.target.files]); e.target.value = ''; } });
  // Each file joins the library and this project, and lands on the canvas as a shot of its own.
  async function uploadFiles(files) {
    const usable = files.filter((f) => /^(image|video|audio)\//.test(f.type));
    if (!usable.length) return note('Only images, videos and sound can be uploaded.', { error: true });
    const made = [];
    for (const [i, file] of usable.entries()) {
      note(usable.length > 1 ? `Uploading ${i + 1} of ${usable.length}: ${file.name}` : `Uploading ${file.name}…`, { stay: true });
      const data = new FormData();
      data.append('file', file, file.name);
      data.append('project_id', project || '');
      try { made.push((await api('/api/library/upload', { method: 'POST', body: data })).id); } catch (e) { return note(e.message, { error: true }); }
    }
    await loadItems();
    selected.clear();
    for (const id of made) selected.add(id);
    draw();
    note(made.length === 1 ? 'Uploaded. It is on the canvas.' : `${made.length} files uploaded. They are on the canvas.`);
  }
  stage.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); view.classList.add('dropping'); } });
  stage.addEventListener('dragleave', (e) => { if (e.target === stage) view.classList.remove('dropping'); });
  stage.addEventListener('drop', (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    view.classList.remove('dropping');
    uploadFiles([...e.dataTransfer.files]);
  });

  // The library drawer: everything the user has made or brought in, to bring onto this canvas.
  const drawer = el('div', { class: 'float canvas-library hidden', role: 'dialog', 'aria-label': 'Library' });
  const shelf = { kind: '', q: '', all: [], loaded: false };
  const libraryButton = el('button', { type: 'button', class: 'tool-btn', 'aria-label': 'Library', 'data-tip': 'Library', onclick: () => toggleLibrary() }, icon('grid'));
  async function toggleLibrary(open = drawer.classList.contains('hidden')) {
    drawer.classList.toggle('hidden', !open);
    libraryButton.classList.toggle('on', open);
    if (!open) return;
    drawShelf();
    try { shelf.all = (await api('/api/library')).items; shelf.loaded = true; } catch (e) { return note(e.message, { error: true }); }
    drawShelf();
  }
  const grid = el('div', { class: 'library-grid' });
  const kinds = el('div');
  drawer.append(
    el('div', { class: 'library-head' }, el('b', {}, 'Library'), el('span', { style: 'flex:1' }),
      el('a', { class: 'btn small quiet', href: '/library' }, 'Open page'),
      el('button', { class: 'icon-btn', 'aria-label': 'Close the library', title: 'Close', onclick: () => toggleLibrary(false) }, '×')),
    kinds,
    el('input', { type: 'search', class: 'search', placeholder: 'Search by name', 'aria-label': 'Search the library',
      oninput: (e) => { shelf.q = e.target.value; drawShelf(); } }),
    grid);
  function drawShelf() {
    kinds.replaceChildren(segmented([{ id: '', label: 'All' }, { id: 'image', label: 'Images' }, { id: 'video', label: 'Videos' }, { id: 'audio', label: 'Audio' }],
      shelf.kind, (k) => { shelf.kind = k; drawShelf(); }));
    const words = shelf.q.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = shelf.all.filter((i) => (!shelf.kind || i.kind === shelf.kind) && words.every((w) => i.name.toLowerCase().includes(w)));
    grid.replaceChildren(...(shown.length ? shown.map((item) => {
      const here = !project || item.project_id === project;
      return el('button', { type: 'button', class: 'library-tile' + (here ? ' here' : ''),
        title: here ? 'Open it' : `In ${item.project_name || 'no project'}. Click to move it to this project's canvas.`,
        onclick: async () => {
          if (here) return open(item);
          try {
            await api('/api/library/' + item.id, { method: 'PUT', json: { project_id: project } });
            item.project_id = project;
            await loadItems();
            selected.clear();
            selected.add(item.id);
            draw();
            drawShelf();
            note(`${item.name} is on the canvas.`);
          } catch (e) { note(e.message, { error: true }); }
        } },
        el('span', { class: 'library-thumb' }, still(`/api/library/${item.id}/file`, item.kind, item.name)),
        el('span', { class: 'library-name' }, item.name),
        el('span', { class: 'library-where' }, here ? (project ? 'On this canvas' : item.project_name || 'No project') : '+ Add to canvas'));
    }) : [el('p', { class: 'muted small' }, shelf.loaded ? (shelf.all.length ? 'Nothing matches.' : 'Your library is empty.') : 'Loading…')]));
  }
  const tools = el('div', { class: 'float canvas-tools', role: 'toolbar', 'aria-label': 'Canvas tools', 'aria-orientation': 'vertical' },
    el('button', { type: 'button', class: 'tool-btn', 'aria-label': 'Upload an image, video or sound', 'data-tip': 'Upload image, video or audio',
      onclick: () => filePicker.click() }, icon('upload')),
    libraryButton, filePicker);

  view.replaceChildren(stage,
    el('div', { class: 'float canvas-bar' }, picker, count, el('a', { class: 'btn small quiet', href: '/timeline', title: 'Put this project\'s videos in order' }, 'Timeline')),
    tools, drawer, toolNote,
    context,
    el('div', { class: 'float canvas-view' },
      balance,
      assetsButton,
      el('button', { class: 'btn small quiet', title: 'Fit everything (1)', onclick: () => fit() }, 'Fit'),
      zoomLabel, panelButton),
    map, hint, panel);

  // ------------------------------------------------------------ layout

  const lazy = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      lazy.unobserve(entry.target);
      entry.target.append(media(entry.target.item));
    }
  }, { root: stage, rootMargin: '300px' });

  const media = (item) => still(`/api/library/${item.id}/file`, item.kind, item.name);

  // Every shot is a row. Work made from scratch starts a new row at the bottom; work made from a frame
  // (continued from it, re-run, trimmed, split) joins that frame's row at the right end.
  const rowOf = (key) => layout.rows.find((row) => row.keys.includes(key));
  const newRow = () => layout.rows[layout.rows.push({ id: ++layout.count, name: '', keys: [] }) - 1];
  // The frame something was made from: sent with the job, or the first clip of an edit.
  const parentOf = (settings) => (settings && (settings.parent || (Array.isArray(settings.clips) && settings.clips[0] && settings.clips[0].id))) || null;

  function arrange() {
    const before = JSON.stringify(layout);
    const jobs = store.jobs.filter((j) => ACTIVE.includes(j.status) && (!project || j.project_id === project));
    const known = new Set(items.map((i) => i.id));
    const live = new Set(jobs.map((j) => 'job:' + j.id));
    for (const item of [...items].reverse()) {   // oldest first, so shots are numbered in the order they were made
      if (rowOf(item.id)) continue;
      const held = item.job_id && rowOf('job:' + item.job_id);   // finished work takes the place its job was holding
      if (held) held.keys.splice(held.keys.indexOf('job:' + item.job_id), 0, item.id);
      else (rowOf(parentOf(item.settings)) || newRow()).keys.push(item.id);
    }
    for (const job of [...jobs].reverse()) {
      if (rowOf('job:' + job.id) || items.some((i) => i.job_id === job.id)) continue;
      (rowOf(parentOf(job.settings)) || newRow()).keys.push('job:' + job.id);
    }
    for (const row of layout.rows) row.keys = row.keys.filter((key) => (typeof key === 'number' ? known.has(key) : live.has(key)));
    layout.rows = layout.rows.filter((row) => row.keys.length);

    const heights = new Map(items.map((i) => [i.id, heightOf(i)]));
    spots.clear();
    bands = [];
    let y = 0;
    for (const row of layout.rows) {
      const sizes = row.keys.map((key) => heights.get(key) || heightOf());
      row.keys.forEach((key, i) => spots.set(key, { x: i * (FRAME + GAP), y, h: sizes[i] }));
      bands.push({ row, y, h: Math.max(...sizes) });
      y += Math.max(...sizes) + SLATE + GAP;
    }
    if (ready && JSON.stringify(layout) !== before) save();
    return jobs;
  }

  function drawItems() {
    for (const key of [...boxes.keys()]) if (typeof key === 'number') boxes.delete(key);
    lazy.disconnect();
    itemLayer.replaceChildren(...items.map((item) => {
      const spot = spots.get(item.id);
      const shot = el('div', { class: 'shot gate', style: `height:${spot.h}px` });
      shot.item = item;
      lazy.observe(shot);
      const c = item.context || {};
      const label = el('b', {}, take(spot));
      // "+" on a frame adds it to the agent's message, opening the agent when it is not showing.
      const toChat = store.user.agent && el('button', { type: 'button', class: 'frame-attach', title: 'Add to chat', 'aria-label': `Add ${item.name} to the chat`,
        onpointerdown: (e) => e.stopPropagation(), ondblclick: (e) => e.stopPropagation(),
        onclick: (e) => { e.stopPropagation(); addToChat([item]); } }, icon('plus'));
      const node = el('div', { class: 'frame' + (selected.has(item.id) ? ' selected' : ''), style: `left:${spot.x}px;top:${spot.y}px`, title: item.name,
        onpointerdown: (e) => grab(e, item.id), ondblclick: () => open(item) },
        shot, toChat,
        el('div', { class: 'slate' }, label, el('span', {}, c.width ? `${item.kind} · ${c.width}×${c.height}` : item.name)));
      node.take = label;
      boxes.set(item.id, { key: item.id, ...spot, node });
      return node;
    }));
    count.textContent = items.length === 1 ? '1 item' : `${items.length} items`;
  }

  // Frames of jobs are kept between updates, so the running Gate isn't restarted by every progress message.
  function drawJobs(jobs) {
    for (const [id, frame] of jobFrames) {
      if (jobs.some((j) => j.id === id)) continue;
      frame.node.remove();
      jobFrames.delete(id);
      boxes.delete('job:' + id);
    }
    for (const job of jobs) {
      const spot = spots.get('job:' + job.id);
      if (!spot) continue;   // its result is already on the canvas
      let frame = jobFrames.get(job.id);
      if (!frame) {
        const clock = el('span');
        const fact = el('span');
        const shot = el('div', { class: 'shot', style: `height:${spot.h}px` }, clock);
        const film = reel(20);
        const node = el('div', { class: 'frame developing' + (agentJobs.has(job.id) ? ' by-agent' : ''), title: job.name },
          shot, el('div', { class: 'slate' }, el('b', {}, job.workflow.split('/')[0]), film.node, fact));
        frame = { node, shot, clock, fact, film, gate: null };
        jobFrames.set(job.id, frame);
        jobLayer.append(node);
        boxes.set('job:' + job.id, { key: 'job:' + job.id, ...spot, node });
      }
      const waiting = job.status === 'queued';
      if (!waiting && !frame.gate) frame.gate = frame.shot.appendChild(runningGate());
      // The frame develops like a print in a tray: the grain clears as the steps go by.
      const done = job.steps ? (Math.max(job.clip, 1) - 1 + job.step / job.steps) / Math.max(job.clips, 1) : 0;
      frame.shot.style.setProperty('--developed', done.toFixed(3));
      frame.node.classList.toggle('waiting', waiting);
      frame.clock.textContent = waiting ? 'queued' : elapsed(job);   // how long it has been at it; no percentage
      frame.film.set(done);   // a reel that fills, and what the job is at in words, in place of a step count
      frame.fact.textContent = waiting ? `position ${job.position}` : job.steps ? phaseOf(done) : 'Setting up the shot';
    }
    hint.classList.toggle('hidden', boxes.size > 0);
  }

  // Move every frame to where its row puts it, and name the rows down the left side.
  function settle() {
    for (const box of boxes.values()) {
      const spot = spots.get(box.key);
      if (!spot) continue;
      Object.assign(box, spot);
      box.node.style.left = spot.x + 'px';
      box.node.style.top = spot.y + 'px';
      if (box.node.take) box.node.take.textContent = take(spot);
    }
    // All the shots sit in one board, the names of the shots down its left side and a line between one shot and the
    // next, halfway across the gap. The board is as wide as the longest shot.
    const pad = GAP / 3;
    const last = bands[bands.length - 1];
    const left = -LABEL - GAP / 4;
    const width = Math.max(1, ...bands.map((band) => band.row.keys.length)) * (FRAME + GAP) - left - GAP / 2;
    boardBox = { left, width };
    const board = last ? [el('div', { class: 'lane lane-board',
      style: `left:${left}px;top:${bands[0].y - pad}px;width:${width}px;height:${last.y + last.h + SLATE + pad - (bands[0].y - pad)}px` })] : [];
    const lines = bands.slice(1).map((band, i) => {
      const above = bands[i];
      const y = (above.y + above.h + SLATE + band.y) / 2;
      return el('div', { class: 'lane-divider', style: `left:${left + GAP / 4}px;top:${y}px;width:${width - GAP / 2}px` });
    });
    labelLayer.replaceChildren(...board, ...lines,
    ...bands.map((band, i) => el('button', { class: 'shot-label', title: 'Rename this shot',
      style: `left:${-LABEL}px;top:${band.y}px;width:${LABEL - GAP / 2}px;height:${band.h}px`,
      onpointerdown: (e) => e.stopPropagation(), onclick: (e) => rename(band.row, e.currentTarget, i) }, band.row.name || `Shot ${i + 1}`)));
    drawOverlay();
  }

  function rename(row, label, index) {
    const input = el('input', { type: 'text', class: 'shot-name', maxlength: 40, value: row.name || `Shot ${index + 1}`, 'aria-label': 'Name of the shot' });
    const done = (keep) => {
      if (!input.isConnected) return;
      if (keep) { row.name = input.value.trim() === `Shot ${index + 1}` ? '' : input.value.trim(); save(); }
      settle();
    };
    input.addEventListener('pointerdown', (e) => e.stopPropagation());
    input.addEventListener('blur', () => done(true));
    input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') done(true); else if (e.key === 'Escape') done(false); });
    label.replaceChildren(input);
    input.select();
  }

  // update(): jobs or rows changed. draw(): the items themselves changed, so their frames are rebuilt too.
  function update() {
    const jobs = arrange();
    drawJobs(jobs);
    settle();
  }

  function draw() {
    const jobs = arrange();
    drawItems();
    drawJobs(jobs);
    settle();
  }

  // ------------------------------------------------------------ one item in view: where the agent's results lead

  // Where an item is, as the agent's panel names it: "Shot 3", take 2.
  function locate(id) {
    const index = layout.rows.findIndex((row) => row.keys.includes(id));
    if (index < 0) return null;
    const row = layout.rows[index];
    return { shot: row.name || `Shot ${index + 1}`, take: row.keys.indexOf(id) + 1 };
  }

  // Glide to one item and select it: it comes to the middle of the part of the canvas the panel leaves free, at a size
  // it can be seen at, with a ring that shows which one it is.
  let glide = null;
  async function focusItem(id) {
    if (!boxes.has(id)) {   // made a moment ago, it may not be drawn yet
      try { await loadItems(); draw(); } catch { /* said below */ }
    }
    const box = boxes.get(id);
    if (!box) return note(project ? 'That one is not in this project. Pick All work to see it.' : 'That one is no longer in the library.', { error: true });
    const rect = stage.getBoundingClientRect();
    const covered = isOpen() ? panelWidth + 12 : 0;
    const room = { w: Math.max(200, rect.width - covered), h: rect.height };
    cam.k = clamp(Math.min((room.w * 0.55) / FRAME, (room.h * 0.62) / (box.h + SLATE)), 0.35, 1.6);
    cam.x = room.w / 2 - (box.x + FRAME / 2) * cam.k;
    cam.y = room.h / 2 - (box.y + (box.h + SLATE) / 2) * cam.k;
    world.classList.add('gliding');
    applyCamera();
    clearTimeout(glide);
    glide = setTimeout(() => world.classList.remove('gliding'), 650);
    selected.clear();
    selected.add(id);
    selectionChanged();
    box.node.classList.remove('spotlight');
    void box.node.offsetWidth;   // starts the ring again when it is already there
    box.node.classList.add('spotlight');
  }

  // ------------------------------------------------------------ camera

  function applyCamera() {
    world.style.transform = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;
    world.style.setProperty('--inv', 1 / cam.k);
    stage.style.setProperty('--grid', 96 * cam.k + 'px');
    stage.style.setProperty('--grid-x', cam.x + 'px');
    stage.style.setProperty('--grid-y', cam.y + 'px');
    stage.classList.toggle('far', cam.k < 0.5);   // far away: just the pictures, no slates or grid
    zoomLabel.textContent = Math.round(cam.k * 100) + '%';
    drawOverlay();
  }

  function zoomAt(clientX, clientY, k) {
    const rect = stage.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const wx = (px - cam.x) / cam.k;
    const wy = (py - cam.y) / cam.k;
    cam.k = clamp(k, MIN_ZOOM, MAX_ZOOM);
    cam.x = px - wx * cam.k;
    cam.y = py - wy * cam.k;
    applyCamera();
  }

  function zoomTo(k) {
    const rect = stage.getBoundingClientRect();
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, k);
  }

  function bounds(list) {
    return { x: Math.min(...list.map((b) => b.x)), y: Math.min(...list.map((b) => b.y)),
      right: Math.max(...list.map((b) => b.x + FRAME)), bottom: Math.max(...list.map((b) => b.y + b.h + SLATE)) };
  }

  function fit() {
    if (!boxes.size && !assetBox) { cam.x = 96; cam.y = 96; cam.k = 1; return applyCamera(); }
    const all = boxes.size ? bounds([...boxes.values()]) : { ...assetBox };
    all.x -= boxes.size ? LABEL : 0;   // the names of the shots are part of the picture
    if (assetBox) Object.assign(all, { x: Math.min(all.x, assetBox.x), y: Math.min(all.y, assetBox.y),
      right: Math.max(all.right, assetBox.right), bottom: Math.max(all.bottom, assetBox.bottom) });
    const rect = stage.getBoundingClientRect();
    const covered = isOpen() ? panelWidth + 12 : 0;   // the open panel covers the right side
    const room = { w: rect.width - 160 - covered, h: rect.height - 160 };
    cam.k = clamp(Math.min(room.w / (all.right - all.x), room.h / (all.bottom - all.y)), MIN_ZOOM, 1);
    cam.x = (rect.width - covered - (all.right - all.x) * cam.k) / 2 - all.x * cam.k;
    cam.y = 80 + (room.h - (all.bottom - all.y) * cam.k) / 2 - all.y * cam.k;
    applyCamera();
  }

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) return zoomAt(e.clientX, e.clientY, cam.k * Math.exp(-e.deltaY * 0.01));
    cam.x -= e.deltaX;
    cam.y -= e.deltaY;
    applyCamera();
  }, { passive: false });

  // Drag the empty canvas to pan; a click on it clears the selection.
  stage.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const from = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
    let moved = false;
    stage.classList.add('panning');
    track((ev) => {
      moved = moved || Math.abs(ev.clientX - from.x) + Math.abs(ev.clientY - from.y) > 3;
      cam.x = from.cx + ev.clientX - from.x;
      cam.y = from.cy + ev.clientY - from.y;
      applyCamera();
    }, () => {
      stage.classList.remove('panning');
      if (!moved && selected.size) { selected.clear(); selectionChanged(); }
    });
  });

  function track(onMove, onEnd) {
    const end = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', end); onEnd(); };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', end);
  }

  // ------------------------------------------------------------ selecting and moving

  // Where a dragged frame would start a new shot: in the gap above the first shot or between two shots, near the
  // line between them. The index the new shot takes, or -1 when the pointer is over a shot (it joins that one).
  function gapAt(y) {
    if (!bands.length) return -1;
    if (y > bands[0].y - GAP && y < bands[0].y + 12) return 0;
    for (let i = 1; i < bands.length; i++) {
      if (y > bands[i - 1].y + bands[i - 1].h + SLATE - 12 && y < bands[i].y + 12) return i;
    }
    return -1;
  }
  const gapLine = (i) => (i === 0 ? bands[0].y - GAP / 2 : (bands[i - 1].y + bands[i - 1].h + SLATE + bands[i].y) / 2);
  const insertMark = el('div', { class: 'insert-mark' }, el('span', {}, 'New shot here'));

  function grab(e, id) {
    if (e.button !== 0) return;
    e.stopPropagation();
    if (e.shiftKey) { selected.has(id) ? selected.delete(id) : selected.add(id); }
    else if (!selected.has(id)) { selected.clear(); selected.add(id); }
    selectionChanged();
    const from = { x: e.clientX, y: e.clientY };
    const moving = [...selected].map((key) => boxes.get(key)).filter(Boolean).map((box) => ({ box, x: box.x, y: box.y }));
    let moved = false;
    // Where the pointer is on the canvas, to tell a drop on a shot from a drop in the gap between two shots.
    const held = boxes.get(id);
    const grip = held ? (from.y - held.node.getBoundingClientRect().top) / cam.k : 0;
    const startY = held ? held.y + grip : 0;
    let gap = -1;
    track((ev) => {
      const dx = (ev.clientX - from.x) / cam.k;
      const dy = (ev.clientY - from.y) / cam.k;
      moved = moved || Math.abs(dx) + Math.abs(dy) > 3 / cam.k;
      if (!moved) return;
      context.classList.add('hidden');
      gap = gapAt(startY + dy);
      if (gap >= 0) {   // over the line between two shots: it lights up, and the frames will start a new shot there
        Object.assign(insertMark.style, { left: boardBox.left + GAP / 4 + 'px', width: boardBox.width - GAP / 2 + 'px', top: gapLine(gap) + 'px' });
        if (!insertMark.isConnected) labelLayer.append(insertMark);
      } else insertMark.remove();
      for (const m of moving) {
        m.box.x = Math.round((m.x + dx) / SNAP) * SNAP;
        m.box.y = Math.round((m.y + dy) / SNAP) * SNAP;
        m.box.node.style.left = m.box.x + 'px';
        m.box.node.style.top = m.box.y + 'px';
      }
    }, () => {
      // A click only selects: looking at a frame does not put it into the message. The agent offers the selection as
      // one suggestion to use, and each frame has its own "+" to add it. While a panel asked for a frame ("From
      // canvas" with nothing selected), the click gives it this frame.
      if (!moved && picking) { const done = picking; stopPicking(); done(items.find((i) => i.id === id)); return; }
      if (!moved) return;
      // Dropped frames join the shot they were dropped on, at that place in the row; below the last row they start a new shot.
      const dropped = boxes.get(id);
      const middle = dropped.y + dropped.h / 2;
      const ids = moving.map((m) => m.box.key).filter((key) => typeof key === 'number');
      const band = bands.find((b) => middle < b.y + b.h + SLATE + GAP / 2);
      const at = Math.max(0, Math.round(dropped.x / (FRAME + GAP)));
      for (const row of layout.rows) row.keys = row.keys.filter((key) => !ids.includes(key));
      insertMark.remove();
      // Dropped on the line between two shots (or above the first): a new shot there, between them.
      const fresh = gap >= 0 ? { id: ++layout.count, name: '', keys: [] } : null;
      if (fresh) layout.rows.splice(layout.rows.indexOf(bands[gap].row), 0, fresh);
      const row = fresh || (band ? band.row : newRow());
      row.keys.splice(Math.min(fresh ? 0 : at, row.keys.length), 0, ...ids);
      update();
      save();
    });
  }

  // "From canvas" in a panel's + menu: what is selected, or, with nothing selected, the next frame clicked.
  let picking = null;
  const stopPicking = () => { picking = null; view.classList.remove('picking'); toolNote.classList.add('hidden'); };
  function pickFromCanvas(onPick) {
    const chosen = items.filter((i) => selected.has(i.id));
    if (chosen.length) { onPick(chosen); return; }
    picking = (item) => onPick([item]);
    clearTimeout(noteTimer);
    view.classList.add('picking');
    toolNote.replaceChildren(el('span', {}, 'Click a frame to use it'),
      el('button', { class: 'btn small quiet', onclick: stopPicking }, 'Cancel'));
    toolNote.classList.remove('hidden');
  }

  // Put items into the agent's message, opening the agent tab first when another one is showing.
  function addToChat(list) {
    if (!(isOpen() && tab === 'agent')) showPanel(true, 'agent');
    for (const item of list) agent.attach(item);
    agent.focus();
  }

  function selectionChanged() {
    agent.selectionChanged();   // the message box offers what is selected, without adding it
    for (const box of boxes.values()) box.node.classList.toggle('selected', selected.has(box.key));
    dock.refresh();
    drawOverlay();
  }

  const download = (item) => el('a', { href: `/api/library/${item.id}/file?download=true`, download: item.filename }).click();
  const open = (item) => openViewer(item, { actions: /^(edit|upload)\//.test(item.workflow) ? []
    : [{ label: 'Re-run', run: (dialog) => { dialog.close(); store.rerun = item; store.from = '/canvas'; go('/create'); } }] });

  async function addToTimeline(videos, button) {
    button.disabled = true;
    try {
      const board = (await api('/api/boards/timeline?project=' + project)).data;
      const clips = (board.clips || []).concat(videos.map((v) => ({ id: v.id, start: 0, end: 0 })));   // end 0 = the whole clip
      await api('/api/boards/timeline', { method: 'PUT', json: { project: project || null, data: { ...board, clips } } });
      button.textContent = 'Added';
    } catch (e) { alert(e.message); button.disabled = false; }
  }

  // ------------------------------------------------------------ what floats over the canvas

  let overlayQueued = false;
  function drawOverlay() {
    if (overlayQueued) return;
    overlayQueued = true;
    requestAnimationFrame(() => { overlayQueued = false; drawContext(); drawMap(); });
  }

  function drawContext() {
    const chosen = items.filter((i) => selected.has(i.id) && boxes.has(i.id));
    context.classList.toggle('hidden', !chosen.length);
    if (!chosen.length) return;
    const videos = chosen.filter((i) => i.kind === 'video');
    const one = chosen.length === 1 ? chosen[0] : null;
    context.replaceChildren(...[
      !one && el('span', { class: 'slate-text' }, `${chosen.length} selected`),
      one && el('button', { class: 'btn small quiet', onclick: () => open(one) }, 'Open'),
      one && !/^(edit|upload)\//.test(one.workflow) && el('button', { class: 'btn small quiet', title: 'Open Create with the same settings',
        onclick: () => { store.rerun = one; store.from = '/canvas'; go('/create'); } }, 'Re-run'),
      videos.length > 0 && el('button', { class: 'btn small quiet', onclick: (e) => addToTimeline(videos, e.currentTarget) },
        one ? 'Add to timeline' : `Add ${videos.length} to timeline`),
      el('button', { class: 'btn small quiet', title: 'Download (D)', onclick: () => chosen.forEach(download) }, one ? 'Download' : `Download ${chosen.length}`),
      one && el('button', { class: 'btn small quiet', title: `Keep it in this project's ${KIT} under a name`,
        onclick: async () => { if (await addToKitDialog({ project, item: one })) { shared.load(); dock.recast(); } } }, `Add to ${KIT}`),
    ].filter(Boolean));
    const area = bounds(chosen.map((i) => boxes.get(i.id)));
    context.style.left = Math.max(8, cam.x + area.x * cam.k) + 'px';
    context.style.top = Math.max(56, cam.y + area.y * cam.k - 48) + 'px';
  }

  function drawMap() {
    map.classList.toggle('hidden', boxes.size < 2);
    if (boxes.size < 2) return;
    const rect = stage.getBoundingClientRect();
    const seen = { x: -cam.x / cam.k, y: -cam.y / cam.k, h: rect.height / cam.k, right: (rect.width - cam.x) / cam.k, bottom: (rect.height - cam.y) / cam.k };
    const all = bounds([...boxes.values()]);
    const left = Math.min(all.x, seen.x);
    const top = Math.min(all.y, seen.y);
    const scale = Math.min(120 / (Math.max(all.right, seen.right) - left), 72 / (Math.max(all.bottom, seen.bottom) - top));
    const at = (x, y, w, h) => `left:${(x - left) * scale}px;top:${(y - top) * scale}px;width:${w * scale}px;height:${h * scale}px`;
    map.replaceChildren(
      ...[...boxes.values()].map((b) => el('i', { class: selected.has(b.key) ? 'on' : '', style: at(b.x, b.y, FRAME, b.h) })),
      el('b', { style: at(seen.x, seen.y, seen.right - seen.x, seen.bottom - seen.y) }));
  }

  // ------------------------------------------------------------ loading and saving

  let saveTimer;
  function save() {
    agent.redraw();   // where each of the agent's results is ("Shot 3 › Take 2") may have changed
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => api('/api/boards/canvas', { method: 'PUT', json: { project: project || null, data: layout } }).catch(() => {}), 400);
  }

  async function loadItems() {
    items = (await api('/api/library' + (project ? '?project=' + project : ''))).items;
    for (const id of [...selected]) if (!items.some((i) => i.id === id)) selected.delete(id);
  }

  async function load() {
    ready = false;
    for (const [id, frame] of jobFrames) { frame.node.remove(); boxes.delete('job:' + id); }
    jobFrames.clear();
    try {
      projects = (await api('/api/projects')).projects;
      if (project && !projects.some((p) => p.id === project)) project = 0;
      picker.textContent = (projects.find((p) => p.id === project) || { name: 'All work' }).name;
      tabTitle((projects.find((p) => p.id === project) || { name: 'Canvas' }).name);
      const [board] = await Promise.all([api('/api/boards/canvas?project=' + project), loadItems(), loadAssets()]);
      drawAssets();
      const saved = board.data || {};
      layout = { rows: Array.isArray(saved.rows) ? saved.rows.filter((row) => row && Array.isArray(row.keys)) : [], count: Number(saved.count) || 0 };
      ready = true;
      draw();
      fit();
    } catch (e) { hint.textContent = e.message; hint.classList.remove('hidden'); }
  }

  const onKey = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); return showPanel(!isOpen()); }
    if (e.target.closest('input, textarea, select, dialog, [contenteditable]') || e.metaKey || e.ctrlKey) return;
    if (e.key === '1') fit();
    else if (e.key === '0') zoomTo(1);
    else if (e.key === 'Escape' && picking) stopPicking();
    else if (e.key === 'Escape' && selected.size) { selected.clear(); selectionChanged(); }
    else if (e.key === 'Enter' && selected.size === 1) open(items.find((i) => selected.has(i.id)));
    else if (e.key.toLowerCase() === 'd' && !e.altKey && !e.repeat) items.filter((i) => selected.has(i.id)).forEach(download);
  };
  window.addEventListener('keydown', onKey);
  const ticker = setInterval(() => {   // keeps elapsed time moving
    for (const job of store.jobs) if (job.status === 'running' && jobFrames.has(job.id)) jobFrames.get(job.id).clock.textContent = elapsed(job);
  }, 1000);
  const unsubscribe = subscribe((change) => {
    if (!ready) return;
    if (change === 'jobs') update();
    if (change === 'library') loadItems().then(draw).catch(() => {});
  });

  applyCamera();
  load();
  setWidth(Number(localStorage.getItem('scene.panel.width')));
  showPanel(true);
  return () => {
    unsubscribe();
    dock.destroy();
    agent.destroy();
    shared.destroy();
    clearInterval(ticker);
    clearTimeout(saveTimer);
    lazy.disconnect();
    window.removeEventListener('keydown', onKey);
    leaveBalance();
    view.classList.remove('full', 'with-panel', 'resizing');
    view.style.removeProperty('--panel-w');
  };
}
