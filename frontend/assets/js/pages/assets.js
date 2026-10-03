// The Assets page: saved characters, outfits, backgrounds and voices.

import { api } from '../api.js';
import { el, segmented } from '../dom.js';
import { TAGS, assetThumb, saveAssetDialog } from '../components/assets.js';

export function render(view) {
  let tag = '';
  const filter = el('div');
  const grid = el('div', { class: 'media-grid' });
  const file = el('input', { type: 'file', accept: 'image/*,video/*,audio/*', hidden: true, onchange: (e) => {
    if (e.target.files[0]) saveAssetDialog({ file: e.target.files[0], onSaved: draw });
    e.target.value = '';
  } });
  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Assets'), filter,
      el('button', { class: 'btn primary', onclick: () => file.click() }, 'Add asset'), file),
    el('p', { class: 'page-sub' },
      'Keep the characters, outfits, backgrounds and voices you reuse. On the Create page, press Saved in a reference box to use one.'),
    grid);

  async function draw() {
    filter.replaceChildren(segmented([{ id: '', label: 'All' }, ...TAGS.map((t) => ({ id: t, label: t[0].toUpperCase() + t.slice(1) }))], tag,
      (t) => { tag = t; draw(); }));
    try {
      const assets = (await api('/api/assets')).assets.filter((a) => !tag || a.tag === tag);
      grid.replaceChildren(...(assets.length ? assets.map(card) : [el('div', { class: 'empty', style: 'grid-column:1/-1' }, 'No assets here yet.')]));
    } catch (e) {
      grid.replaceChildren(el('p', { class: 'error' }, e.message));
    }
  }

  function card(asset) {
    const rename = async () => {
      const name = prompt('Name', asset.name);
      if (name && name.trim()) { await api('/api/assets/' + asset.id, { method: 'PUT', json: { name } }).catch((e) => alert(e.message)); draw(); }
    };
    const remove = async () => {
      if (!confirm(`Delete "${asset.name}" from your assets? This can't be undone.`)) return;
      await api('/api/assets/' + asset.id, { method: 'DELETE' }).catch((e) => alert(e.message));
      draw();
    };
    const retag = async (e) => { await api('/api/assets/' + asset.id, { method: 'PUT', json: { tag: e.target.value } }).catch((err) => alert(err.message)); draw(); };
    return el('div', { class: 'media' },
      el('div', { class: 'thumb plain' }, assetThumb(asset), el('span', { class: 'kind' }, asset.tag)),
      el('div', { class: 'meta' },
        el('div', { class: 'title', title: asset.name }, asset.name),
        el('div', { class: 'row' },
          el('select', { class: 'small', onchange: retag }, TAGS.map((t) => el('option', { value: t, selected: t === asset.tag }, t[0].toUpperCase() + t.slice(1)))),
          el('button', { class: 'btn small', onclick: rename }, 'Rename'),
          el('button', { class: 'btn small quiet danger', onclick: remove }, 'Delete'))));
  }

  draw();
}
