// Bulk generation, a tab of the canvas's side panel for admins: where the compare board opens (components/compare.js),
// for a new test or one run before. Free. See backend/scene/api/bulk.py.

import { api } from '../api.js';
import { el } from '../dom.js';
import { compareBoard } from './compare.js';

export function bulkPanel({ projectId, onQueued }) {
  const node = el('div', { class: 'panel-bulk' });
  const board = compareBoard({ projectId, onQueued });
  const when = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

  async function draw() {
    let runs = [];
    try { runs = (await api('/api/bulk/runs')).runs; } catch (e) { /* shown empty */ }
    node.replaceChildren(
      el('p', { class: 'muted small' }, 'Test and compare workflows: several prompts, many workflows, the same seed for all, on one board. '
        + 'Prompts are rows, workflows are columns. The results also come onto this canvas. Free. Admins only.'),
      el('button', { class: 'btn primary block', onclick: () => board.open() }, 'Open the compare board'),
      runs.length ? el('h4', { class: 'bulk-runs-head' }, 'Earlier runs') : null,
      ...runs.slice(0, 12).map((r) => el('button', { class: 'bulk-run', onclick: () => board.open(r.run) },
        el('span', { class: 'bulk-run-prompt' }, r.prompt || 'No prompt'),
        el('span', { class: 'muted small' }, `${when(r.created)} · ${r.cells} cells · ${r.done} made`
          + (r.failed ? ` · ${r.failed} failed` : '') + (r.queued || r.running ? ` · ${r.queued + r.running} to go` : '')))));
  }

  return { node, draw, focus: () => { const b = node.querySelector('button'); if (b) b.focus(); } };
}
