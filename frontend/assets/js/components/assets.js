// The library picker: a library item (something made or uploaded, in any project) for a reference slot or a message.
// (The saved assets of before are the kit of each project now: see kit.js.)

import { api } from '../api.js';
import { el } from '../dom.js';

function openDialog(...content) {
  const dialog = el('dialog', {}, ...content);
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Resolves with a library item (something made or uploaded, in any project) the user picks, or null. kinds: the
// kinds it may be, e.g. ['image', 'video']; all when not given.
export function pickLibraryItem(kinds = null) {
  return new Promise((resolve) => {
    let chosen = null;
    let timer = null;
    const grid = el('div', { class: 'asset-grid library-pick-grid' });
    const search = el('input', { type: 'search', placeholder: 'Search your library…', 'aria-label': 'Search your library',
      oninput: () => { clearTimeout(timer); timer = setTimeout(fill, 250); } });
    const dialog = openDialog(el('h2', {}, 'From your library'), search, grid,
      el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', onclick: () => dialog.close() }, 'Close')));
    dialog.addEventListener('close', () => resolve(chosen));
    async function fill() {
      let list = [];
      try { list = (await api('/api/library?q=' + encodeURIComponent(search.value.trim()))).items || []; } catch (e) { grid.replaceChildren(el('p', { class: 'error' }, e.message)); return; }
      list = list.filter((item) => !kinds || kinds.includes(item.kind)).slice(0, 60);
      grid.replaceChildren(...(list.length ? list.map((item) => el('button', { type: 'button', class: 'asset', onclick: () => { chosen = item; dialog.close(); } },
        el('div', { class: 'asset-thumb' }, item.kind === 'audio' ? el('span', { class: 'note' }, '♪')
          : el('img', { src: `/api/library/${item.id}/${item.kind === 'video' ? 'poster' : 'file'}`, alt: item.name, loading: 'lazy' })),
        el('div', { class: 'asset-name' }, item.name),
        el('div', { class: 'muted' }, item.project_name || item.kind)))
        : [el('p', { class: 'muted' }, search.value.trim() ? 'Nothing in your library matches that.' : 'Your library is empty.')]));
    }
    fill();
    search.focus();
  });
}
