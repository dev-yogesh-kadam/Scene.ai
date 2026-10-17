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

// The name on the browser tab: what is open (a project, a page), then the app.
export function tabTitle(name) { document.title = name ? `${name} · Scene.ai` : 'Scene.ai'; }

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
  memory: '<path d="M12 3.5 3.5 8 12 12.5 20.5 8z"/><path d="M3.5 12 12 16.5 20.5 12"/><path d="M3.5 16 12 20.5 20.5 16"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l9-11h-6z"/>',
  back: '<path d="M14.5 6 8.5 12l6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  image: '<path d="M4 5h16v14H4z"/><path d="M4 16l4.5-4.5 4 4 2.5-2.5 5 5"/><circle cx="15.5" cy="9.5" r="1.5"/>',
  video: '<path d="M3.5 6h12v12h-12z"/><path d="M15.5 10.5 20.5 8v8l-5-2.5"/>',
  audio: '<path d="M5 10v4M9 6v12M13 9v6M17 4v16M21 10v4"/>',
  title: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
  upscale: '<path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/>',
  // the agent's composer and approval card
  hand: '<path d="M8 12V6.5a1.5 1.5 0 0 1 3 0V11M11 10.5V5a1.5 1.5 0 0 1 3 0v5.5M14 10.5V6.5a1.5 1.5 0 0 1 3 0V14c0 3.6-2.4 6.5-6 6.5-2.6 0-4.2-1.4-5.4-3.6L4 13.5a1.4 1.4 0 0 1 2.3-1.6L8 14"/>',
  handvideo: '<path d="M7 13V7.5a1.4 1.4 0 0 1 2.8 0V11M9.8 10.5V6a1.4 1.4 0 0 1 2.8 0v5M12.6 11V8a1.4 1.4 0 0 1 2.8 0v6c0 3.3-2.2 6-5.5 6-2.4 0-3.8-1.3-4.9-3.3L3.5 14a1.3 1.3 0 0 1 2.1-1.5L7 14.5"/><path d="M17 4.5h3.5v3H17zM20.5 5.2 22 4.5v3l-1.5-.7"/>',
  forward: '<path d="M4 6.5v11l7-5.5zM12.5 6.5v11l7-5.5z"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  frame: '<path d="M8 3.5v17M16 3.5v17M3.5 8h17M3.5 16h17"/>',
  gem: '<path d="M7 4.5h10l3.5 5L12 20 3.5 9.5z"/><path d="M3.5 9.5h17M9.5 4.5 8 9.5l4 10.5 4-10.5-1.5-5"/>',
  bars: '<path d="M5 20V10M9.5 20V6M14 20v-8M18.5 20V4"/>',
  expand: '<path d="M14 4h6v6M20 4l-6 6M10 20H4v-6M4 20l6-6"/>',
  arrowup: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  // the agent's conversation: its work, its thoughts and what it made
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1.1 1.3 1.1 2.2h5c0-.9.5-1.7 1.1-2.2A6 6 0 0 0 12 3z"/>',
  wrench: '<path d="M15 4.5a4.5 4.5 0 0 0-4.3 5.8L4.6 16.4a1.9 1.9 0 0 0 2.7 2.7l6.1-6.1A4.5 4.5 0 0 0 19.5 9l-2.6 2.6-2.4-.6-.6-2.4L16.5 6A4.5 4.5 0 0 0 15 4.5z"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20v3H6.5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  skill: '<path d="M4.5 4.5h15v15h-15z"/><path d="M9 15l6-6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
  skip: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>',
  retry: '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4h4"/>',
  queue: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  branch: '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 8v8M18 11c0 3-3 4-6 4H6"/>',
  thumbup: '<path d="M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 2.5 2.4L12.8 10H18a2 2 0 0 1 2 2.3l-1.2 6a2 2 0 0 1-2 1.7H7"/>',
  thumbdown: '<path d="M7 13V4H4v9zM7 13l4 7a2 2 0 0 0 2.5-2.4L12.8 14H18a2 2 0 0 0 2-2.3l-1.2-6a2 2 0 0 0-2-1.7H7"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
  film: '<path d="M4 4h16v16H4z"/><path d="M8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  right: '<path d="M9 6l6 6-6 6"/>',
  target: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  copy: '<path d="M8.5 8.5h11v11h-11z"/><path d="M5.5 15.5h-1v-11h11v1"/>',
  attachment: '<path d="M8 12.5l6.5-6.5a3 3 0 0 1 4.2 4.2l-8 8a5 5 0 0 1-7-7l7.5-7.5"/>',
  upload: '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4.5 14.5v4a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-4"/>',
  menu: '<path d="M8 10l4 4 4-4"/>',
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

// The spill: a made item, far out of focus, lighting the top of a page. show() takes a library item id and kind,
// or nothing for the studio's own faint light. The picture is loaded first, so the light fades in instead of popping.
export function spill() {
  const node = el('div', { class: 'spill wait', 'aria-hidden': 'true' });
  let shown = null;
  const show = (id, kind) => {
    const url = id && kind !== 'audio' ? `/api/library/${id}/${kind === 'video' ? 'poster' : 'file'}` : '';
    if (url === shown) return;
    shown = url;
    node.classList.add('wait');
    const lit = () => { if (shown !== url) return; node.style.setProperty('--spill-image', url ? `url("${url}")` : ''); node.classList.remove('wait'); };
    if (!url) return lit();
    const picture = new Image();
    picture.onload = lit;
    picture.onerror = () => { shown = null; show(); };
    picture.src = url;
  };
  return { node, show };
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
