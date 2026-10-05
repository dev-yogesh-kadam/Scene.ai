// The admin console shell: its own tab bar, and one section per tab (see pages/admin/).

import { el } from '../dom.js';
import { store } from '../store.js';
import { overview } from './admin/overview.js';
import { users, jobs, library, credits, workflows, system, audit, settings } from './admin/sections.js';
import { pricing } from './admin/pricing.js';
import { economics } from './admin/economics.js';

const TABS = [
  { id: 'overview', label: 'Overview', draw: overview, live: 15000 },
  { id: 'users', label: 'Users', draw: users },
  { id: 'jobs', label: 'Jobs', draw: jobs, live: 5000 },
  { id: 'library', label: 'Library', draw: library },
  { id: 'credits', label: 'Credits', draw: credits },
  { id: 'pricing', label: 'Pricing', draw: pricing },
  { id: 'economics', label: 'Economics', draw: economics },
  { id: 'workflows', label: 'Workflows', draw: workflows },
  { id: 'system', label: 'System', draw: system, live: 10000 },
  { id: 'audit', label: 'Audit log', draw: audit },
  { id: 'settings', label: 'Settings', draw: settings },
];

export function render(view) {
  if (store.user.role !== 'admin') {
    view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, 'Admin')), el('p', { class: 'muted' }, 'Only an admin can open this page.'));
    return null;
  }
  const saved = sessionStorage.getItem('scene.admin.tab');
  let tab = TABS.some((t) => t.id === saved) ? saved : 'overview';
  let drawn = 0;
  const nav = el('nav', { class: 'tabs', 'aria-label': 'Admin sections' });
  const body = el('div');
  view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, 'Admin console')), nav, body);

  // What each section remembers while the console is open: filters, searches, the period.
  const ctx = {
    days: 30,
    state: {
      users: { q: '', show: '' }, jobs: { status: 'active', q: '', offset: 0 }, library: { kind: '', q: '', owner: '', project: '', offset: 0 },
      credits: { reason: '', q: '' }, audit: { q: '' },
    },
    draw,
    go(target, changes) {
      tab = target;
      if (changes) Object.assign(ctx.state[target], changes);
      sessionStorage.setItem('scene.admin.tab', tab);
      draw();
    },
  };

  async function draw() {
    nav.replaceChildren(...TABS.map((t) => el('button', { class: t.id === tab ? 'on' : '', onclick: () => ctx.go(t.id) }, t.label)));
    const shown = tab;
    // Keep the search box focused and its caret in place across a redraw.
    const focused = body.contains(document.activeElement) && document.activeElement.classList.contains('search') ? document.activeElement.selectionStart : null;
    try {
      const content = await TABS.find((t) => t.id === tab).draw(ctx);
      if (shown !== tab) return;
      body.replaceChildren(...content.filter(Boolean));
      if (focused != null) {
        const box = body.querySelector('.search');
        if (box) { box.focus(); box.setSelectionRange(focused, focused); }
      }
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error' }, e.message));
    }
    drawn = Date.now();
  }

  draw();
  // Sections that follow the queue or the server redraw themselves, unless the admin is in the middle of something.
  const timer = setInterval(() => {
    const live = TABS.find((t) => t.id === tab).live;
    const busy = document.querySelector('dialog[open], .drawer-backdrop, .chart:hover, .chart:focus-within') || body.contains(document.activeElement);
    if (live && !busy && !document.hidden && Date.now() - drawn >= live) draw();
  }, 1000);
  return () => { clearInterval(timer); document.querySelectorAll('.drawer-backdrop').forEach((d) => d.remove()); };
}
