// The compare board: a full-screen board over the canvas for testing workflows against each other. On the left a test
// is set up (prompts, workflows, pictures, takes, one seed for all); on the right a run is shown as a grid, prompts down
// the side and workflows across the top, each cell filling in live with what it made, how long it took, or why it
// failed. A cell opens big; the best of a row can be starred; each column says how its workflow did. Earlier runs are
// kept and can be opened again. Admins only. See backend/scene/api/bulk.py.

import { api } from '../api.js';
import { el, field, icon, segmented, still } from '../dom.js';
import { subscribe } from '../store.js';

const KINDS = [{ id: 'image', label: 'Images' }, { id: 'video', label: 'Videos' }];
const QUALITY = [{ id: 'draft', label: 'Draft' }, { id: 'final', label: 'Final' }];
const SIZES = [{ id: 480, label: '480p' }, { id: 720, label: '720p' }, { id: 1080, label: '1080p' }];
const SHAPES = [{ id: 'landscape', label: 'Landscape' }, { id: 'portrait', label: 'Portrait' }, { id: 'square', label: 'Square' }];
const TAKES = [1, 2, 3, 4].map((n) => ({ id: n, label: String(n) }));
const MOST_PICTURES = 6;
const MOST_PROMPTS = 20;
const MOST_JOBS = 400;
const LIVE = 3000;   // ms between looks at a run that is still being made

const short = (title) => String(title || '').replace(/^(Text|Image) to (Image|Video): /, '');
const clock = (s) => (s == null ? '' : s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);

// Stars are this browser's notes on a run: which cell was best. Kept per run.
const starsOf = (run) => { try { return new Set(JSON.parse(localStorage.getItem('scene.stars.' + run) || '[]')); } catch (e) { return new Set(); } };
const keepStars = (run, set) => { try { localStorage.setItem('scene.stars.' + run, JSON.stringify([...set])); } catch (e) { /* no storage */ } };

export function compareBoard({ projectId, onQueued }) {
  const s = { kind: 'image', prompts: [''], pictures: [], quality: 'final', resolution: 720, orientation: 'landscape', duration: 5,
    takes: 1, sameSeed: true, picked: {}, lists: {}, filter: '', run: null, grid: null, runs: [], view: 'setup' };
  let timer = 0;
  let unsubscribe = null;
  const root = el('div', { class: 'board', role: 'dialog', 'aria-label': 'Compare board' });
  const setup = el('aside', { class: 'board-setup' });
  const main = el('section', { class: 'board-main' });
  const head = el('header', { class: 'board-head' });
  root.append(head, el('div', { class: 'board-body' }, setup, main));

  // ---------------------------------------------------------------- the test

  async function list() {
    if (!s.lists[s.kind]) {
      s.lists[s.kind] = (await api('/api/bulk/workflows?kind=' + s.kind)).workflows;
      s.picked[s.kind] = s.picked[s.kind] || new Set();
    }
    return s.lists[s.kind];
  }
  const usable = (w) => !w.error && !w.needs_other.length && w.needs_pictures <= s.pictures.length;
  const why = (w) => w.error ? 'Not readable' : w.needs_other.length ? `Needs ${w.needs_other.join(', ')}`
    : w.needs_pictures > s.pictures.length ? `Needs ${w.needs_pictures} picture${w.needs_pictures === 1 ? '' : 's'}`
      : w.pictures ? `${w.pictures} picture slot${w.pictures === 1 ? '' : 's'}` : 'Prompt only';

  async function drawSetup() {
    let workflows = [];
    const notice = el('p', { class: 'notice' });
    try { workflows = await list(); } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
    const picked = s.picked[s.kind];
    const ready = workflows.filter((w) => picked.has(w.id) && usable(w));
    const prompts = s.prompts.filter((p) => p.trim());
    const total = prompts.length * ready.length * s.takes;
    const count = el('div', { class: 'board-count' });
    const go = el('button', { class: 'btn primary block' });
    const refresh = () => {
      const p = s.prompts.filter((x) => x.trim()).length;
      const n = p * ready.length * s.takes;
      count.replaceChildren(el('b', {}, `${p} prompt${p === 1 ? '' : 's'} × ${ready.length} workflow${ready.length === 1 ? '' : 's'}`
        + (s.takes > 1 ? ` × ${s.takes} takes` : '')), el('span', {}, ` = ${n} render${n === 1 ? '' : 's'}`));
      go.disabled = !n || n > MOST_JOBS;
      go.textContent = n > MOST_JOBS ? `At most ${MOST_JOBS} renders in one run` : `Run the test · ${n} render${n === 1 ? '' : 's'}`;
    };
    go.onclick = () => start(go, notice);

    const promptRows = s.prompts.map((p, i) => el('div', { class: 'board-prompt' },
      el('span', { class: 'board-shot' }, `Shot ${i + 1}`),
      el('textarea', { rows: 2, placeholder: i ? 'Another prompt' : 'What to make', oninput: (e) => { s.prompts[i] = e.target.value; refresh(); } }, p),
      s.prompts.length > 1 && el('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove shot ${i + 1}`, title: 'Remove',
        onclick: () => { s.prompts.splice(i, 1); drawSetup(); } }, '×')));
    const paste = () => {   // many prompts at once: one per line
      const text = prompt('Paste prompts, one per line:');
      if (!text) return;
      const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      s.prompts = [...s.prompts.filter((x) => x.trim()), ...lines].slice(0, MOST_PROMPTS);
      if (!s.prompts.length) s.prompts = [''];
      drawSetup();
    };

    const files = el('input', { type: 'file', accept: 'image/*', multiple: true, class: 'hidden',
      onchange: (e) => { s.pictures = [...s.pictures, ...e.target.files].slice(0, MOST_PICTURES); drawSetup(); } });
    const shown = workflows.filter((w) => !s.filter || w.title.toLowerCase().includes(s.filter.toLowerCase()));
    const checks = el('div', { class: 'board-checks' }, shown.map((w) => el('label', { class: 'bulk-check' + (usable(w) ? '' : ' off') },
      el('input', { type: 'checkbox', checked: picked.has(w.id), disabled: !!w.error,
        onchange: (e) => { if (e.target.checked) picked.add(w.id); else picked.delete(w.id); drawSetup(); } }),
      el('span', { class: 'bulk-name', title: w.title }, short(w.title)),
      el('span', { class: 'muted small' }, why(w)))));

    setup.replaceChildren(
      segmented(KINDS, s.kind, (k) => { s.kind = k; drawSetup(); }),
      el('div', { class: 'board-group' },
        el('div', { class: 'board-label' }, el('span', {}, `Prompts · ${s.prompts.length} of ${MOST_PROMPTS}`),
          el('span', { class: 'row' },
            el('button', { class: 'btn small quiet', type: 'button', onclick: paste }, 'Paste many'),
            el('button', { class: 'btn small', type: 'button', disabled: s.prompts.length >= MOST_PROMPTS,
              onclick: () => { s.prompts.push(''); drawSetup(); setup.querySelectorAll('textarea')[s.prompts.length - 1]?.focus(); } }, '+ Prompt'))),
        el('p', { class: 'hint' }, 'Each prompt is a row of the board, a shot made by every workflow.'),
        ...promptRows),
      el('div', { class: 'board-group' },
        el('div', { class: 'board-label' }, el('span', {}, `Workflows · ${picked.size} ticked`),
          el('span', { class: 'row' },
            el('button', { class: 'btn small quiet', type: 'button', onclick: () => { workflows.filter(usable).forEach((w) => picked.add(w.id)); drawSetup(); } }, 'All'),
            el('button', { class: 'btn small quiet', type: 'button', onclick: () => { picked.clear(); drawSetup(); } }, 'None'))),
        el('input', { type: 'search', class: 'search', placeholder: 'Find a workflow', value: s.filter,
          oninput: (e) => { s.filter = e.target.value; const at = e.target.selectionStart; drawSetup().then(() => { const box = setup.querySelector('.board-group input[type=search]'); box.focus(); box.setSelectionRange(at, at); }); } }),
        checks),
      el('div', { class: 'board-group' },
        el('div', { class: 'board-label' }, el('span', {}, `Pictures · ${s.pictures.length} of ${MOST_PICTURES}`)),
        el('div', { class: 'bulk-pictures' },
          ...s.pictures.map((file, i) => el('div', { class: 'bulk-picture', title: `Picture ${i + 1}: ${file.name}` },
            el('img', { src: URL.createObjectURL(file), alt: file.name }),
            el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + file.name, onclick: () => { s.pictures.splice(i, 1); drawSetup(); } }, '×'))),
          s.pictures.length >= MOST_PICTURES ? null : el('button', { class: 'bulk-add', type: 'button', title: 'Add pictures', onclick: () => files.click() }, '+'),
          files),
        el('p', { class: 'hint' }, 'The same pictures for every prompt: picture 1 in each workflow\'s first picture slot, and so on.')),
      el('div', { class: 'board-group board-grid2' },
        field('Quality', segmented(QUALITY, s.quality, (q) => { s.quality = q; drawSetup(); })),
        field('Takes per cell', segmented(TAKES, s.takes, (t) => { s.takes = t; drawSetup(); })),
        s.kind === 'video' && field('Size', segmented(SIZES, s.resolution, (r) => { s.resolution = r; drawSetup(); })),
        s.kind === 'video' && field('Shape', segmented(SHAPES, s.orientation, (o) => { s.orientation = o; drawSetup(); })),
        s.kind === 'video' && field('Length (seconds)', el('input', { type: 'number', min: 1, max: 20, value: s.duration, oninput: (e) => { s.duration = Number(e.target.value) || 5; } }))),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: s.sameSeed, onchange: (e) => { s.sameSeed = e.target.checked; } }),
        'One seed for every cell (a fair comparison; each take gets its own)'),
      el('div', { class: 'board-go' }, count, notice, go));
    refresh();
  }

  async function start(button, notice) {
    const form = new FormData();
    form.append('kind', s.kind);
    form.append('prompts', JSON.stringify(s.prompts.filter((p) => p.trim())));
    form.append('workflows', JSON.stringify([...s.picked[s.kind]].filter((id) => s.lists[s.kind].some((w) => w.id === id && usable(w)))));
    form.append('quality', s.quality);
    form.append('takes', s.takes);
    form.append('same_seed', s.sameSeed ? '1' : '');
    form.append('project_id', projectId() || '');
    if (s.kind === 'video') { form.append('resolution', s.resolution); form.append('orientation', s.orientation); form.append('duration', s.duration); }
    for (const file of s.pictures) form.append('picture', file);
    button.disabled = true;
    button.textContent = 'Starting…';
    try {
      const done = await api('/api/bulk', { method: 'POST', body: form });
      if (done.skipped.length) alert(`Left out:\n${done.skipped.map((x) => `${short(x.title)}: ${x.why}`).join('\n')}`);
      onQueued();
      await openRun(done.run);
    } catch (e) {
      notice.className = 'notice error'; notice.textContent = e.message;
      button.disabled = false; button.textContent = 'Run the test';
    }
  }

  // ---------------------------------------------------------------- runs

  async function drawHead() {
    try { s.runs = (await api('/api/bulk/runs')).runs; } catch (e) { s.runs = []; }
    const picker = el('select', { class: 'board-runs', 'aria-label': 'Earlier runs', onchange: (e) => (e.target.value ? openRun(e.target.value) : newTest()) },
      el('option', { value: '', selected: !s.run }, 'New test'),
      ...s.runs.map((r) => el('option', { value: r.run, selected: r.run === s.run },
        `${new Date(r.created * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })} · ${r.cells} cells · ${r.prompt.slice(0, 50)}`)));
    const busy = s.grid && s.grid.cells.some((c) => c.status === 'queued');
    head.replaceChildren(...[
      el('button', { class: 'btn small board-back', onclick: close, title: 'Back to the canvas (Esc)' }, icon('back'), 'Back to the canvas'),
      el('h2', {}, 'Compare board'),
      picker,
      s.run && el('button', { class: 'btn small', onclick: newTest }, '+ New test'),
      s.run && el('button', { class: 'btn small', onclick: () => { s.view = s.view === 'setup' ? 'grid' : 'setup'; layout(); } }, s.view === 'setup' ? 'Hide the setup' : 'Show the setup'),
      busy && el('button', { class: 'btn small quiet danger', onclick: stopRun }, 'Stop the waiting renders'),
      el('span', { style: 'flex:1' }),
      el('button', { class: 'icon-btn', 'aria-label': 'Close the board', title: 'Close', onclick: close }, '×')].filter(Boolean));
  }

  function newTest() {
    s.run = null; s.grid = null; s.view = 'setup';
    clearTimeout(timer);
    layout(); drawHead(); drawSetup(); drawGrid();
  }

  async function openRun(run) {
    s.run = run;
    s.view = 'grid';
    await load();
    layout(); drawHead();
  }

  async function load() {
    clearTimeout(timer);
    if (!s.run) return;
    try { s.grid = await api('/api/bulk/runs/' + s.run); } catch (e) { s.grid = null; main.replaceChildren(el('p', { class: 'notice error' }, e.message)); return; }
    drawGrid();
    if (s.grid.cells.some((c) => c.status === 'queued' || c.status === 'running')) timer = setTimeout(load, LIVE);
    else drawHead();   // finished: the Stop button goes
  }

  async function stopRun() {
    if (!confirm('Cancel every render of this run that is still waiting? The ones running finish.')) return;
    try { await api(`/api/bulk/runs/${s.run}`, { method: 'DELETE' }); onQueued(); await load(); drawHead(); } catch (e) { alert(e.message); }
  }

  async function again(cell) {
    try { await api(`/api/bulk/runs/${s.run}/again`, { method: 'POST', json: { job: cell.job } }); onQueued(); await load(); drawHead(); } catch (e) { alert(e.message); }
  }

  // ---------------------------------------------------------------- the grid

  function drawGrid() {
    const g = s.grid;
    if (!g) {
      main.replaceChildren(el('div', { class: 'board-empty' },
        el('h3', {}, 'Set up a test on the left'),
        el('p', { class: 'muted' }, 'Write a prompt or a few, tick the workflows to compare, and run it. The board fills in as the renders finish: one row per prompt, one column per workflow.')));
      return;
    }
    const stars = starsOf(g.run);
    const at = new Map();
    for (const c of g.cells) at.set(`${c.row}|${c.workflow}`, [...(at.get(`${c.row}|${c.workflow}`) || []), c]);
    const cols = g.workflows;
    const table = el('div', { class: 'board-table', style: `grid-template-columns: minmax(180px, 240px) repeat(${cols.length}, minmax(200px, 1fr))` });
    table.append(el('div', { class: 'board-corner' },
      el('b', {}, `${g.prompts.length} × ${cols.length}${g.takes > 1 ? ` × ${g.takes}` : ''}`),
      el('span', { class: 'muted small' }, g.same_seed ? 'One seed per take' : 'Random seeds')));
    for (const w of cols) table.append(el('div', { class: 'board-col', title: w.title }, short(w.title)));
    g.rows.forEach((row, i) => {
      table.append(el('div', { class: 'board-rowhead' }, el('b', {}, `Shot ${i + 1}`), el('p', { title: g.prompts[i] }, g.prompts[i])));
      for (const w of cols) table.append(cell(at.get(`${row}|${w.id}`) || [], stars, g, i, w));
    });
    // How each workflow did over the whole run.
    table.append(el('div', { class: 'board-foothead muted small' }, 'Over the run'));
    for (const w of cols) {
      const mine = g.cells.filter((c) => c.workflow === w.id);
      const done = mine.filter((c) => c.status === 'done');
      const times = done.map((c) => c.seconds).filter((x) => x != null);
      const failed = mine.filter((c) => c.status === 'failed').length;
      const starred = mine.filter((c) => stars.has(c.job)).length;
      table.append(el('div', { class: 'board-foot' },
        el('span', {}, `${done.length} of ${mine.length} made`),
        times.length ? el('span', {}, `avg ${clock(times.reduce((a, b) => a + b, 0) / times.length)}`) : null,
        failed ? el('span', { class: 'bad' }, `${failed} failed`) : null,
        starred ? el('span', { class: 'star-count' }, `★ ${starred}`) : null));
    }
    const made = g.cells.filter((c) => c.status === 'done').length;
    main.replaceChildren(
      el('div', { class: 'board-progress' }, el('i', { style: `width:${(100 * g.cells.filter((c) => !['queued', 'running'].includes(c.status)).length / g.cells.length).toFixed(1)}%` })),
      el('p', { class: 'muted small board-status' }, `${made} of ${g.cells.length} made` + (g.cells.some((c) => c.status === 'running') ? ' · rendering' : '')),
      el('div', { class: 'board-scroll' }, table));
  }

  function cell(takes, stars, g, rowIndex, w) {
    const box = el('div', { class: 'board-cell' });
    if (!takes.length) { box.append(el('div', { class: 'board-blank muted small' }, 'Left out')); return box; }
    for (const c of takes.sort((a, b) => a.take - b.take)) {
      const item = c.items[0];
      const frame = el('div', { class: 'board-frame ' + c.status });
      if (c.status === 'done' && item) {
        frame.append(still(`/api/library/${item.id}/file`, item.kind, item.name));
        frame.tabIndex = 0;
        frame.onclick = () => openBig(g, rowIndex, w, c);
      } else if (c.status === 'failed') {
        frame.append(el('div', { class: 'board-why' }, el('b', {}, 'Failed'), el('span', {}, c.error || 'Something went wrong.')));
      } else if (c.status === 'running') {
        frame.append(el('div', { class: 'board-wait' }, el('span', { class: 'board-dot' }), clock(c.started ? Date.now() / 1000 - c.started : 0)));
      } else {
        frame.append(el('div', { class: 'board-wait muted' }, c.status === 'cancelled' ? 'Stopped' : 'Waiting'));
      }
      const starred = stars.has(c.job);
      const meta = el('div', { class: 'board-meta' },
        el('span', {}, g.takes > 1 ? `Take ${c.take + 1}` : ''),
        el('span', { class: 'muted' }, c.status === 'done' || c.status === 'failed' ? clock(c.seconds) : ''),
        c.status === 'done' && el('button', { class: 'star' + (starred ? ' on' : ''), title: starred ? 'Unstar' : 'Star the best', 'aria-pressed': String(starred),
          onclick: () => { if (starred) stars.delete(c.job); else stars.add(c.job); keepStars(g.run, stars); drawGrid(); } }, starred ? '★' : '☆'),
        (c.status === 'failed' || c.status === 'done' || c.status === 'cancelled') && el('button', { class: 'again', title: 'Make this cell again', onclick: () => again(c) }, icon('retry')));
      box.append(el('div', { class: 'board-take' }, frame, meta));
    }
    return box;
  }

  // One result big, with what made it; arrows walk along the row (the same prompt, the next workflow).
  function openBig(g, rowIndex, w, c) {
    const row = g.rows[rowIndex];
    const along = g.workflows.flatMap((col) => g.cells.filter((x) => x.row === row && x.workflow === col.id && x.status === 'done' && x.items[0])
      .map((x) => ({ col, x })));
    let i = along.findIndex((a) => a.x.job === c.job);
    const shade = el('div', { class: 'board-big', onclick: (e) => { if (e.target === shade) shut(); } });
    const show = () => {
      const { col, x } = along[i];
      const item = x.items[0];
      const media = item.kind === 'video' ? el('video', { src: `/api/library/${item.id}/file`, controls: true, autoplay: true, loop: true })
        : el('img', { src: `/api/library/${item.id}/file`, alt: item.name });
      shade.replaceChildren(el('div', { class: 'board-big-inner' },
        el('div', { class: 'board-big-media' }, media),
        el('div', { class: 'board-big-facts' },
          el('b', {}, short(col.title)), el('span', { class: 'muted' }, `Shot ${rowIndex + 1}${g.takes > 1 ? ` · take ${x.take + 1}` : ''} · ${clock(x.seconds)}${x.seed ? ` · seed ${x.seed}` : ''}`),
          el('p', {}, g.prompts[rowIndex]),
          el('span', { class: 'muted small' }, `${i + 1} of ${along.length} in this row · ← → to move, Esc to close`))));
    };
    const keys = (e) => {
      if (e.key === 'Escape') shut();
      else if (e.key === 'ArrowRight') { i = (i + 1) % along.length; show(); } else if (e.key === 'ArrowLeft') { i = (i - 1 + along.length) % along.length; show(); }
    };
    const shut = () => { document.removeEventListener('keydown', keys, true); shade.remove(); };
    document.addEventListener('keydown', keys, true);
    show();
    root.append(shade);
  }

  // ---------------------------------------------------------------- the board

  function layout() {
    root.classList.toggle('setup-hidden', s.view !== 'setup' && !!s.run);
  }

  function close() {
    clearTimeout(timer);
    if (unsubscribe) unsubscribe();
    unsubscribe = null;
    document.removeEventListener('keydown', escape);
    root.remove();
  }
  const escape = (e) => { if (e.key === 'Escape' && !root.querySelector('.board-big')) close(); };

  async function open(run) {
    document.body.append(root);
    document.addEventListener('keydown', escape);
    // A job of the run that changes (finished, failed) shows at once, not on the next look.
    unsubscribe = subscribe((change) => { if (change === 'jobs' && s.run && s.grid && s.grid.cells.some((c) => c.status === 'queued' || c.status === 'running')) { clearTimeout(timer); timer = setTimeout(load, 400); } });
    if (run) await openRun(run);
    else newTest();
    drawSetup();
  }

  return { open };
}
