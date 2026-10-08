// Cards for finished images and videos, and the viewer with its details panel.

import { api } from '../api.js';
import { still, el, duration, when } from '../dom.js';
import { store } from '../store.js';
import { saveAssetDialog } from './assets.js';

const title = (text) => String(text).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const fileSize = (bytes) => (bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + ' GB' : bytes >= 1e6 ? (bytes / 1e6).toFixed(1) + ' MB' : Math.round((bytes || 0) / 1e3) + ' KB');

// The prompt a generation was made with. Older items don't store it separately, so fall back to the longest text setting.
export function promptOf(item) {
  const settings = item.settings || {};
  if (settings.prompt != null) return settings.prompt;
  return Object.values(settings.values || {}).filter((v) => typeof v === 'string').sort((a, b) => b.length - a.length)[0] || '';
}

// The facts about a generation that are worth showing: [label, value] pairs, empty ones left out.
export function detailsOf(item, { owner } = {}) {
  const s = item.settings || {};
  const c = item.context || {};
  const made = new Date(item.created * 1000);
  const refs = Object.values(s.refs || {}).map((r) => r.name || r.comfy_name).filter(Boolean);
  return [
    owner && ['Made by', `${item.user_name} · ${item.user_email}`],
    ['Type', title(item.kind)],
    ['Workflow', s.workflow_title || title(item.workflow.split('/')[1])],
    ...Object.entries(s.options || {}).map(([k, v]) => [title(k), title(v)]),
    ['Resolution', c.width ? `${c.width} × ${c.height}` + (c.resolution ? ` (${c.resolution}p ${c.orientation || ''})` : '') : c.resolution ? c.resolution + 'p' : null],
    ['Length', c.duration ? (c.clips > 1 ? `${c.clips} clips of ${c.duration} s` : `${c.duration} s`) : null],
    ['Seed', c.seed != null ? String(c.seed) : null],
    ...(s.details || []).map(([k, v]) => [k, typeof v === 'boolean' ? (v ? 'On' : 'Off') : String(v)]),
    ['References', refs.join(', ')],
    ['Project', item.project_name],
    ['Date', made.toLocaleDateString([], { dateStyle: 'long' })],
    ['Time', made.toLocaleTimeString([], { timeStyle: 'short' })],
    ['Render time', item.seconds ? duration(item.seconds) : null],
    ['Credits', item.cost ? String(item.cost) : null],
    ['File', `${item.filename} · ${fileSize(item.size)}`],
    ['Generation ID', String(item.id)],
    ['Job ID', item.job_id],
  ].filter((row) => row && row[1] != null && row[1] !== '');
}

// base: where the file is served from. owner: show who made it (admin). actions: extra buttons.
export function openViewer(item, { base = '/api/library', owner = false, actions = [] } = {}) {
  const url = `${base}/${item.id}/file`;
  const media = item.kind === 'video' ? el('video', { src: url, controls: true, autoplay: true, loop: true })
    : item.kind === 'audio' ? el('audio', { src: url, controls: true, autoplay: true })
      : el('img', { src: url, alt: item.name });
  const promptText = promptOf(item);
  const copy = el('button', { class: 'btn small quiet', onclick: async () => {
    try { await navigator.clipboard.writeText(promptText); copy.textContent = 'Copied'; } catch (e) { copy.textContent = 'Copy failed'; }
    setTimeout(() => { copy.textContent = 'Copy'; }, 1500);
  } }, 'Copy');
  const dialog = el('dialog', { class: 'viewer' },
    el('div', { class: 'viewer-grid' },
      el('div', { class: 'viewer-media' }, media),
      el('aside', { class: 'viewer-panel' },
        el('div', { class: 'viewer-title' }, el('h2', {}, item.name), el('button', { class: 'icon-btn', title: 'Close', 'aria-label': 'Close', onclick: () => dialog.close() }, '×')),
        el('div', { class: 'viewer-scroll' },
          promptText && el('div', { class: 'viewer-section' }, el('div', { class: 'label-row' }, el('h3', {}, 'Prompt'), copy), el('p', { class: 'prose' }, promptText)),
          el('div', { class: 'viewer-section' }, el('h3', {}, 'Details'),
            el('dl', { class: 'facts' }, detailsOf(item, { owner }).flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])))),
        el('div', { class: 'viewer-actions' },
          el('a', { class: 'btn primary', href: url + '?download=true', download: item.filename }, 'Download'),
          actions.map((a) => el('button', { class: 'btn' + (a.danger ? ' danger' : ''), onclick: () => a.run(dialog) }, a.label))))));
  dialog.addEventListener('close', () => dialog.remove());
  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Open Create with this item as the first frame: an image as it is, a video's last frame.
async function useAsFirstFrame(item, button) {
  if (button) button.disabled = true;
  try {
    const ref = await api(`/api/library/${item.id}/reference`, { method: 'POST' });
    store.prefill = { slot: 'first_frame', ref, parent: item.id };
    location.hash = '#/create';
    return true;
  } catch (e) { alert(e.message); if (button) button.disabled = false; return false; }
}

// `manage` adds the library-only actions: move to a project, save as asset, delete.
export function mediaCard(item, { manage, projects = [], onChanged } = {}) {
  const fileUrl = `/api/library/${item.id}/file`;
  const thumb = still(fileUrl, item.kind, item.name);
  const sound = item.kind === 'audio';   // a sound can't be the first frame of a video
  const rerun = () => { store.rerun = item; location.hash = '#/create'; };
  const next = item.kind === 'video' ? 'Continue' : 'Use as first frame';
  const remove = async () => {
    if (!confirm(`Delete "${item.name}" from your library? This can't be undone.`)) return;
    try { await api('/api/library/' + item.id, { method: 'DELETE' }); onChanged(); } catch (e) { alert(e.message); }
  };
  const move = async (e) => {
    try {
      await api('/api/library/' + item.id, { method: 'PUT', json: { project_id: Number(e.target.value) || null } });
      onChanged();
    } catch (err) { alert(err.message); }
  };
  const edited = item.workflow.startsWith('edit/');   // a timeline export: there is no form to re-run
  const view = () => openViewer(item, { actions: [
    !edited && { label: 'Re-run', run: (dialog) => { dialog.close(); rerun(); } },
    !sound && { label: next, run: async (dialog) => { if (await useAsFirstFrame(item)) dialog.close(); } },
  ].filter(Boolean) });
  return el('div', { class: 'media' },
    el('div', { class: 'thumb', onclick: view }, thumb, el('span', { class: 'kind' }, item.kind)),
    el('div', { class: 'meta' },
      el('div', { class: 'title', title: item.name }, item.name),
      el('div', { class: 'sub' }, [item.summary, item.seconds && 'took ' + duration(item.seconds)].filter(Boolean).join(' · ') || when(item.created)),
      el('div', { class: 'row' },
        el('a', { class: 'btn small', href: fileUrl + '?download=true', download: item.filename }, 'Download'),
        !edited && el('button', { class: 'btn small', onclick: rerun, title: 'Open Create with the same settings' }, 'Re-run'),
        !sound && el('button', { class: 'btn small', onclick: (e) => useAsFirstFrame(item, e.currentTarget),
          title: item.kind === 'video' ? 'Start a new video on the last frame of this one' : 'Start a video on this image' }, next)),
      manage && el('div', { class: 'row' },
        el('select', { class: 'small', title: 'Project', onchange: move },
          el('option', { value: '' }, 'No project'),
          projects.map((p) => el('option', { value: p.id, selected: p.id === item.project_id }, p.name))),
        item.kind === 'image' && el('button', { class: 'btn small', onclick: () => saveAssetDialog({ generation: item }) }, 'Save as asset'),
        el('button', { class: 'btn small quiet danger', onclick: remove }, 'Delete'))));
}
