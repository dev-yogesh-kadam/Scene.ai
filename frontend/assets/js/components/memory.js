// The Shared memory tab of the Canvas panel: the assets the agent plans with. Two groups: the assets saved for reuse,
// and the files dropped into jobs in this project. Each item shows what it is and what it shows.

import { api } from '../api.js';
import { ago, el } from '../dom.js';
import { assetNotesDialog, assetThumb } from './assets.js';

const GROUPS = [
  { id: 'assets', label: 'Assets', hint: 'Characters, places, products and voices saved for reuse, in every project.' },
  { id: 'uploads', label: 'Uploads', hint: 'Files dropped into a job in this project. Keep one to use it in every project.' },
];
const OPEN_KEY = 'scene.memory.open';

// projectId(): the current project or 0.
export function memoryPanel({ projectId = () => 0 } = {}) {
  let found = null;          // what /api/memory gave, or null while it loads
  let loadedAt = 0;
  let open = new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || '["assets"]'));
  let shown = null;          // the "group:id" whose details are open
  const stamp = el('span', { class: 'slate-text' });
  const body = el('div', { class: 'memory-body' });
  const node = el('div', { class: 'memory-panel' },
    el('div', { class: 'memory-head' }, el('b', {}, 'Shared memory'), el('span', { style: 'flex:1' }), stamp,
      el('button', { class: 'icon-btn', title: 'Refresh', 'aria-label': 'Refresh', onclick: () => load() }, '↻')),
    el('p', { class: 'small muted memory-lead' }, 'The agent knows everything here by its name, and what each picture shows.'),
    body);

  const remember = () => localStorage.setItem(OPEN_KEY, JSON.stringify([...open]));
  const toggle = (id) => { if (open.has(id)) open.delete(id); else open.add(id); remember(); draw(); };

  function draw() {
    stamp.textContent = loadedAt ? 'refreshed ' + ago(loadedAt / 1000) : '';
    if (!found) { body.replaceChildren(el('p', { class: 'small muted' }, 'Loading…')); return; }
    body.replaceChildren(...GROUPS.map((group) => {
      const list = found[group.id] || [];
      const isOpen = open.has(group.id);
      return el('section', { class: 'memory-group' + (isOpen ? ' open' : '') },
        el('button', { type: 'button', class: 'memory-group-head', 'aria-expanded': String(isOpen), onclick: () => toggle(group.id) },
          el('span', { class: 'memory-caret' }, '›'), el('b', {}, group.label), el('span', { class: 'slate-text' }, `· ${list.length} ${list.length === 1 ? 'item' : 'items'}`)),
        isOpen && el('div', { class: 'memory-items' },
          el('p', { class: 'small muted' }, group.hint),
          ...list.map((entry) => row(group.id, entry)),
          list.length === 0 && el('p', { class: 'small muted' }, 'Nothing here yet.')));
    }));
  }

  function row(group, entry) {
    const key = group + ':' + entry.id;
    const isShown = shown === key;
    return el('div', { class: 'memory-item' + (isShown ? ' shown' : '') },
      el('button', { type: 'button', class: 'memory-item-head', onclick: () => { shown = isShown ? null : key; draw(); } },
        el('span', { class: 'memory-thumb' }, assetThumb(entry)),
        el('span', { class: 'memory-item-text' }, el('b', {}, entry.name), el('span', { class: 'slate-text' }, [entry.type, entry.kind].join(' · ')),
          el('span', { class: 'small muted memory-about' }, entry.use_note || entry.about || 'Not looked at yet.'))),
      isShown && el('div', { class: 'memory-detail' },
        entry.about && el('p', { class: 'small' }, el('b', {}, 'Shows: '), entry.about),
        entry.use_note && el('p', { class: 'small' }, el('b', {}, 'How to use: '), entry.use_note),
        el('div', { class: 'row' },
          el('button', { class: 'btn small', onclick: () => assetNotesDialog(entry, load) }, 'Notes'),
          group === 'uploads' && el('button', { class: 'btn small', title: 'Save it to your assets, for every project', onclick: () => keep(entry) }, 'Keep as asset'))));
  }

  async function keep(entry) {
    try { await api('/api/assets/' + entry.id, { method: 'PUT', json: { origin: 'saved' } }); await load(); } catch (e) { alert(e.message); }
  }

  async function load() {
    try {
      found = await api('/api/memory?project=' + (projectId() || 0));
      loadedAt = Date.now();
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error small' }, e.message));
      return;
    }
    draw();
  }

  const tick = setInterval(() => { if (node.isConnected && loadedAt) stamp.textContent = 'refreshed ' + ago(loadedAt / 1000); }, 30000);
  draw();
  return { node, reload: () => { found = null; shown = null; draw(); return load(); }, load, focus: () => {},
    count: () => (found ? found.assets.length + found.uploads.length : null),
    destroy: () => clearInterval(tick) };
}
