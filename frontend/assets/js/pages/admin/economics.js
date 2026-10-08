// The admin console's Economics section: what each workflow earned in credits and what it cost to run, from real jobs.
// The cost is electricity only. It is for the studio's own eyes: none of it is shown to users.

import { api } from '../../api.js';
import { el, segmented } from '../../dom.js';
import { number, bytes, span, tile, table, exportLink } from './shared.js';

const rupees = (value) => (value == null ? 'Not measured' : (value < 0 ? '−₹' : '₹') + Number(Math.abs(value).toFixed(2)).toLocaleString());
const percent = (value) => (value == null ? '' : value + '%');

export async function economics(ctx) {
  const data = await api('/api/admin/economics?days=' + ctx.days);
  const t = data.totals;
  const none = el('span', { class: 'muted' }, 'Not measured');
  return [
    el('div', { class: 'toolbar' },
      segmented([7, 30, 90].map((d) => ({ id: d, label: `${d} days` })), data.days, (d) => { ctx.days = d; ctx.draw(); }),
      el('span', { class: 'push' }), exportLink('jobs')),
    el('div', { class: 'tiles' },
      tile('Value of credits used', rupees(t.revenue_inr), `${number(t.credits)} cr used · ${number(t.refunded)} cr refunded`),
      tile('Electricity', rupees(t.electricity_inr), `${span(t.run_seconds) || '0 s'} of rendering at ₹${data.electricity_inr_per_kwh} per kWh`),
      tile('Left after electricity', rupees(t.margin_inr), t.margin_percent == null ? 'No credits used yet' : `${t.margin_percent}% of the value`),
      tile('Runs that failed', t.failure_rate == null ? 'None yet' : t.failure_rate + '%', `${number(t.failed)} failed · ${number(t.done)} done · ${number(t.cancelled)} cancelled`)),
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'By workflow')),
      table(['Workflow', 'Done', 'Failed', 'Runs per result', 'Avg. render', 'Render per second made', 'Credits used', 'Value', 'Electricity', 'Left', 'Output'],
        data.workflows.map((w) => [
          el('div', {}, w.title, el('div', { class: 'muted small' }, w.id)), number(w.done),
          w.failed ? el('span', { class: 'error' }, `${number(w.failed)} · ${percent(100 - w.success_rate)}`) : '0',
          w.runs_per_success == null ? '' : String(w.runs_per_success), span(w.avg_seconds),
          w.render_ratio == null ? '' : span(w.render_ratio), number(w.credits), rupees(w.revenue_inr),
          w.electricity_inr == null ? none : rupees(w.electricity_inr), w.margin_inr == null ? none : el('b', {}, rupees(w.margin_inr)),
          w.output_bytes ? bytes(w.output_bytes) : '']),
        { empty: 'No jobs finished in this period.' })),
    el('p', { class: 'muted small', style: 'margin-top:10px' },
      'Value is credits used at the price of 1,000 credits; until credits are sold it is what the work would have earned. ' +
      'Electricity is the time each job ran, failed runs included, at the power of its server. Cooling, depreciation, storage and bandwidth are not counted. ' +
      'Runs per result: 1.08 means 108 runs were needed for 100 results. Jobs from before 5 October were priced by GPU time.'),
    data.unmeasured.length > 0 && el('p', { class: 'muted small' },
      `No power is set for ${data.unmeasured.join(' and ')}, so work done there shows as not measured. Set it in Pricing, under Servers.`),
  ];
}
