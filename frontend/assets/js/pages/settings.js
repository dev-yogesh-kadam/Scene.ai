// Settings: the signed-in user's own account. Installation settings are in the admin console.

import { api } from '../api.js';
import { creditsText, el, field } from '../dom.js';
import { store } from '../store.js';
import { consoleAddress } from '../nav.js';

export function render(view) {
  const current = el('input', { type: 'password', autocomplete: 'current-password', required: true });
  const next = el('input', { type: 'password', autocomplete: 'new-password', required: true, minlength: 8 });
  const notice = el('p', { class: 'notice' });
  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Settings')),
    el('div', { class: 'narrow' },
      el('div', { class: 'card' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Account')),
        el('p', {}, store.user.name, el('span', { class: 'muted' }, ` · ${store.user.email} · ${store.user.role} · ${creditsText(store.user.credits)}`)),
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
      twoStep(),
      store.user.console && el('div', { class: 'card' },
        el('div', { class: 'card-head' }, el('h2', {}, 'Administration')),
        el('p', { class: 'muted' }, 'Users, credits, the render server and every job are managed in the admin console. It is a site of its own, with its own sign-in.'),
        el('a', { class: 'btn', style: 'margin-top:12px', href: consoleAddress(store.user), target: '_blank', rel: 'noopener' }, 'Open admin console'))));
}

// Two-step sign-in: after the password, a code from an authenticator app (Google Authenticator, 1Password, Authy…).
function twoStep() {
  const card = el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Two-step sign-in')),
    el('p', { class: 'muted' }, 'Loading…'));
  const notice = el('p', { class: 'notice' });
  const fail = (err) => { notice.className = 'notice error'; notice.textContent = err.message; };
  const show = (...body) => { notice.textContent = ''; card.replaceChildren(card.firstChild, ...body, notice); };
  const password = () => el('input', { type: 'password', autocomplete: 'current-password', required: true });
  const code = () => el('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 20, placeholder: '123456' });

  const off = () => {
    const pw = password();
    show(el('p', {}, 'Off. Turn it on and signing in also asks for a code from an app on your phone, so a stolen password is not enough.'),
      el('form', { onsubmit: async (e) => {
        e.preventDefault();
        try { adding(await api('/api/auth/mfa/setup', { method: 'POST', json: { password: pw.value } })); } catch (err) { fail(err); }
      } }, field('Your password', pw), el('button', { class: 'btn', style: 'margin-top:12px', type: 'submit' }, 'Turn on')));
  };

  const adding = ({ secret, uri }) => {
    const c = code();
    show(el('p', {}, 'In your authenticator app, add an account and type in this key (on this phone, the link opens the app):'),
      el('div', { class: 'secret' }, secret.match(/.{1,4}/g).join(' ')),
      el('p', { class: 'small' }, el('a', { href: uri }, 'Open in the authenticator app')),
      el('form', { onsubmit: async (e) => {
        e.preventDefault();
        try { saved((await api('/api/auth/mfa/enable', { method: 'POST', json: { code: c.value } })).recovery_codes); } catch (err) { fail(err); }
      } }, field('The code the app shows now', c), el('button', { class: 'btn primary', style: 'margin-top:12px', type: 'submit' }, 'Confirm and turn on')));
    c.focus();
  };

  const saved = (codes) => {
    show(el('p', {}, 'On. Keep these recovery codes somewhere safe: each signs you in once if you lose your phone. They are not shown again.'),
      el('div', { class: 'secret recovery-codes' }, codes.map((x) => el('span', {}, x))),
      el('div', { class: 'row', style: 'margin-top:12px' },
        el('button', { class: 'btn', onclick: () => navigator.clipboard.writeText(codes.join('\n')).then(() => { notice.className = 'notice ok'; notice.textContent = 'Copied.'; }) }, 'Copy codes'),
        el('button', { class: 'btn', onclick: load }, 'Done')));
  };

  const on = (state) => {
    const pw = password();
    const c = code();
    show(el('p', {}, 'On. ', el('span', { class: 'muted' }, `${state.recovery_left} recovery codes left.`)),
      el('form', { onsubmit: async (e) => {
        e.preventDefault();
        try { await api('/api/auth/mfa/disable', { method: 'POST', json: { password: pw.value, code: c.value } }); load(); } catch (err) { fail(err); }
      } }, el('div', { class: 'grid2' }, field('Your password', pw), field('A code from the app, or a recovery code', c)),
        el('button', { class: 'btn quiet danger', style: 'margin-top:12px', type: 'submit' }, 'Turn off')));
  };

  const load = () => api('/api/auth/mfa').then((state) => (state.enabled ? on(state) : off())).catch(fail);
  load();
  return card;
}
