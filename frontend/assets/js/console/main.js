// The admin console: a site of its own beside the studio, on its own port, with its own sign-in (email, password, and
// the second step when it is on). Only an admin can sign in. One section per address: /overview, /users, /jobs…

import { api } from '../api.js';
import { go, here, linkClicks } from '../nav.js';
import { el, field, icon, segmented } from '../dom.js';
import { session } from './session.js';
import { overview } from './overview.js';
import { users, jobs, library, credits, system, audit, settings } from './sections.js';
import { workflows } from './workflows.js';
import { agent } from './agent.js';
import { projects } from './projects.js';
import { moderation } from './moderation.js';
import { pricing } from './pricing.js';
import { economics } from './economics.js';
import { skills } from './skills.js';
import { roles } from './roles.js';
import { servers } from './servers.js';

// `live`: how often the section redraws itself while it is open, in ms. `group` is the heading it sits under.
const SECTIONS = [
  { id: 'overview', label: 'Overview', icon: 'home', draw: overview, live: 15000, group: 'Live' },
  { id: 'jobs', label: 'Jobs', icon: 'clock', draw: jobs, live: 5000, group: 'Live' },
  { id: 'system', label: 'System', icon: 'bolt', draw: system, live: 10000, group: 'Live' },
  { id: 'users', label: 'Users', icon: 'eye', draw: users, group: 'People' },
  { id: 'credits', label: 'Credits', icon: 'gem', draw: credits, group: 'People' },
  { id: 'library', label: 'Library', icon: 'grid', draw: library, group: 'People' },
  { id: 'projects', label: 'Projects', icon: 'folder', draw: projects, group: 'People' },
  { id: 'moderation', label: 'Moderation', icon: 'shield', draw: moderation, group: 'People' },
  { id: 'pricing', label: 'Pricing', icon: 'sliders', draw: pricing, group: 'Money' },
  { id: 'economics', label: 'Economics', icon: 'bars', draw: economics, group: 'Money' },
  { id: 'workflows', label: 'Workflows', icon: 'frame', draw: workflows, group: 'Studio' },
  { id: 'agent', label: 'Agent', icon: 'chat', draw: agent, group: 'Studio' },
  { id: 'skills', label: 'Skills', icon: 'skill', draw: skills, group: 'Studio' },
  { id: 'endpoints', label: 'Servers & APIs', icon: 'server', draw: servers, group: 'Studio' },
  { id: 'roles', label: 'Roles', icon: 'people', draw: roles, group: 'Records' },
  { id: 'audit', label: 'Audit log', icon: 'book', draw: audit, group: 'Records' },
  { id: 'settings', label: 'Settings', icon: 'wrench', draw: settings, group: 'Records' },
];
const FIRST = '/overview';
const THEMES = [{ id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }, { id: 'system', label: 'Auto', hint: 'Same as this computer' }];
const root = document.getElementById('app');
let leave = null;

function applyTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('scene.theme', theme); } catch (e) { /* no storage */ }
}

const title = (name) => { document.title = name ? `${name} · Admin console` : 'Admin console · Scene.ai'; };

// Sign in: email and password, then the authenticator code when the account has two-step sign-in on.
function showSignIn(message) {
  if (leave) leave();
  leave = null;
  session.user = null;
  title();
  const wanted = SECTIONS.some((s) => '/' + s.id === here()) ? here() : FIRST;   // a section's address opened before signing in
  if (here() !== '/signin') history.replaceState(null, '', '/signin');
  let second = null;   // {email, password} once the password was right and a code is asked for

  const page = (...card) => root.replaceChildren(el('div', { class: 'auth' },
    el('div', { class: 'auth-hero' },
      el('div', { class: 'auth-frame', 'aria-hidden': 'true' }),
      el('span', { class: 'brand' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), 'Scene.ai'),
      el('div', {},
        el('h2', {}, 'Admin console.'),
        el('p', {}, 'The queue, the render server, users, credits and pricing of the studio. For its admins only.')),
      el('div', { class: 'auth-points' }, ['Its own address, apart from the studio', 'Its own sign-in', 'Every change goes into the audit log']
        .map((p) => el('div', {}, icon('check'), p)))),
    el('div', { class: 'auth-side' }, el('div', { class: 'auth-card' }, ...card))));

  const signIn = async (body, error, submit) => {
    submit.disabled = true;
    try {
      const user = await api('/api/console/login', { method: 'POST', json: body });
      history.replaceState(null, '', wanted);
      showConsole(user);
    } catch (err) {
      if (!second && err.data && err.data.mfa_required) {
        second = { email: body.email, password: body.password };
        return drawCode();
      }
      error.textContent = err.message;
      submit.disabled = false;
    }
  };

  const drawPassword = () => {
    const email = el('input', { type: 'email', autocomplete: 'username', required: true, placeholder: 'you@company.com' });
    const password = el('input', { type: 'password', autocomplete: 'current-password', required: true, placeholder: 'Your password' });
    const error = el('p', { class: 'error notice' }, message || '');
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, 'Sign in');
    page(el('h1', {}, 'Admin sign-in'),
      el('p', { class: 'muted' }, 'With the email and password of an admin account of the studio.'),
      el('form', { onsubmit: (e) => { e.preventDefault(); signIn({ email: email.value, password: password.value }, error, submit); } },
        field('Email', email), field('Password', password), error, submit));
    email.focus();
  };

  const drawCode = () => {
    const code = el('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 20, placeholder: '123456' });
    const error = el('p', { class: 'error notice' });
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, 'Sign in');
    page(el('h1', {}, 'Two-step sign-in'),
      el('p', { class: 'muted' }, 'Enter the 6-digit code your authenticator app shows for Scene.ai, or one of your recovery codes.'),
      el('form', { onsubmit: (e) => { e.preventDefault(); signIn({ ...second, code: code.value }, error, submit); } },
        field('Code', code), error, submit),
      el('div', { class: 'auth-switch muted' }, el('button', { type: 'button', onclick: () => { second = null; drawPassword(); } }, 'Back')));
    code.focus();
  };
  drawPassword();
}

function showConsole(user) {
  session.user = user;
  // The sections this person's role may open (staff.py on the server); the rest are not shown, and are refused there.
  const mine = SECTIONS.filter((s) => !user.sections || user.sections.includes(s.id));
  const first = '/' + (mine[0] || SECTIONS[0]).id;
  const studio = `${location.protocol}//${location.hostname}:${user.studio.port}`;
  const nav = el('nav', { class: 'nav', 'aria-label': 'Sections' });
  const view = el('main', { class: 'view' });
  const sidebar = el('aside', { class: 'sidebar', 'aria-label': 'Admin console' });
  root.replaceChildren(el('div', { class: 'shell railed console' }, sidebar, view));

  // How many people have the studio open, kept up to date by the console's live connection as they come and go, and
  // how many alerts are open (shown on System in the sidebar).
  let people = null;
  let alerts = 0;
  let queue = null;   // {running, waiting}: shown on Jobs in the sidebar
  const count = el('b');
  const live = el('div', { class: 'live-count', role: 'status', 'aria-live': 'polite', title: 'People with the studio open right now. Several tabs count once.' },
    el('span', { class: 'dot online' }), count, el('span', { class: 'muted' }));
  const showPeople = (changed) => {
    count.textContent = people == null ? '…' : people;
    live.lastChild.textContent = people === 1 ? 'person live now' : 'people live now';
    if (changed) { live.classList.remove('bump'); void live.offsetWidth; live.classList.add('bump'); }
  };
  showPeople(false);

  const drawSidebar = () => {
    const at = here().slice(1);
    nav.replaceChildren(...mine.flatMap((s, i) => [
      s.group !== (mine[i - 1] || {}).group && el('div', { class: 'nav-label' }, s.group),
      el('a', { href: '/' + s.id, class: s.id === at ? 'on' : '' }, icon(s.icon), el('span', { class: 'grow' }, s.label),
        s.id === 'system' && alerts > 0 && el('span', { class: 'pill failed', title: 'Open alerts' }, String(alerts)),
        s.id === 'jobs' && queue && queue.running + queue.waiting > 0 && el('span', { class: 'nav-count', title: `${queue.running} running, ${queue.waiting} waiting` },
          queue.running ? `${queue.running} · ${queue.waiting}` : String(queue.waiting))),
    ].filter(Boolean)));
    sidebar.replaceChildren(
      el('div', { class: 'sidebar-brand' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), el('b', {}, 'Scene.ai'),
        el('span', { class: 'console-tag' }, user.role_label || 'Admin')),
      el('div', { class: 'app-menu-who' },
        el('div', { class: 'avatar' }, (user.name[0] || '?').toUpperCase()),
        el('div', { class: 'who' }, el('b', {}, user.name), el('span', {}, user.email))),
      el('button', { class: 'menu-item search-item', onclick: () => openSearch() }, icon('search'), el('span', { class: 'grow' }, 'Search'), el('kbd', {}, 'Ctrl K')),
      nav,
      el('div', { class: 'menu-sep' }),
      el('a', { href: studio, target: '_blank', rel: 'noopener' }, icon('forward'), el('span', { class: 'grow' }, 'Open the studio')),
      el('div', { class: 'menu-row' }, 'Theme', segmented(THEMES, localStorage.getItem('scene.theme') || 'system', (theme) => { applyTheme(theme); drawSidebar(); })),
      el('button', { class: 'menu-item', onclick: signOut }, icon('logout'), 'Sign out'));
  };

  // What each section remembers while the console is open: filters, searches, the period.
  let drawn = 0;
  let body = el('div');
  const ctx = {
    days: 30,
    state: {
      users: { q: '', show: '' }, jobs: { status: 'active', q: '', offset: 0 }, library: { kind: '', q: '', owner: '', project: '', offset: 0 },
      credits: { reason: '', q: '' }, audit: { q: '' }, workflows: { show: '' }, agent: { days: 7 }, projects: { q: '' }, moderation: { show: 'review' },
    },
    draw,
    go(target, changes) {
      if (changes) Object.assign(ctx.state[target], changes);
      if (here() === '/' + target) draw();
      else go('/' + target);
    },
  };
  const current = () => mine.find((s) => '/' + s.id === here());

  async function draw() {
    const shown = current();
    // Keep the search box focused and its caret in place across a redraw.
    const focused = body.contains(document.activeElement) && document.activeElement.classList.contains('search') ? document.activeElement.selectionStart : null;
    try {
      const content = await shown.draw(ctx);
      if (shown !== current()) return;
      body.replaceChildren(...content.filter(Boolean));
      if (focused != null) {
        const box = body.querySelector('.search');
        if (box) { box.focus(); box.setSelectionRange(focused, focused); }
      }
    } catch (e) {
      if (e.status !== 401) body.replaceChildren(el('p', { class: 'error' }, e.message));
    }
    drawn = Date.now();
  }

  const route = () => {
    const shown = current();
    if (!shown) { go(first, { replace: true }); return; }
    document.querySelectorAll('.drawer-backdrop').forEach((d) => d.remove());
    title(shown.label);
    body = el('div');
    view.replaceChildren(el('div', { class: 'page-head' }, el('h1', {}, shown.label), live), body);
    drawSidebar();
    window.scrollTo(0, 0);
    draw();
  };

  // Sections that follow the queue or the server redraw themselves, unless the admin is in the middle of something.
  const timer = setInterval(() => {
    const shown = current();
    const busy = document.querySelector('dialog[open], .drawer-backdrop, .chart:hover, .chart:focus-within') || body.contains(document.activeElement);
    if (shown && shown.live && !busy && !document.hidden && Date.now() - drawn >= shown.live) draw();
  }, 1000);

  let socket = null;
  let retry = null;
  const connect = () => {
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/console/events');
    // Redraw the section if it shows what changed, unless the admin is in the middle of something.
    const follow = (...ids) => {
      const busy = document.querySelector('dialog[open], .drawer-backdrop') || body.contains(document.activeElement);
      if (ids.includes(here().slice(1)) && !busy) draw();
    };
    socket.onmessage = (e) => {
      const message = JSON.parse(e.data);
      if (message.online_users != null) {
        people = message.online_users;
        showPeople(true);
        follow('overview');   // it lists who is online
      }
      if (message.jobs) {
        if (typeof message.jobs === 'object') {
          const changed = !queue || queue.running !== message.jobs.running || queue.waiting !== message.jobs.waiting;
          queue = message.jobs;
          if (changed) drawSidebar();
        }
        follow('overview', 'jobs');
      }
      (message.news || []).forEach((n) => toast(n.level, n.text, () => ctx.go('system')));
      if (message.alerts != null && message.alerts !== alerts) {
        alerts = message.alerts;
        drawSidebar();
        follow('overview', 'system');
      }
    };
    socket.onclose = () => { retry = setTimeout(connect, 3000); };
  };
  connect();

  // Search (Ctrl+K): the sections by name, and people, jobs, projects and workflows by name, email or id.
  let closeSearch = null;
  function openSearch() {
    if (closeSearch) return;
    const box = el('input', { type: 'search', class: 'palette-input', placeholder: 'Search people, jobs, projects, workflows, sections…', 'aria-label': 'Search' });
    const list = el('div', { class: 'palette-list', role: 'listbox' });
    let items = [];
    let at = 0;
    let asked = 0;
    const pick = (item) => { close(); item.run(); };
    const draw = () => {
      list.replaceChildren(...(items.length ? items.map((item, i) => el('button', { class: 'palette-item' + (i === at ? ' on' : ''), role: 'option',
        onmouseenter: () => { at = i; draw(); }, onclick: () => pick(item) },
      el('span', { class: 'palette-kind' }, item.kind), el('span', { class: 'grow' }, item.label), item.note && el('span', { class: 'muted small' }, item.note)))
        : [el('p', { class: 'muted small', style: 'padding:10px 12px' }, box.value.trim().length < 2 ? 'Type a name, an email or a job\'s id.' : 'Nothing found.')]));
    };
    const find = async () => {
      const q = box.value.trim();
      const low = q.toLowerCase();
      const sections = mine.filter((s) => low && s.label.toLowerCase().includes(low)).map((s) => ({ kind: 'Section', label: s.label, run: () => go('/' + s.id) }));
      items = sections;
      at = 0;
      draw();
      if (q.length < 2) return;
      const ticket = ++asked;   // a later search makes this one stale
      let found;
      try { found = await api('/api/admin/search?q=' + encodeURIComponent(q)); } catch (e) { return; }
      const can = (id) => mine.some((s) => s.id === id);
      if (ticket !== asked) return;
      items = [...sections,
        ...found.users.filter(() => can('users')).map((u) => ({ kind: 'Person', label: u.name, note: u.email + (u.role !== 'user' ? ' · ' + u.role : '') + (u.disabled ? ' · disabled' : ''), run: () => ctx.go('users', { q: u.email, show: '' }) })),
        ...found.jobs.filter(() => can('jobs')).map((j) => ({ kind: 'Job', label: j.name, note: `${j.user_name} · ${j.status}`, run: () => ctx.go('jobs', { q: j.name, status: '', offset: 0 }) })),
        ...found.projects.map((p) => ({ kind: p.parent_id ? 'Module' : 'Project', label: p.name, note: p.user_name, run: () => ctx.go('projects', { q: p.name }) })),
        ...found.workflows.filter(() => can('workflows')).map((w) => ({ kind: 'Workflow', label: w.title, note: w.id, run: () => ctx.go('workflows', { show: '' }) }))];
      draw();
    };
    let timer;
    box.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(find, 180); });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); at = (at + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % Math.max(items.length, 1); draw(); }
      if (e.key === 'Enter' && items[at]) pick(items[at]);
    });
    const shade = el('div', { class: 'palette-shade', onclick: (e) => { if (e.target === shade) close(); } },
      el('div', { class: 'palette', role: 'dialog', 'aria-label': 'Search' }, box, list));
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    function close() { shade.remove(); document.removeEventListener('keydown', onKey); closeSearch = null; }
    closeSearch = close;
    document.addEventListener('keydown', onKey);
    document.body.append(shade);
    draw();
    box.focus();
  }
  const searchKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); } };
  document.addEventListener('keydown', searchKey);

  window.addEventListener('scene:route', route);
  leave = () => {
    document.removeEventListener('keydown', searchKey);
    if (closeSearch) closeSearch();
    clearInterval(timer);
    clearTimeout(retry);
    if (socket) { socket.onclose = null; socket.close(); }
    window.removeEventListener('scene:route', route);
    document.querySelectorAll('.drawer-backdrop').forEach((d) => d.remove());
  };
  route();
}

// A short notice at the bottom right: an alert that opened or closed while the console is open. It goes by itself.
const LEVELS = { critical: 'Critical', serious: 'Serious', warning: 'Warning', resolved: 'Resolved' };
function toast(level, text, onOpen) {
  let stack = document.querySelector('.toasts');
  if (!stack) {
    stack = el('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
    document.body.append(stack);
  }
  const note = el('div', { class: 'toast ' + level },
    el('button', { class: 'toast-body', onclick: () => { note.remove(); onOpen(); } }, el('b', {}, LEVELS[level] || level), el('span', {}, text)),
    el('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: () => note.remove() }, '×'));
  stack.append(note);
  setTimeout(() => note.remove(), level === 'critical' ? 20000 : 9000);
}

async function signOut() {
  await api('/api/console/logout', { method: 'POST' }).catch(() => {});
  showSignIn();
}

// A call refused for want of a sign-in (it ran out, or the account stopped being an admin) leads back to signing in.
window.addEventListener('scene:signed-out', () => { if (session.user) showSignIn('Your sign-in to the console ended. Sign in again.'); });
linkClicks();

api('/api/console/me')
  .then((user) => { if (here() === '/signin' || here() === '/') history.replaceState(null, '', FIRST); showConsole(user); })
  .catch(() => showSignIn());
