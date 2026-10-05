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

// Line icons (24px grid, drawn with the text colour): 1.6px stroke with rounded ends and corners.
// The markup is fixed text from this file, never user input.
const ICONS = {
  home: '<path d="M4 10.5 12 4l8 6.5V20H4z"/><path d="M9.5 20v-6h5v6"/>',
  folder: '<path d="M3.5 5.5h6l2 2.5h9v10.5h-17z"/>',
  play: '<path d="M7.5 5v14l11-7z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  grid: '<path d="M3.5 3.5h7v7h-7zM13.5 3.5h7v7h-7zM3.5 13.5h7v7h-7zM13.5 13.5h7v7h-7z"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><path d="M13 4h4v4h-4zM7 10h4v4H7zM15 16h4v4h-4z"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z"/>',
  logout: '<path d="M15 4h5v16h-5"/><path d="M10 8l-4 4 4 4M6 12h10"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  chevron: '<path d="M8 10l4-4 4 4M8 14l4 4 4-4"/>',
  pencil: '<path d="M14.5 5.5l4 4L8 20H4v-4z"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.8 13h9.4l.8-13"/>',
  chat: '<path d="M4 5h16v11H10l-5 4v-4H4z"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l9-11h-6z"/>',
  back: '<path d="M14.5 6 8.5 12l6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  image: '<path d="M4 5h16v14H4z"/><path d="M4 16l4.5-4.5 4 4 2.5-2.5 5 5"/><circle cx="15.5" cy="9.5" r="1.5"/>',
  video: '<path d="M3.5 6h12v12h-12z"/><path d="M15.5 10.5 20.5 8v8l-5-2.5"/>',
  audio: '<path d="M5 10v4M9 6v12M13 9v6M17 4v16M21 10v4"/>',
  title: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
  upscale: '<path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/>',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: 'icon', 'aria-hidden': 'true' })) svg.setAttribute(k, v);
  svg.innerHTML = ICONS[name] || '';
  return svg;
}

// A still of a made item, for a thumbnail: an image as it is, a video as its poster, a sound as a mark and its name.
// The poster is a small picture the server makes from the video, so a page of thumbnails doesn't start loading every video.
export function still(url, kind, name = '') {
  if (kind === 'video') return el('img', { src: url.replace(/\/file$/, '/poster'), alt: name, loading: 'lazy', draggable: 'false' });
  if (kind === 'audio') return el('div', { class: 'sound' }, icon('audio'), el('span', {}, name));
  return el('img', { src: url, alt: name, loading: 'lazy', draggable: 'false' });
}

// The running Gate: two brackets circling a frame while it is being made.
export function runningGate() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'run');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = '<rect width="100%" height="100%" pathLength="100"/>';
  return svg;
}

// Seconds as HH:MM:SS:FF at 24 frames a second.
export function timecode(seconds) {
  const frames = Math.round(seconds * 24);
  const two = (n) => String(n).padStart(2, '0');
  return [Math.floor(frames / 86400), Math.floor(frames / 1440) % 60, Math.floor(frames / 24) % 60, frames % 24].map(two).join(':');
}

export function duration(seconds) {
  if (seconds == null) return '';
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
}

// The first letters of a name's first two words, for a project that has no picture yet.
export const initials = (name) => name.trim().split(/\s+/).slice(0, 2).map((word) => [...word][0]).join('').toUpperCase();

// How long ago, in a few characters: "just now", "8h ago", "3d ago"; a date once it is over a month.
export function ago(timestamp) {
  const seconds = Date.now() / 1000 - timestamp;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
  if (seconds < 30 * 86400) return Math.floor(seconds / 86400) + 'd ago';
  return new Date(timestamp * 1000).toLocaleDateString([], { dateStyle: 'medium' });
}

export function when(timestamp) {
  return new Date(timestamp * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function segmented(choices, current, onPick) {
  return el('div', { class: 'seg' }, choices.map((c) =>
    el('button', { type: 'button', class: String(c.id) === String(current) ? 'on' : '', title: c.hint || '', 'aria-pressed': String(String(c.id) === String(current)),
      onclick: () => onPick(c.id) }, c.label)));
}

export function field(label, ...content) {
  return el('div', { class: 'field' }, el('div', { class: 'label' }, label), ...content);
}
