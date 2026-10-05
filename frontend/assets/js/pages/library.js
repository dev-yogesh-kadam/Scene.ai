// The Library page: everything the user has made, with search and projects.

import { api } from '../api.js';
import { el, segmented } from '../dom.js';
import { subscribe } from '../store.js';
import { mediaCard } from '../components/media.js';

export function render(view) {
  const filters = { kind: '', q: '', project: '' };   // project: '' = all, 'none', or a project id
  let projects = [];
  const kinds = el('div');
  const projectBar = el('div', { class: 'row', style: 'margin-bottom:16px' });
  const grid = el('div', { class: 'media-grid' });
  let searchTimer;
  const search = el('input', { type: 'text', placeholder: 'Search names and prompts', style: 'max-width:260px',
    oninput: (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { filters.q = e.target.value; drawItems(); }, 250); } });
  view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, 'Library'),
    el('a', { class: 'btn quiet', href: '#/assets', title: 'Saved characters, outfits, backgrounds and voices' }, 'Assets'),
    el('a', { class: 'btn quiet', href: '#/queue' }, 'Queue'), search, kinds), projectBar, grid);

  const run = (action) => action().then(draw).catch((e) => alert(e.message));

  function drawProjects() {
    const current = projects.find((p) => String(p.id) === filters.project);
    const select = el('select', { style: 'max-width:240px', onchange: (e) => { filters.project = e.target.value; draw(); } },
      el('option', { value: '' }, 'All projects'),
      el('option', { value: 'none', selected: filters.project === 'none' }, 'Not in a project'),
      projects.map((p) => el('option', { value: p.id, selected: p === current }, `${p.name} (${p.items})`)));
    projectBar.replaceChildren(...[select,
      el('button', { class: 'btn small', onclick: () => {
        const name = prompt('Name of the new project');
        if (name && name.trim()) run(async () => { filters.project = String((await api('/api/projects', { method: 'POST', json: { name } })).id); });
      } }, 'New project'),
      current && el('button', { class: 'btn small', onclick: () => {
        const name = prompt('Project name', current.name);
        if (name && name.trim()) run(() => api('/api/projects/' + current.id, { method: 'PUT', json: { name } }));
      } }, 'Rename'),
      current && el('button', { class: 'btn small quiet danger', onclick: () => {
        if (confirm(`Delete the project "${current.name}"? Its ${current.items} items stay in your library.`)) {
          run(async () => { await api('/api/projects/' + current.id, { method: 'DELETE' }); filters.project = ''; });
        }
      } }, 'Delete project')].filter(Boolean));
  }

  async function drawItems() {
    try {
      const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
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
    kinds.replaceChildren(segmented(
      [{ id: '', label: 'All' }, { id: 'video', label: 'Videos' }, { id: 'image', label: 'Images' }, { id: 'audio', label: 'Audio' }], filters.kind,
      (k) => { filters.kind = k; draw(); }));
    try { projects = (await api('/api/projects')).projects; } catch (e) { projects = []; }
    drawProjects();
    await drawItems();
  }

  draw();
  return subscribe((change) => { if (change === 'library') draw(); });
}
