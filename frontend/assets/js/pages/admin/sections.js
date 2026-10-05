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
  const note = el('input', { type: 'text', maxlength: 200, placeholder: 'Optional. Shown in the credit log, for example "Launch bonus"' });
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
    confirm.disabled = !person || value < 1 || (mode === 'take' && now === 0);
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
    el('p', { class: 'muted' }, 'The change is applied at once and recorded in the credit log and the audit log.'),
    people.length > 1 && field('User', who),
    el('div', { class: 'field' }, modeBox),
    field('Amount', amount, el('div', { class: 'chips' }, [100, 500, 1000, 5000].map((n) =>
      el('button', { type: 'button', class: 'btn small', onclick: () => { amount.value = n; draw(); } }, number(n))))),
    field('Note', note),
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
    !self && el('button', { class: 'btn small quiet danger', onclick: () => {
      if (u.disabled || confirm(`Disable ${u.name}? They are signed out and can't sign in until you enable them again.`)) put({ disabled: !u.disabled });
    } }, u.disabled ? 'Enable account' : 'Disable account'));
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
        u.disabled ? el('span', { class: 'pill failed' }, 'Disabled') : null),
      el('div', { class: 'tiles small-tiles' },
        tile('Credits', number(u.credits), `${number(u.spent)} spent`),
        tile('Jobs', number(u.jobs), `${d.stats.done} done · ${d.stats.failed} failed · ${d.stats.cancelled} cancelled`),
        tile('GPU time', span(d.stats.gpu_seconds) || '0 s'),
        tile('Library', number(u.generations), `${bytes(d.storage_bytes)} · ${d.assets} assets · ${d.projects} projects`)),
      userActions(ctx, u, () => { load(); ctx.draw(); }),
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
    panel.replace(
      el('div', { class: 'drawer-title' }, el('div', {}, el('b', {}, j.name), el('div', { class: 'muted' }, `${j.user_name} · ${j.user_email}`)), pill(j.status)),
      j.error && el('div', { class: 'alert critical static' }, el('span', { class: 'alert-level' }, 'Error'), el('span', { class: 'alert-text' }, j.error)),
      active && el('button', { class: 'btn small danger', onclick: () => {
        if (confirm(`Cancel "${j.name}"? The user's credits are refunded.`)) {
          api('/api/admin/jobs/' + j.id, { method: 'DELETE' }).then(() => { panel.close(); ctx.draw(); }).catch((e) => alert(e.message));
        }
      } }, 'Cancel this job'),
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
    return j.error || j.summary;
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

export async function system() {
  const s = await api('/api/admin/system');
  const sys = s.server.system || {};
  const gb = (v) => (v / 1024 ** 3).toFixed(1) + ' GB';
  const st = s.storage;
  return [el('div', { class: 'grid-2' },
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Render server'), el('span', { class: 'pill ' + (s.server.online ? 'done' : 'failed') }, s.server.online ? 'Online' : 'Offline')),
      facts([['Address', s.server.url], ['ComfyUI', sys.comfyui_version], ['Operating system', sys.os], ['Python', sys.python_version && sys.python_version.split(' ')[0]],
        ['PyTorch', sys.pytorch_version],
        ['ComfyUI queue', s.server.queue && `${s.server.queue.running} running · ${s.server.queue.pending} waiting (all clients)`]]),
      !s.server.online && el('p', { class: 'muted' }, 'It does not answer. Check that ComfyUI is started and the address in Settings is right.'),
      (s.server.devices || []).map((d) => el('div', {}, el('h3', {}, d.name.replace(/^cuda:\d+\s*/, '').split(' : ')[0] || d.type),
        meter('Video memory', d.vram_total - d.vram_free, d.vram_total, gb))),
      sys.ram_total && meter('System memory', sys.ram_total - sys.ram_free, sys.ram_total, gb)),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Scene.ai app')),
      facts([['Version', s.app.version], ['Running for', span(s.app.uptime_seconds)], ['Python', s.app.python], ['Operating system', s.app.os],
        ['ffmpeg (for long videos)', s.app.ffmpeg ? 'Available' : 'Missing: run the start script again'], ['Open browser connections', String(s.app.open_connections)]])),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Storage')),
      meter('Disk', st.disk_total - st.disk_free, st.disk_total, gb),
      facts([['Library files', bytes(st.library)], ['Asset files', bytes(st.assets)], ['Database', bytes(st.database)], ['Free space', gb(st.disk_free)], ['Folder', st.folder]])),
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

export async function settings() {
  const current = await api('/api/admin/settings');
  const url = el('input', { type: 'text', value: current.comfy_url });
  const signup = el('input', { type: 'checkbox', checked: current.allow_signup });
  const welcome = el('input', { type: 'number', min: 0, step: 1, value: current.signup_credits });
  const notice = el('p', { class: 'notice' });
  const save = async () => {
    try {
      await api('/api/admin/settings', { method: 'PUT', json: { comfy_url: url.value, allow_signup: signup.checked, signup_credits: welcome.value } });
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
    el('h3', {}, 'Credits'),
    field('Credits for a new account', welcome),
    el('p', { class: 'muted small', style: 'margin-top:8px' }, 'What each kind of work costs is set in the Pricing section.'),
    notice,
    el('button', { class: 'btn primary', style: 'margin-top:12px', onclick: save }, 'Save'))];
}
