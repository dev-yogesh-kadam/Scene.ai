// Sharing a project: add people by email with a role, and see, change or remove who is in it. Opened from the project's
// page and from its canvas. The server decides what each role may do (sharing.py); this only offers what the user's
// own role lets them change.

import { api } from '../api.js';
import { ask, el, icon, initials } from '../dom.js';
import { store } from '../store.js';

const EMAIL = /[^\s,;<>()"']+@[^\s,;<>()"']+\.[^\s,;<>()"']+/g;
const RANK = { viewer: 1, creator: 2, manager: 3, owner: 4 };

// Resolves true when anyone was added, changed or removed, so the page can show the new list.
export function shareDialog({ projectId, projectName }) {
  return new Promise((resolve) => {
    let changed = false;
    let info = { members: [], roles: [], role: null };   // role: the user's own, once the list has come
    let pending = [];   // [{email, role}] typed or pasted, not added yet
    const typed = el('input', { type: 'text', placeholder: 'Type or paste email addresses', autocomplete: 'off',
      'aria-label': 'Email addresses',
      onkeydown: (e) => {
        if (['Enter', ',', ';', ' '].includes(e.key) && typed.value.trim()) { e.preventDefault(); take(typed.value); }
        else if (e.key === 'Backspace' && !typed.value && pending.length) { pending.pop(); draw(); }
      },
      onpaste: (e) => { const text = e.clipboardData.getData('text'); if (EMAIL.test(text)) { e.preventDefault(); take(text); } EMAIL.lastIndex = 0; },
      onblur: () => { if (typed.value.trim()) take(typed.value); } });
    const pendingList = el('div', { class: 'share-pending' });
    const note = el('p', { class: 'share-note muted small' });
    const error = el('p', { class: 'error notice' });
    const people = el('div', { class: 'share-people' });
    const addButton = el('button', { class: 'btn primary', type: 'button', onclick: add }, 'Add');
    const adder = el('div', { class: 'share-adder' },
      el('label', { class: 'label' }, 'Email address(es)'), typed, pendingList, note);
    const dialog = el('dialog', { class: 'share-dialog', 'aria-label': 'People in ' + projectName },
      el('div', { class: 'share-head' }, el('h2', {}, 'Add to ' + projectName),
        el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: () => dialog.close() }, '×')),
      adder, error, el('div', { class: 'dialog-buttons' }, el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Cancel'), addButton),
      el('h3', { class: 'share-sub' }, 'In this project'), people);
    dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(changed); });

    const mayManage = () => RANK[info.role] >= RANK.manager;
    const givable = () => info.roles.filter((r) => r.id !== 'manager' || info.role === 'owner');   // only the owner makes managers

    function take(text) {
      const found = (text.match(EMAIL) || []).map((e) => e.toLowerCase().replace(/[.]+$/, ''));
      EMAIL.lastIndex = 0;
      if (!found.length) { error.textContent = `"${text.trim()}" is not an email address.`; return; }
      error.textContent = '';
      for (const email of found) if (!pending.some((p) => p.email === email)) pending.push({ email, role: 'creator' });
      typed.value = '';
      draw();
    }

    function roleSelect(current, onPick, choices = givable().length ? givable() : [{ id: 'creator', label: 'Creator' }]) {
      return el('select', { class: 'small share-role', 'aria-label': 'Role', title: (choices.find((r) => r.id === current) || {}).about || '',
        onchange: (e) => onPick(e.target.value) },
        ...choices.map((r) => el('option', { value: r.id, selected: r.id === current, title: r.about }, r.label)));
    }

    function draw() {
      const looker = info.role && !mayManage();   // only seeing who is in it: nothing to add (shown until that is known)
      adder.classList.toggle('hidden', looker);
      addButton.classList.toggle('hidden', looker);
      addButton.disabled = !pending.length;
      addButton.textContent = pending.length > 1 ? `Add ${pending.length} people` : 'Add';
      pendingList.replaceChildren(...(pending.length ? [el('div', { class: 'muted small' }, pending.length === 1 ? '1 person' : `${pending.length} people`)] : []),
        ...pending.map((p) => el('div', { class: 'share-row' },
          el('span', { class: 'share-email grow' }, p.email),
          roleSelect(p.role, (role) => { p.role = role; }),
          el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + p.email, onclick: () => { pending = pending.filter((x) => x !== p); draw(); } }, '×'))));
      note.replaceChildren('Selected people get added to the whole project ', el('b', {}, projectName), ', all its modules included. They need an account here.');
      const me = store.user && store.user.id;
      people.replaceChildren(...info.members.map((m) => {
        const self = m.user_id === me;
        const canChange = mayManage() && m.role !== 'owner' && !self && (info.role === 'owner' || m.role !== 'manager');
        const label = (info.roles.find((r) => r.id === m.role) || { label: 'Owner' }).label;
        return el('div', { class: 'share-row member' },
          el('span', { class: 'share-avatar', 'aria-hidden': 'true' }, initials(m.name || m.email)),
          el('span', { class: 'grow share-who' }, el('b', {}, m.name + (self ? ' (you)' : '')), el('span', { class: 'muted small' }, m.email)),
          canChange ? roleSelect(m.role, (role) => change(m, role)) : el('span', { class: 'share-badge' + (m.role === 'owner' ? ' owner' : '') }, label),
          canChange && el('button', { class: 'icon-btn', type: 'button', title: 'Remove from the project', 'aria-label': 'Remove ' + m.email, onclick: () => remove(m) }, icon('trash')),
          self && m.role !== 'owner' && el('button', { class: 'btn small quiet', type: 'button', onclick: () => remove(m, true) }, 'Leave'));
      }));
    }

    async function load() {
      try { info = await api(`/api/projects/${projectId}/members`); draw(); } catch (e) { error.textContent = e.message; }
    }

    async function add() {
      if (typed.value.trim()) take(typed.value);
      if (!pending.length) return;
      addButton.disabled = true;
      try {
        const found = await api(`/api/projects/${projectId}/members`, { method: 'POST', json: { people: pending } });
        info.members = found.members;
        if (found.added.length) changed = true;
        pending = pending.filter((p) => found.problems.some((x) => x.email === p.email));   // what could not be added stays, with why
        error.replaceChildren(...found.problems.map((x) => el('div', {}, `${x.email}: ${x.problem}`)));
      } catch (e) { error.textContent = e.message; }
      draw();
    }

    async function change(member, role) {
      try { info.members = (await api(`/api/projects/${projectId}/members/${member.user_id}`, { method: 'PUT', json: { role } })).members; changed = true; }
      catch (e) { error.textContent = e.message; }
      draw();
    }

    async function remove(member, leaving = false) {
      const sure = await ask(leaving
        ? { title: `Leave ${projectName}?`, message: 'What you made there stays in the project. Its owner can add you again.', confirm: 'Leave', danger: true }
        : { title: `Remove ${member.name}?`, message: 'They no longer see the project. What they made there stays in it.', confirm: 'Remove', danger: true });
      if (!sure) return;
      try {
        info.members = (await api(`/api/projects/${projectId}/members/${member.user_id}`, { method: 'DELETE' })).members;
        changed = true;
        if (leaving) { dialog.close(); return; }
      } catch (e) { error.textContent = e.message; }
      draw();
    }

    document.body.append(dialog);
    dialog.showModal();
    typed.focus();
    draw();
    load();
  });
}
