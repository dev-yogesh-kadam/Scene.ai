// The admin console's Skills section: create, edit and delete the recipes the agent follows. Skills are Markdown
// files on the server; a change takes effect on the next agent message, with no restart.

import { api } from '../api.js';
import { el, field } from '../dom.js';
import { table } from './shared.js';

// A skill file as text: "key: value" lines, a line of three dashes, then the steps. Skills written for other tools come with
// a YAML header between two lines of dashes, sometimes two of them in a row: every header is read, the first value of a key
// wins (name, label, description and user_description stand in for id, title and desc). A plain Markdown file with no header
// works too: its name is the id, its first "# heading" the title, and all of it the steps.
function parseSkill(source, filename) {
  let text = String(source).replace(/\r\n/g, '\n').replace(/^\uFEFF/, '');
  const meta = {};
  const pairs = (block) => {
    for (const line of block.split('\n')) {
      const at = line.indexOf(':');
      const key = line.slice(0, at).trim().toLowerCase();
      if (at <= 0 || /\s/.test(key) || key in meta) continue;
      let value = line.slice(at + 1).trim();
      if (value.length > 1 && value[0] === value[value.length - 1] && '\'"'.includes(value[0])) value = value.slice(1, -1);
      meta[key] = value;
    }
  };
  const header = (block) => block.split('\n').every((l) => !l.trim() || l.includes(':'));
  if (text.startsWith('---\n')) text = text.slice(4);
  const cut = text.indexOf('\n---\n');
  if (cut >= 0 && header(text.slice(0, cut))) { pairs(text.slice(0, cut)); text = text.slice(cut + 5); }
  for (;;) {   // more headers straight after the first, or a lone separator
    text = text.replace(/^\n+/, '');
    if (!text.startsWith('---\n')) break;
    const body = text.slice(4);
    const end = body.indexOf('\n---\n');
    if (end >= 0 && body.slice(0, end).trim() && header(body.slice(0, end))) { pairs(body.slice(0, end)); text = body.slice(end + 5); } else text = body;
  }
  text = text.trim();
  const stem = (meta.id || meta.name || filename.replace(/\.(md|markdown|txt)$/i, '')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const heading = (text.match(/^#\s+(.+)$/m) || [])[1];
  const about = meta.desc || meta.user_description || meta.description || '';
  // a skill that says when it applies, in quotes ('when the user says "pocket motion v2"'), is triggered by those words
  const quoted = [...(meta.description || '').matchAll(/["\u201c]([^"\u201d]{4,60})["\u201d]/g)].map((m) => m[1].trim().replace(/[ .]+$/, ''))
    .filter((p, i, all) => p.split(/\s+/).length >= 2 && all.findIndex((q) => q.toLowerCase() === p.toLowerCase()) === i);
  const words = meta.words && meta.words !== '(?!)' ? meta.words
    : quoted.length ? '\\b(' + quoted.map((p) => p.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')).join('|') + ')\\b' : '';
  return { id: stem, title: meta.title || meta.label || heading || stem, desc: about.length > 160 ? about.slice(0, 160).replace(/\s+\S*$/, '') + '…' : about,
    version: meta.version || '1', words, text };
}

// Choose a .md file; it opens in the editor filled in, to look over and save. A skill with the same id is replaced.
function importFile(list, onSaved) {
  const picker = el('input', { type: 'file', accept: '.md,.markdown,.txt,text/markdown,text/plain', class: 'hidden' });
  picker.addEventListener('change', async () => {
    const file = picker.files[0];
    picker.remove();
    if (!file) return;
    if (file.size > 200000) { alert('That file is too large for a skill (200 KB at most).'); return; }
    editor(parseSkill(await file.text(), file.name), onSaved, { imported: true, ids: list.map((s) => s.id) });
  });
  document.body.append(picker);
  picker.click();
}

// A modal to make a new skill or change one. On save it calls onSaved() so the list behind it refreshes.
// imported: the skill comes from a file, so it is saved as a new one (or over the skill that has its id).
function editor(skill, onSaved, { imported = false, ids = [] } = {}) {
  const isNew = !skill || imported;
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
      if (isNew && !ids.includes(payload.id)) await api('/api/admin/skills', { method: 'POST', json: payload });
      else if (imported) await api('/api/admin/skills/' + encodeURIComponent(payload.id), { method: 'PUT', json: payload });
      else await api('/api/admin/skills/' + encodeURIComponent(skill.id), { method: 'PUT', json: payload });
      dialog.close();
      onSaved();
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  }
  const dialog = el('dialog', { class: 'skill-editor' },
    el('h2', {}, imported ? 'Skill from a file' : isNew ? 'New skill' : 'Edit skill'),
    imported && el('p', { class: 'notice' }, ids.includes(skill.id) ? `A skill with the id “${skill.id}” exists: saving replaces it.` : 'Look it over, add trigger words if the file had none, and save.'),
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
      el('button', { class: 'btn small', title: 'Add a skill from a Markdown file', onclick: () => importFile(list, ctx.draw) }, 'Upload .md'),
      el('button', { class: 'btn primary small', onclick: () => editor(null, ctx.draw) }, 'New skill')),
    el('p', { class: 'muted small', style: 'margin:-6px 0 16px' }, 'Recipes the agent follows for a kind of work. Saved as files on the server; a change takes effect on the next message, no restart needed. Users call one by typing /id or from the skills box.'),
    table(['Skill', 'Command', 'Version', 'Trigger words', ''], rows, { empty: 'No skills yet. Add one with “New skill”.' })),
  ];
}
