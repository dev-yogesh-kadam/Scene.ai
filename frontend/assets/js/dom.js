// Small DOM and formatting helpers.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  node.append(...children.flat().filter((c) => c != null && c !== false));
  return node;
}

// Line icons (24px grid, drawn with the text colour). The markup is fixed text from this file, never user input.
const ICONS = {
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  bookmark: '<path d="M6 4h12v17l-6-4-6 4z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.800-1-8-4.500-8-9V6z"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 8l-4 4 4 4M6 12h10"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.500 1.500M17.500 17.500L19 19M5 19l1.500-1.500M17.500 6.500L19 5"/>',
  moon: '<path d="M20 14.500A8 8 0 0 1 9.500 4 8 8 0 1 0 20 14.500z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  check: '<path d="M5 12.500l4.500 4.500L19 7.500"/>',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.75',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: 'icon', 'aria-hidden': 'true' })) svg.setAttribute(k, v);
  svg.innerHTML = ICONS[name] || '';
  return svg;
}

export function duration(seconds) {
  if (seconds == null) return '';
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
}

export function when(timestamp) {
  return new Date(timestamp * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function segmented(choices, current, onPick) {
  return el('div', { class: 'seg' }, choices.map((c) =>
    el('button', { type: 'button', class: String(c.id) === String(current) ? 'on' : '', title: c.hint || '',
      onclick: () => onPick(c.id) }, c.label)));
}

export function field(label, ...content) {
  return el('div', { class: 'field' }, el('div', { class: 'label' }, label), ...content);
}
