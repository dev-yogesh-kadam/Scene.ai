// Scene.ai front end entry: sign-in gate, app shell and page routing.

import { api } from './api.js';
import { el, icon } from './dom.js';
import { store, subscribe, startLive, stopLive, refreshJobs } from './store.js';
import { renderAuth } from './pages/auth.js';
import * as create from './pages/create.js';
import * as canvas from './pages/canvas.js';
import * as timeline from './pages/timeline.js';
import * as library from './pages/library.js';
import * as assets from './pages/assets.js';
import * as queue from './pages/queue.js';
import * as settings from './pages/settings.js';
import * as admin from './pages/admin.js';

const root = document.getElementById('app');
const PAGES = [
  { path: '#/create', label: 'Create', icon: 'generate', page: create },
  { path: '#/canvas', label: 'Canvas', icon: 'canvas', page: canvas },
  { path: '#/timeline', label: 'Timeline', icon: 'timeline', page: timeline },
  { path: '#/library', label: 'Library', icon: 'grid', page: library },
  { path: '#/assets', label: 'Assets', icon: 'bookmark', page: assets },
  { path: '#/queue', label: 'Queue', icon: 'list', page: queue },
  { path: '#/settings', label: 'Settings', icon: 'sliders', page: settings },
  { path: '#/admin', label: 'Admin console', icon: 'shield', page: admin, adminOnly: true },
];
const THEMES = { system: 'Theme: same as system', light: 'Theme: light', dark: 'Theme: dark' };
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
  renderAuth(root, (user) => { store.user = user; showApp(); });
}

function showApp() {
  const view = el('main', { class: 'view' });
  const nav = el('nav', { class: 'nav' });
  const dot = el('span', { class: 'dot' });
  const server = el('span', {}, 'Checking render server…');
  const credits = el('div', { class: 'credits', title: 'Credits pay for generations. An admin can add more.' });
  const themeButton = el('button', { class: 'icon-btn', onclick: () => {
    const order = Object.keys(THEMES);
    applyTheme(order[(order.indexOf(localStorage.getItem('scene.theme') || 'system') + 1) % order.length]);
    drawTheme();
  } });
  const drawTheme = () => {
    const theme = localStorage.getItem('scene.theme') || 'system';
    themeButton.title = THEMES[theme] + '. Click to change.';
    themeButton.setAttribute('aria-label', themeButton.title);
    themeButton.replaceChildren(icon({ system: 'monitor', light: 'sun', dark: 'moon' }[theme]));
  };
  const signOut = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); showAuth(); };

  root.replaceChildren(el('div', { class: 'shell' },
    el('aside', { class: 'sidebar' },
      el('div', { class: 'brand' }, el('img', { src: '/assets/img/logo.svg', alt: '' }), 'Scene.ai'),
      nav,
      el('div', { class: 'spacer' }),
      credits,
      el('div', { class: 'server' }, dot, server),
      el('div', { class: 'account' },
        el('div', { class: 'avatar' }, (store.user.name[0] || '?').toUpperCase()),
        el('div', { class: 'who' }, el('b', {}, store.user.name), el('span', {}, store.user.email)),
        themeButton,
        el('button', { class: 'icon-btn', title: 'Sign out', 'aria-label': 'Sign out', onclick: signOut }, icon('logout')))),
    view));

  const drawNav = () => {
    const active = store.jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;
    const link = (p) => el('a', { href: p.path, class: location.hash === p.path ? 'on' : '' },
      icon(p.icon), el('span', { class: 'grow' }, p.label), p.path === '#/queue' && active > 0 && el('span', { class: 'badge' }, String(active)));
    nav.replaceChildren(
      ...PAGES.filter((p) => !p.adminOnly).map(link),
      ...(store.user.role === 'admin' ? [el('div', { class: 'nav-label' }, 'Administration'), ...PAGES.filter((p) => p.adminOnly).map(link)] : []));
  };
  const drawStatus = () => {
    dot.className = 'dot ' + (store.online == null ? '' : store.online ? 'online' : 'offline');
    server.textContent = store.online == null ? 'Checking render server…' : store.online ? 'Render server online' : 'Render server offline';
  };
  const drawCredits = () => credits.replaceChildren(el('b', {}, Number(store.user.credits ?? 0).toLocaleString()), 'cr');
  const route = () => {
    const target = PAGES.find((p) => p.path === location.hash);
    if (!target) { location.hash = PAGES[0].path; return; }
    if (leavePage) leavePage();
    leavePage = target.page.render(view) || null;
    drawNav();
    window.scrollTo(0, 0);
  };

  drawCredits();
  drawTheme();
  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') drawNav();
    if (change === 'status') drawStatus();
    if (change === 'credits') drawCredits();
  });
  window.addEventListener('hashchange', route);
  leaveShell = () => { unsubscribe(); window.removeEventListener('hashchange', route); };

  startLive();
  refreshJobs().catch(() => {});
  route();
}

window.addEventListener('scene:signed-out', () => { if (store.user) showAuth(); });

api('/api/auth/me').then((user) => { store.user = user; showApp(); }).catch(showAuth);
