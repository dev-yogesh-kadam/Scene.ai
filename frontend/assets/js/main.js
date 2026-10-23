// Scene.ai front end entry: sign-in gate, app shell and page routing.

import { api } from './api.js';
import { consoleAddress, go, here, linkClicks, oldAddress } from './nav.js';
import { creditMark, el, icon, segmented, tabTitle } from './dom.js';
import { store, subscribe, startLive, stopLive, refreshJobs } from './store.js';
import { renderAuth } from './pages/auth.js';
import { renderLanding } from './pages/landing.js';
import * as home from './pages/home.js';
import * as create from './pages/create.js';
import * as canvas from './pages/canvas.js';
import * as timeline from './pages/timeline.js';
import * as projects from './pages/projects.js';
import * as project from './pages/project.js';
import * as library from './pages/library.js';
import * as skills from './pages/skills.js';
import * as settings from './pages/settings.js';
import * as guide from './pages/guide.js';
import * as analytics from './pages/analytics.js';

const root = document.getElementById('app');
// The first page is where a visit starts. `group` is the heading a page sits under in the menu.
// A page with `under` has no menu entry of its own: it is reached from the page it names, which stays lit while it is open.
// A page with `menu` is listed lower in the menu, with the settings and signing out.
const PAGES = [
  { path: '/home', label: 'Home', icon: 'home', page: home },
  { path: '/projects', label: 'All projects', crumb: 'Projects', icon: 'folder', page: projects, group: 'Workspace' },
  { path: '/library', label: 'Library', icon: 'grid', page: library, group: 'Workspace' },
  { path: '/skills', label: 'Skills', icon: 'skill', page: skills, group: 'Workspace' },
  { path: '/guide', label: 'Guide', icon: 'book', page: guide, group: 'Help' },
  { path: '/create', page: create, under: '/home' },
  { path: '/project', page: project, under: '/projects' },
  { path: '/analytics', label: 'Analytics', page: analytics, under: '/projects' },
  { path: '/canvas', page: canvas, under: '/projects' },
  { path: '/timeline', page: timeline, under: '/projects' },
  { path: '/settings', label: 'Settings', icon: 'sliders', page: settings, menu: true },
];
const LANDING = '/projects';
// The pages that show the menu in full down the left, as a sidebar; every other page has it in the dropdown under the
// logo, beside where you are. A narrow screen always uses the dropdown.
const SIDEBAR_PAGES = ['/home', '/projects'];   // where signing in, or opening the site with no page in the address, leads
const THEMES = [{ id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }, { id: 'system', label: 'Auto', hint: 'Same as this computer' }];
let leavePage = null;
let leaveShell = null;

function applyTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  localStorage.setItem('scene.theme', theme);
}

// What someone who is not signed in sees: the landing page at the site's address, Create account at /signup, and
// Sign in at /signin or at any page of the studio (an old link, or a session that ran out).
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
    const at = here();
    if (at === '/') return renderLanding(root, { signupOpen: info.signup_open });
    // Signing in always lands on All projects. replaceState does not fire a route event, so the page is routed once, by showApp.
    renderAuth(root, (user) => { store.user = user; leaveDoor(); history.replaceState(null, '', LANDING); showApp(); },
      at === '/signup' && info.signup_open ? 'register' : 'login');
  };
  if (leaveDoor) leaveDoor();
  window.addEventListener('scene:route', door);
  leaveDoor = () => { window.removeEventListener('scene:route', door); leaveDoor = null; };
  door();
}

function showApp() {
  const view = el('main', { class: 'view' });
  const nav = el('nav', { class: 'nav', 'aria-label': 'Pages' });
  const working = el('span', { class: 'working hidden' });   // says that something is being made; the whole queue is in the admin console
  const dot = el('span', { class: 'dot' });
  const server = el('span', {}, 'Checking render server…');
  const credits = el('div', { class: 'credit-badge', title: 'Credits pay for generations. An admin can add more.' });
  // On Home and All projects the pages are in a sidebar; elsewhere in a dropdown from the logo at the top left, beside
  // where you are (Projects › Name). The account (settings, theme, signing out) is in one from your name at the top
  // right, beside the Guide and the balance.
  const menu = el('div', { class: 'app-menu hidden', role: 'menu', 'aria-label': 'Pages' });
  const account = el('div', { class: 'app-menu account-menu hidden', role: 'menu', 'aria-label': 'Account' });
  const badge = el('span', { class: 'app-menu-badge hidden', 'aria-hidden': 'true' });
  const opener = el('button', { type: 'button', class: 'app-menu-button', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
    title: 'Menu', 'aria-label': 'Open the menu', onclick: (e) => { e.stopPropagation(); toggle(menu, opener); } },
    el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), icon('chevron'), badge);
  const whoChip = el('button', { type: 'button', class: 'who-chip', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-label': 'Your account',
    onclick: (e) => { e.stopPropagation(); toggle(account, whoChip); } },
    el('span', { class: 'avatar' }, (store.user.name[0] || '?').toUpperCase()), el('span', { class: 'who-name' }, store.user.name));
  const crumbs = el('nav', { class: 'crumbs', 'aria-label': 'Where you are' });
  const topRight = el('div', { class: 'topbar-right' },
    el('a', { class: 'top-btn', href: '/guide' }, icon('book'), 'Guide'), credits, el('div', { class: 'account-wrap' }, whoChip, account));

  // One dropdown open at a time; a click outside it or Escape closes it.
  let open = null;
  const close = (e) => {
    if (!open) return;
    if (e && e.type === 'keydown' && e.key !== 'Escape') return;
    if (e && e.type === 'click' && e.composedPath().includes(open.panel)) return;
    const was = open;
    open.panel.classList.add('hidden');
    open.button.setAttribute('aria-expanded', 'false');
    open = null;
    for (const event of ['click', 'keydown']) window.removeEventListener(event, close);
    if (e && e.type === 'keydown') was.button.focus();
  };
  function toggle(panel, button) {
    const again = open && open.panel === panel;
    close();
    if (again) return;
    open = { panel, button };
    drawNav();
    panel.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
    for (const event of ['click', 'keydown']) window.addEventListener(event, close);
    const first = panel.querySelector('a, button');
    if (first) first.focus();
  }
  const signOut = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); history.replaceState(null, '', '/'); showAuth(); };

  const sidebar = el('aside', { class: 'sidebar', 'aria-label': 'Scene.ai' });
  const shell = el('div', { class: 'shell compact' }, el('div', { class: 'app-menu-wrap' }, opener, crumbs, menu), sidebar, topRight, view);
  root.replaceChildren(shell);
  const narrow = window.matchMedia('(max-width: 860px)');

  const drawNav = () => {
    const active = store.jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;
    const at = PAGES.find((p) => p.path === here()) || {};
    const link = (p) => el('a', { href: p.path, role: 'menuitem', class: p.path === (at.under || at.path) ? 'on' : '', onclick: () => close() },
      icon(p.icon), el('span', { class: 'grow' }, p.label));
    const shown = PAGES.filter((p) => !p.under && !p.menu);
    // While something is being made, the logo carries a mark and the menu a line that leads to the queue.
    badge.classList.toggle('hidden', !active);
    working.classList.toggle('hidden', !active);
    working.replaceChildren(el('i', { class: 'cell-mark stepping' }), active === 1 ? '1 job in the queue' : `${active} jobs in the queue`);
    nav.replaceChildren(...shown.flatMap((p, i) =>
      (p.group && p.group !== (shown[i - 1] || {}).group ? [el('div', { class: 'nav-label' }, p.group), link(p)] : [link(p)])));
    const pages = [nav, el('div', { class: 'menu-sep' }), working,
      // Whether the render server answers is the admin's business; other users are not shown it.
      store.user.role === 'admin' && el('div', { class: 'server' }, dot, server)].filter(Boolean);
    const railed = SIDEBAR_PAGES.includes(here()) && !narrow.matches;
    shell.classList.toggle('railed', railed);
    shell.classList.toggle('compact', !railed);
    if (railed) {
      if (open && open.panel === menu) close();
      menu.replaceChildren();
      sidebar.replaceChildren(
        el('a', { class: 'sidebar-brand', href: '/home', 'aria-label': 'Home' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), el('b', {}, 'Scene.ai')),
        ...pages);
    } else {
      sidebar.replaceChildren();
      menu.replaceChildren(...pages);
    }
    account.replaceChildren(...[
      el('div', { class: 'app-menu-who' },
        el('div', { class: 'avatar' }, (store.user.name[0] || '?').toUpperCase()),
        el('div', { class: 'who' }, el('b', {}, store.user.name), el('span', {}, store.user.email))),
      el('div', { class: 'menu-sep' }),
      ...PAGES.filter((p) => p.menu).map((p) => link(p)),
      // The admin console is a site of its own, on its own port and sign-in: it opens in a tab of its own.
      store.user.console && el('a', { href: consoleAddress(store.user), target: '_blank', rel: 'noopener', role: 'menuitem', onclick: () => close() },
        icon('shield'), el('span', { class: 'grow' }, 'Admin console')),
      el('div', { class: 'menu-row' }, 'Theme', segmented(THEMES, localStorage.getItem('scene.theme') || 'system', (theme) => { applyTheme(theme); drawNav(); })),
      el('button', { role: 'menuitem', class: 'menu-item', onclick: signOut }, icon('logout'), 'Sign out'),
    ].filter(Boolean));   // a block left out (the admin console, for a user) is false, which would show as "false"
    shell.classList.toggle('on-canvas', here() === '/canvas');   // the canvas has its own tool bar: no Guide, balance or name here
  };

  // Where you are, beside the logo: the page, or the page it is reached from and its own name (a page that knows more,
  // such as a project's, says so with a "scene:crumbs" event: [{label, href?}]).
  let trail = null;
  const drawCrumbs = () => {
    const at = PAGES.find((p) => p.path === here()) || {};
    const parent = at.under && PAGES.find((p) => p.path === at.under);
    const steps = trail || (parent ? [{ label: parent.crumb || parent.label, href: parent.path }] : at.label ? [{ label: at.crumb || at.label }] : []);
    crumbs.replaceChildren(...steps.flatMap((s, i) => [
      i > 0 && el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, '›'),
      s.href && i < steps.length - 1 ? el('a', { href: s.href }, s.label) : el('b', {}, s.label)].filter(Boolean)));
    crumbs.classList.toggle('hidden', !steps.length);
  };
  const onCrumbs = (e) => { trail = e.detail; drawCrumbs(); };
  window.addEventListener('scene:crumbs', onCrumbs);

  const drawStatus = () => {
    dot.className = 'dot ' + (store.online == null ? '' : store.online ? 'online' : 'offline');
    server.textContent = store.online == null ? 'Checking render server…' : store.online ? 'Render server online' : 'Render server offline';
  };
  const drawCredits = () => credits.replaceChildren(creditMark(''), el('b', {}, Number(store.user.credits ?? 0).toLocaleString()), Number(store.user.credits) === 1 ? 'credit' : 'credits');
  const route = () => {
    // Where the admin console used to be, in an old link: it is a site of its own now.
    if (here() === '/admin' && store.user.console) { location.replace(consoleAddress(store.user)); return; }
    const target = PAGES.find((p) => p.path === here());
    if (!target) { go(LANDING, { replace: true }); return; }
    if (leavePage) leavePage();
    close();
    trail = null;
    tabTitle(target.label);   // the canvas and the timeline put the name of their project here once it is loaded
    leavePage = target.page.render(view) || null;
    drawNav();
    drawCrumbs();
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
  window.addEventListener('scene:route', route);
  const onResize = () => drawNav();   // crossing the narrow breakpoint swaps the sidebar and the dropdown
  narrow.addEventListener('change', onResize);
  const leaveNews = announcement();
  // An admin viewing the studio as this user (from the admin console): read only, and said so at the top of every page.
  const viewingBar = store.user.viewing && el('div', { class: 'viewing-bar', role: 'status' },
      el('span', {}, el('b', {}, `Viewing as ${store.user.name}`), ` · read only · opened by ${store.user.viewing.by}`),
      el('button', { class: 'btn small', onclick: signOut }, 'Stop viewing'));
  if (viewingBar) document.body.append(viewingBar);
  leaveShell = () => {
    unsubscribe(); leaveNews(); close();
    if (viewingBar) viewingBar.remove();
    window.removeEventListener('scene:crumbs', onCrumbs);
    narrow.removeEventListener('change', onResize);
    window.removeEventListener('scene:route', route);
  };

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
  return () => { clearInterval(timer); bar.remove(); };
}

window.addEventListener('scene:signed-out', () => { if (store.user) showAuth(); });
oldAddress();   // /#/library from an old link becomes /library
linkClicks();

api('/api/auth/me').then((user) => { store.user = user; showApp(); }).catch(showAuth);
