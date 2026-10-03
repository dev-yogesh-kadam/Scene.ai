// Small chart kit for the admin console: column charts, sparklines, bar lists and meters.
// Plain DOM, no library. Colours come from the --series-* and --status-* tokens in app.css.

import { el } from '../dom.js';

const SVG = 'http://www.w3.org/2000/svg';

function niceMax(value) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 5, 10].map((m) => m * power).find((m) => m >= value);
}

const swatch = (color) => el('span', { class: 'swatch', style: `background:${color}` });

// A column per label, stacked when there are several series. Hover or focus a column for its values.
export function columnChart({ labels, series, format = String, height = 170 }) {
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + s.values[i], 0));
  const max = niceMax(Math.max(...totals));
  const tooltip = el('div', { class: 'chart-tip hidden' });
  const show = (i, column) => {
    tooltip.replaceChildren(
      el('div', { class: 'tip-title' }, labels[i]),
      ...series.map((s) => el('div', { class: 'tip-row' }, el('span', { class: 'tip-key', style: `background:${s.color}` }),
        el('b', {}, format(s.values[i])), el('span', { class: 'muted' }, s.name))),
      series.length > 1 && el('div', { class: 'tip-row' }, el('span', { class: 'tip-key' }), el('b', {}, format(totals[i])), el('span', { class: 'muted' }, 'Total')));
    tooltip.classList.remove('hidden');
    const left = column.offsetLeft + column.offsetWidth / 2;
    tooltip.style.left = Math.min(Math.max(left, 80), column.parentElement.offsetWidth - 80) + 'px';
  };
  const hide = () => tooltip.classList.add('hidden');
  // Label a handful of columns so the axis stays readable at 90 days.
  const every = Math.ceil(labels.length / 6);
  const short = (label) => label.slice(5);

  return el('div', { class: 'chart' },
    series.length > 1 && el('div', { class: 'legend' }, series.map((s) => el('span', {}, swatch(s.color), s.name))),
    el('div', { class: 'plot', style: `height:${height}px` },
      [1, 0.5, 0].map((t) => el('div', { class: 'grid-line', style: `bottom:${t * 100}%` }, el('span', {}, format(max * t)))),
      el('div', { class: 'cols', onpointerleave: hide },
        labels.map((label, i) => el('div', { class: 'col', tabindex: 0, 'aria-label': `${label}: ${format(totals[i])}`,
          onpointerenter: (e) => show(i, e.currentTarget), onfocus: (e) => show(i, e.currentTarget), onblur: hide },
        series.filter((s) => s.values[i] > 0).map((s) => el('div', { class: 'seg-bar', style: `height:${(100 * s.values[i]) / max}%;background:${s.color}` })))),
        tooltip)),
    el('div', { class: 'x-axis' }, labels.map((label, i) => el('span', {}, i % every === 0 || i === labels.length - 1 ? short(label) : ''))));
}

// The same numbers as rows, for people who prefer a table (and for values the bars can't label).
export function chartTable({ labels, series, format = String }) {
  return el('div', { class: 'table-wrap chart-table' }, el('table', {},
    el('tr', {}, el('th', {}, 'Day'), series.map((s) => el('th', {}, s.name))),
    labels.map((label, i) => el('tr', {}, el('td', {}, label), series.map((s) => el('td', {}, format(s.values[i]))))).reverse()));
}

// A card holding a chart, with a Chart / Table switch.
export function chartCard(title, subtitle, spec) {
  let table = false;
  const body = el('div');
  const button = el('button', { class: 'btn small quiet', onclick: () => { table = !table; draw(); } });
  const draw = () => {
    body.replaceChildren(table ? chartTable(spec) : columnChart(spec));
    button.textContent = table ? 'Show chart' : 'Show table';
  };
  draw();
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('div', { style: 'flex:1' }, el('h2', {}, title), el('div', { class: 'muted small' }, subtitle)), button), body);
}

// A tiny trend line for a stat tile. No axes: the tile's number is the value, this is the shape.
export function sparkline(values) {
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? 100 / (values.length - 1) : 100;
  const points = values.map((v, i) => `${(i * step).toFixed(2)},${(28 - (26 * v) / max).toFixed(2)}`).join(' ');
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 100 30');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'spark');
  svg.setAttribute('aria-hidden', 'true');
  const line = document.createElementNS(SVG, 'polyline');
  line.setAttribute('points', points);
  svg.append(line);
  return svg;
}

// Ranked horizontal bars: one hue, value at the end of each bar.
export function barList(rows, format = String) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return el('div', { class: 'bar-list' }, rows.map((r) => el('div', { class: 'bar-row', title: r.title || '' },
    el('div', { class: 'bar-name' }, r.label, r.sub && el('span', { class: 'muted small' }, ' ' + r.sub)),
    el('div', { class: 'bar-track' }, el('div', { class: 'bar-value', style: `width:${Math.max(1.5, (100 * r.value) / max)}%` })),
    el('div', { class: 'bar-number' }, format(r.value)))));
}

// A used / total meter with its numbers written out.
export function meter(label, used, total, format) {
  const share = total ? Math.min(100, (100 * used) / total) : 0;
  return el('div', { class: 'meter' },
    el('div', { class: 'meter-head' }, el('span', {}, label), el('span', { class: 'muted' }, `${format(used)} of ${format(total)} used (${Math.round(share)}%)`)),
    el('div', { class: 'bar-track' }, el('div', { class: 'bar-value' + (share > 90 ? ' high' : ''), style: `width:${share}%` })));
}
