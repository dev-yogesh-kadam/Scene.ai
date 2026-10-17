// The admin console's Skills section: create, edit and delete the recipes the agent follows. Skills are Markdown
// files on the server; a change takes effect on the next agent message, with no restart.

import { api } from '../../api.js';
import { el, field } from '../../dom.js';
import { table } from './shared.js';

// A modal to make a new skill or change one. On save it calls onSaved() so the list behind it refreshes.
function editor(skill, onSaved) {
  const isNew = !skill;
  const id = el('input', { type: 'text', value: skill ? skill.id : '', placeholder: 'short-film', spellcheck: 'false', disabled: !isNew });
  const title = el('input', { type: 'text', value: skill ? skill.title : '' });
  const desc = el('input', { type: 'text', value: skill ? skill.desc : '', placeholder: 'Use when… (one line, shown in the picker)' });
  const version = el('input', { type: 'text', value: skill ? skill.version : '1' });
  const words = el('input', { type: 'text', value: skill ? skill.words : '', spellcheck: 'false', placeholder: '\\b(film|story|scene)\\b' });
  const text = el('textarea', { rows: 14, spellcheck: 'false' }, skill ? skill.text : '');
  const notice = el('p', { class: 'notice' });
  async function save() {
    const payload = { id: id.value.trim(), title: title.value, desc: desc.value, version: version.value, words: words.value, text: text.value };
    try {
      if (isNew) await api('/api/admin/skills', { method: 'POST', json: payload });
      else await api('/api/admin/skills/' + encodeURIComponent(skill.id), { method: 'PUT', json: payload });
      dialog.close();
      onSaved();
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  }
  const dialog = el('dialog', { class: 'skill-editor' },
    el('h2', {}, isNew ? 'New skill' : 'Edit skill'),
    el('p', { class: 'muted small', style: 'margin-bottom:14px' }, 'The id is the /command and the file name. Trigger words are a regular expression; the skill is given to the agent when a message matches them.'),
    field('Id', id),
    field('Title', title),
    field('Description', desc),
    field('Trigger words (regular expression)', words),
    field('Version', version),
    field('Steps the agent follows', text),
    notice,
    el('div', { class: 'dialog-buttons' },
      el('button', { type: 'button', class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
      el('button', { type: 'button', class: 'btn primary', onclick: save }, 'Save')));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

async function del(skill, onDone) {
  if (!confirm(`Delete the skill “${skill.title}” (/${skill.id})? This cannot be undone.`)) return;
  try { await api('/api/admin/skills/' + encodeURIComponent(skill.id), { method: 'DELETE' }); onDone(); }
  catch (e) { alert(e.message); }
}

export async function skills(ctx) {
  const { skills: list } = await api('/api/admin/skills');
  const clip = (s) => (s && s.length > 48 ? s.slice(0, 48) + '…' : (s || ''));
  const rows = list.map((s) => [
    el('div', {}, el('b', {}, s.title), s.desc && el('div', { class: 'muted small' }, s.desc)),
    el('code', {}, '/' + s.id),
    'v' + s.version,
    el('code', { class: 'small muted' }, clip(s.words)),
    el('div', { class: 'skill-row-actions' },
      el('button', { class: 'btn small', onclick: () => editor(s, ctx.draw) }, 'Edit'),
      el('button', { class: 'btn small danger', onclick: () => del(s, ctx.draw) }, 'Delete')),
  ]);
  return [el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', { style: 'flex:1' }, 'Skills'),
      el('button', { class: 'btn primary small', onclick: () => editor(null, ctx.draw) }, 'New skill')),
    el('p', { class: 'muted small', style: 'margin:-6px 0 16px' }, 'Recipes the agent follows for a kind of work. Saved as files on the server; a change takes effect on the next message, no restart needed. Users call one by typing /id or from the skills box.'),
    table(['Skill', 'Command', 'Version', 'Trigger words', ''], rows, { empty: 'No skills yet. Add one with “New skill”.' })),
  ];
}
