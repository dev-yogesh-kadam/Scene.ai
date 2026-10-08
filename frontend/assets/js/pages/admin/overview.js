// Admin overview: what needs attention, the headline numbers with trends, the live queue, charts and rankings.

import { api } from '../../api.js';
import { el, segmented } from '../../dom.js';
import { chartCard, sparkline, barList } from '../../components/charts.js';
import { number, span, ago, table } from './shared.js';

const LEVEL = { critical: 'Critical', serious: 'Problem', warning: 'Check' };
const DOT = { done: 'good', failed: 'critical', cancelled: 'warning', audit: 'neutral' };

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

function kpi(label, value, delta, trend) {
  return el('div', { class: 'tile kpi' },
    el('div', { class: 'tile-label' }, label), el('div', { class: 'tile-value' }, value), delta, trend && sparkline(trend));
}

export async function overview(ctx) {
  const o = await api('/api/admin/overview?days=' + ctx.days);
  const { current: now, previous: before, series, days } = o;
  const picker = segmented([7, 30, 90].map((d) => ({ id: d, label: `${d} days` })), days, (d) => { ctx.days = d; ctx.draw(); });

  const attention = o.attention.length
    ? el('div', { class: 'attention' }, o.attention.map((a) => el('button', { class: 'alert ' + a.level, onclick: () => ctx.go(a.tab) },
      el('span', { class: 'alert-level' }, LEVEL[a.level]), el('span', { class: 'alert-text' }, a.text), el('span', { class: 'muted small' }, 'Open'))))
    : el('div', { class: 'all-clear' }, el('span', { class: 'status-dot good' }), 'Nothing needs your attention right now.');

  const kpis = el('div', { class: 'tiles kpis' },
    kpi('Active users', number(now.active_users), change(now.active_users, before.active_users, days), series.active_users),
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

  const running = o.queue.running;
  const share = running && running.steps ? Math.round((100 * (Math.max(running.clip, 1) - 1 + running.step / running.steps)) / Math.max(running.clips, 1)) : 0;
  const queue = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Queue right now'),
      el('span', { class: 'muted small' }, o.server.online ? 'Render server online · ComfyUI ' + o.server.version : 'Render server offline'),
      el('button', { class: 'btn small quiet', onclick: () => ctx.go('jobs') }, 'All jobs')),
    running
      ? el('div', { class: 'job' },
        el('div', { class: 'job-head' }, el('span', { class: 'name' }, running.name), el('span', { class: 'pill running' }, 'Running')),
        el('div', { class: 'sub' }, `${running.user_name} · ${running.workflow} · started ${ago(running.started)}`),
        el('div', { class: 'bar' + (running.steps ? '' : ' busy') }, el('div', { style: running.steps ? `width:${share}%` : '' })),
        el('div', { class: 'sub' }, [running.clips > 1 && `Clip ${running.clip} of ${running.clips}`,
          running.steps ? `Step ${running.step} of ${running.steps}` : 'Starting', running.node].filter(Boolean).join(' · ')))
      : el('div', { class: 'empty' }, 'Nothing is rendering.'),
    o.queue.waiting.length > 0 && el('div', {},
      el('h3', {}, `Waiting (${o.queue.waiting_total})`),
      o.queue.waiting.map((j, i) => el('div', { class: 'feed-row' }, el('span', { class: 'muted' }, `${i + 1}.`),
        el('span', { class: 'feed-text' }, j.name, el('span', { class: 'muted' }, ` · ${j.user_name}`)),
        el('span', { class: 'muted small' }, 'added ' + ago(j.created))))));

  const activity = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Recent activity'), el('button', { class: 'btn small quiet', onclick: () => ctx.go('audit') }, 'Audit log')),
    o.activity.length
      ? o.activity.map((a) => el('div', { class: 'feed-row' }, el('span', { class: 'status-dot ' + DOT[a.kind] }),
        el('span', { class: 'feed-text' }, el('b', {}, a.who || 'Someone'), ' ', a.text), el('span', { class: 'muted small' }, ago(a.time))))
      : el('div', { class: 'empty' }, 'No activity yet.'));

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
      el('span', { class: 'muted small', style: 'margin-left:auto' }, 'Updated ' + new Date().toLocaleTimeString())),
    attention, kpis, secondary, el('div', { class: 'grid-2' }, queue, activity), charts, rankings,
  ];
}
