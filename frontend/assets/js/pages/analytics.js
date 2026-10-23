// A project's analytics (/analytics?id=<project>): what it spent and made in a period, by day and kind of thing made,
// and by module. Reached from the project's page; Back to project returns there.

import { api } from '../api.js';
import { el, icon, segmented } from '../dom.js';
import { columnChart } from '../components/charts.js';
import { go } from '../nav.js';

const PERIODS = [{ id: 'today', label: 'Today' }, { id: '7', label: 'Last 7 days' }, { id: '30', label: 'Last 30 days' }, { id: 'month', label: 'This month' }];
// One colour per kind of thing made, the same in the chart, the legend and a module's breakdown.
const COLOURS = { video: '#a8a8b2', voiceover: '#e5534b', music: '#e9a23b', image: '#3fb950', motion: '#a371f7', edit: '#2bb3a6', llm: '#3987e5' };
const number = (n) => Number(n || 0).toLocaleString();
const day = (t) => new Date(t * 1000).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });

export function render(view) {
  const id = Number(new URLSearchParams(location.search).get('id')) || 0;
  let period = (() => { try { return localStorage.getItem('scene.analytics.period') || '7'; } catch (e) { return '7'; } })();
  const body = el('div', { class: 'an-body' }, el('p', { class: 'muted' }, 'Loading…'));
  const periodBox = el('div');
  const exportLink = el('a', { class: 'btn', download: '' }, 'Export CSV');
  const drawPeriod = () => {
    periodBox.replaceChildren(segmented(PERIODS, period, (p) => {
      period = p;
      try { localStorage.setItem('scene.analytics.period', p); } catch (e) { /* no storage */ }
      drawPeriod();
      load();
    }));
    exportLink.href = `/api/projects/${id}/analytics.csv?period=${period}`;
  };
  drawPeriod();
  const back = el('a', { class: 'an-back', href: '/project?id=' + id }, icon('back'), 'Back to project');
  view.replaceChildren(el('div', { class: 'an-page' }, back,
    el('div', { class: 'an-head' }, el('h1', {}, 'Analytics'), el('div', { class: 'an-tools' }, periodBox, exportLink)), body));

  function tiles(d) {
    const change = d.change == null ? null : d.change;
    return el('div', { class: 'an-tiles' },
      el('div', { class: 'an-tile' }, el('span', { class: 'an-label' }, 'Project spend'),
        el('div', {}, el('b', { class: 'an-value' }, number(d.spend)), el('span', { class: 'muted' }, ' credits')),
        el('span', { class: 'small ' + (change == null ? 'muted' : change > 0 ? 'an-up' : 'an-down') },
          change == null ? (d.spend_before ? '' : 'Nothing spent the period before') : `${change > 0 ? '↑' : '↓'} ${Math.abs(change)}% vs previous period`)),
      el('div', { class: 'an-tile' }, el('span', { class: 'an-label' }, 'Generations'),
        el('div', {}, el('b', { class: 'an-value' }, number(d.generations)), el('span', { class: 'muted' }, d.generations === 1 ? ' generation' : ' generations')),
        el('span', { class: 'small muted' }, `${d.active_modules} active ${d.active_modules === 1 ? 'module' : 'modules'}`)),
      el('div', { class: 'an-tile' }, el('span', { class: 'an-label' }, 'Contributors'),
        el('div', {}, el('b', { class: 'an-value' }, number(d.contributors)), el('span', { class: 'muted' }, d.contributors === 1 ? ' person' : ' people')),
        el('span', { class: 'small muted' }, d.owner)));
  }

  function daily(d) {
    const total = d.types.reduce((sum, t) => sum + t.credits, 0);
    const series = d.types.filter((t) => t.credits).map((t) => ({ name: t.label, color: COLOURS[t.id], values: d.daily.map((x) => x[t.id]) }));
    return el('div', { class: 'card an-daily' },
      el('div', { class: 'an-chart' },
        el('h2', {}, 'Daily spend'), el('p', { class: 'muted small' }, 'Credits spent across this project, by the kind of thing made.'),
        series.length ? columnChart({ labels: d.days, series, format: number, height: 220 }) : el('div', { class: 'an-empty' }, 'No spend in this period yet.')),
      el('div', { class: 'an-legend' }, el('h3', {}, 'Spend by kind'),
        d.types.map((t) => el('div', { class: 'an-legend-row' }, el('span', { class: 'an-dot', style: `background:${COLOURS[t.id]}` }), el('span', { class: 'grow' }, t.label),
          el('b', {}, number(t.credits)), el('span', { class: 'muted small' }, `${t.generations} gen · ${total ? Math.round((100 * t.credits) / total) : 0}%`)))));
  }

  function modules(d) {
    const row = (m) => {
      const detail = el('div', { class: 'an-detail hidden' }, Object.keys(m.types).length
        ? d.types.filter((t) => m.types[t.id]).map((t) => el('div', { class: 'an-legend-row' }, el('span', { class: 'an-dot', style: `background:${COLOURS[t.id]}` }),
          el('span', { class: 'grow' }, t.label), el('b', {}, number(m.types[t.id].credits)), el('span', { class: 'muted small' }, `${m.types[t.id].generations} gen`)))
        : el('p', { class: 'muted small' }, 'Nothing spent or made in this period.'));
      const head = el('button', { class: 'an-row', 'aria-expanded': 'false', onclick: () => {
        const opened = detail.classList.toggle('hidden') === false;
        head.setAttribute('aria-expanded', String(opened));
      } },
        el('span', { class: 'an-number' }, String(m.number)),
        el('span', { class: 'an-name' }, el('b', {}, m.name), el('span', { class: 'muted small' }, m.first ? `1st generation: ${day(m.first)} · ${d.owner}` : 'Not generated yet')),
        el('span', { class: 'an-stat' }, el('span', {}, 'Generations'), el('b', {}, number(m.generations))),
        el('span', { class: 'an-stat' }, el('span', {}, 'Kinds'), el('b', {}, number(m.asset_types))),
        el('span', { class: 'an-stat' }, el('span', {}, 'Credits'), el('b', {}, number(m.credits))),
        el('span', { class: 'an-open', 'aria-hidden': 'true' }, '›'));
      return el('div', { class: 'an-module' }, head, detail);
    };
    return el('section', { class: 'an-modules' },
      el('h2', {}, 'Spend by module'), el('p', { class: 'muted small' }, 'The modules that spent the most first. Open one for what it spent on.'),
      d.modules.map(row));
  }

  async function load() {
    try {
      const d = await api(`/api/projects/${id}/analytics?period=${period}`);
      if (d.project.id !== id) return go(`/analytics?id=${d.project.id}`, { replace: true });   // a module's address shows its project
      document.title = `Analytics · ${d.project.name} · Scene.ai`;
      window.dispatchEvent(new CustomEvent('scene:crumbs', { detail: [{ label: 'Projects', href: '/projects' }, { label: d.project.name, href: '/project?id=' + id }, { label: 'Analytics' }] }));
      body.replaceChildren(
        el('div', { class: 'an-showing muted small' }, icon('clock'), 'Showing ', el('b', {}, `${day(d.start)} – ${day(d.end)}`)),
        tiles(d), daily(d), modules(d));
    } catch (e) {
      body.replaceChildren(el('p', { class: 'error' }, e.message), el('a', { class: 'btn', href: '/projects' }, 'All projects'));
    }
  }
  load();
  return null;
}
