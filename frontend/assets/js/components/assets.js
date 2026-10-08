// Dialogs for saved assets: pick one for a reference slot, or save a new one.

import { api } from '../api.js';
import { el, field } from '../dom.js';

export const TAGS = ['character', 'outfit', 'background', 'prop', 'voice', 'other'];
const assetUrl = (asset) => `/api/assets/${asset.id}/file`;

export function assetThumb(asset) {
  if (asset.kind === 'image') return el('img', { src: assetUrl(asset), alt: asset.name, loading: 'lazy' });
  if (asset.kind === 'video') return el('video', { src: assetUrl(asset) + '#t=0.1', preload: 'metadata', muted: true });
  return el('span', { class: 'note' }, '♪');
}

function openDialog(...content) {
  const dialog = el('dialog', {}, ...content);
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Resolves with the chosen asset, or null if the dialog is closed.
export function pickAsset(kind) {
  return new Promise(async (resolve) => {
    let assets = [];
    try { assets = (await api('/api/assets?kind=' + kind)).assets; } catch (e) { alert(e.message); return resolve(null); }
    let chosen = null;
    const dialog = openDialog(
      el('h2', {}, 'Your saved assets'),
      assets.length
        ? el('div', { class: 'asset-grid' }, assets.map((asset) =>
          el('button', { type: 'button', class: 'asset', onclick: () => { chosen = asset; dialog.close(); } },
            el('div', { class: 'asset-thumb' }, assetThumb(asset)),
            el('div', { class: 'asset-name' }, asset.name),
            el('div', { class: 'muted' }, asset.tag))))
        : el('p', { class: 'muted' }, `No saved ${kind === 'audio' ? 'voices' : kind + 's'} yet. Add some on the Assets page, or press Save on a reference you dropped in.`),
      el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', onclick: () => dialog.close() }, 'Close')));
    dialog.addEventListener('close', () => resolve(chosen));
  });
}

// Save a file (from a reference box or a file picker) or a library item as an asset.
export function saveAssetDialog({ file, generation, onSaved }) {
  const name = el('input', { type: 'text', value: (file ? file.name.replace(/\.[^.]+$/, '') : generation.name).slice(0, 60) });
  const tag = el('select', {}, TAGS.map((t) => el('option', { value: t }, t[0].toUpperCase() + t.slice(1))));
  const error = el('p', { class: 'error notice' });
  const save = async () => {
    try {
      if (file) {
        const data = new FormData();
        data.append('file', file, file.name);
        data.append('name', name.value);
        data.append('tag', tag.value);
        await api('/api/assets', { method: 'POST', body: data });
      } else {
        await api('/api/assets', { method: 'POST', json: { generation_id: generation.id, name: name.value, tag: tag.value } });
      }
      dialog.close();
      onSaved && onSaved();
    } catch (e) { error.textContent = e.message; }
  };
  const dialog = openDialog(
    el('h2', {}, 'Save to your assets'),
    el('p', { class: 'muted' }, 'Saved assets can be picked in any reference box with the Saved button.'),
    field('Name', name), field('Type', tag), error,
    el('div', { class: 'dialog-buttons' },
      el('button', { class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
      el('button', { class: 'btn primary', onclick: save }, 'Save')));
  name.focus();
}
