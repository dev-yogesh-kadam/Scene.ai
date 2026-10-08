// The project window: name a new project (and optionally write its brief), or rename one.

import { api } from '../api.js';
import { el, field } from '../dom.js';

// project: the one to rename; leave it out to create a new one. Resolves to the saved project, or null if cancelled.
export function projectDialog({ project } = {}) {
  return new Promise((resolve) => {
    let saved = null;
    const today = new Date().toLocaleDateString([], { day: 'numeric', month: 'short' });
    const name = el('input', { type: 'text', maxlength: 60, required: true, value: project ? project.name : 'Project ' + today });
    const brief = el('textarea', { rows: 4, placeholder: 'Style, characters, places, rules. The agent keeps these true in every shot.' });
    const error = el('p', { class: 'error notice' });
    const submit = el('button', { class: 'btn primary', type: 'submit' }, project ? 'Save' : 'Create project');
    const cancel = el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Cancel');
    // While a request is running the window cannot be closed, so its result is never lost.
    const busy = (on) => { submit.disabled = cancel.disabled = on; };
    const dialog = el('dialog', { class: 'project-dialog', oncancel: (e) => { if (submit.disabled) e.preventDefault(); } },
      el('form', { method: 'dialog', onsubmit: async (e) => {
        e.preventDefault();
        busy(true);
        try {
          if (project) {
            await api('/api/projects/' + project.id, { method: 'PUT', json: { name: name.value } });
            saved = { ...project, name: name.value.trim() };
          } else {
            // Created once: if only the brief failed, a second try saves the brief and makes no second project.
            if (!saved) {
              saved = await api('/api/projects', { method: 'POST', json: { name: name.value } });
              name.disabled = true;
              submit.textContent = 'Save brief';
              cancel.textContent = 'Skip the brief';
            }
            if (brief.value.trim()) await api('/api/boards/brief', { method: 'PUT', json: { project: saved.id, data: { text: brief.value } } });
          }
          dialog.close();
        } catch (err) {
          error.textContent = saved && !project ? 'The project was created, but its brief was not saved: ' + err.message : err.message;
          busy(false);
        }
      } },
        el('h2', {}, project ? 'Rename project' : 'New project'),
        el('p', { class: 'muted' }, project ? 'Its items, canvas and timeline stay as they are.'
          : 'A project keeps the shots, the canvas and the timeline of one piece of work together.'),
        field('Name', name),
        !project && field('Brief (optional)', brief),
        error,
        el('div', { class: 'dialog-buttons' },
          cancel, submit)));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(saved); });
    document.body.append(dialog);
    dialog.showModal();
    name.select();
  });
}
