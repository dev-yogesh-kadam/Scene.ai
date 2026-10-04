// The Timeline page: put finished videos in order, trim them, watch the cut and export it as one video.

import { api } from '../api.js';
import { el, icon, timecode } from '../dom.js';
import { subscribe } from '../store.js';

const fileUrl = (id) => `/api/library/${id}/file`;
const lengths = {};   // generation id -> promise of the video's length in seconds
const lengthOf = (id) => lengths[id] || (lengths[id] = new Promise((resolve) => {
  const probe = document.createElement('video');
  probe.preload = 'metadata';
  probe.onloadedmetadata = () => resolve(probe.duration || 0);
  probe.onerror = () => resolve(0);
  probe.src = fileUrl(id);
}));

export function render(view) {
  let project = Number(localStorage.getItem('scene.project')) || 0;   // 0 = everything
  let videos = [];
  let clips = [];        // {id, start, end, len}: start and end are seconds into the source video
  let chosen = -1;       // index of the selected clip
  let playing = false;
  let current = 0;       // index of the clip in the player
  let scale = 60;        // pixels per second
  let dragged = -1;

  const picker = el('select', { 'aria-label': 'Project', style: 'max-width:220px',
    onchange: (e) => { project = Number(e.target.value) || 0; localStorage.setItem('scene.project', project || ''); load(); } });
  const name = el('input', { type: 'text', value: 'Timeline', 'aria-label': 'Name of the exported video', style: 'max-width:200px', oninput: save });
  const exportButton = el('button', { class: 'btn primary', onclick: exportCut }, 'Export');
  const notice = el('p', { class: 'notice' });
  const video = el('video', { playsinline: true, onclick: toggle });
  const playButton = el('button', { class: 'icon-btn', onclick: toggle });
  const clock = el('span', { class: 'timecode' });
  const ruler = el('div', { class: 'tl-ruler', onclick: (e) => seek((e.clientX - ruler.getBoundingClientRect().left) / scale) });
  const lane = el('div', { class: 'tl-lane' });
  const playhead = el('div', { class: 'playhead' });
  const inner = el('div', { class: 'tl-inner' }, ruler, lane, playhead);
  const strip = el('div', { class: 'tl' }, el('div', { class: 'tl-name' }, 'V1'), el('div', { class: 'tl-scroll' }, inner));
  const inspector = el('div', { class: 'row tl-inspector' });
  const bin = el('div', { class: 'media-grid' });
  const body = el('div');

  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Timeline'), el('a', { class: 'btn quiet', href: '#/canvas' }, 'Canvas'), picker, name, exportButton),
    notice, body);

  const span = (c) => c.end - c.start;
  const total = () => clips.reduce((sum, c) => sum + span(c), 0);
  const before = (index) => clips.slice(0, index).reduce((sum, c) => sum + span(c), 0);
  const now = () => (clips[current] ? before(current) + clamp(video.currentTime - clips[current].start, 0, span(clips[current])) : 0);
  const clamp = (n, low, high) => Math.max(low, Math.min(high, n));

  // ------------------------------------------------------------ the player

  function show(index, offset, play) {
    const clip = clips[index];
    if (!clip) return stop();
    current = index;
    if (video.dataset.id !== String(clip.id)) { video.src = fileUrl(clip.id); video.dataset.id = clip.id; }
    video.currentTime = clip.start + offset;
    if (play) video.play().catch(() => {});
  }

  function seek(seconds) {
    let left = clamp(seconds, 0, Math.max(0, total() - 0.01));
    let index = 0;
    while (index < clips.length - 1 && left >= span(clips[index])) left -= span(clips[index++]);
    show(index, left, playing);
    drawClock();
  }

  function toggle() {
    if (!clips.length) return;
    playing = !playing;
    if (playing) {
      if (now() >= total() - 0.05) show(0, 0, true);   // at the end: start over
      else video.play().catch(() => {});
      requestAnimationFrame(tick);
    } else video.pause();
    drawClock();
  }

  function stop() {
    playing = false;
    video.pause();
    drawClock();
  }

  function tick() {
    if (!playing) return;
    const clip = clips[current];
    if (clip && video.currentTime >= clip.end - 0.02) {
      if (current + 1 < clips.length) show(current + 1, 0, true);
      else stop();
    }
    drawClock();
    requestAnimationFrame(tick);
  }

  function drawClock() {
    clock.textContent = `${timecode(now())} / ${timecode(total())}`;
    playhead.style.left = now() * scale + 'px';
    playButton.replaceChildren(icon(playing ? 'pause' : 'play'));
    playButton.title = playing ? 'Pause (Space)' : 'Play (Space)';
    playButton.setAttribute('aria-label', playButton.title);
  }

  // ------------------------------------------------------------ the strip

  function move(from, to) {
    if (to < 0 || to >= clips.length || from === to) return;
    clips.splice(to, 0, clips.splice(from, 1)[0]);
    chosen = to;
    changed();
  }

  function changed() {
    stop();
    draw();
    show(clamp(chosen, 0, clips.length - 1), 0, false);
    save();
  }

  function draw() {
    const seconds = total();
    scale = clamp((strip.clientWidth - 64) / Math.max(seconds, 1), 24, 120);
    const step = scale >= 60 ? 1 : scale >= 30 ? 2 : 5;
    ruler.replaceChildren(...Array.from({ length: Math.ceil(seconds / step) + 1 }, (_, i) =>
      el('span', { style: `width:${step * scale}px` }, timecode(i * step).slice(3, 8))));
    lane.replaceChildren(...(clips.length ? clips.map((clip, index) => {
      const item = videos.find((v) => v.id === clip.id) || { name: 'Missing video' };
      return el('div', { class: 'clip' + (index === chosen ? ' on gate' : ''), style: `width:${span(clip) * scale}px`, draggable: 'true',
        title: item.name,
        onclick: () => { chosen = index; stop(); draw(); show(index, 0, false); drawClock(); },
        ondragstart: () => { dragged = index; },
        ondragover: (e) => e.preventDefault(),
        ondrop: (e) => { e.preventDefault(); move(dragged, index); } },
        `${item.name} · ${span(clip).toFixed(1)} s`);
    }) : [el('span', { class: 'tl-hint muted' }, 'Add clips from your videos below.')]));
    playhead.classList.toggle('hidden', !clips.length);
    exportButton.disabled = !clips.length;

    const clip = clips[chosen];
    const cut = (key, low, high) => el('input', { type: 'number', step: 0.1, min: low.toFixed(1), max: high.toFixed(1), value: clip[key].toFixed(1), style: 'width:90px',
      onchange: (e) => { clip[key] = clamp(Number(e.target.value) || 0, low, high); changed(); } });
    inspector.replaceChildren(...(clip ? [
      el('span', { class: 'slate-text' }, `Clip ${chosen + 1} of ${clips.length}`),
      el('label', { class: 'row' }, el('span', { class: 'slate-text' }, 'In'), cut('start', 0, clip.end - 0.1)),
      el('label', { class: 'row' }, el('span', { class: 'slate-text' }, 'Out'), cut('end', clip.start + 0.1, clip.len)),
      el('button', { class: 'btn small', disabled: chosen === 0, onclick: () => move(chosen, chosen - 1) }, 'Move left'),
      el('button', { class: 'btn small', disabled: chosen === clips.length - 1, onclick: () => move(chosen, chosen + 1) }, 'Move right'),
      el('button', { class: 'btn small quiet danger', onclick: () => { clips.splice(chosen, 1); chosen = Math.min(chosen, clips.length - 1); changed(); } }, 'Remove'),
    ] : [el('span', { class: 'muted small' }, clips.length ? 'Click a clip to trim or move it. Drag clips to reorder them.' : '')]));
    drawClock();
  }

  function drawBin() {
    bin.replaceChildren(...videos.map((item) => el('div', { class: 'media' },
      el('div', { class: 'thumb', title: 'Add to the timeline', onclick: () => add(item) },
        el('video', { src: fileUrl(item.id) + '#t=0.1', preload: 'metadata', muted: true })),
      el('div', { class: 'meta' },
        el('div', { class: 'title', title: item.name }, item.name),
        el('div', { class: 'row' }, el('button', { class: 'btn small', onclick: () => add(item) }, 'Add to timeline'))))));
  }

  async function add(item) {
    const len = await lengthOf(item.id);
    if (!len) { notice.className = 'notice error'; notice.textContent = `${item.name} can't be read as a video.`; return; }
    clips.push({ id: item.id, start: 0, end: len, len });
    chosen = clips.length - 1;
    changed();
  }

  // ------------------------------------------------------------ loading, saving, exporting

  let saveTimer;
  function save() {
    clearTimeout(saveTimer);
    const data = { name: name.value, clips: clips.map(({ id, start, end }) => ({ id, start, end })) };
    saveTimer = setTimeout(() => api('/api/boards/timeline', { method: 'PUT', json: { project: project || null, data } }).catch(() => {}), 400);
  }

  async function exportCut() {
    notice.className = 'notice';
    notice.textContent = '';
    exportButton.disabled = true;
    exportButton.textContent = 'Exporting…';
    stop();
    try {
      const made = await api('/api/timeline/export', { method: 'POST', json: { name: name.value, project_id: project || null,
        clips: clips.map(({ id, start, end }) => ({ id, start, end })) } });
      notice.className = 'notice ok';
      notice.replaceChildren(`Exported "${made.name}" (${made.seconds.toFixed(1)} s). `, el('a', { href: '#/library' }, 'Open the library'));
    } catch (e) {
      notice.className = 'notice error';
      notice.textContent = e.message;
    }
    exportButton.textContent = 'Export';
    exportButton.disabled = !clips.length;
  }

  async function load() {
    try {
      const [projects, library, board] = await Promise.all([api('/api/projects'),
        api('/api/library?kind=video' + (project ? '&project=' + project : '')), api('/api/boards/timeline?project=' + project)]);
      picker.replaceChildren(el('option', { value: '' }, 'All work'),
        ...projects.projects.map((p) => el('option', { value: p.id, selected: p.id === project }, p.name)));
      videos = library.items;
      name.value = board.data.name || 'Timeline';
      // A saved clip keeps its place only while its video is still in the library; end 0 means the whole video.
      clips = [];
      for (const saved of (board.data.clips || []).filter((c) => videos.some((v) => v.id === c.id))) {
        const len = await lengthOf(saved.id);
        if (len) clips.push({ id: saved.id, start: clamp(saved.start || 0, 0, len - 0.1), end: clamp(saved.end || len, 0.1, len), len });
      }
      chosen = -1;
      if (!videos.length) {
        body.replaceChildren(el('div', { class: 'empty' }, 'No videos yet. Make one on the Create page, then put it in order here.'));
        exportButton.disabled = true;
        return;
      }
      body.replaceChildren(
        el('div', { class: 'player' }, video),
        el('div', { class: 'transport' }, playButton, clock),
        strip, inspector,
        el('h3', {}, 'Your videos'), bin);
      drawBin();
      draw();
      show(0, 0, false);
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error' }, e.message));
    }
  }

  const onKey = (e) => {
    if (e.key !== ' ' || e.target.closest('input, textarea, select, button, dialog')) return;
    e.preventDefault();
    toggle();
  };
  const onResize = () => { if (videos.length) draw(); };
  window.addEventListener('keydown', onKey);
  window.addEventListener('resize', onResize);
  const unsubscribe = subscribe((change) => {
    if (change !== 'library') return;
    api('/api/library?kind=video' + (project ? '&project=' + project : '')).then((library) => {
      if (!videos.length) return load();
      videos = library.items;
      drawBin();
      if (clips.some((c) => !videos.some((v) => v.id === c.id))) { clips = clips.filter((c) => videos.some((v) => v.id === c.id)); chosen = -1; changed(); }
    }).catch(() => {});
  });

  load();
  return () => {
    unsubscribe();
    clearTimeout(saveTimer);
    video.pause();
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('resize', onResize);
  };
}
