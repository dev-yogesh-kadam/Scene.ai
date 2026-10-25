// The console's Roles section: the staff roles, what each may see and change in the console, and how many people have
// each. An admin changes a role, makes a new one (for the internal team's own tools, say) or deletes one no one has.
// Users get a role on the Users page. See backend/scene/staff.py.

import { api } from '../api.js';
import { el, field } from '../dom.js';
import { number } from './shared.js';

// One role: its name and what it is for, then a row per area of the console: See, and Change (which needs See).
function roleCard(role, areas, ctx, open) {
  const label = el('input', { type: 'text', value: role.label, maxlength: 40, disabled: role.fixed });
  const about = el('textarea', { rows: 2, maxlength: 300, disabled: role.fixed }, role.about);
  const read = new Set(role.read);
  const write = new Set(role.write);
  const notice = el('p', { class: 'notice' });
  const grid = el('div', { class: 'role-grid' });
  const drawGrid = () => grid.replaceChildren(
    el('span', { class: 'muted small' }, 'Area'), el('span', { class: 'muted small' }, 'See'), el('span', { class: 'muted small' }, 'Change'),
    ...areas.flatMap((a) => [
      el('span', {}, a.label),
      el('input', { type: 'checkbox', checked: read.has(a.id), disabled: role.fixed, 'aria-label': 'See ' + a.label,
        onchange: (e) => { if (e.target.checked) read.add(a.id); else { read.delete(a.id); write.delete(a.id); } drawGrid(); } }),
      el('input', { type: 'checkbox', checked: write.has(a.id), disabled: role.fixed, 'aria-label': 'Change ' + a.label,
        onchange: (e) => { if (e.target.checked) { write.add(a.id); read.add(a.id); } else write.delete(a.id); drawGrid(); } }),
    ]));
  drawGrid();
  const save = async () => {
    try {
      await api('/api/admin/roles/' + (role.id || 'new'), { method: 'PUT', json: { label: label.value, about: about.value, read: [...read], write: [...write] } });
      ctx.draw();
    } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  };
  const remove = async () => {
    if (!confirm(`Delete the role "${role.label}"?${role.built_in ? ' It is one the console comes with; it comes back only if you make it again.' : ''}`)) return;
    try { await api('/api/admin/roles/' + role.id, { method: 'DELETE' }); ctx.draw(); } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
  };
  return el('details', { class: 'card role-card', open },
    el('summary', { class: 'card-head' }, el('h2', {}, role.id ? role.label : 'New role'),
      role.id && el('span', { class: 'muted small' }, `${number(role.people)} ${role.people === 1 ? 'person' : 'people'}`),
      role.built_in && !role.fixed && el('span', { class: 'pill' }, 'Built in'), role.fixed && el('span', { class: 'pill' }, 'Can\'t be changed')),
    el('p', { class: 'muted small' }, role.fixed ? role.about : 'What people with this role see in the console, and what they may change there. Roles and Settings are for admins only.'),
    !role.fixed && el('div', { class: 'grid2' }, field('Name', label), field('What it is for', about)),
    !role.fixed && grid,
    notice,
    !role.fixed && el('div', { class: 'row', style: 'margin-top:12px' },
      el('button', { class: 'btn primary', onclick: save }, role.id ? 'Save' : 'Make the role'),
      role.id && el('button', { class: 'btn quiet danger', disabled: role.people > 0, title: role.people ? 'Give its people another role first' : '', onclick: remove }, 'Delete')));
}

export async function roles(ctx) {
  const d = await api('/api/admin/roles');
  const fresh = { id: '', label: '', about: '', read: ['overview'], write: [], built_in: false, fixed: false, people: 0 };
  return [
    el('p', { class: 'muted' }, 'Give your team the parts of the console their work needs. People get a role on the Users page.'),
    ...d.roles.map((r) => roleCard(r, d.areas, ctx, false)),
    roleCard(fresh, d.areas, ctx, false),
  ];
}
