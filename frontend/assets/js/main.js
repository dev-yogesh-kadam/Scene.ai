// Scene.ai front end entry: sign-in gate, app shell and page routing.

import { api } from './api.js';
import { creditMark, el, icon, segmented, tabTitle } from './dom.js';
import { store, subscribe, startLive, stopLive, refreshJobs } from './store.js';
import { renderAuth } from './pages/auth.js';
import { renderLanding } from './pages/landing.js';
import * as home from './pages/home.js';
import * as create from './pages/create.js';
import * as canvas from './pages/canvas.js';
import * as timeline from './pages/timeline.js';
import * as projects from './pages/projects.js';
import * as library from './pages/library.js';
import * as skills from './pages/skills.js';
import * as assets from './pages/assets.js';
import * as queue from './pages/queue.js';
import * as settings from './pages/settings.js';
import * as admin from './pages/admin.js';

const root = document.getElementById('app');
// The first page is where a visit starts. `group` is the heading a page sits under in the menu.
// A page with `under` has no menu entry of its own: it is reached from the page it names, which stays lit while it is open.
// A page with `menu` is listed lower in the menu, with the settings and signing out.
const PAGES = [
  { path: '#/home', label: 'Home', icon: 'home', page: home },
  { path: '#/projects', label: 'All projects', icon: 'folder', page: projects, group: 'Workspace' },
  { path: '#/library', label: 'Library', icon: 'grid', page: library, group: 'Workspace' },
  { path: '#/skills', label: 'Skills', icon: 'skill', page: skills, group: 'Workspace' },
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

// What someone who is not signed in sees: the landing page at the site's address, Create account at #/signup, and
// Sign in at #/signin or at any page of the studio (an old link, or a session that ran out).
let leaveDoor = null;
async function showAuth() {
  if (leavePage) leavePage();
  if (leaveShell) leaveShell();
  leavePage = leaveShell = null;
  stopLive();
  tabTitle();
  store.user = null;
  let info = { signup_open: false };
  try { info = await api('/api/auth/state'); } catch (e) { /* show the pages anyway */ }
  const door = () => {
    if (store.user) return;
    const hash = location.hash;
    if (!hash || hash === '#/' || hash === '#') return renderLanding(root, { signupOpen: info.signup_open });
    // Signing in always lands on All projects. replaceState does not fire hashchange, so the page is routed once, by showApp.
    renderAuth(root, (user) => { store.user = user; leaveDoor(); history.replaceState(null, '', LANDING); showApp(); },
      hash === '#/signup' && info.signup_open ? 'register' : 'login');
  };
  if (leaveDoor) leaveDoor();
  window.addEventListener('hashchange', door);
  leaveDoor = () => { window.removeEventListener('hashchange', door); leaveDoor = null; };
  door();
}

function showApp() {
  const view = el('main', { class: 'view' });
  const nav = el('nav', { class: 'nav', 'aria-label': 'Pages' });
  const working = el('a', { class: 'working hidden', href: '#/queue', title: 'Open the queue' });
  const dot = el('span', { class: 'dot' });
  const server = el('span', {}, 'Checking render server…');
  // The balance sits at the top right of every page (on the canvas, in its own tool bar at the top right).
  const credits = el('div', { class: 'credit-badge', title: 'Credits pay for generations. An admin can add more.' });
  // Everything the sidebar used to hold is in one menu that opens from the logo at the top left: the pages, the queue, the
  // credits, the render server, settings, the theme and signing out. The pages get the whole width of the screen.
  const menu = el('div', { class: 'app-menu hidden', role: 'menu', 'aria-label': 'Scene.ai' });
  const badge = el('span', { class: 'app-menu-badge hidden', 'aria-hidden': 'true' });
  const opener = el('button', { type: 'button', class: 'app-menu-button', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
    title: 'Menu', 'aria-label': 'Open the menu', onclick: (e) => { e.stopPropagation(); showMenu(menu.classList.contains('hidden')); } },
    el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), icon('menu'), badge);
  const closeMenu = (e) => {
    if (e.type === 'keydown' ? e.key === 'Escape' : !e.composedPath().includes(menu)) { showMenu(false); if (e.type === 'keydown') opener.focus(); }
  };
  function showMenu(open) {
    menu.classList.toggle('hidden', !open);
    opener.setAttribute('aria-expanded', String(open));
    for (const event of ['click', 'keydown']) window[open ? 'addEventListener' : 'removeEventListener'](event, closeMenu);
    if (!open) return;
    drawNav();
    const first = menu.querySelector('a, button');
    if (first) first.focus();
  }
  const signOut = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); history.replaceState(null, '', '#/'); showAuth(); };

  // Outside the canvas the sidebar is shown in full, down the left. In the canvas it folds into the menu above, so the
  // stage gets the whole width. Narrow screens always use the menu.
  const sidebar = el('aside', { class: 'sidebar', 'aria-label': 'Scene.ai' });
  const shell = el('div', { class: 'shell' }, el('div', { class: 'app-menu-wrap' }, opener, menu), sidebar, view, credits);
  root.replaceChildren(shell);
  const narrow = window.matchMedia('(max-width: 860px)');

  const drawNav = () => {
    const active = store.jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;
    const here = PAGES.find((p) => p.path === location.hash) || {};
    // The canvas folds the sidebar into the menu to free the stage; everywhere else shows it in full, unless the
    // screen is too narrow for a sidebar.
    const compact = location.hash === '#/canvas' || narrow.matches;
    const link = (p) => el('a', { href: p.path, role: 'menuitem', class: p.path === (here.under || here.path) ? 'on' : '', onclick: () => showMenu(false) },
      icon(p.icon), el('span', { class: 'grow' }, p.label));
    const shown = PAGES.filter((p) => !p.under && !p.menu);
    // While something is being made, the logo carries a mark and the menu a line that leads to the queue.
    badge.classList.toggle('hidden', !active);
    working.classList.toggle('hidden', !active);
    working.replaceChildren(el('i', { class: 'cell-mark stepping' }), active === 1 ? '1 job in the queue' : `${active} jobs in the queue`);
    nav.replaceChildren(...shown.flatMap((p, i) =>
      (p.group && p.group !== (shown[i - 1] || {}).group ? [el('div', { class: 'nav-label' }, p.group), link(p)] : [link(p)])));
    // The same blocks go into the menu (compact) or the sidebar (full): who, the pages, the queue and credits, then
    // the settings pages, the theme and signing out.
    const content = () => [
      el('div', { class: 'app-menu-who' },
        el('div', { class: 'avatar' }, (store.user.name[0] || '?').toUpperCase()),
        el('div', { class: 'who' }, el('b', {}, store.user.name), el('span', {}, store.user.email))),
      nav,
      el('div', { class: 'menu-sep' }),
      working,
      // Whether the render server answers is the admin's business; other users are not shown it.
      store.user.role === 'admin' && el('div', { class: 'server' }, dot, server),
      el('div', { class: 'menu-sep' }),
      ...PAGES.filter((p) => p.menu && (!p.adminOnly || store.user.role === 'admin')).map((p) => link(p)),
      el('div', { class: 'menu-row' }, 'Theme', segmented(THEMES, localStorage.getItem('scene.theme') || 'system', (theme) => { applyTheme(theme); drawNav(); })),
      el('button', { role: 'menuitem', class: 'menu-item', onclick: signOut }, icon('logout'), 'Sign out'),
    ].filter(Boolean);   // a block left out (the server line, for a non-admin) is false, which would show as "false"
    shell.classList.toggle('compact', compact);
    shell.classList.toggle('on-canvas', location.hash === '#/canvas');   // the canvas shows the balance in its own tool bar
    shell.classList.toggle('railed', !compact);
    if (compact) {
      sidebar.replaceChildren();
      if (!menu.classList.contains('hidden')) menu.replaceChildren(...content());
    } else {
      showMenu(false);   // the dropdown never stays open once the full sidebar is showing
      sidebar.replaceChildren(
        el('a', { class: 'sidebar-brand', href: '#/home', 'aria-label': 'Home' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), el('b', {}, 'Scene.ai')),
        ...content());
    }
  };
  const drawStatus = () => {
    dot.className = 'dot ' + (store.online == null ? '' : store.online ? 'online' : 'offline');
    server.textContent = store.online == null ? 'Checking render server…' : store.online ? 'Render server online' : 'Render server offline';
  };
  const drawCredits = () => credits.replaceChildren(creditMark(''), el('b', {}, Number(store.user.credits ?? 0).toLocaleString()), Number(store.user.credits) === 1 ? 'credit' : 'credits');
  const route = () => {
    const target = PAGES.find((p) => p.path === location.hash);
    if (!target) { location.hash = LANDING; return; }
    if (leavePage) leavePage();
    tabTitle(target.label);   // the canvas and the timeline put the name of their project here once it is loaded
    leavePage = target.page.render(view) || null;
    drawNav();
    window.scrollTo(0, 0);
  };

  drawCredits();
  // A tab opened before the studio was updated runs the old page: it says so once, and Reload brings the new one.
  const loaded = Number((import.meta.url.match(/\/v\/(\d+)\//) || [])[1]) || null;
  let offered = false;
  const offerReload = () => {
    if (offered || !loaded || !store.page || store.page <= loaded) return;
    offered = true;
    document.body.append(el('div', { class: 'update-bar', role: 'status' },
      el('span', {}, 'Scene.ai has been updated.'),
      el('button', { class: 'btn small primary', onclick: () => location.reload() }, 'Reload'),
      el('button', { class: 'icon-btn', title: 'Later', 'aria-label': 'Later', onclick: (e) => e.currentTarget.parentNode.remove() }, '×')));
  };
  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') drawNav();
    if (change === 'status') { drawStatus(); offerReload(); }
    if (change === 'credits') drawCredits();
  });
  window.addEventListener('hashchange', route);
  const onResize = () => drawNav();   // crossing the narrow breakpoint swaps the sidebar and the menu
  narrow.addEventListener('change', onResize);
  const leaveNews = announcement();
  leaveShell = () => { unsubscribe(); leaveNews(); showMenu(false); narrow.removeEventListener('change', onResize); window.removeEventListener('hashchange', route); };

  startLive();
  refreshJobs().catch(() => {});
  route();
}

// The message an admin set for everyone, floating at the top of the studio until it ends or is closed.
// Closing it hides that message for this browser session; a new message shows again.
function announcement() {
  const bar = el('div', { class: 'announce-wrap', role: 'status' });
  document.body.append(bar);
  const draw = async () => {
    let news = {};
    try { news = await api('/api/announcement'); } catch (e) { return; }
    let closed = '';
    try { closed = sessionStorage.getItem('scene.announce.closed') || ''; } catch (e) { /* no storage */ }
    if (!news.text || closed === news.text) return bar.replaceChildren();
    bar.replaceChildren(el('div', { class: 'announce ' + news.level }, icon(news.level === 'warning' ? 'bolt' : 'chat'), el('span', {}, news.text),
      el('button', { class: 'icon-btn', title: 'Close', 'aria-label': 'Close the message', onclick: () => {
        try { sessionStorage.setItem('scene.announce.closed', news.text); } catch (e) { /* no storage */ }
        bar.replaceChildren();
      } }, '×')));
  };
  draw();
  const timer = setInterval(draw, 60000);
  window.addEventListener('scene:announcement', draw);   // the admin console asks for a redraw after publishing
  return () => { clearInterval(timer); window.removeEventListener('scene:announcement', draw); bar.remove(); };
}

window.addEventListener('scene:signed-out', () => { if (store.user) showAuth(); });

api('/api/auth/me').then((user) => { store.user = user; showApp(); }).catch(showAuth);
