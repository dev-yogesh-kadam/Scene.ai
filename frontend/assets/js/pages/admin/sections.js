// The admin console's list sections: users, jobs, library, credits, workflows, system, audit log, settings.

import { api } from '../../api.js';
import { still, el, field, segmented } from '../../dom.js';
import { store, refreshStatus } from '../../store.js';
import { meter } from '../../components/charts.js';
import { openViewer } from '../../components/media.js';
import { number, bytes, span, ago, stamp, person, pill, tile, table, searchBox, exportLink, drawer, section, facts } from './shared.js';

const REASON = { welcome: 'Sign-up credits', generation: 'Generation', refund: 'Refund', 'admin grant': 'Changed by an admin' };
const act = (ctx, request) => request.then(ctx.draw).catch((e) => alert(e.message));
const itemUrl = (id) => `/api/admin/library/${id}/file`;
const thumb = (item) => still(itemUrl(item.id), item.kind, item.name);

// ---------------------------------------------------------------- give or take credits

// `people` is the list to choose from; pass one user to skip the choice. `after` runs once the change is saved.
export function creditsDialog(people, after) {
  let mode = 'give';
  let person = people.length === 1 ? people[0] : null;
  const who = el('select', { onchange: (e) => { person = people.find((p) => String(p.id) === e.target.value) || null; draw(); } },
    el('option', { value: '' }, 'Choose a user'), people.map((p) => el('option', { value: p.id }, `${p.name} · ${p.email}`)));
  const amount = el('input', { type: 'number', min: 1, step: 1, value: 500, style: 'width:100%', oninput: () => draw() });
  const note = el('input', { type: 'text', maxlength: 200, placeholder: 'Shown in the credit log, for example "Launch bonus"', oninput: () => draw() });
  const modeBox = el('div');
  const balance = el('div', { class: 'balance' });
  const error = el('p', { class: 'error notice' });
  const confirm = el('button', { class: 'btn primary', onclick: save });

  function draw() {
    modeBox.replaceChildren(segmented([{ id: 'give', label: 'Give credits' }, { id: 'take', label: 'Take credits' }], mode, (m) => { mode = m; draw(); }));
    const value = Math.max(0, Math.floor(Number(amount.value) || 0));
    const now = person ? person.credits : 0;
    const next = mode === 'give' ? now + value : Math.max(0, now - value);
    balance.replaceChildren(
      el('span', { class: 'muted' }, person ? `${person.name} has ${number(now)} now` : 'Choose a user to see their balance'),
      person && el('span', {}, el('span', { class: 'muted' }, 'New balance '), el('b', {}, number(next))));
    confirm.textContent = mode === 'give' ? `Give ${number(value)} credits` : `Take ${number(Math.min(value, now))} credits`;
    confirm.disabled = !person || value < 1 || (mode === 'take' && now === 0) || !note.value.trim();
    error.textContent = mode === 'take' && person && value > now && now > 0 ? `They only have ${number(now)}, so the balance goes to 0.` : '';
  }

  async function save() {
    const value = Math.floor(Number(amount.value) || 0);
    confirm.disabled = true;
    try {
      await api('/api/admin/users/' + person.id, { method: 'PUT', json: { add_credits: mode === 'give' ? value : -value, note: note.value } });
      dialog.close();
      after();
    } catch (e) { error.textContent = e.message; confirm.disabled = false; }
  }

  const dialog = el('dialog', {},
    el('h2', {}, 'Give or take credits'),
    el('p', { class: 'muted' }, 'The change is applied at once and recorded, with its reason, in the credit log and the audit log.'),
    people.length > 1 && field('User', who),
    el('div', { class: 'field' }, modeBox),
    field('Amount', amount, el('div', { class: 'chips' }, [100, 500, 1000, 5000].map((n) =>
      el('button', { type: 'button', class: 'btn small', onclick: () => { amount.value = n; draw(); } }, number(n))))),
    field('Reason', note),
    balance, error,
    el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'), confirm));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  draw();
  dialog.showModal();
}

// ---------------------------------------------------------------- users

function userActions(ctx, u, after) {
  const put = (json) => api('/api/admin/users/' + u.id, { method: 'PUT', json }).then(after).catch((e) => alert(e.message));
  const self = u.id === store.user.id;
  return el('div', { class: 'row' },
    el('button', { class: 'btn small primary', onclick: () => creditsDialog([u], after) }, 'Give or take credits'),
    el('button', { class: 'btn small', onclick: () => {
      const password = prompt(`New password for ${u.name} (at least 8 characters). They are signed out everywhere.`);
      if (password) put({ password });
    } }, 'Set password'),
    !self && el('button', { class: 'btn small', onclick: () => {
      if (confirm(`Make ${u.name} ${u.role === 'admin' ? 'a normal user' : 'an admin'}?`)) put({ role: u.role === 'admin' ? 'user' : 'admin' });
    } }, u.role === 'admin' ? 'Make user' : 'Make admin'),
    u.role !== 'admin' && el('button', { class: 'btn small', title: 'The agent is "coming soon" for users who have not been given it. Admins always have it.',
      onclick: () => put({ agent: !u.agent }) }, u.agent ? 'Take agent away' : 'Give agent access'),
    u.mfa_enabled && el('button', { class: 'btn small', onclick: () => {
      if (confirm(`Turn off two-step sign-in for ${u.name}? Do this only when you know it is them asking, for example after a lost phone. They are signed out everywhere.`)) put({ mfa_off: true });
    } }, 'Turn off two-step sign-in'),
    !self && el('button', { class: 'btn small quiet danger', onclick: () => {
      if (u.disabled || confirm(`Disable ${u.name}? They are signed out and can't sign in until you enable them again.`)) put({ disabled: !u.disabled });
    } }, u.disabled ? 'Enable account' : 'Disable account'));
}

// How many credits the user may spend in 24 hours: the studio's limit, their own, or none.
function limitSection(d, u, after) {
  const l = d.limits;
  if (l.exempt) return section('Daily spending limit', el('p', { class: 'muted' }, 'Admins have no daily limit.'));
  const box = el('input', { type: 'number', min: 0, step: 50, value: l.own == null ? '' : l.own, placeholder: l.studio ? `Studio limit: ${number(l.studio)}` : 'Studio: no limit', style: 'width:180px' });
  const save = (value) => api('/api/admin/users/' + u.id, { method: 'PUT', json: { daily_cap: value } }).then(after).catch((e) => alert(e.message));
  return section('Daily spending limit',
    el('p', { class: 'muted small' }, `${number(l.spent_today)} credits spent in the last 24 hours. `,
      l.in_force ? `The limit in force is ${number(l.in_force)}${l.own == null ? ' (the studio\'s)' : ' (their own)'}.` : 'No limit is in force for them.'),
    el('div', { class: 'row', style: 'margin-top:8px' }, box,
      el('button', { class: 'btn small', onclick: () => save(box.value === '' ? null : Number(box.value)) }, 'Save'),
      l.own != null && el('button', { class: 'btn small quiet', onclick: () => save(null) }, 'Use the studio\'s limit')),
    el('p', { class: 'muted small', style: 'margin-top:6px' }, 'Leave it empty to follow the studio\'s limit (Settings). 0 means no limit for this user.'));
}

async function openUser(ctx, id) {
  const panel = drawer('User', el('p', { class: 'muted' }, 'Loading…'));
  const load = async () => {
    const d = await api('/api/admin/users/' + id);
    const u = d.user;
    panel.replace(
      el('div', { class: 'drawer-title' }, el('div', { class: 'avatar' }, (u.name[0] || '?').toUpperCase()),
        el('div', {}, el('b', {}, u.name), el('div', { class: 'muted' }, u.email)),
        el('span', { class: 'pill ' + (u.role === 'admin' ? 'running' : 'queued') }, u.role),
        u.role !== 'admin' && u.agent ? el('span', { class: 'pill done' }, 'Agent') : null,
        u.mfa_enabled ? el('span', { class: 'pill done' }, 'Two-step') : null,
        u.disabled ? el('span', { class: 'pill failed' }, 'Disabled') : null),
      el('div', { class: 'tiles small-tiles' },
        tile('Credits', number(u.credits), `${number(u.spent)} spent`),
        tile('Jobs', number(u.jobs), `${d.stats.done} done · ${d.stats.failed} failed · ${d.stats.cancelled} cancelled`),
        tile('GPU time', span(d.stats.gpu_seconds) || '0 s'),
        tile('Library', number(u.generations), `${bytes(d.storage_bytes)} · ${d.assets} assets · ${d.projects} projects`)),
      userActions(ctx, u, () => { load(); ctx.draw(); }),
      limitSection(d, u, () => { load(); ctx.draw(); }),
      section('Account', facts([['Joined', stamp(u.created)], ['Last sign-in', u.last_sign_in ? stamp(u.last_sign_in) : 'No active session'],
        ['Last job', u.last_job ? stamp(u.last_job) : 'Never']])),
      section('Latest items', d.items.length
        ? el('div', { class: 'thumbs' }, d.items.map((i) => el('div', { class: 'thumb-box', title: i.name }, thumb(i))))
        : el('p', { class: 'muted' }, 'Nothing made yet.')),
      section('Latest jobs', table(['Job', 'Status', 'Credits', 'Added'], d.jobs.map((j) => [
        el('div', {}, j.name, el('div', { class: j.error ? 'error small' : 'muted small' }, j.error || j.summary)), pill(j.status), String(j.cost), ago(j.created)]),
      { empty: 'No jobs yet.' })),
      section('Credit history', table(['When', 'Credits', 'Reason'], d.credits.map((c) => [
        ago(c.created), (c.amount > 0 ? '+' : '') + c.amount, REASON[c.reason] + [c.job_name, c.note].filter(Boolean).map((x) => ` · ${x}`).join('')]), { empty: 'No credit changes.' })));
  };
  load().catch((e) => panel.replace(el('p', { class: 'error' }, e.message)));
}

export async function users(ctx) {
  const s = ctx.state.users;
  const list = (await api('/api/admin/users?' + new URLSearchParams({ q: s.q, show: s.show }))).users;
  return [
    el('div', { class: 'toolbar' },
      searchBox('Search name or email', s.q, (q) => { s.q = q; ctx.draw(); }),
      segmented([{ id: '', label: 'All' }, { id: 'admins', label: 'Admins' }, { id: 'no_credits', label: 'Out of credits' }, { id: 'disabled', label: 'Disabled' }],
        s.show, (v) => { s.show = v; ctx.draw(); }),
      el('span', { class: 'muted small', style: 'margin-left:auto' }, `${list.length} user${list.length === 1 ? '' : 's'}`), exportLink('users')),
    el('div', { class: 'card' }, table(
      ['User', 'Role', 'Credits', 'Spent', 'Items', 'Jobs', 'Last job', 'Joined', ''],
      list.map((u) => [
        el('div', {}, u.name, u.disabled ? el('span', { class: 'pill failed', style: 'margin-left:6px' }, 'Disabled') : null, el('div', { class: 'muted small' }, u.email)),
        u.role, el('b', {}, number(u.credits)), number(u.spent), number(u.generations), number(u.jobs), ago(u.last_job), ago(u.created),
        el('button', { class: 'btn small', onclick: (e) => { e.stopPropagation(); creditsDialog([u], ctx.draw); } }, 'Credits')]),
      { onRow: (i) => openUser(ctx, list[i].id), empty: 'No users match.' })),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, 'Select a user to see their jobs, credits and items, and to manage the account.'),
  ];
}

// ---------------------------------------------------------------- jobs

async function openJob(ctx, id) {
  const panel = drawer('Job', el('p', { class: 'muted' }, 'Loading…'));
  try {
    const j = await api('/api/admin/jobs/' + id);
    const st = j.settings;
    const values = Object.entries(st.values || {});
    const promptText = (values.find(([, v]) => typeof v === 'string' && v.length > 20) || [])[1];
    const active = ['queued', 'running'].includes(j.status);
    const retry = (free) => api(`/api/admin/jobs/${j.id}/retry`, { method: 'POST', json: { free } })
      .then(() => { panel.close(); ctx.go('jobs', { status: 'active' }); }).catch((e) => alert(e.message));
    panel.replace(
      el('div', { class: 'drawer-title' }, el('div', {}, el('b', {}, j.name), el('div', { class: 'muted' }, `${j.user_name} · ${j.user_email}`)), pill(j.status)),
      j.error && el('div', { class: 'alert critical static' }, el('span', { class: 'alert-level' }, 'Error'),
        el('span', { class: 'alert-text' }, j.explained ? el('span', {}, el('b', {}, j.explained), el('div', { class: 'muted small' }, j.error)) : j.error)),
      el('div', { class: 'row' },
        active && el('button', { class: 'btn small danger', onclick: () => {
          if (confirm(`Cancel "${j.name}"? The user's credits are refunded.`)) {
            api('/api/admin/jobs/' + j.id, { method: 'DELETE' }).then(() => { panel.close(); ctx.draw(); }).catch((e) => alert(e.message));
          }
        } }, 'Cancel this job'),
        j.status === 'queued' && el('button', { class: 'btn small', onclick: () => api(`/api/admin/jobs/${j.id}/front`, { method: 'POST' })
          .then(() => { panel.close(); ctx.draw(); }).catch((e) => alert(e.message)) }, 'Move to the front'),
        ['failed', 'cancelled'].includes(j.status) && [
          el('button', { class: 'btn small primary', title: 'Its first run was refunded, so this is charged like a new job', onclick: () => {
            if (confirm(`Run "${j.name}" again for ${j.user_name}? It costs them ${j.cost} credits, as a new job would.`)) retry(false);
          } }, `Run again (${j.cost} cr)`),
          el('button', { class: 'btn small', title: 'For a failure that was the studio\'s fault', onclick: () => {
            if (confirm(`Run "${j.name}" again for ${j.user_name} at no charge?`)) retry(true);
          } }, 'Run again free')]),
      section('Details', facts([
        ['Workflow', j.workflow], ['Settings', j.summary],
        ['Credits', String(j.cost) + (j.credits_reserved ? ' (held)' : j.credits_consumed ? ' (used)' : j.status === 'done' || active ? '' : ' (refunded)')],
        ['Length asked for', j.seconds_requested ? span(j.seconds_requested) : null], ['Server', j.server], ['Output size', j.output_size ? bytes(j.output_size) : null],
        ['Added', stamp(j.created)], ['Waited in queue', j.started ? span(j.started - j.created) : 'Not started'],
        ['Render time', j.finished && j.started ? span(j.finished - j.started) : null], ['Estimated', j.est_seconds ? span(j.est_seconds) : 'No estimate'],
        ['Job id', j.id]])),
      promptText && section('Prompt', el('p', { class: 'prose' }, promptText)),
      section('Options', facts([
        ...Object.entries(st.options || {}).map(([k, v]) => [k, String(v)]),
        ['Resolution', st.resolution && `${st.resolution}p ${st.orientation || ''}`], ['Clips', st.clips > 1 ? String(st.clips) : null], ['Seed', st.seed_mode],
        ...values.filter(([, v]) => v !== promptText).map(([k, v]) => ['Node ' + k, String(v)])])),
      Object.keys(st.refs || {}).length > 0 && section('References', facts(Object.entries(st.refs).map(([slot, r]) => ['Slot ' + slot, r.name || r.comfy_name]))),
      j.items.length > 0 && section('Result', el('div', { class: 'thumbs' }, j.items.map((i) => el('a', { class: 'thumb-box', href: itemUrl(i.id), target: '_blank', title: 'Open ' + i.filename }, thumb(i))))));
  } catch (e) { panel.replace(el('p', { class: 'error' }, e.message)); }
}

export async function jobs(ctx) {
  const s = ctx.state.jobs;
  const data = await api('/api/admin/jobs?' + new URLSearchParams({ status: s.status, q: s.q, offset: s.offset }));
  const detail = (j) => {
    if (j.status === 'running') return [j.clips > 1 && `clip ${j.clip}/${j.clips}`, j.steps ? `step ${j.step}/${j.steps}` : 'starting', j.node].filter(Boolean).join(' · ');
    return j.explained || j.error || j.summary;
  };
  const pages = Math.max(1, Math.ceil(data.total / 50));
  const page = Math.floor(s.offset / 50) + 1;
  return [
    el('div', { class: 'toolbar' },
      segmented([{ id: 'active', label: 'Running and waiting' }, { id: 'done', label: 'Done' }, { id: 'failed', label: 'Failed' },
        { id: 'cancelled', label: 'Cancelled' }, { id: '', label: 'All' }], s.status, (v) => { s.status = v; s.offset = 0; ctx.draw(); }),
      searchBox('Search job, workflow or user', s.q, (q) => { s.q = q; s.offset = 0; ctx.draw(); }),
      el('span', { class: 'muted small', style: 'margin-left:auto' }, `${number(data.total)} job${data.total === 1 ? '' : 's'}`), exportLink('jobs')),
    el('div', { class: 'card' }, table(
      ['Job', 'User', 'Status', 'Details', 'Waited', 'Render', 'Credits', 'Added'],
      data.jobs.map((j) => [
        el('div', {}, j.name, el('div', { class: 'muted small' }, j.workflow)), person(j.user_name, j.user_email), pill(j.status),
        el('span', { class: (j.status === 'failed' ? 'error ' : '') + 'small clip-text', title: detail(j) }, detail(j)),
        j.started ? span(j.started - j.created) : '', j.finished && j.started ? span(j.finished - j.started) : '', String(j.cost), ago(j.created)]),
      { onRow: (i) => openJob(ctx, data.jobs[i].id), empty: s.status === 'active' ? 'Nothing is running or waiting.' : 'No jobs match.' })),
    pages > 1 && el('div', { class: 'toolbar', style: 'margin-top:12px' },
      el('button', { class: 'btn small', disabled: page === 1, onclick: () => { s.offset -= 50; ctx.draw(); } }, 'Newer'),
      el('span', { class: 'muted small' }, `Page ${page} of ${pages}`),
      el('button', { class: 'btn small', disabled: page === pages, onclick: () => { s.offset += 50; ctx.draw(); } }, 'Older')),
  ];
}

// ---------------------------------------------------------------- library of all users

export async function library(ctx) {
  const s = ctx.state.library;
  const data = await api('/api/admin/library?' + new URLSearchParams({ kind: s.kind, q: s.q, owner: s.owner, project: s.project, offset: s.offset }));
  const change = (key) => (e) => { s[key] = e.target.value; if (key === 'owner') s.project = ''; s.offset = 0; ctx.draw(); };
  // Projects belong to one user, so the project list follows the chosen user.
  const projects = data.projects.filter((p) => !s.owner || String(p.user_id) === s.owner);
  const open = (item) => openViewer(item, { base: '/api/admin/library', owner: true, actions: [{ label: 'Delete from their library', danger: true, run: (dialog) => {
    if (confirm(`Delete "${item.name}" from ${item.user_name}'s library? This can't be undone.`)) {
      api('/api/admin/library/' + item.id, { method: 'DELETE' }).then(() => { dialog.close(); ctx.draw(); }).catch((e) => alert(e.message));
    }
  } }] });
  const pages = Math.max(1, Math.ceil(data.total / 50));
  const page = Math.floor(s.offset / 50) + 1;
  return [
    el('div', { class: 'toolbar' },
      segmented([{ id: '', label: 'All' }, { id: 'video', label: 'Videos' }, { id: 'image', label: 'Images' }, { id: 'audio', label: 'Audio' }], s.kind, (v) => { s.kind = v; s.offset = 0; ctx.draw(); }),
      el('select', { class: 'filter', 'aria-label': 'User', onchange: change('owner') },
        el('option', { value: '' }, 'All users'),
        data.owners.map((u) => el('option', { value: u.id, selected: String(u.id) === s.owner }, `${u.name} (${u.items})`))),
      el('select', { class: 'filter', 'aria-label': 'Project', onchange: change('project') },
        el('option', { value: '' }, 'All projects'),
        el('option', { value: 'none', selected: s.project === 'none' }, 'Not in a project'),
        projects.map((p) => el('option', { value: p.id, selected: String(p.id) === s.project }, s.owner ? p.name : `${p.name} · ${p.user_name}`))),
      searchBox('Search name, prompt or user', s.q, (q) => { s.q = q; s.offset = 0; ctx.draw(); }),
      el('span', { class: 'muted small push' }, `${number(data.total)} item${data.total === 1 ? '' : 's'}`)),
    el('div', { class: 'card' }, table(
      ['Name', 'Type', 'User', 'Project', 'Workflow', 'Settings', 'Size', 'Made'],
      data.items.map((item) => [
        el('b', {}, item.name), { video: 'Video', image: 'Image', audio: 'Audio' }[item.kind] || item.kind, person(item.user_name, item.user_email),
        item.project_name || el('span', { class: 'muted' }, 'None'), item.settings.workflow_title || item.workflow.split('/')[1].replace(/_/g, ' '),
        el('span', { class: 'small' }, item.summary), bytes(item.size), stamp(item.created)]),
      { onRow: (i) => open(data.items[i]), empty: 'No items match.' })),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, 'Select a row to watch the item and see its prompt and details.'),
    pages > 1 && el('div', { class: 'toolbar', style: 'margin-top:12px' },
      el('button', { class: 'btn small', disabled: page === 1, onclick: () => { s.offset -= 50; ctx.draw(); } }, 'Newer'),
      el('span', { class: 'muted small' }, `Page ${page} of ${pages}`),
      el('button', { class: 'btn small', disabled: page === pages, onclick: () => { s.offset += 50; ctx.draw(); } }, 'Older')),
  ];
}

// ---------------------------------------------------------------- credits

// The same credits to every account that is not disabled: for a launch, a holiday, or an apology after an outage.
function everyoneDialog(after) {
  const amount = el('input', { type: 'number', min: 1, step: 1, value: 200, style: 'width:100%', oninput: () => draw() });
  const note = el('input', { type: 'text', maxlength: 200, placeholder: 'For example "Sorry for Tuesday\'s outage"', oninput: () => draw() });
  const error = el('p', { class: 'error notice' });
  const confirm = el('button', { class: 'btn primary', onclick: save });
  function draw() {
    const value = Math.max(0, Math.floor(Number(amount.value) || 0));
    confirm.textContent = `Give everyone ${number(value)} credits`;
    confirm.disabled = value < 1 || !note.value.trim();
  }
  async function save() {
    confirm.disabled = true;
    try {
      const done = await api('/api/admin/credits/everyone', { method: 'POST', json: { amount: Math.floor(Number(amount.value)), note: note.value } });
      dialog.close();
      alert(`Gave ${number(done.amount)} credits to ${done.accounts} account${done.accounts === 1 ? '' : 's'}.`);
      after();
    } catch (e) { error.textContent = e.message; confirm.disabled = false; }
  }
  const dialog = el('dialog', {},
    el('h2', {}, 'Give everyone credits'),
    el('p', { class: 'muted' }, 'Every account that is not disabled gets the same amount, with your reason in its credit history. This can\'t be undone in one step.'),
    field('Amount for each account', amount, el('div', { class: 'chips' }, [100, 200, 500, 1000].map((n) =>
      el('button', { type: 'button', class: 'btn small', onclick: () => { amount.value = n; draw(); } }, number(n))))),
    field('Reason', note), error,
    el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'), confirm));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  draw();
  dialog.showModal();
}

export async function credits(ctx) {
  const s = ctx.state.credits;
  const data = await api('/api/admin/credits?' + new URLSearchParams({ reason: s.reason, q: s.q }));
  const sum = data.summary;
  const give = async () => creditsDialog((await api('/api/admin/users')).users, ctx.draw);
  return [
    el('div', { class: 'tiles' },
      tile('Held by users now', number(sum.held), 'what could still be spent'),
      tile('Spent on generations', number(sum.charged - sum.refunded), `${number(sum.charged)} charged · ${number(sum.refunded)} refunded`),
      tile('Given at sign-up', number(sum.welcome)),
      tile('Given by admins', number(sum.granted), 'grants minus removals')),
    el('div', { class: 'toolbar' },
      segmented([{ id: '', label: 'All' }, { id: 'generation', label: 'Charges' }, { id: 'refund', label: 'Refunds' },
        { id: 'admin grant', label: 'By admins' }, { id: 'welcome', label: 'Sign-up' }], s.reason, (v) => { s.reason = v; ctx.draw(); }),
      searchBox('Search user', s.q, (q) => { s.q = q; ctx.draw(); }),
      el('span', { class: 'push' }), exportLink('credits'),
      el('button', { class: 'btn small', onclick: () => everyoneDialog(ctx.draw) }, 'Give everyone credits'),
      el('button', { class: 'btn small primary', onclick: () => give().catch((e) => alert(e.message)) }, 'Give or take credits')),
    el('div', { class: 'card' }, table(['When', 'User', 'Credits', 'Reason', 'Job or note'],
      data.events.map((e) => [stamp(e.created), person(e.user_name, e.user_email), el('b', {}, (e.amount > 0 ? '+' : '') + number(e.amount)), REASON[e.reason] || e.reason, e.job_name || e.note || '']),
      { empty: 'No credit changes match.' })),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, 'The latest 300 changes. Export CSV gives the full history.'),
  ];
}

// ---------------------------------------------------------------- workflows

export async function workflows() {
  const report = await api('/api/admin/workflows');
  return [
    el('div', { class: 'card' }, table(
      ['Workflow', 'Type', 'File', 'Status', 'Presets', 'Jobs', 'Succeeded', 'Avg. time', 'Last used'],
      report.workflows.map((w) => [
        el('div', {}, w.title, w.description && el('div', { class: 'muted small' }, w.description)), w.kind, w.file,
        w.error ? el('div', {}, el('span', { class: 'pill failed' }, 'Can\'t be read'), el('div', { class: 'error small' }, w.error)) : el('span', { class: 'pill done' }, 'Ready'),
        w.presets ? 'Yes' : 'No', number(w.jobs), w.done + w.failed ? Math.round((100 * w.done) / (w.done + w.failed)) + '%' : '', span(w.avg_seconds), ago(w.last_used)]))),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, `Workflow files are read from ${report.folder}. Add a file there and it appears on the Create page.`),
  ];
}

// ---------------------------------------------------------------- system

// How a dated copy is put back, for the database the studio runs on.
const RESTORE = {
  sqlite: (b) => [
    'Stop the studio app (Ctrl+C in its window).',
    `Copy the scene_<date>.db you want from ${b.folder} over scene.db in ${b.storage}. Keep the old scene.db aside until you have checked.`,
    'Start the app again and sign in to check.'],
  postgres: (b) => [
    'Stop the studio app (Ctrl+C in its window).',
    'In a Command Prompt, as the postgres account: pg_restore -h localhost -U postgres --clean --if-exists -d scene ' + b.folder + '\\scene_<date>.dump',
    'Start the app again and sign in to check. docs/database.md has the full steps.'],
};

function backupsCard(b, ctx) {
  const now = el('button', { class: 'btn small primary', disabled: !b.on, onclick: async () => {
    now.disabled = true;
    now.textContent = 'Backing up…';
    try { await api('/api/admin/backups', { method: 'POST' }); ctx.draw(); } catch (e) { alert(e.message); now.disabled = false; now.textContent = 'Back up now'; }
  } }, 'Back up now');
  const databases = b.copies.filter((c) => c.what === 'database');
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Backups'), el('span', { class: 'pill ' + (b.on ? 'done' : 'failed') }, b.on ? 'On' : 'Off'), now),
    el('p', { class: 'muted small' },
      'A backup is a dated copy of the studio\'s database: the accounts, projects, canvases, jobs, credits, prices and settings. ',
      'With it goes a copy of config.json, which holds the server addresses and keys. ',
      'The finished pictures, videos and sounds are not in it; they stay in the outputs folder, and the database only names them.'),
    el('p', { class: 'muted small' }, b.on
      ? `A copy is made each time the app starts and once a day while it runs. The last ${b.keep} days are kept in ${b.folder}. A copy made today replaces today's earlier one.`
      : 'Backups are switched off on this installation (backup_keep is 0 in config.json).'),
    el('h3', {}, databases.length ? `Copies (${databases.length})` : 'Copies'),
    databases.length
      ? table(['Copy', 'Made', 'Size'], databases.slice(0, 14).map((c) => [c.name, stamp(c.made), bytes(c.bytes)]))
      : el('p', { class: 'muted' }, 'No copies yet.'),
    el('h3', {}, 'To put a copy back'),
    el('ol', { class: 'steps' }, (RESTORE[b.database_kind] || RESTORE.sqlite)(b).map((step) => el('li', {}, step))),
    el('p', { class: 'muted small' }, 'Everything done in the studio after that copy was made is lost, so restore only when the database is damaged or lost.'));
}

function storageCards(st, ctx) {
  const open = (item) => openViewer({ ...item, settings: {}, context: {}, workflow: '', user_name: item.user_name }, { base: '/api/admin/library', owner: true,
    actions: [{ label: 'Delete from their library', danger: true, run: (dialog) => {
      if (confirm(`Delete "${item.name}" from ${item.user_name}'s library? This frees ${bytes(item.size)} and can't be undone.`)) {
        api('/api/admin/library/' + item.id, { method: 'DELETE' }).then(() => { dialog.close(); ctx.draw(); }).catch((e) => alert(e.message));
      }
    } }] });
  const rs = st.render_server;
  return [
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Storage by user'), el('span', { class: 'muted small' }, 'finished work and saved assets on this machine')),
      table(['User', 'Finished work', 'Assets', 'Together'], st.people.map((p) => [person(p.name, p.email),
        `${bytes(p.bytes)} · ${number(p.files)} files`, `${bytes(p.asset_bytes)} · ${number(p.asset_files)}`, el('b', {}, bytes(p.bytes + p.asset_bytes))]), { empty: 'No users.' })),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Largest files'), el('span', { class: 'muted small' }, 'select one to watch it or delete it')),
      table(['Item', 'User', 'Size', 'Made'], st.largest.map((i) => [el('b', {}, i.name), person(i.user_name, i.user_email), bytes(i.size), ago(i.created)]),
        { onRow: (n) => open(st.largest[n]), empty: 'Nothing made yet.' })),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Files on the render PC'), el('span', { class: 'muted small' }, `${number(rs.total)} reference files`)),
      el('p', { class: 'muted small' }, 'Pictures, videos and sounds people added as references are sent to the render PC and stay in ComfyUI\'s input folder, ',
        'named scene_<code>_<name>. The studio can count them but cannot delete them: ComfyUI has no way to delete a file over its connection. ',
        'To free the space, delete old scene_ files in that folder on the render PC.'),
      rs.by_user.length
        ? table(['User', 'Files', 'Newest'], rs.by_user.map((u) => [person(u.user_name, u.user_email), number(u.files), ago(u.newest)]))
        : el('p', { class: 'muted' }, 'None recorded yet.')),
  ];
}

export async function system(ctx) {
  const [s, b, st] = await Promise.all([api('/api/admin/system'), api('/api/admin/backups'), api('/api/admin/storage')]);
  const sys = s.server.system || {};
  const gb = (v) => (v / 1024 ** 3).toFixed(1) + ' GB';
  const disk = s.storage;
  const check = el('button', { class: 'btn small', onclick: async () => {
    check.disabled = true;
    check.textContent = 'Checking…';
    try { await api('/api/admin/server/check', { method: 'POST' }); ctx.draw(); } catch (e) { alert(e.message); check.disabled = false; check.textContent = 'Check now'; }
  } }, 'Check now');
  return [el('div', { class: 'grid-2' },
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Render server'), el('span', { class: 'pill ' + (s.server.online ? 'done' : 'failed') }, s.server.online ? 'Online' : 'Offline'), check),
      facts([[s.server.online ? 'Online since' : 'Offline since', stamp(s.server.since)], ['Address', s.server.url], ['ComfyUI', sys.comfyui_version], ['Operating system', sys.os],
        ['Python', sys.python_version && sys.python_version.split(' ')[0]], ['PyTorch', sys.pytorch_version],
        ['ComfyUI queue', s.server.queue && `${s.server.queue.running} running · ${s.server.queue.pending} waiting (all clients)`]]),
      !s.server.online && el('p', { class: 'muted' }, 'It does not answer. Check that the render PC is on, Tailscale is connected and ComfyUI is started, and that the address in Settings is right.'),
      (s.server.devices || []).map((d) => el('div', {}, el('h3', {}, d.name.replace(/^cuda:\d+\s*/, '').split(' : ')[0] || d.type),
        meter('Video memory', d.vram_total - d.vram_free, d.vram_total, gb))),
      sys.ram_total && meter('System memory', sys.ram_total - sys.ram_free, sys.ram_total, gb)),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Scene.ai app')),
      facts([['Version', s.app.version], ['Running for', span(s.app.uptime_seconds)], ['Python', s.app.python], ['Operating system', s.app.os],
        ['ffmpeg (for long videos)', s.app.ffmpeg ? 'Available' : 'Missing: run the start script again'], ['Users online now', String(s.app.online_users)], ['Open browser tabs', String(s.app.open_connections)]])),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Disk')),
      meter('Disk', disk.disk_total - disk.disk_free, disk.disk_total, gb),
      facts([['Library files', bytes(disk.library)], ['Asset files', bytes(disk.assets)], ['Database', `${bytes(disk.database)} · ${disk.database_kind === 'postgres' ? 'PostgreSQL' : 'SQLite'}`],
        ['Free space', gb(disk.disk_free)], ['Folder', disk.folder]])),
    backupsCard(b, ctx),
    ...storageCards(st, ctx),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Records')),
      facts(Object.entries(s.counts).map(([k, v]) => [k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()), number(v)]))))];
}

// ---------------------------------------------------------------- audit log

export async function audit(ctx) {
  const s = ctx.state.audit;
  const entries = (await api('/api/admin/audit?' + new URLSearchParams({ q: s.q }))).entries;
  return [
    el('div', { class: 'toolbar' }, searchBox('Search person, action or target', s.q, (q) => { s.q = q; ctx.draw(); }),
      el('span', { style: 'margin-left:auto' }), exportLink('audit')),
    el('div', { class: 'card' }, table(['When', 'Who', 'Action', 'On', 'Details', 'Address'],
      entries.map((e) => [stamp(e.created), e.actor_name ? person(e.actor_name, e.actor_email) : el('span', { class: 'muted' }, 'Not signed in'),
        e.action, e.target, e.detail, el('span', { class: 'muted small' }, e.ip)]), { empty: 'No entries match.' })),
    el('p', { class: 'muted small', style: 'margin-top:10px' },
      'Sign-ins, failed sign-ins, new accounts and every admin action are recorded here. The latest 300 are shown; Export CSV gives all of them.'),
  ];
}

// ---------------------------------------------------------------- settings

// The message every user sees at the top of the studio.
function announcementCard(current) {
  const text = el('textarea', { rows: 2, maxlength: 300, placeholder: 'For example: Renders are down for maintenance until 6 pm.' }, current.text || '');
  let level = current.level || 'info';
  let hours = '4';
  const levelBox = el('div');
  const drawLevel = () => levelBox.replaceChildren(segmented([{ id: 'info', label: 'News' }, { id: 'warning', label: 'Warning' }], level, (v) => { level = v; drawLevel(); }));
  drawLevel();
  const length = el('select', { onchange: (e) => { hours = e.target.value; } },
    [['1', '1 hour'], ['4', '4 hours'], ['24', '1 day'], ['168', '1 week'], ['0', 'Until I remove it']].map(([v, label]) => el('option', { value: v, selected: v === hours }, label)));
  const notice = el('p', { class: 'notice' });
  const send = async (body) => {
    try {
      const shown = await api('/api/admin/announcement', { method: 'PUT', json: body });
      window.dispatchEvent(new Event('scene:announcement'));
      notice.className = 'notice ok';
      notice.textContent = shown.text ? (shown.until ? `Showing to everyone until ${stamp(shown.until)}.` : 'Showing to everyone until you remove it.') : 'Removed.';
      if (!shown.text) text.value = '';
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  };
  return el('div', { class: 'card narrow' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Announcement'), current.text ? el('span', { class: 'pill done' }, 'Showing') : null),
    el('p', { class: 'muted small' }, 'A short message every user sees at the foot of the studio, on every page. Each person can close it for their session.'),
    field('Message', text),
    el('div', { class: 'grid2' }, el('div', { class: 'field' }, el('div', { class: 'label' }, 'Kind'), levelBox), field('Show for', length)),
    notice,
    el('div', { class: 'row', style: 'margin-top:12px' },
      el('button', { class: 'btn primary', onclick: () => send({ text: text.value, level, hours: Number(hours) }) }, 'Publish'),
      current.text && el('button', { class: 'btn quiet danger', onclick: () => send({ text: '' }) }, 'Remove')));
}

export async function settings() {
  const [current, admins, news] = await Promise.all([api('/api/admin/settings'), api('/api/admin/admins'), api('/api/announcement')]);
  const url = el('input', { type: 'text', value: current.comfy_url });
  const signup = el('input', { type: 'checkbox', checked: current.allow_signup });
  const welcome = el('input', { type: 'number', min: 0, step: 1, value: current.signup_credits });
  const cap = el('input', { type: 'number', min: 0, step: 50, value: current.daily_cap });
  const mfa = el('input', { type: 'checkbox', checked: current.admin_mfa });
  const without = admins.admins.filter((a) => !a.mfa_enabled);
  const notice = el('p', { class: 'notice' });
  const save = async () => {
    try {
      await api('/api/admin/settings', { method: 'PUT', json: { comfy_url: url.value, allow_signup: signup.checked, signup_credits: welcome.value,
        daily_cap: cap.value || 0, admin_mfa: mfa.checked } });
      await refreshStatus();
      notice.className = 'notice ' + (store.online ? 'ok' : 'error');
      notice.textContent = store.online ? 'Saved. The render server is online.' : 'Saved, but the render server does not answer at this address.';
    } catch (err) { notice.className = 'notice error'; notice.textContent = err.message; }
  };
  return [el('div', { class: 'card narrow' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Render server')),
    field('ComfyUI address', url),
    el('h3', {}, 'Accounts'),
    el('label', { class: 'check', style: 'margin-top:0' }, signup, 'Anyone who can open this site may create an account'),
    el('label', { class: 'check' }, mfa, 'Admins must use two-step sign-in to open the admin console'),
    el('p', { class: 'muted small', style: 'margin:6px 0 0 25px' }, without.length
      ? `Without it now: ${without.map((a) => a.name).join(', ')}. They keep using the studio but can't open this console until they turn it on in Settings.`
      : 'Every admin has two-step sign-in.'),
    el('h3', {}, 'Credits'),
    field('Credits for a new account', welcome),
    field('Daily spending limit per user', cap),
    el('p', { class: 'muted small', style: 'margin-top:6px' }, 'The most credits one user may spend in 24 hours. 0 means no limit. Admins have none, and a user can be given their own limit (Users, select the user).'),
    el('p', { class: 'muted small', style: 'margin-top:8px' }, 'What each kind of work costs is set in the Pricing section.'),
    notice,
    el('button', { class: 'btn primary', style: 'margin-top:12px', onclick: save }, 'Save')),
  announcementCard(news)];
}
