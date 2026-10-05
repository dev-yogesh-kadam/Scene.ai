// The cast of a project: the pictures (and voice) that must stay the same in every shot.
// A frame selected on the canvas is pinned to a role; every generation in the project then gets it as a reference.

import { api } from '../api.js';
import { el, still } from '../dom.js';

const FITS = { image: ['image', 'video'], audio: ['audio', 'video'] };   // what a role can be filled with

// projectId(): the current project or 0. selected(): the one frame selected on the canvas, or null.
// onChange(): the cast was changed. Returns the button that opens the editor, and the editor itself.
export function castEditor({ projectId = () => 0, selected = () => null, onChange = () => {} } = {}) {
  let roles = [];
  let cast = {};      // role id -> {id, name, kind}
  const count = el('span', { class: 'cast-count' });
  const button = el('button', { class: 'btn small quiet', title: 'The character, outfit and place that stay the same in every shot of this project',
    onclick: () => { box.classList.toggle('hidden'); draw(); } }, 'Cast', count);
  const box = el('div', { class: 'cast-box hidden' });

  async function load() {
    try {
      const found = await api('/api/cast?project=' + (projectId() || 0));
      roles = found.roles;
      cast = found.cast;
    } catch (e) { roles = []; cast = {}; }
    draw();
  }

  async function pin(role, id) {
    const pins = Object.fromEntries(Object.entries(cast).map(([r, p]) => [r, p.id]));
    if (id) pins[role] = id; else delete pins[role];
    try {
      await api('/api/boards/cast', { method: 'PUT', json: { project: projectId() || null, data: pins } });
      await load();
      onChange();
    } catch (e) { alert(e.message); }
  }

  function draw() {
    const pinned = Object.keys(cast).length;
    count.textContent = pinned ? String(pinned) : '';
    if (box.classList.contains('hidden')) return;
    const item = selected();
    box.replaceChildren(
      el('p', { class: 'muted small' }, 'Pin what must stay the same in every shot of this project. Select a frame on the canvas, then pin it to a role. '
        + 'Each generation that has a place for it gets it as a reference.'),
      ...roles.map((role) => {
        const now = cast[role.id];
        const fits = item && FITS[role.takes].includes(item.kind);
        return el('div', { class: 'cast-row' },
          el('span', { class: 'attach-thumb' }, now && still(`/api/library/${now.id}/file`, now.kind)),
          el('div', { class: 'cast-words' }, el('b', {}, role.label), el('span', { class: 'slate-text' }, now ? now.name : 'Not set')),
          now
            ? el('button', { class: 'btn small quiet', onclick: () => pin(role.id, null) }, 'Clear')
            : el('button', { class: 'btn small', disabled: !fits,
              title: fits ? `Pin "${item.name}" here` : item ? `This needs ${role.takes === 'audio' ? 'a sound' : 'a picture'}` : 'Select a frame on the canvas first',
              onclick: () => pin(role.id, item.id) }, 'Pin selected'));
      }));
  }

  // refresh(): the selection changed. reload(): the project changed.
  return { button, box, refresh: draw, reload: load };
}
