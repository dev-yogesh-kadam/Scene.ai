// The Assets page: saved characters, outfits, backgrounds and voices.

import { api } from '../api.js';
import { el, segmented } from '../dom.js';
import { TAGS, assetNotesDialog, assetThumb, saveAssetDialog } from '../components/assets.js';

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
      'Keep the characters, outfits, places, products and voices you reuse. On the Create page, press Saved in a reference box to use one. '
      + 'The agent knows every asset by its name: give each a clear name and a note on how to use it.'),
    grid);

  async function draw() {
    // Uploads are the files dropped into jobs, kept by the shared memory of each project; the rest were saved on purpose.
    filter.replaceChildren(segmented([{ id: '', label: 'All' }, ...TAGS.map((t) => ({ id: t, label: t[0].toUpperCase() + t.slice(1) })),
      { id: 'upload', label: 'Uploads', hint: 'Files you dropped into a job, kept with their project' }], tag,
    (t) => { tag = t; draw(); }));
    try {
      const assets = (await api('/api/assets')).assets.filter((a) => (tag === 'upload' ? a.origin === 'upload' : a.origin !== 'upload' && (!tag || a.tag === tag)));
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
        (asset.use_note || asset.about) && el('p', { class: 'small muted asset-about', title: asset.about || '' }, asset.use_note || asset.about),
        el('div', { class: 'row' },
          el('select', { class: 'small', onchange: retag }, TAGS.map((t) => el('option', { value: t, selected: t === asset.tag }, t[0].toUpperCase() + t.slice(1)))),
          el('button', { class: 'btn small', onclick: rename }, 'Rename'),
          el('button', { class: 'btn small', title: 'What it shows and how the agent should use it', onclick: () => assetNotesDialog(asset, draw) }, 'Notes'),
          asset.origin === 'upload' && el('button', { class: 'btn small', title: 'Save it to your assets, for every project',
            onclick: async () => { await api('/api/assets/' + asset.id, { method: 'PUT', json: { origin: 'saved' } }).catch((e) => alert(e.message)); draw(); } }, 'Keep'),
          el('button', { class: 'btn small quiet danger', onclick: remove }, 'Delete'))));
  }

  draw();
}
