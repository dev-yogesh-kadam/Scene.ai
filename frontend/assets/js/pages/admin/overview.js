// Admin overview: what needs attention, the headline numbers with trends, who is online, new accounts, the live queue
// and its controls, earnings against electricity, charts and rankings.

import { api } from '../../api.js';
import { el, segmented } from '../../dom.js';
import { chartCard, sparkline, barList } from '../../components/charts.js';
import { number, span, ago, table } from './shared.js';

const LEVEL = { critical: 'Critical', serious: 'Problem', warning: 'Check' };
const DOT = { done: 'good', failed: 'critical', cancelled: 'warning', audit: 'neutral' };
// The studio's pages, as a tab reports them, in the words of the menu.
const PAGE = { '#/home': 'Home', '#/projects': 'All projects', '#/library': 'Library', '#/create': 'Create', '#/canvas': 'Canvas',
  '#/timeline': 'Timeline', '#/assets': 'Assets', '#/settings': 'Settings', '#/admin': 'Admin console' };
const rupees = (value) => '₹' + Math.round(value || 0).toLocaleString();
const clock = (timestamp) => new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// "12% more than the 30 days before". `goodUp` says which direction is good news.
function change(now, before, days, goodUp = true) {
  if (now == null || before == null) return el('div', { class: 'delta muted' }, 'No earlier data to compare');
  if (!before) return el('div', { class: 'delta muted' }, now ? `Nothing in the ${days} days before` : 'No change');
  const percent = Math.round((100 * (now - before)) / before);
  if (percent === 0) return el('div', { class: 'delta muted' }, `Same as the ${days} days before`);
  const good = percent > 0 === goodUp;
  return el('div', { class: 'delta ' + (good ? 'good' : 'bad') },
    el('span', { class: 'arrow' }, percent > 0 ? '▲' : '▼'), ` ${Math.abs(percent)}% `, el('span', { class: 'muted' }, `vs the ${days} days before`));
}

function kpi(label, value, delta, trend, note) {
  return el('div', { class: 'tile kpi' },
    el('div', { class: 'tile-label' }, label), el('div', { class: 'tile-value' }, value), note && el('div', { class: 'tile-note' }, note),
    delta, trend && sparkline(trend));
}

export async function overview(ctx) {
  const o = await api('/api/admin/overview?days=' + ctx.days);
  const { current: now, previous: before, series, days } = o;
  const picker = segmented([7, 30, 90].map((d) => ({ id: d, label: `${d} days` })), days, (d) => { ctx.days = d; ctx.draw(); });
  const act = (request) => request.then(ctx.draw).catch((e) => alert(e.message));

  const attention = o.attention.length
    ? el('div', { class: 'attention' }, o.attention.map((a) => el('button', { class: 'alert ' + a.level, onclick: () => ctx.go(a.tab) },
      el('span', { class: 'alert-level' }, LEVEL[a.level]), el('span', { class: 'alert-text' }, a.text), el('span', { class: 'muted small' }, 'Open'))))
    : el('div', { class: 'all-clear' }, el('span', { class: 'status-dot good' }, ''), 'Nothing needs your attention right now.');

  const kpis = el('div', { class: 'tiles kpis' },
    kpi('Users who made something', number(now.active_users), change(now.active_users, before.active_users, days), series.active_users,
      `in the last ${days} days`),
    kpi('Items made', number(now.items), change(now.items, before.items, days), series.videos.map((v, i) => v + series.images[i])),
    kpi('Jobs that succeeded', now.success_rate == null ? 'No jobs' : now.success_rate + '%',
      change(now.success_rate, before.success_rate, days), series.done),
    kpi('GPU time', span(now.gpu_seconds), change(now.gpu_seconds, before.gpu_seconds, days), series.gpu_minutes),
    kpi('Credits spent', number(now.credits), change(now.credits, before.credits, days), series.credits));

  const secondary = el('div', { class: 'stat-row' }, [
    ['Jobs', number(now.jobs)], ['Failed', number(now.failed)], ['Average wait in queue', span(now.avg_wait) || '0 s'],
    ['Average render time', span(now.avg_run) || 'none yet'], ['New accounts', number(now.signups)],
    ['All users', number(o.totals.users)], ['All library items', number(o.totals.items)], ['Credits held by users', number(o.totals.credits_held)],
  ].map(([k, v]) => el('div', {}, el('span', { class: 'muted' }, k), el('b', {}, v))));

  // Who has the studio open now, where, and what they are making.
  const online = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Online now'), el('span', { class: 'muted small' }, o.online.length === 1 ? '1 person' : `${o.online.length} people`)),
    o.online.length
      ? o.online.map((p) => el('div', { class: 'feed-row' },
        el('div', { class: 'avatar small' }, (p.name[0] || '?').toUpperCase()),
        el('div', { class: 'feed-text' }, el('b', {}, p.name), p.role === 'admin' ? el('span', { class: 'muted small' }, ' · admin') : null,
          el('div', { class: 'muted small' }, [p.pages.map((page) => PAGE[page] || page).join(', ') || 'Opening the studio',
            p.tabs > 1 && `${p.tabs} tabs`, p.job && `${p.job.status === 'running' ? 'making' : 'waiting for'} "${p.job.name}"`].filter(Boolean).join(' · '))),
        el('span', { class: 'muted small' }, 'since ' + clock(p.since))))
      : el('div', { class: 'empty' }, 'Nobody has the studio open.'));

  // New accounts: whether anyone may sign up, how many came today, and a quick way to stop one.
  const s = o.signups;
  const signups = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'New accounts'),
      el('span', { class: 'muted small' }, `${s.today} in the last 24 hours` + (s.per_day ? ` · ${s.per_day} a day allowed from one address` : '')),
      el('button', { class: 'btn small' + (s.open ? '' : ' primary'), onclick: () => {
        if (s.open && !confirm('Close sign-up? Nobody new can create an account until you open it again. Existing accounts are not affected.')) return;
        act(api('/api/admin/settings', { method: 'PUT', json: { allow_signup: !s.open } }));
      } }, s.open ? 'Close sign-up' : 'Open sign-up')),
    el('p', { class: 'muted small', style: 'margin:-6px 0 8px' }, s.open ? 'Sign-up is open: anyone who finds the site can make an account.' : 'Sign-up is closed.'),
    s.recent.length
      ? s.recent.map((u) => el('div', { class: 'feed-row' },
        el('div', { class: 'feed-text' }, el('b', {}, u.name), u.disabled ? el('span', { class: 'pill failed', style: 'margin-left:6px' }, 'Disabled') : null,
          el('div', { class: 'muted small' }, [u.email, u.ip, `${u.jobs} job${u.jobs === 1 ? '' : 's'}`].filter(Boolean).join(' · '))),
        el('span', { class: 'muted small' }, ago(u.created)),
        el('button', { class: 'btn small quiet' + (u.disabled ? '' : ' danger'), onclick: () => {
          if (!u.disabled && !confirm(`Disable ${u.name}? They are signed out and can't sign in until you enable them again.`)) return;
          act(api('/api/admin/users/' + u.id, { method: 'PUT', json: { disabled: !u.disabled } }));
        } }, u.disabled ? 'Enable' : 'Disable')))
      : el('div', { class: 'empty' }, 'No accounts yet.'));

  const q = o.queue;
  const running = q.running;
  const share = running && running.steps ? Math.round((100 * (Math.max(running.clip, 1) - 1 + running.step / running.steps)) / Math.max(running.clips, 1)) : 0;
  const serverLine = o.server.online ? `Render server online since ${clock(o.server.since)} · ComfyUI ${o.server.version}` : `Render server offline since ${clock(o.server.since)}`;
  const check = el('button', { class: 'btn small quiet', title: 'Ask the render server now instead of waiting for the next refresh', onclick: async () => {
    check.disabled = true;
    check.textContent = 'Checking…';
    try {
      const found = await api('/api/admin/server/check', { method: 'POST' });
      check.textContent = found.online ? 'Online' : 'Still offline';
      setTimeout(ctx.draw, 900);
    } catch (e) { alert(e.message); check.disabled = false; check.textContent = 'Check now'; }
  } }, 'Check now');
  const queue = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Queue right now'),
      el('button', { class: 'btn small' + (q.paused ? ' primary' : ''), title: q.paused ? 'Let waiting jobs start again' : 'Waiting renders stay waiting; the one running finishes. Edits and motion graphics keep running.',
        onclick: () => act(api('/api/admin/queue', { method: 'PUT', json: { paused: !q.paused } })) }, q.paused ? 'Resume renders' : 'Pause renders'),
      el('button', { class: 'btn small quiet', onclick: () => ctx.go('jobs') }, 'All jobs')),
    el('div', { class: 'server-line' }, el('span', { class: 'dot ' + (o.server.online ? 'online' : 'offline') }), el('span', { class: 'muted small' }, serverLine), check),
    q.paused && el('div', { class: 'alert warning static' }, el('span', { class: 'alert-level' }, 'Paused'),
      el('span', { class: 'alert-text' }, 'Renders are paused. Jobs wait until you resume them; users see them as waiting.')),
    running
      ? el('div', { class: 'job' },
        el('div', { class: 'job-head' }, el('span', { class: 'name' }, running.name), el('span', { class: 'pill running' }, 'Running')),
        el('div', { class: 'sub' }, `${running.user_name} · ${running.workflow} · started ${ago(running.started)}`),
        el('div', { class: 'bar' + (running.steps ? '' : ' busy') }, el('div', { style: running.steps ? `width:${share}%` : '' })),
        el('div', { class: 'sub' }, [running.clips > 1 && `Clip ${running.clip} of ${running.clips}`,
          running.steps ? `Step ${running.step} of ${running.steps}` : 'Starting', running.node].filter(Boolean).join(' · ')))
      : el('div', { class: 'empty' }, 'Nothing is rendering.'),
    q.waiting.length > 0 && el('div', {},
      el('h3', {}, `Waiting (${q.waiting_total})`),
      q.waiting.map((j, i) => el('div', { class: 'feed-row' }, el('span', { class: 'muted' }, `${i + 1}.`),
        el('span', { class: 'feed-text' }, j.name, el('span', { class: 'muted' }, ` · ${j.user_name}`),
          el('div', { class: 'muted small' }, 'added ' + ago(j.created) + (j.priority ? ' · moved to the front' : ''))),
        i > 0 && el('button', { class: 'btn small quiet', title: 'Start this one next', onclick: () => act(api(`/api/admin/jobs/${j.id}/front`, { method: 'POST' })) }, 'To front'),
        el('button', { class: 'btn small quiet danger', onclick: () => {
          if (confirm(`Cancel "${j.name}"? ${j.user_name} gets the credits back.`)) act(api('/api/admin/jobs/' + j.id, { method: 'DELETE' }));
        } }, 'Cancel')))));

  const activity = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Recent activity'), el('button', { class: 'btn small quiet', onclick: () => ctx.go('audit') }, 'Audit log')),
    o.activity.length
      ? o.activity.map((a) => el('div', { class: 'feed-row' }, el('span', { class: 'status-dot ' + DOT[a.kind] }),
        el('span', { class: 'feed-text' }, el('b', {}, a.who || 'Someone'), ' ', a.text), el('span', { class: 'muted small' }, ago(a.time))))
      : el('div', { class: 'empty' }, 'No activity yet.'));

  // What each workflow earned against what its electricity cost, in this period.
  const money = o.economics;
  const top = Math.max(1, ...money.workflows.map((w) => Math.max(w.revenue_inr || 0, w.electricity_inr || 0)));
  const earnings = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Earnings and electricity'),
      el('span', { class: 'muted small' }, money.totals.revenue_inr
        ? `${rupees(money.totals.revenue_inr)} earned · ${rupees(money.totals.electricity_inr)} electricity · ${money.totals.margin_percent}% left`
        : `last ${days} days`),
      el('button', { class: 'btn small quiet', onclick: () => ctx.go('economics') }, 'Economics')),
    money.workflows.length
      ? [el('div', { class: 'earn-list' }, money.workflows.map((w) => el('div', { class: 'earn-row' + (w.margin_inr != null && w.margin_inr < 0 ? ' losing' : '') },
        el('div', { class: 'earn-name' }, el('b', {}, w.title), el('span', { class: 'muted small' }, `${number(w.done)} made`)),
        el('div', { class: 'earn-bars', title: `${rupees(w.revenue_inr)} earned, ${w.electricity_inr == null ? 'electricity not known' : rupees(w.electricity_inr) + ' electricity'}` },
          el('i', { class: 'earned', style: `width:${(100 * (w.revenue_inr || 0)) / top}%` }),
          el('i', { class: 'spent', style: `width:${(100 * (w.electricity_inr || 0)) / top}%` })),
        el('div', { class: 'earn-figure' }, w.margin_inr == null ? el('span', { class: 'muted' }, 'power not known') : rupees(w.margin_inr))))),
      el('div', { class: 'legend' }, el('span', {}, el('i', { class: 'swatch earned' }), 'Earned'), el('span', {}, el('i', { class: 'swatch spent' }), 'Electricity'),
        el('span', {}, 'Right: what is left'))]
      : el('div', { class: 'empty' }, `No finished jobs in the last ${days} days.`),
    money.unmeasured.length > 0 && el('p', { class: 'muted small' }, `The power of ${money.unmeasured.join(', ')} is not set (Pricing, Servers), so its electricity is not counted.`));

  const labels = o.calendar;
  const charts = el('div', { class: 'grid-2' },
    chartCard('Items made per day', 'Finished videos and images', { labels, format: number, series: [
      { name: 'Videos', color: 'var(--series-1)', values: series.videos }, { name: 'Images', color: 'var(--series-2)', values: series.images }] }),
    chartCard('Jobs per day by result', 'By the day the job was added', { labels, format: number, series: [
      { name: 'Done', color: 'var(--series-1)', values: series.done }, { name: 'Failed', color: 'var(--status-critical)', values: series.failed },
      { name: 'Cancelled', color: 'var(--chart-neutral)', values: series.cancelled }] }),
    chartCard('GPU minutes per day', 'Render time of finished jobs', { labels, format: (v) => number(Math.round(v * 10) / 10),
      series: [{ name: 'GPU minutes', color: 'var(--series-1)', values: series.gpu_minutes }] }),
    chartCard('Credits spent per day', 'Charges minus refunds', { labels, format: number,
      series: [{ name: 'Credits', color: 'var(--series-1)', values: series.credits }] }));

  const rankings = el('div', { class: 'grid-3' },
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Most active users'), el('span', { class: 'muted small' }, 'credits spent')),
      o.top_users.length
        ? barList(o.top_users.map((u) => ({ label: u.name, sub: `${u.jobs} jobs`, value: u.credits || 0, title: `${u.email} · GPU ${span(u.gpu_seconds)}` })), number)
        : el('div', { class: 'empty' }, 'No jobs in this period.')),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Workflows used')),
      table(['Workflow', 'Jobs', 'Succeeded', 'Avg. time'], o.top_workflows.map((w) => [
        w.workflow.split('/')[1].replace(/_/g, ' '), number(w.jobs),
        w.done + w.failed ? Math.round((100 * w.done) / (w.done + w.failed)) + '%' : '', span(w.avg_seconds)]), { empty: 'No jobs in this period.' })),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Why jobs failed'), el('button', { class: 'btn small quiet', onclick: () => ctx.go('jobs', { status: 'failed' }) }, 'Failed jobs')),
      o.failures.length
        ? o.failures.map((f) => el('div', { class: 'feed-row top' }, el('b', {}, f.jobs + '×'),
          el('span', { class: 'feed-text small' }, f.error || 'No error message'), el('span', { class: 'muted small' }, ago(f.last_seen))))
        : el('div', { class: 'empty' }, 'No failed jobs in this period.')));

  return [
    el('div', { class: 'toolbar' }, el('span', { class: 'muted' }, 'Period'), picker,
      o.announcement.text && el('button', { class: 'btn small quiet', title: 'Change it in Settings', onclick: () => ctx.go('settings') }, 'Announcement showing'),
      el('span', { class: 'muted small', style: 'margin-left:auto' }, 'Updated ' + new Date().toLocaleTimeString())),
    attention, kpis, secondary, el('div', { class: 'grid-2' }, online, signups), el('div', { class: 'grid-2' }, queue, activity),
    earnings, charts, rankings,
  ];
}
