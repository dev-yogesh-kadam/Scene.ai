// Settings: the signed-in user's own account. Installation settings are in the admin console.

import { api } from '../api.js';
import { el, field } from '../dom.js';
import { store } from '../store.js';

export function render(view) {
  const current = el('input', { type: 'password', autocomplete: 'current-password', required: true });
  const next = el('input', { type: 'password', autocomplete: 'new-password', required: true, minlength: 8 });
  const notice = el('p', { class: 'notice' });
  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Settings')),
    el('div', { class: 'narrow' },
      el('div', { class: 'card' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Account')),
        el('p', {}, store.user.name, el('span', { class: 'muted' }, ` · ${store.user.email} · ${store.user.role} · ${store.user.credits ?? 0} cr`)),
        el('form', { onsubmit: async (e) => {
          e.preventDefault();
          try {
            await api('/api/auth/password', { method: 'PUT', json: { current: current.value, new: next.value } });
            notice.className = 'notice ok';
            notice.textContent = 'Password changed. Other devices were signed out.';
            current.value = next.value = '';
          } catch (err) { notice.className = 'notice error'; notice.textContent = err.message; }
        } },
          el('div', { class: 'grid2' }, field('Current password', current), field('New password', next)),
          notice,
          el('button', { class: 'btn', style: 'margin-top:12px', type: 'submit' }, 'Change password'))),
      store.user.role === 'admin' && el('div', { class: 'card' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Administration')),
        el('p', { class: 'muted' }, 'Users, credits, the render server and every job are managed in the admin console.'),
        el('a', { class: 'btn', style: 'margin-top:12px', href: '#/admin' }, 'Open admin console'))));
}
