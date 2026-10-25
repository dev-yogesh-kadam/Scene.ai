// A project's page: on the left its cover, its analytics, its details and what can be done with it; on the right its
// modules. A module is a canvas of its own, with its own timeline and agent tabs, inside the project; the project's own
// canvas is the first one, "Main". The page is /project?id=<project id>; opening a module goes to its canvas.

import { api } from '../api.js';
import { ask, el, icon, still, ago, initials, spill } from '../dom.js';
import { store, subscribe } from '../store.js';
import { projectDialog } from '../components/projects.js';
import { shareDialog } from '../components/share.js';
import { go } from '../nav.js';

// What the user's role in the project lets them do (the server checks it too: sharing.py).
const RANK = { viewer: 1, creator: 2, manager: 3, owner: 4 };
const may = (role, need) => RANK[role || 'owner'] >= RANK[need];

// A module with nothing in it yet gets a colour of its own, from its number, instead of an empty frame.
const TINTS = [['#ef6b8a', '#d12f7c'], ['#6b8bef', '#3f4fd1'], ['#3fbf9a', '#14876a'], ['#f0a25a', '#d0612b'], ['#a77bef', '#6a3fd1'], ['#4fb8e8', '#1f78b8']];

export function render(view) {
  const id = Number(new URLSearchParams(location.search).get('id')) || 0;
  let data = null;
  let query = '';
  const light = spill();
  const side = el('aside', { class: 'proj-side' });
  const grid = el('div', { class: 'pcard-grid proj-modules' });
  const search = el('input', { type: 'text', class: 'proj-search', placeholder: 'Search modules…', 'aria-label': 'Search modules',
    oninput: (e) => { query = e.target.value.trim().toLowerCase(); drawModules(); } });
  view.replaceChildren(light.node, el('div', { class: 'proj-page' }, side, el('div', { class: 'proj-main' },
    el('section', { class: 'proj-section' },
      el('div', { class: 'section-head' }, el('h2', {}, 'Modules'), el('span', { style: 'flex:1' }), search,
        el('button', { class: 'btn primary add-module', onclick: addModule }, icon('plus'), 'Add module')),
      grid))));

  // A module opens on its canvas; the project's own canvas is "Main".
  const open = (module) => { localStorage.setItem('scene.project', module.id); go('/canvas'); };
  const run = (action) => action().then(load).catch((e) => alert(e.message));
  async function addModule() {
    const made = await projectDialog({ parent: data.project, count: data.modules.length });
    if (made) open(made);
  }
  const act = (fn) => (e) => { e.stopPropagation(); fn(); };
  const cover = (m, number) => (m.cover_id ? still(`/api/library/${m.cover_id}/file`, m.cover_kind, m.name)
    : el('span', { class: 'proj-tint', style: `background:linear-gradient(160deg, ${TINTS[number % TINTS.length][0]}, ${TINTS[number % TINTS.length][1]})` },
      m.main ? 'MAIN' : 'M ' + String(number).padStart(2, '0')));

  const card = (m, number) => el('div', { class: 'pcard', role: 'button', tabindex: '0', 'aria-label': 'Open ' + m.name,
    onclick: () => open(m), onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(m); } },
    el('div', { class: 'pcard-cover' }, cover(m, number), m.main && el('span', { class: 'proj-badge' }, 'Main')),
    el('div', { class: 'pcard-info' },
      el('b', { title: m.name }, m.name),
      el('span', { class: 'muted small' }, `${m.items === 1 ? '1 item' : `${m.items} items`} · ${ago(m.updated || m.created)}`)),
    may(data.project.role, 'manager') && el('div', { class: 'pcard-actions' },
      el('button', { class: 'icon-btn', title: 'Rename', 'aria-label': 'Rename ' + m.name,
        onclick: act(async () => { if (await projectDialog({ project: m, module: true, canvas: m.main })) load(); }) }, icon('pencil')),
      !m.main && el('button', { class: 'icon-btn', title: 'Delete', 'aria-label': 'Delete ' + m.name, onclick: act(async () => {
        if (await ask({ title: `Delete "${m.name}"?`, danger: true, confirm: 'Delete module',
          message: `Its ${m.items} ${m.items === 1 ? 'item is' : 'items are'} deleted with it, for good, with its canvas, timeline and agent tabs. This can't be undone.` })) {
          run(() => api('/api/projects/' + m.id, { method: 'DELETE' }));
        }
      }) }, icon('trash'))));

  function drawSide() {
    const p = data.project;
    view.querySelector('.add-module').classList.toggle('hidden', !may(p.role, 'creator'));   // a viewer only looks
    const fact = (label, value) => el('div', { class: 'proj-fact' }, el('span', {}, label), el('b', {}, value));
    const modules = data.modules.length - 1;   // the first is the project's own canvas
    side.replaceChildren(
      el('div', { class: 'proj-cover' }, p.cover_id ? still(`/api/library/${p.cover_id}/file`, p.cover_kind, p.name) : el('span', {}, initials(p.name)),
        el('div', { class: 'proj-title' }, el('h1', {}, p.name), el('span', {}, `${modules} ${modules === 1 ? 'module' : 'modules'} · ${p.items} items`))),
      el('a', { class: 'proj-analytics', href: '/analytics?id=' + p.id },
        el('span', { class: 'proj-analytics-icon' }, icon('bars')),
        el('span', { class: 'grow' }, el('b', {}, 'View analytics'), el('span', { class: 'muted small' }, 'Spend, generations, modules')),
        el('span', { class: 'proj-arrow', 'aria-hidden': 'true' }, '→')),
      el('div', { class: 'proj-facts' },
        fact('Created', new Date(p.created * 1000).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })),
        fact('Last updated', p.updated ? ago(p.updated) : 'Nothing made yet'),
        fact('Modules', String(modules)),
        fact('Items', String(p.items))),
      // Who is in the project: its owner first, then the people it is shared with, and Add for a manager or the owner.
      el('div', { class: 'proj-owner' },
        el('div', { class: 'row proj-members-head' }, el('span', { class: 'muted small grow' }, `Members · ${p.members.length}`),
          el('button', { class: 'btn small quiet', onclick: share, title: may(p.role, 'manager') ? 'Add people to this project' : 'See who is in this project' },
            icon('people'), may(p.role, 'manager') ? 'Add' : 'View')),
        ...p.members.slice(0, 6).map((m) => el('div', { class: 'proj-person' }, el('span', { class: 'avatar' }, initials(m.name || m.email)),
          el('span', { class: 'grow' }, el('b', {}, m.name + (m.user_id === store.user.id ? ' (you)' : '')), el('span', { class: 'muted small' }, m.email)),
          el('span', { class: 'owner-tag' + (m.role === 'owner' ? '' : ' member') }, m.role[0].toUpperCase() + m.role.slice(1)))),
        p.members.length > 6 && el('button', { class: 'btn small quiet', onclick: share }, `and ${p.members.length - 6} more`)),
      el('div', { class: 'proj-side-actions' },
        may(p.role, 'manager') && el('button', { class: 'btn block', onclick: async () => { if (await projectDialog({ project: p })) load(); } }, icon('pencil'), 'Edit details'),
        may(p.role, 'owner') && el('button', { class: 'btn block', onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { const copy = await api(`/api/projects/${p.id}/duplicate`, { method: 'POST' }); go('/project?id=' + copy.id); } catch (err) { alert(err.message); }
        } }, icon('frame'), 'Duplicate project'),
        may(p.role, 'owner') && el('button', { class: 'btn block quiet danger', onclick: async () => {
          if (await ask({ title: `Delete "${p.name}"?`, danger: true, confirm: 'Delete project',
            message: `Its ${modules} ${modules === 1 ? 'module' : 'modules'}, its ${p.items} items and its NeuralCore are deleted with it, for good. This can't be undone.` })) {
            api('/api/projects/' + p.id, { method: 'DELETE' }).then(() => go('/projects')).catch((e) => alert(e.message));
          }
        } }, icon('trash'), 'Delete project')));
  }

  async function share() {
    if (await shareDialog({ projectId: data.project.id, projectName: data.project.name })) load();
  }

  function drawModules() {
    const shown = data.modules.map((m, i) => [m, i]).filter(([m]) => !query || m.name.toLowerCase().includes(query));
    grid.replaceChildren(...(shown.length ? shown.map(([m, i]) => card(m, i)) : [el('div', { class: 'empty', style: 'grid-column:1/-1' }, 'No module matches.')]));
  }

  async function load() {
    try {
      data = await api('/api/projects/' + id);
      if (data.project.id !== id) return go('/project?id=' + data.project.id, { replace: true });   // a module's address shows its project
      light.show(data.project.cover_id, data.project.cover_kind);
      document.title = data.project.name + ' · Scene.ai';
      window.dispatchEvent(new CustomEvent('scene:crumbs', { detail: [{ label: 'Projects', href: '/projects' }, { label: data.project.name }] }));
      drawSide();
      drawModules();
    } catch (e) {
      view.replaceChildren(el('div', { class: 'empty' }, el('p', {}, e.message), el('a', { class: 'btn', href: '/projects' }, 'All projects')));
    }
  }

  load();
  return subscribe((change) => { if (change === 'library') load(); });
}
