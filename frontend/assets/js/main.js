// Scene.ai front end entry: sign-in gate, app shell and page routing.

import { api } from './api.js';
import { el, icon, segmented } from './dom.js';
import { store, subscribe, startLive, stopLive, refreshJobs } from './store.js';
import { renderAuth } from './pages/auth.js';
import * as home from './pages/home.js';
import * as create from './pages/create.js';
import * as canvas from './pages/canvas.js';
import * as timeline from './pages/timeline.js';
import * as projects from './pages/projects.js';
import * as library from './pages/library.js';
import * as assets from './pages/assets.js';
import * as queue from './pages/queue.js';
import * as settings from './pages/settings.js';
import * as admin from './pages/admin.js';

const root = document.getElementById('app');
// The first page is where a visit starts. `group` is the heading a page sits under in the sidebar.
// A page with `under` has no sidebar entry of its own: it is reached from the page it names, which stays lit while it is open.
// A page with `menu` is listed in the menu that opens from the user's name instead of in the sidebar.
const PAGES = [
  { path: '#/home', label: 'Home', icon: 'home', page: home },
  { path: '#/projects', label: 'All projects', icon: 'folder', page: projects, group: 'Workspace' },
  { path: '#/library', label: 'Library', icon: 'grid', page: library, group: 'Workspace' },
  { path: '#/create', page: create, under: '#/home' },
  { path: '#/canvas', page: canvas, under: '#/projects' },
  { path: '#/timeline', page: timeline, under: '#/projects' },
  { path: '#/assets', page: assets, under: '#/library' },
  { path: '#/queue', page: queue, under: '#/library' },
  { path: '#/settings', label: 'Settings', icon: 'sliders', page: settings, menu: true },
  { path: '#/admin', label: 'Admin console', icon: 'shield', page: admin, menu: true, adminOnly: true },
];
const LANDING = '#/projects';   // where signing in, or opening the site with no page in the address, leads
const THEMES = [{ id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }, { id: 'system', label: 'Auto', hint: 'Same as this computer' }];
let leavePage = null;
let leaveShell = null;

function applyTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  localStorage.setItem('scene.theme', theme);
}

function showAuth() {
  if (leavePage) leavePage();
  if (leaveShell) leaveShell();
  leavePage = leaveShell = null;
  stopLive();
  store.user = null;
  // Signing in always lands on All projects. replaceState does not fire hashchange, so the page is routed once, by showApp.
  renderAuth(root, (user) => { store.user = user; history.replaceState(null, '', LANDING); showApp(); });
}

function showApp() {
  const view = el('main', { class: 'view' });
  const nav = el('nav', { class: 'nav' });
  const working = el('a', { class: 'working hidden', href: '#/queue', title: 'Open the queue' });
  const dot = el('span', { class: 'dot' });
  const server = el('span', {}, 'Checking render server…');
  const credits = el('div', { class: 'credits', title: 'Credits pay for generations. An admin can add more.' });
  // The menu behind the user's name: settings, the admin console, the theme and signing out.
  const menu = el('div', { class: 'account-menu float hidden', role: 'menu' });
  const account = el('button', { class: 'account', 'aria-haspopup': 'menu', onclick: (e) => { e.stopPropagation(); showMenu(menu.classList.contains('hidden')); } },
    el('div', { class: 'avatar' }, (store.user.name[0] || '?').toUpperCase()),
    el('div', { class: 'who' }, el('b', {}, store.user.name), el('span', {}, store.user.email)),
    icon('chevron'));
  const closeMenu = (e) => { if (e.type === 'keydown' ? e.key === 'Escape' : !e.composedPath().includes(menu)) showMenu(false); };
  function showMenu(open) {
    menu.classList.toggle('hidden', !open);
    account.setAttribute('aria-expanded', String(open));
    for (const event of ['click', 'keydown']) window[open ? 'addEventListener' : 'removeEventListener'](event, closeMenu);
    if (!open) return;
    menu.replaceChildren(
      ...PAGES.filter((p) => p.menu && (!p.adminOnly || store.user.role === 'admin')).map((p) =>
        el('a', { href: p.path, role: 'menuitem', onclick: () => showMenu(false) }, icon(p.icon), p.label)),
      el('div', { class: 'menu-row' }, 'Theme', segmented(THEMES, localStorage.getItem('scene.theme') || 'system', (theme) => { applyTheme(theme); showMenu(true); })),
      el('button', { role: 'menuitem', onclick: signOut }, icon('logout'), 'Sign out'));
  }
  const signOut = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); showAuth(); };

  root.replaceChildren(el('div', { class: 'shell' },
    el('aside', { class: 'sidebar' },
      el('div', { class: 'brand' }, el('img', { src: '/assets/img/logo.svg', alt: '' }), 'Scene.ai'),
      nav,
      el('div', { class: 'spacer' }),
      working,
      credits,
      // Whether the render server answers is the admin's business; other users are not shown it.
      store.user.role === 'admin' && el('div', { class: 'server' }, dot, server),
      el('div', { class: 'account-wrap' }, menu, account)),
    view));

  const drawNav = () => {
    const active = store.jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;
    const here = PAGES.find((p) => p.path === location.hash) || {};
    const link = (p) => el('a', { href: p.path, class: p.path === (here.under || here.path) ? 'on' : '' },
      icon(p.icon), el('span', { class: 'grow' }, p.label));
    const shown = PAGES.filter((p) => !p.under && !p.menu);
    account.classList.toggle('on', !!here.menu);
    // The queue has no sidebar entry; while something is being made, this line leads to it.
    working.classList.toggle('hidden', !active);
    working.replaceChildren(el('i', { class: 'cell-mark stepping' }), active === 1 ? '1 job in the queue' : `${active} jobs in the queue`);
    nav.replaceChildren(...shown.flatMap((p, i) =>
      (p.group && p.group !== (shown[i - 1] || {}).group ? [el('div', { class: 'nav-label' }, p.group), link(p)] : [link(p)])));
  };
  const drawStatus = () => {
    dot.className = 'dot ' + (store.online == null ? '' : store.online ? 'online' : 'offline');
    server.textContent = store.online == null ? 'Checking render server…' : store.online ? 'Render server online' : 'Render server offline';
  };
  const drawCredits = () => credits.replaceChildren(el('b', {}, Number(store.user.credits ?? 0).toLocaleString()), 'cr');
  const route = () => {
    const target = PAGES.find((p) => p.path === location.hash);
    if (!target) { location.hash = LANDING; return; }
    if (leavePage) leavePage();
    leavePage = target.page.render(view) || null;
    drawNav();
    window.scrollTo(0, 0);
  };

  drawCredits();
  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') drawNav();
    if (change === 'status') drawStatus();
    if (change === 'credits') drawCredits();
  });
  window.addEventListener('hashchange', route);
  leaveShell = () => { unsubscribe(); showMenu(false); window.removeEventListener('hashchange', route); };

  startLive();
  refreshJobs().catch(() => {});
  route();
}

window.addEventListener('scene:signed-out', () => { if (store.user) showAuth(); });

api('/api/auth/me').then((user) => { store.user = user; showApp(); }).catch(showAuth);
