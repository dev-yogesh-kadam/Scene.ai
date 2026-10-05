// The admin console's Pricing section: what credits are worth, the rate of each kind of work, each workflow's own
// pricing, the credit packages, and the servers with what they draw.

import { api } from '../../api.js';
import { el, field } from '../../dom.js';
import { number, table } from './shared.js';

const KINDS = [
  { id: 'image', label: 'Image' }, { id: 'video', label: 'Video' }, { id: 'audio', label: 'Audio' },
  { id: 'motion', label: 'Motion graphics' }, { id: 'overlay', label: 'Motion graphics over a video' }, { id: 'upscaler', label: 'Upscale' },
];
const trim = (value) => Number(Number(value).toFixed(2)).toLocaleString();
const rupees = (value) => '₹' + trim(value);

// A window for the fields of one row. fields: [{id, label, type: 'text' | 'number' | 'check' | 'choice', choices, hint}].
// save(values) and remove() return promises; a number left empty is sent as null.
function editDialog(title, about, fields, values, { save, remove }) {
  const inputs = {};
  const error = el('p', { class: 'error notice' });
  const control = (f) => {
    if (f.type === 'check') return el('label', { class: 'check' }, inputs[f.id] = el('input', { type: 'checkbox', checked: !!values[f.id] }), f.label);
    inputs[f.id] = f.type === 'choice'
      ? el('select', {}, f.choices.map((c) => el('option', { value: c.id, selected: c.id === (values[f.id] ?? '') }, c.label)))
      : el('input', { type: f.type, min: 0, step: 'any', style: 'width:100%', placeholder: f.hint || '', value: values[f.id] ?? '' });
    return field(f.label, inputs[f.id]);
  };
  const read = () => Object.fromEntries(fields.map((f) => [f.id,
    f.type === 'check' ? inputs[f.id].checked : f.type === 'number' ? (inputs[f.id].value.trim() === '' ? null : Number(inputs[f.id].value)) : inputs[f.id].value]));
  const run = (work) => work.then(() => dialog.close()).catch((e) => { error.textContent = e.message; });
  const dialog = el('dialog', {},
    el('h2', {}, title),
    about && el('p', { class: 'muted' }, about),
    el('div', { class: 'grid2' }, fields.filter((f) => f.type !== 'check').map(control)),
    fields.filter((f) => f.type === 'check').map(control),
    error,
    el('div', { class: 'dialog-buttons' },
      remove && el('button', { class: 'btn quiet danger', style: 'margin-right:auto', onclick: () => { if (confirm('Delete this? It can\'t be undone.')) run(remove()); } }, 'Delete'),
      el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
      el('button', { class: 'btn primary', onclick: () => run(save(read())) }, 'Save')));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

const PACKAGE = [
  { id: 'name', label: 'Name', type: 'text', hint: 'Starter' },
  { id: 'price_inr', label: 'Price (₹)', type: 'number' },
  { id: 'credits', label: 'Credits', type: 'number' },
  { id: 'bonus_credits', label: 'Bonus credits', type: 'number' },
  { id: 'active', label: 'Offered for sale', type: 'check' },
];
const SERVER = [
  { id: 'name', label: 'Name', type: 'text' },
  { id: 'role', label: 'What it does', type: 'text' },
  { id: 'cpu', label: 'CPU', type: 'text' },
  { id: 'gpu', label: 'GPU', type: 'text' },
  { id: 'vram_gb', label: 'Video memory (GB)', type: 'number' },
  { id: 'idle_power_w', label: 'Idle power (W)', type: 'number', hint: 'Not measured yet' },
  { id: 'generation_power_w', label: 'Average power while generating (W)', type: 'number', hint: 'Not measured yet' },
  { id: 'max_power_w', label: 'Maximum power (W)', type: 'number', hint: 'Not measured yet' },
  { id: 'preferred_workflows', label: 'Preferred for', type: 'text', hint: 'video, image, audio' },
  { id: 'supported_workflows', label: 'Can also run', type: 'text', hint: 'image' },
  { id: 'purchase_price_inr', label: 'Purchase price (₹)', type: 'number' },
  { id: 'purchase_date', label: 'Purchase date', type: 'text', hint: '2026-01-31' },
  { id: 'life_months', label: 'Expected life (months)', type: 'number' },
  { id: 'salvage_value_inr', label: 'Salvage value (₹)', type: 'number' },
  { id: 'productive_hours', label: 'Expected productive hours', type: 'number' },
  { id: 'renders', label: 'Generation jobs are recorded against this server', type: 'check' },
  { id: 'active', label: 'In use', type: 'check' },
];

export async function pricing(ctx) {
  const data = await api('/api/admin/pricing');
  const perJob = (kind) => data.per_job.includes(kind);
  const worth = (credits) => rupees((credits * data.inr_per_1000_credits) / 1000);
  const price = (credits) => `${number(credits)} cr · ${worth(credits)}`;

  // ---- what credits are worth, and the rate of each kind
  const value = el('input', { type: 'number', min: 0, step: 'any', value: data.inr_per_1000_credits });
  const power = el('input', { type: 'number', min: 0, step: 'any', value: data.electricity_inr_per_kwh });
  const rates = Object.fromEntries(KINDS.map((k) => [k.id, el('input', { type: 'number', min: 0, step: 'any', value: data.rates[k.id] })]));
  const notice = el('p', { class: 'notice' });
  const saveRates = async () => {
    try {
      await api('/api/admin/pricing', { method: 'PUT', json: { inr_per_1000_credits: value.value, electricity_inr_per_kwh: power.value,
        rates: Object.fromEntries(KINDS.map((k) => [k.id, rates[k.id].value])) } });
      ctx.draw();
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  };
  const ratesCard = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Rates')),
    el('p', { class: 'muted small' }, 'What a user pays follows what they asked for, never how long the render took: a flat price for an image, a price per second of the result for everything else.'),
    el('div', { class: 'grid2' },
      KINDS.map((k) => field(`${k.label} (credits per ${perJob(k.id) ? 'generation' : 'second'})`, rates[k.id])),
      field('Price of 1,000 credits (₹)', value)),
    el('p', { class: 'muted small', style: 'margin-top:8px' },
      `Now: an image costs ${price(data.rates.image)}, a 5-second video ${price(data.rates.video * 5)}, a minute of music ${price(data.rates.audio * 60)}.`),
    el('h3', {}, 'Electricity'),
    field('Price of electricity (₹ per kWh)', power),
    el('p', { class: 'muted small', style: 'margin-top:8px' }, 'Used for the running cost of each server below. It is never shown to users and does not change what they pay.'),
    notice,
    el('button', { class: 'btn primary', style: 'margin-top:12px', onclick: saveRates }, 'Save'));

  // ---- each workflow's own pricing
  const servers = [{ id: '', label: 'Any' }, ...data.servers.map((s) => ({ id: s.name, label: s.name }))];
  const rateText = (w) => [w.base ? `${trim(w.base)} cr` : null, w.per_second ? `${trim(w.per_second)} cr/s` : null].filter(Boolean).join(' + ') || 'Free';
  const own = (w) => w.credits_per_second != null || w.base_credits != null;
  const editWorkflow = (w) => editDialog(w.title, `${w.id}. Leave a rate empty to follow the rate for its type.`, [
    { id: 'credits_per_second', label: 'Credits per second', type: 'number', hint: perJob(w.kind) ? 'None' : `${trim(data.rates[w.kind])} (the ${w.kind} rate)` },
    { id: 'base_credits', label: 'Base credits per generation', type: 'number', hint: perJob(w.kind) ? `${trim(data.rates[w.kind])} (the ${w.kind} rate)` : 'None' },
    { id: 'resolution_multiplier', label: 'Resolution multiplier', type: 'number' },
    { id: 'quality_multiplier', label: 'Quality multiplier', type: 'number' },
    { id: 'preferred_server', label: 'Preferred server', type: 'choice', choices: servers },
    { id: 'fallback_servers', label: 'Fallback servers', type: 'text', hint: 'Names, separated by commas' },
    { id: 'enabled', label: 'Offered to users', type: 'check' },
  ], w, { save: (values) => api('/api/admin/pricing/workflow', { method: 'PUT', json: { workflow: w.id, ...values } }).then(ctx.draw) });
  const workflowsCard = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Workflows')),
    table(['Workflow', 'Type', 'Rate', 'Multiplier', 'One image, or 5 seconds', 'Preferred server', 'Status'],
      data.workflows.map((w) => [
        el('div', {}, w.title, el('div', { class: 'muted small' }, w.id)), w.kind,
        el('div', {}, rateText(w), el('div', { class: 'muted small' }, own(w) ? 'Its own rate' : 'The rate of its type')),
        w.multiplier === 1 ? '' : '× ' + trim(w.multiplier), price(w.example), w.preferred_server || el('span', { class: 'muted' }, 'Any'),
        el('span', { class: 'pill ' + (w.enabled ? 'done' : 'cancelled') }, w.enabled ? 'Offered' : 'Switched off')]),
      { onRow: (i) => editWorkflow(data.workflows[i]) }),
    el('p', { class: 'muted small', style: 'margin-top:10px' },
      'Select a workflow to give it its own rate or multipliers, or to switch it off. The server is recorded for the scheduler; jobs are not routed by it yet.'));

  // ---- credit packages
  const rowDialog = (list, what, fields, row) => editDialog(row ? row.name : 'New ' + what, null, fields, row || { active: true }, {
    save: (values) => api(`/api/admin/pricing/${list}` + (row ? '/' + row.id : ''), { method: row ? 'PUT' : 'POST', json: values }).then(ctx.draw),
    remove: row && (() => api(`/api/admin/pricing/${list}/${row.id}`, { method: 'DELETE' }).then(ctx.draw)),
  });
  const packagesCard = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Credit packages'),
      el('button', { class: 'btn small primary', onclick: () => rowDialog('packages', 'package', PACKAGE) }, 'Add a package')),
    table(['Package', 'Price', 'Credits', 'Bonus', 'Per 1,000 credits', 'Status'],
      data.packages.map((p) => [
        el('b', {}, p.name), rupees(p.price_inr), number(p.credits), p.bonus_credits ? '+' + number(p.bonus_credits) : '',
        p.credits + p.bonus_credits ? rupees((1000 * p.price_inr) / (p.credits + p.bonus_credits)) : '',
        el('span', { class: 'pill ' + (p.active ? 'done' : 'cancelled') }, p.active ? 'Offered' : 'Not offered')]),
      { onRow: (i) => rowDialog('packages', 'package', PACKAGE, data.packages[i]), empty: 'No packages yet.' }),
    el('p', { class: 'muted small', style: 'margin-top:10px' }, 'Packages are kept here for when payments are added. Until then credits are given by an admin.'));

  // ---- servers
  const hourly = (s) => (s.generation_power_w ? rupees((s.generation_power_w / 1000) * data.electricity_inr_per_kwh) + ' an hour' : el('span', { class: 'muted' }, 'Not measured'));
  const serversCard = el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Servers'),
      el('button', { class: 'btn small primary', onclick: () => rowDialog('servers', 'server', SERVER) }, 'Add a server')),
    table(['Server', 'Hardware', 'Power while generating', 'Electricity while generating', 'Preferred for', 'Status'],
      data.servers.map((s) => [
        el('div', {}, el('b', {}, s.name), el('div', { class: 'muted small' }, s.role)),
        el('div', {}, s.gpu + (s.vram_gb ? ` · ${trim(s.vram_gb)} GB` : ''), el('div', { class: 'muted small' }, s.cpu)),
        s.generation_power_w ? number(s.generation_power_w) + ' W' : el('span', { class: 'muted' }, 'Not measured'), hourly(s),
        s.preferred_workflows || el('span', { class: 'muted' }, 'Not set'),
        el('span', { class: 'pill ' + (s.active ? 'done' : 'cancelled') }, s.active ? (s.renders ? 'Renders jobs' : 'In use') : 'Not in use')]),
      { onRow: (i) => rowDialog('servers', 'server', SERVER, data.servers[i]), empty: 'No servers yet.' }),
    el('p', { class: 'muted small', style: 'margin-top:10px' },
      'Electricity only: cooling, depreciation, storage and failed runs are not counted here. Replace an assumed power with one measured at the wall.'));

  return [ratesCard, workflowsCard, packagesCard, serversCard];
}
