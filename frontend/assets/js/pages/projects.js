// The All projects page: every project as a card with its newest item as the thumbnail. Opening one goes to its Canvas.

import { api } from '../api.js';
import { el, icon, ago, initials } from '../dom.js';
import { subscribe } from '../store.js';
import { projectDialog } from '../components/projects.js';

export function render(view) {
  let projects = [];
  let query = '';
  const body = el('div');
  const search = el('input', { type: 'text', style: 'width:240px', placeholder: 'Search projects', 'aria-label': 'Search projects',
    oninput: (e) => { query = e.target.value.trim().toLowerCase(); draw(); } });
  const tools = el('div', { class: 'row' }, search,
    el('button', { class: 'btn', title: 'Everything you have made, in or out of a project', onclick: () => open(0) }, 'Open all work'),
    el('button', { class: 'btn primary', onclick: create }, 'New project'));
  view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, 'All projects'), tools), body);

  function open(id) {
    localStorage.setItem('scene.project', id || '');
    location.hash = '#/canvas';
  }
  const run = (action) => action().then(load).catch((e) => alert(e.message));
  async function create() {
    const made = await projectDialog();
    if (made) open(made.id);   // a new project opens straight away, on its empty canvas
  }
  const rename = async (p) => { if (await projectDialog({ project: p })) load(); };
  const remove = (p) => {
    if (confirm(`Delete the project "${p.name}"? Its ${p.items} items stay in your library.`)) run(() => api('/api/projects/' + p.id, { method: 'DELETE' }));
  };
  const act = (fn) => (e) => { e.stopPropagation(); fn(); };   // a button on a card must not also open the card

  // The newest item is the thumbnail. A project with nothing in it yet shows its initials.
  const cover = (p) => (!p.cover_id ? initials(p.name)
    : p.cover_kind === 'video' ? el('video', { src: `/api/library/${p.cover_id}/file#t=0.1`, preload: 'metadata', muted: true })
      : el('img', { src: `/api/library/${p.cover_id}/file`, alt: '', loading: 'lazy' }));

  const card = (p) => el('div', { class: 'pcard', role: 'button', tabindex: '0', 'aria-label': 'Open ' + p.name,
    onclick: () => open(p.id), onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(p.id); } },
    el('div', { class: 'pcard-cover' }, cover(p)),
    el('div', { class: 'pcard-info' },
      el('b', { title: p.name }, p.name),
      el('span', {}, p.items === 1 ? '1 item' : `${p.items} items`),
      el('span', { class: 'muted small' }, ago(p.updated || p.created))),
    el('div', { class: 'pcard-actions' },
      el('button', { class: 'icon-btn', title: 'Rename', 'aria-label': 'Rename ' + p.name, onclick: act(() => rename(p)) }, icon('pencil')),
      el('button', { class: 'icon-btn', title: 'Delete', 'aria-label': 'Delete ' + p.name, onclick: act(() => remove(p)) }, icon('trash'))));

  function draw() {
    tools.classList.toggle('hidden', !projects.length);
    if (!projects.length) {
      return body.replaceChildren(el('div', { class: 'empty first' },
        el('h2', {}, 'Create your first project'),
        el('p', {}, 'A project keeps the shots, the canvas and the timeline of one piece of work together.'),
        el('button', { class: 'btn primary', onclick: create }, 'Create your first project')));
    }
    const shown = projects.filter((p) => p.name.toLowerCase().includes(query));
    body.replaceChildren(shown.length ? el('div', { class: 'pcard-grid' }, shown.map(card))
      : el('div', { class: 'empty' }, `No project matches "${query}".`));
  }

  async function load() {
    try {
      projects = (await api('/api/projects')).projects.sort((a, b) => (b.updated || b.created) - (a.updated || a.created));
      draw();
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error' }, e.message));
    }
  }

  load();
  return subscribe((change) => { if (change === 'library') load(); });
}
