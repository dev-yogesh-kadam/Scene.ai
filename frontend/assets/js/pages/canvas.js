// The Canvas page: every finished item as a frame on an endless board. A panel on the right makes new work,
// either directly (Quick action) or through the agent.
// Each row is a shot: new work starts a row, work made from a frame joins that frame's row. Frames can be
// dragged between rows, and the rows are remembered per project. Work in progress shows as a frame the Gate runs around.

import { api } from '../api.js';
import { el, icon, runningGate, segmented, still } from '../dom.js';
import { store, subscribe } from '../store.js';
import { openViewer } from '../components/media.js';
import { quickActions } from '../components/quick.js';
import { agentPanel } from '../components/agent.js';
import { castEditor } from '../components/cast.js';

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
const TABS = [{ id: 'quick', label: 'Quick actions', icon: 'bolt' }, { id: 'agent', label: 'Agent', icon: 'chat' }];

const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
const heightOf = (item) => {
  const c = (item && item.context) || {};
  return Math.round(FRAME * (c.width && c.height ? c.height / c.width : 9 / 16));
};
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
  const boxes = new Map();        // what is on the canvas now: key -> {key, x, y, h, node}
  const jobFrames = new Map();    // job id -> the parts of its frame that change while it runs
  let agentJobs = new Set();      // jobs the agent started: their frames are drawn in the agent's colour

  const itemLayer = el('div');
  const jobLayer = el('div');
  const labelLayer = el('div');
  const world = el('div', { class: 'canvas-world' }, labelLayer, itemLayer, jobLayer);
  const stage = el('div', { class: 'canvas-stage' }, world);
  const picker = el('select', { 'aria-label': 'Project', onchange: (e) => { project = Number(e.target.value) || 0; localStorage.setItem('scene.project', project || ''); selected.clear(); load(); agent.reload(); cast.reload().then(() => dock.recast()); } });
  const count = el('span', { class: 'slate-text' });
  const context = el('div', { class: 'float canvas-context hidden' });
  const zoomLabel = el('button', { class: 'btn small quiet', title: 'Zoom to 100% (0)', onclick: () => zoomTo(1) });
  const map = el('div', { class: 'minimap hidden', 'aria-hidden': 'true' });
  const hint = el('p', { class: 'canvas-hint muted' }, 'Use the panel on the right to make a shot. Everything you make lands here.');
  const dock = quickActions({
    startFrom: () => (selected.size === 1 ? items.find((i) => selected.has(i.id) && i.kind !== 'audio') : null),   // a sound is not a frame to start on
    projectId: () => project || null,
  });

  // The agent is open to admins and to users an admin has given it to. For the others its tab says so.
  const comingSoon = () => ({ node: el('div', { class: 'agent-panel soon' },
    el('div', { class: 'soon-box' }, icon('chat'), el('span', { class: 'soon-tag' }, 'Coming soon'), el('b', {}, 'The agent'),
      el('p', { class: 'muted small' }, 'Describe what you want and have it planned for you. It is not open on your account yet.'),
      el('button', { class: 'btn small', onclick: () => showPanel(true, 'quick') }, 'Use Quick actions'))),
    attach: () => {}, reload: () => {}, focus: () => {}, destroy: () => {} });
  const agent = !store.user.agent ? comingSoon() : agentPanel({
    projectId: () => project,
    onJobs: (ids) => { agentJobs = new Set(ids); for (const [id, frame] of jobFrames) frame.node.classList.toggle('by-agent', agentJobs.has(id)); },
  });
  // The panel is open every time the canvas is entered, and remembers which of its two tabs was showing.
  let tab = localStorage.getItem('scene.panel.tab') === 'agent' && store.user.agent ? 'agent' : 'quick';   // Quick actions unless the agent was chosen
  const title = el('b', { class: 'panel-title' });
  const tabs = el('div');
  const quick = el('div', { class: 'panel-quick' }, dock.node);
  // The project's cast: its button sits in the head of the panel, for both tabs.
  const cast = castEditor({
    projectId: () => project,
    selected: () => (selected.size === 1 ? items.find((i) => selected.has(i.id)) || null : null),
    onChange: () => dock.recast(),
  });
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
    el('div', { class: 'panel-head' }, title, el('span', { style: 'flex:1' }), cast.button, tabs,
      el('button', { class: 'icon-btn', title: 'Close (Ctrl or ⌘ + J)', 'aria-label': 'Close the panel', onclick: () => showPanel(false) }, '×')),
    cast.box, quick, agent.node);
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
    if (open) (tab === 'agent' ? agent : dock).focus();
    if (ready) fit();
  }

  view.replaceChildren(stage,
    el('div', { class: 'float canvas-bar' }, picker, count, el('a', { class: 'btn small quiet', href: '#/timeline', title: 'Put this project\'s videos in order' }, 'Timeline')),
    context,
    el('div', { class: 'float canvas-view' },
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
      const node = el('div', { class: 'frame' + (selected.has(item.id) ? ' selected' : ''), style: `left:${spot.x}px;top:${spot.y}px`, title: item.name,
        onpointerdown: (e) => grab(e, item.id), ondblclick: () => open(item) },
        shot,
        el('div', { class: 'slate' }, el('b', {}, item.kind), el('span', {}, c.width ? `${c.width}×${c.height}` : item.name)));
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
        const node = el('div', { class: 'frame developing' + (agentJobs.has(job.id) ? ' by-agent' : ''), title: job.name },
          shot, el('div', { class: 'slate' }, el('b', {}, job.workflow.split('/')[0]), fact));
        frame = { node, shot, clock, fact, gate: null };
        jobFrames.set(job.id, frame);
        jobLayer.append(node);
        boxes.set('job:' + job.id, { key: 'job:' + job.id, ...spot, node });
      }
      const waiting = job.status === 'queued';
      if (!waiting && !frame.gate) frame.gate = frame.shot.appendChild(runningGate());
      frame.clock.textContent = waiting ? 'queued' : elapsed(job);
      frame.fact.textContent = waiting ? `position ${job.position}` : job.steps ? `step ${job.step} of ${job.steps}` : 'starting';
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
    }
    labelLayer.replaceChildren(...bands.map((band, i) => el('button', { class: 'shot-label', title: 'Rename this shot',
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
    if (!boxes.size) { cam.x = 96; cam.y = 96; cam.k = 1; return applyCamera(); }
    const all = bounds([...boxes.values()]);
    all.x -= LABEL;   // the names of the shots are part of the picture
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

  function grab(e, id) {
    if (e.button !== 0) return;
    e.stopPropagation();
    if (e.shiftKey) { selected.has(id) ? selected.delete(id) : selected.add(id); }
    else if (!selected.has(id)) { selected.clear(); selected.add(id); }
    selectionChanged();
    const from = { x: e.clientX, y: e.clientY };
    const moving = [...selected].map((key) => boxes.get(key)).filter(Boolean).map((box) => ({ box, x: box.x, y: box.y }));
    let moved = false;
    track((ev) => {
      const dx = (ev.clientX - from.x) / cam.k;
      const dy = (ev.clientY - from.y) / cam.k;
      moved = moved || Math.abs(dx) + Math.abs(dy) > 3 / cam.k;
      if (!moved) return;
      context.classList.add('hidden');
      for (const m of moving) {
        m.box.x = Math.round((m.x + dx) / SNAP) * SNAP;
        m.box.y = Math.round((m.y + dy) / SNAP) * SNAP;
        m.box.node.style.left = m.box.x + 'px';
        m.box.node.style.top = m.box.y + 'px';
      }
    }, () => {
      // A click on a frame while the agent is open attaches it to the message, so several can be named one after another.
      if (!moved && isOpen() && tab === 'agent') agent.attach(items.find((i) => i.id === id));
      if (!moved) return;
      // Dropped frames join the shot they were dropped on, at that place in the row; below the last row they start a new shot.
      const dropped = boxes.get(id);
      const middle = dropped.y + dropped.h / 2;
      const ids = moving.map((m) => m.box.key).filter((key) => typeof key === 'number');
      const band = bands.find((b) => middle < b.y + b.h + SLATE + GAP / 2);
      const at = Math.max(0, Math.round(dropped.x / (FRAME + GAP)));
      for (const row of layout.rows) row.keys = row.keys.filter((key) => !ids.includes(key));
      const row = band ? band.row : newRow();
      row.keys.splice(Math.min(at, row.keys.length), 0, ...ids);
      update();
      save();
    });
  }

  function selectionChanged() {
    for (const box of boxes.values()) box.node.classList.toggle('selected', selected.has(box.key));
    dock.refresh();
    cast.refresh();
    drawOverlay();
  }

  const open = (item) => openViewer(item, { actions: item.workflow.startsWith('edit/') ? []
    : [{ label: 'Re-run', run: (dialog) => { dialog.close(); store.rerun = item; location.hash = '#/create'; } }] });

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
      one && !one.workflow.startsWith('edit/') && el('button', { class: 'btn small quiet', title: 'Open Create with the same settings',
        onclick: () => { store.rerun = one; location.hash = '#/create'; } }, 'Re-run'),
      videos.length > 0 && el('button', { class: 'btn small quiet', onclick: (e) => addToTimeline(videos, e.currentTarget) },
        one ? 'Add to timeline' : `Add ${videos.length} to timeline`),
      one && el('a', { class: 'btn small quiet', href: `/api/library/${one.id}/file?download=true`, download: one.filename }, 'Download'),
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
      picker.replaceChildren(el('option', { value: '' }, 'All work'),
        ...projects.map((p) => el('option', { value: p.id, selected: p.id === project }, p.name)));
      const [board] = await Promise.all([api('/api/boards/canvas?project=' + project), loadItems()]);
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
    else if (e.key === 'Escape' && selected.size) { selected.clear(); selectionChanged(); }
    else if (e.key === 'Enter' && selected.size === 1) open(items.find((i) => selected.has(i.id)));
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
  cast.reload();
  setWidth(Number(localStorage.getItem('scene.panel.width')));
  showPanel(true);
  return () => {
    unsubscribe();
    dock.destroy();
    agent.destroy();
    clearInterval(ticker);
    clearTimeout(saveTimer);
    lazy.disconnect();
    window.removeEventListener('keydown', onKey);
    view.classList.remove('full', 'with-panel', 'resizing');
    view.style.removeProperty('--panel-w');
  };
}
