// The pieces the agent's conversation is drawn with: replies in light markdown with small pictures of the items they
// name, rows that fold open ("Thought for 6s", "Worked 12s · Checked the result"), and the rows of the agent's work.
// Nothing the model wrote is ever put in the page as HTML: every word becomes a text node.

import { el, icon, still } from '../dom.js';

// "6s", "1m 20s".
export const span = (seconds) => {
  const s = Math.max(0, Math.round(seconds || 0));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};
// "0:04", the place of a frame in a clip.
export const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

const ITEM_URL = { item: (id) => `/api/library/${id}/file`, asset: (id) => `/api/assets/${id}/file` };

// An item or a saved asset named in a message: its picture and its name. onPick(table, id) when it is clicked.
export function chip(table, id, known, onPick) {
  return el('button', { type: 'button', class: 'md-chip', title: known.name, onclick: () => onPick(table, id) },
    el('span', { class: 'md-chip-thumb' }, still(ITEM_URL[table](id), known.kind, known.name)), el('span', { class: 'md-chip-name' }, known.name));
}

// One line of a reply: **bold**, *italic*, `code` and [[item:12]] / [[asset:3]].
function inline(text, chips, onPick) {
  const parts = [];
  const pattern = /\[\[(item|asset):(\d+)\]\]|\*\*([^*]+)\*\*|`([^`]+)`|(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])/g;
  let last = 0;
  let found;
  while ((found = pattern.exec(text))) {
    if (found.index > last) parts.push(document.createTextNode(text.slice(last, found.index)));
    if (found[1]) {
      const known = chips[`${found[1]}:${found[2]}`];
      if (known) parts.push(chip(found[1], Number(found[2]), known, onPick));
    } else if (found[3]) parts.push(el('b', {}, found[3]));
    else if (found[4]) parts.push(el('code', {}, found[4]));
    else if (found[5]) parts.push(el('i', {}, found[5]));
    last = pattern.lastIndex;
  }
  if (last < text.length) parts.push(document.createTextNode(text.slice(last)));
  return parts;
}

const LIST = /^\s*([-*•]|\d+[.)])\s+/;
const FENCE = /```csv[ \t]*\n([\s\S]*?)\n```/g;
const LIBRARY_LINK = /^\/api\/(library|assets)\/(\d+)\/file$/;

// One row of CSV: commas split cells, a cell in double quotes may hold commas ("" is a quote mark).
function csvRow(line) {
  const cells = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (quoted && c === '"' && line[i + 1] === '"') { cell += '"'; i += 1; }
    else if (c === '"') quoted = !quoted;
    else if (c === ',' && !quoted) { cells.push(cell.trim()); cell = ''; }
    else cell += c;
  }
  cells.push(cell.trim());
  return cells;
}

// A cell of a table: a link to one of the user's library items (or saved assets) shows its picture — a video its
// poster, found when the file itself is not a picture; anything else is text. Only the studio's own links are shown.
function tableCell(text) {
  const found = LIBRARY_LINK.exec(text);
  if (!found) return el('td', {}, text);
  const img = el('img', { src: text, alt: '', loading: 'lazy' });
  img.addEventListener('error', () => {
    if (found[1] === 'library' && !img.dataset.poster) { img.dataset.poster = '1'; img.src = `/api/library/${found[2]}/poster`; }
    else img.replaceWith(el('a', { href: text, target: '_blank', rel: 'noopener' }, 'open'));
  });
  return el('td', { class: 'md-cell-media' }, el('a', { href: text, target: '_blank', rel: 'noopener', title: text }, img));
}

function table(csv) {
  const [head, ...rows] = csv.split('\n').filter((line) => line.trim()).map(csvRow);
  return el('div', { class: 'md-table' }, el('table', {},
    el('thead', {}, el('tr', {}, (head || []).map((h) => el('th', {}, h)))),
    el('tbody', {}, rows.map((cells) => el('tr', {}, cells.map(tableCell))))));
}

// A reply as paragraphs, lists and ```csv tables. chips: {"item:12": {name, kind}} for the items it may name.
export function markdown(text, chips = {}, onPick = () => {}) {
  const out = [];
  const source = String(text || '').replace(/\r/g, '');
  let at = 0;
  for (const found of source.matchAll(FENCE)) {
    out.push(...prose(source.slice(at, found.index), chips, onPick), table(found[1]));
    at = found.index + found[0].length;
  }
  return [...out, ...prose(source.slice(at), chips, onPick)];
}

function prose(text, chips, onPick) {
  const out = [];
  for (const block of text.split(/\n{2,}/)) {
    let list = null;
    let paragraph = null;
    for (const line of block.split('\n')) {
      if (LIST.test(line)) {
        paragraph = null;
        const ordered = /^\s*\d/.test(line);
        if (!list || list.ordered !== ordered) {
          list = { ordered, node: el(ordered ? 'ol' : 'ul') };
          out.push(list.node);
        }
        list.node.append(el('li', {}, inline(line.replace(LIST, ''), chips, onPick)));
      } else if (line.trim()) {
        list = null;
        if (!paragraph) { paragraph = el('p'); out.push(paragraph); } else paragraph.append(el('br'));
        paragraph.append(...inline(line, chips, onPick));
      }
    }
  }
  return out;
}

// A row that folds open: an icon, a title, a quieter word after it, and what it holds. `state` keeps whether it is open
// (state.open), so it stays open when the conversation is drawn again. Without a body it is a plain row.
export function fold({ glyph, title, sub = '', state = {}, body = null, className = '', onToggle = () => {} }) {
  const has = Boolean(body);
  const head = el(has ? 'button' : 'div', { class: 'fold-head', ...(has ? { type: 'button', 'aria-expanded': String(Boolean(state.open)),
    onclick: () => { state.open = !state.open; onToggle(); } } : {}) },
    glyph && icon(glyph), el('span', { class: 'fold-title' }, title), sub && el('span', { class: 'fold-sub' }, sub),
    has && el('span', { class: 'fold-caret', 'aria-hidden': 'true' }, icon(state.open ? 'down' : 'right')));
  return el('div', { class: 'fold ' + className + (state.open ? ' open' : '') }, head, has && state.open && el('div', { class: 'fold-body' }, body));
}

const WORK_ICONS = { attach: 'attachment', book: 'book', look: 'eye', skill: 'skill', retry: 'retry', skip: 'skip', plan: 'check',
  queue: 'queue', wait: 'clock', ready: 'film', check: 'check', warn: 'skip', status: 'wrench' };

// The rows of the agent's work. A thought among them is a fold of its own.
export function workRows(entries, states, redraw) {
  return entries.map((entry, i) => (entry.type === 'thought'
    ? fold({ glyph: 'bulb', title: `Thought for ${span(entry.seconds)}`, state: (states[i] = states[i] || {}), onToggle: redraw,
      body: entry.text ? el('p', { class: 'fold-text' }, entry.text) : null, className: 'nested' })
    : el('div', { class: 'work-row' }, icon(WORK_ICONS[entry.icon] || 'wrench'), el('span', {}, entry.text))));
}
