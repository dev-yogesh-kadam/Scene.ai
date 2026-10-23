// The project window: name a new project, or rename one.

import { api } from '../api.js';
import { el, field } from '../dom.js';

// project: the one to rename; leave it out to create a new one. parent: make a module inside that project instead (count:
// how many modules it has, for the default name); module: the one renamed is a module. Resolves to the saved project or
// module, or null if cancelled.
// canvas: rename a project's own canvas (the "Main canvas" module), not the project.
export function projectDialog({ project, parent = null, count = 0, module = false, canvas = false } = {}) {
  module = module || !!parent;
  return new Promise((resolve) => {
    let saved = null;
    const today = new Date().toLocaleDateString([], { day: 'numeric', month: 'short' });
    const name = el('input', { type: 'text', maxlength: 60, required: true, value: project ? project.name : parent ? 'Module ' + (count + 1) : 'Project ' + today });
    const error = el('p', { class: 'error notice' });
    const submit = el('button', { class: 'btn primary', type: 'submit' }, project ? 'Save' : module ? 'Create module' : 'Create project');
    const cancel = el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Cancel');
    // While a request is running the window cannot be closed, so its result is never lost.
    const busy = (on) => { submit.disabled = cancel.disabled = on; };
    const dialog = el('dialog', { class: 'project-dialog', oncancel: (e) => { if (submit.disabled) e.preventDefault(); } },
      el('form', { method: 'dialog', onsubmit: async (e) => {
        e.preventDefault();
        busy(true);
        try {
          if (project) {
            await api('/api/projects/' + project.id + (canvas ? '/canvas' : ''), { method: 'PUT', json: { name: name.value } });
            saved = { ...project, name: name.value.trim() };
          } else {
            saved = await api('/api/projects', { method: 'POST', json: { name: name.value, parent_id: parent ? parent.id : null } });
          }
          dialog.close();
        } catch (err) {
          error.textContent = err.message;
          busy(false);
        }
      } },
        el('h2', {}, project ? (canvas ? 'Rename canvas' : module ? 'Rename module' : 'Rename project') : module ? `New module in ${parent.name}` : 'New project'),
        el('p', { class: 'muted' }, project ? 'Its items, canvas and timeline stay as they are.'
          : module ? 'A module is a canvas of its own, with its own timeline and agent tabs, using the project\'s kit.'
            : 'A project keeps the shots, the canvas and the timeline of one piece of work together.'),
        field('Name', name),
        error,
        el('div', { class: 'dialog-buttons' },
          cancel, submit)));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(saved); });
    document.body.append(dialog);
    dialog.showModal();
    name.select();
  });
}
