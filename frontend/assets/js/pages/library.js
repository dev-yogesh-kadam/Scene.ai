// The Library page: everything the user has made, with search. Three views: All (every item), Projects (a folder
// for each project, opened to its items) and Not in a project (items that belong to none).

import { api } from '../api.js';
import { ask, el, segmented, still, initials, ago } from '../dom.js';
import { subscribe } from '../store.js';
import { mediaCard } from '../components/media.js';

const VIEWS = [{ id: 'all', label: 'All' }, { id: 'projects', label: 'Projects' }, { id: 'none', label: 'Not in a project' }];

export function render(view) {
  const filters = { kind: '', q: '', project: '' };   // project: '' = all, 'none', or a project id
  let tab = 'all';
  let open = null;   // the project opened from the Projects view
  let projects = [];
  const tabs = el('div');
  const kinds = el('div');
  const projectBar = el('div', { class: 'row', style: 'margin-bottom:16px' });
  const grid = el('div', { class: 'media-grid' });
  let searchTimer;
  const search = el('input', { type: 'text', placeholder: 'Search Library…', style: 'max-width:260px',
    oninput: (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { filters.q = e.target.value; drawItems(); }, 250); } });
  view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, 'Library'),
    search),
  el('p', { class: 'muted', style: 'margin:0 0 14px' }, 'Everything you have made, in one place. Reuse what is here instead of rebuilding it.'),
  el('div', { class: 'row', style: 'margin-bottom:14px;gap:12px;flex-wrap:wrap' }, tabs, kinds), projectBar, grid);

  const run = (action) => action().then(draw).catch((e) => alert(e.message));

  const pick = (id) => {
    tab = id;
    open = null;
    filters.project = id === 'none' ? 'none' : '';
    draw();
  };

  // The bar over the items of an opened project: back to the folders, its name, rename and delete.
  // On the Projects view it holds the New project button.
  function drawProjects() {
    if (tab === 'projects' && open) {
      projectBar.replaceChildren(
        el('button', { class: 'btn small quiet', onclick: () => { open = null; filters.project = ''; draw(); } }, '← Projects'),
        el('b', {}, open.name), el('span', { class: 'slate-text' }, open.items === 1 ? '1 item' : `${open.items} items`),
        el('span', { style: 'flex:1' }),
        el('button', { class: 'btn small', onclick: () => {
          const name = prompt('Project name', open.name);
          if (name && name.trim()) run(() => api('/api/projects/' + open.id, { method: 'PUT', json: { name } }));
        } }, 'Rename'),
        el('button', { class: 'btn small quiet danger', onclick: async () => {
          if (await ask({ title: `Delete "${open.name}"?`, danger: true, confirm: 'Delete project',
            message: `Its ${open.items} items, its modules and its NeuralCore are deleted with it, for good. This can't be undone.` })) {
            run(async () => { await api('/api/projects/' + open.id, { method: 'DELETE' }); open = null; filters.project = ''; });
          }
        } }, 'Delete project'));
    } else if (tab === 'projects') {
      projectBar.replaceChildren(el('button', { class: 'btn small', onclick: () => {
        const name = prompt('Name of the new project');
        if (name && name.trim()) run(() => api('/api/projects', { method: 'POST', json: { name } }));
      } }, 'New project'));
    } else {
      projectBar.replaceChildren();
    }
  }

  // The folders of the Projects view: the newest item of a project is its cover.
  function drawFolders() {
    const q = filters.q.trim().toLowerCase();
    const shown = projects.filter((p) => !p.parent_id && (!q || p.name.toLowerCase().includes(q)));
    grid.className = 'project-grid';
    grid.replaceChildren(...(shown.length ? shown.map((p) => el('button', { class: 'project', onclick: () => {
      open = p;
      filters.project = String(p.id);
      draw();
    } },
    el('div', { class: 'project-cover' }, p.cover_id ? still(`/api/library/${p.cover_id}/file`, p.cover_kind, p.name) : initials(p.name)),
    el('b', {}, p.name),
    el('span', { class: 'slate-text' }, [p.items === 1 ? '1 item' : `${p.items} items`, ago(p.updated || p.created)].join(' · '))))
      : [el('div', { class: 'empty', style: 'grid-column:1/-1' }, q ? 'No project matches.' : 'No projects yet. Use New project.')]));
  }

  async function drawItems() {
    if (tab === 'projects' && !open) return drawFolders();
    grid.className = 'media-grid';
    try {
      const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
      if (tab === 'projects' && open) query.set('modules', '1');   // an opened project shows its modules' items too
      const items = (await api('/api/library?' + query)).items;
      const empty = filters.q || filters.project || filters.kind ? 'Nothing matches.' : 'Nothing here yet. Make something on the Create page.';
      grid.replaceChildren(...(items.length
        ? items.map((item) => mediaCard(item, { manage: true, projects, onChanged: draw }))
        : [el('div', { class: 'empty', style: 'grid-column:1/-1' }, empty)]));
    } catch (e) {
      grid.replaceChildren(el('p', { class: 'error' }, e.message));
    }
  }

  async function draw() {
    tabs.replaceChildren(segmented(VIEWS, tab, pick));
    // What kind of item is shown applies to items, not to the folders of the Projects view.
    kinds.replaceChildren(...(tab === 'projects' && !open ? [] : [segmented(
      [{ id: '', label: 'All' }, { id: 'video', label: 'Videos' }, { id: 'image', label: 'Images' }, { id: 'audio', label: 'Audio' }], filters.kind,
      (k) => { filters.kind = k; draw(); })]));
    try { projects = (await api('/api/projects')).projects; } catch (e) { projects = []; }
    if (open) open = projects.find((p) => p.id === open.id) || null;   // renamed, counted again, or deleted
    if (!open && tab === 'projects') filters.project = '';
    drawProjects();
    await drawItems();
  }

  draw();
  return subscribe((change) => { if (change === 'library') draw(); });
}
