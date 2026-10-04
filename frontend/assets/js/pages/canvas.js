// The Canvas page: every finished item as a frame on an endless board, with the composer docked below.
// Frames can be moved and are remembered per project. Work in progress shows as a frame the Gate runs around.

import { api } from '../api.js';
import { el, runningGate } from '../dom.js';
import { store, subscribe } from '../store.js';
import { openViewer } from '../components/media.js';
import { composer } from '../components/composer.js';
import { agentPanel } from '../components/agent.js';

const FRAME = 240;      // width of every frame, in canvas units
const SLATE = 24;       // room under a frame for its line of facts
const GAP = 48;
const COLUMNS = 5;      // new work is laid out in this many columns
const SNAP = 8;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const ACTIVE = ['queued', 'running'];

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
  let layout = { items: {} };     // items: generation id -> {x, y}
  let ready = false;              // false until the saved layout is loaded: nothing may be placed before that
  const cam = { x: 96, y: 96, k: 1 };
  const selected = new Set();     // generation ids
  const jobSpots = {};            // job id -> {x, y}: where a job's frame waits and where its result lands
  const boxes = new Map();        // what is on the canvas now: key -> {key, x, y, h, node}
  const jobFrames = new Map();    // job id -> the parts of its frame that change while it runs
  let agentJobs = new Set();      // jobs the agent started: their frames are drawn in the agent's colour

  const itemLayer = el('div');
  const jobLayer = el('div');
  const world = el('div', { class: 'canvas-world' }, itemLayer, jobLayer);
  const stage = el('div', { class: 'canvas-stage' }, world);
  const picker = el('select', { 'aria-label': 'Project', onchange: (e) => { project = Number(e.target.value) || 0; localStorage.setItem('scene.project', project || ''); selected.clear(); load(); agent.reload(); } });
  const count = el('span', { class: 'slate-text' });
  const context = el('div', { class: 'float canvas-context hidden' });
  const zoomLabel = el('button', { class: 'btn small quiet', title: 'Zoom to 100% (0)', onclick: () => zoomTo(1) });
  const map = el('div', { class: 'minimap hidden', 'aria-hidden': 'true' });
  const hint = el('p', { class: 'canvas-hint muted' }, 'Describe a shot below. Everything you make lands here.');
  const dock = composer({
    startFrom: () => (selected.size === 1 ? items.find((i) => selected.has(i.id)) : null),
    projectId: () => project || null,
  });

  const chosenItems = () => items.filter((i) => selected.has(i.id));
  const agent = agentPanel({
    selection: chosenItems,
    projectId: () => project,
    onJobs: (ids) => { agentJobs = new Set(ids); for (const [id, frame] of jobFrames) frame.node.classList.toggle('by-agent', agentJobs.has(id)); },
    onClose: () => showAgent(false),
  });
  const agentButton = el('button', { class: 'btn small quiet', title: 'Open the agent (Ctrl or ⌘ + J)', onclick: () => showAgent(!view.classList.contains('with-agent')) }, 'Agent');
  function showAgent(open) {
    view.classList.toggle('with-agent', open);
    agentButton.classList.toggle('on', open);
    localStorage.setItem('scene.agent', open ? '1' : '');
    if (open) agent.focus();
    if (ready) fit();
  }

  view.replaceChildren(stage,
    el('div', { class: 'float canvas-bar' }, picker, count),
    context,
    el('div', { class: 'float canvas-view' },
      el('button', { class: 'btn small quiet', title: 'Fit everything (1)', onclick: () => fit() }, 'Fit'),
      zoomLabel, agentButton),
    map, agent.node,
    el('div', { class: 'canvas-dock' }, hint, dock.node));

  // ------------------------------------------------------------ layout

  const lazy = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      lazy.unobserve(entry.target);
      entry.target.append(media(entry.target.item));
    }
  }, { root: stage, rootMargin: '300px' });

  const media = (item) => (item.kind === 'video'
    ? el('video', { src: `/api/library/${item.id}/file#t=0.1`, preload: 'metadata', muted: true })
    : el('img', { src: `/api/library/${item.id}/file`, alt: item.name, draggable: 'false' }));

  // Give everything without a saved place a spot under the shortest column.
  function place() {
    const jobs = store.jobs.filter((j) => ACTIVE.includes(j.status) && (!project || j.project_id === project));
    for (const id of Object.keys(jobSpots)) {
      const job = store.jobs.find((j) => j.id === id);
      if (!job || job.status === 'failed' || job.status === 'cancelled') delete jobSpots[id];
    }
    const bottoms = Array(COLUMNS).fill(0);
    const taken = (spot, h) => {
      const column = clamp(Math.round(spot.x / (FRAME + GAP)), 0, COLUMNS - 1);
      bottoms[column] = Math.max(bottoms[column], spot.y + h + SLATE + GAP);
    };
    for (const item of items) if (layout.items[item.id]) taken(layout.items[item.id], heightOf(item));
    for (const spot of Object.values(jobSpots)) taken(spot, heightOf());
    const next = (h) => {
      const column = bottoms.indexOf(Math.min(...bottoms));
      const spot = { x: column * (FRAME + GAP), y: bottoms[column] };
      bottoms[column] += h + SLATE + GAP;
      return spot;
    };
    for (const item of [...items].reverse()) {   // oldest first, so new work lands at the end
      if (layout.items[item.id]) continue;
      layout.items[item.id] = jobSpots[item.job_id] || next(heightOf(item));
      delete jobSpots[item.job_id];
    }
    for (const job of jobs) if (!jobSpots[job.id]) jobSpots[job.id] = next(heightOf());
    return jobs;
  }

  function drawItems() {
    for (const key of [...boxes.keys()]) if (typeof key === 'number') boxes.delete(key);
    lazy.disconnect();
    itemLayer.replaceChildren(...items.map((item) => {
      const spot = layout.items[item.id];
      const h = heightOf(item);
      const shot = el('div', { class: 'shot gate', style: `height:${h}px` });
      shot.item = item;
      lazy.observe(shot);
      const c = item.context || {};
      const node = el('div', { class: 'frame' + (selected.has(item.id) ? ' selected' : ''), style: `left:${spot.x}px;top:${spot.y}px`, title: item.name,
        onpointerdown: (e) => grab(e, item.id), ondblclick: () => open(item) },
        shot,
        el('div', { class: 'slate' }, el('b', {}, item.kind), el('span', {}, c.width ? `${c.width}×${c.height}` : item.name)));
      boxes.set(item.id, { key: item.id, x: spot.x, y: spot.y, h, node });
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
      let frame = jobFrames.get(job.id);
      if (!frame) {
        const spot = jobSpots[job.id];
        const clock = el('span');
        const fact = el('span');
        const shot = el('div', { class: 'shot', style: `height:${heightOf()}px` }, clock);
        const node = el('div', { class: 'frame developing' + (agentJobs.has(job.id) ? ' by-agent' : ''), style: `left:${spot.x}px;top:${spot.y}px`, title: job.name },
          shot, el('div', { class: 'slate' }, el('b', {}, job.workflow.split('/')[0]), fact));
        frame = { node, shot, clock, fact, gate: null };
        jobFrames.set(job.id, frame);
        jobLayer.append(node);
        boxes.set('job:' + job.id, { key: 'job:' + job.id, x: spot.x, y: spot.y, h: heightOf(), node });
      }
      const waiting = job.status === 'queued';
      if (!waiting && !frame.gate) frame.gate = frame.shot.appendChild(runningGate());
      frame.clock.textContent = waiting ? 'queued' : elapsed(job);
      frame.fact.textContent = waiting ? `position ${job.position}` : job.steps ? `step ${job.step} of ${job.steps}` : 'starting';
    }
    hint.classList.toggle('hidden', boxes.size > 0);
    drawOverlay();
  }

  function draw() {
    const jobs = place();
    drawItems();
    drawJobs(jobs);
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
    const rect = stage.getBoundingClientRect();
    const panel = view.classList.contains('with-agent') ? 392 : 0;   // the open agent panel covers the right side
    const room = { w: rect.width - 160 - panel, h: rect.height - 80 - view.querySelector('.canvas-dock').offsetHeight - 80 };
    cam.k = clamp(Math.min(room.w / (all.right - all.x), room.h / (all.bottom - all.y)), MIN_ZOOM, 1);
    cam.x = (rect.width - panel - (all.right - all.x) * cam.k) / 2 - all.x * cam.k;
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
      if (!moved) return;
      for (const m of moving) layout.items[m.box.key] = { x: m.box.x, y: m.box.y };
      save();
      drawOverlay();
    });
  }

  function selectionChanged() {
    for (const box of boxes.values()) box.node.classList.toggle('selected', selected.has(box.key));
    dock.refresh();
    agent.refresh();
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
    for (const [id, frame] of jobFrames) { frame.node.remove(); boxes.delete('job:' + id); delete jobSpots[id]; }
    jobFrames.clear();
    try {
      projects = (await api('/api/projects')).projects;
      if (project && !projects.some((p) => p.id === project)) project = 0;
      picker.replaceChildren(el('option', { value: '' }, 'All work'),
        ...projects.map((p) => el('option', { value: p.id, selected: p.id === project }, p.name)));
      const [board] = await Promise.all([api('/api/boards/canvas?project=' + project), loadItems()]);
      layout = { items: {}, ...board.data };
      ready = true;
      const unplaced = items.some((i) => !layout.items[i.id]);
      draw();
      dock.refresh();
      fit();
      if (unplaced) save();
    } catch (e) { hint.textContent = e.message; hint.classList.remove('hidden'); }
  }

  const onKey = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); return showAgent(!view.classList.contains('with-agent')); }
    if (e.target.closest('input, textarea, select, dialog') || e.metaKey || e.ctrlKey) return;
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
    if (change === 'jobs') drawJobs(place());
    if (change === 'library') loadItems().then(() => { draw(); save(); }).catch(() => {});
  });

  applyCamera();
  load();
  if (localStorage.getItem('scene.agent')) showAgent(true);
  return () => {
    unsubscribe();
    dock.destroy();
    agent.destroy();
    clearInterval(ticker);
    clearTimeout(saveTimer);
    lazy.disconnect();
    window.removeEventListener('keydown', onKey);
    view.classList.remove('full', 'with-agent');
  };
}
