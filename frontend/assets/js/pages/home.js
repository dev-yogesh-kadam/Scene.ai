// The Home page: a bar to start something, the projects worked on lately, and everything made so far.

import { api } from '../api.js';
import { el, segmented, ago, initials } from '../dom.js';
import { store, subscribe } from '../store.js';
import { openViewer } from '../components/media.js';
import { composer } from '../components/composer.js';

const RECENT = 8;    // projects shown
const MADE = 60;     // finished items shown

export function render(view) {
  let kind = '';     // '' = everything, or 'video' / 'image'
  const queued = el('p', { class: 'notice ok home-note' });
  const dock = composer({ onQueued: () => {
    queued.replaceChildren('Added to the queue. ', el('a', { href: '#/canvas' }, 'Watch it on the Canvas'));
  } });
  const recent = el('section', { class: 'home-section hidden' });
  const filter = el('div');
  const grid = el('div', { class: 'made-grid' });

  view.replaceChildren(
    el('div', { class: 'home-hero' }, el('h1', {}, 'What are you making today?')),
    el('div', { class: 'home-bar' }, dock.node, queued),
    recent,
    el('section', { class: 'home-section' },
      el('div', { class: 'section-head' }, el('h2', {}, 'Created on Scene.ai'), filter,
        el('a', { class: 'btn small quiet', href: '#/library' }, 'Open library')),
      grid));

  const openProject = (project) => {
    localStorage.setItem('scene.project', project.id);
    location.hash = '#/canvas';
  };

  const cover = (id, itemKind, name) => (itemKind === 'video'
    ? el('video', { src: `/api/library/${id}/file#t=0.1`, preload: 'metadata', muted: true })
    : el('img', { src: `/api/library/${id}/file`, alt: name, loading: 'lazy' }));

  // Recent projects: left out completely until the user has made one.
  async function drawRecent() {
    const projects = (await api('/api/projects')).projects
      .sort((a, b) => (b.updated || b.created) - (a.updated || a.created)).slice(0, RECENT);
    recent.classList.toggle('hidden', !projects.length);
    if (!projects.length) return;
    recent.replaceChildren(
      el('div', { class: 'section-head' }, el('h2', {}, 'Recent projects'),
        el('a', { class: 'btn small quiet', href: '#/projects' }, 'See all')),
      el('div', { class: 'project-grid' }, projects.map((p) => el('button', { class: 'project', onclick: () => openProject(p) },
        el('div', { class: 'project-cover' }, p.cover_id ? cover(p.cover_id, p.cover_kind, p.name) : initials(p.name)),
        el('b', {}, p.name),
        el('span', { class: 'slate-text' }, [p.items === 1 ? '1 item' : `${p.items} items`, ago(p.updated || p.created)].join(' · '))))));
  }

  async function drawMade() {
    filter.replaceChildren(segmented([{ id: '', label: 'All' }, { id: 'video', label: 'Videos' }, { id: 'image', label: 'Images' }],
      kind, (k) => { kind = k; drawMade().catch(() => {}); }));
    const items = (await api('/api/library' + (kind ? '?kind=' + kind : ''))).items.slice(0, MADE);
    grid.classList.toggle('made-grid', items.length > 0);
    grid.replaceChildren(...(items.length ? items.map((item) => {
      const c = item.context || {};
      return el('button', { class: 'made', title: item.name, style: c.width ? `aspect-ratio:${c.width}/${c.height}` : '',
        onclick: () => openViewer(item, { actions: item.workflow.startsWith('edit/') ? []
          : [{ label: 'Re-run', run: (dialog) => { dialog.close(); store.rerun = item; location.hash = '#/create'; } }] }) },
        cover(item.id, item.kind, item.name), el('span', {}, item.name));
    }) : [el('div', { class: 'empty' }, kind ? 'Nothing of this kind yet.' : 'Nothing made yet. Describe a shot in the bar above and it will appear here.')]));
  }

  const draw = () => Promise.all([drawRecent(), drawMade()]).catch((e) => { grid.replaceChildren(el('p', { class: 'error' }, e.message)); });
  draw();
  const unsubscribe = subscribe((change) => { if (change === 'library') draw(); });
  return () => { unsubscribe(); dock.destroy(); };
}
