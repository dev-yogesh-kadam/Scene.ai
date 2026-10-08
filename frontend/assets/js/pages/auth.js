// Sign in and create account.

import { api } from '../api.js';
import { el, field, icon } from '../dom.js';

const POINTS = [
  'Turn a prompt and a few reference images into video',
  'Chain clips into longer scenes that stay consistent',
  'Keep your characters, outfits and voices to reuse',
];

export async function renderAuth(root, onSignedIn) {
  let info = { first_run: false, signup_open: false };
  try { info = await api('/api/auth/state'); } catch (e) { /* show sign-in anyway */ }
  let mode = 'login';
  let second = null;   // {email, password} once the password was right and an authenticator code is asked for

  const draw = (message) => {
    if (second) return drawCode(message);
    const register = mode === 'register';
    const name = el('input', { type: 'text', autocomplete: 'name', placeholder: 'Your name' });
    const email = el('input', { type: 'email', autocomplete: 'email', required: true, placeholder: 'you@company.com' });
    const password = el('input', { type: 'password', required: true, minlength: register ? 8 : null,
      autocomplete: register ? 'new-password' : 'current-password', placeholder: register ? 'At least 8 characters' : 'Your password' });
    const error = el('p', { class: 'error notice' }, message || '');
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, register ? 'Create account' : 'Sign in');

    const form = el('form', { onsubmit: async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        const user = await api(register ? '/api/auth/register' : '/api/auth/login',
          { method: 'POST', json: { name: name.value, email: email.value, password: password.value } });
        onSignedIn(user);
      } catch (err) {
        if (!register && err.data && err.data.mfa_required) {
          second = { email: email.value, password: password.value };
          return draw();
        }
        error.textContent = err.message;
        submit.disabled = false;
      }
    } },
      register && field('Name', name),
      field('Email', email),
      field('Password', password),
      error, submit);

    page(el('h1', {}, register ? (info.first_run ? 'Set up Scene.ai' : 'Create your account') : 'Welcome back'),
      el('p', { class: 'muted' }, !register ? 'Sign in to your studio.' : info.first_run
        ? 'Create the first account. It becomes the admin of this installation.'
        : 'It takes a few seconds.'),
      form,
      info.signup_open && el('div', { class: 'auth-switch muted' },
        register ? 'Already have an account? ' : 'New here? ',
        el('button', { type: 'button', onclick: () => { mode = register ? 'login' : 'register'; draw(); } },
          register ? 'Sign in' : 'Create an account')));
    (register ? name : email).focus();
  };

  // The second step: a code from the authenticator app, or one of the recovery codes.
  const drawCode = (message) => {
    const code = el('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 20,
      placeholder: '123456' });
    const error = el('p', { class: 'error notice' }, message || '');
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, 'Sign in');
    const form = el('form', { onsubmit: async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        onSignedIn(await api('/api/auth/login', { method: 'POST', json: { ...second, code: code.value } }));
      } catch (err) {
        error.textContent = err.message;
        submit.disabled = false;
        code.select();
      }
    } }, field('Code', code), error, submit);
    page(el('h1', {}, 'Two-step sign-in'),
      el('p', { class: 'muted' }, 'Enter the 6-digit code your authenticator app shows for Scene.ai. Lost the phone? Use one of your recovery codes.'),
      form,
      el('div', { class: 'auth-switch muted' },
        el('button', { type: 'button', onclick: () => { second = null; draw(); } }, 'Back')));
    code.focus();
  };

  const page = (...card) => {
    root.replaceChildren(el('div', { class: 'auth' },
      el('div', { class: 'auth-hero' },
        el('div', { class: 'brand' }, el('img', { src: '/assets/img/logo.svg', alt: '' }), 'Scene.ai'),
        el('div', {},
          el('h2', {}, 'Direct your scene.'),
          el('p', {}, 'A studio for making videos and images with AI, without the node graphs.')),
        el('div', { class: 'auth-points' }, POINTS.map((p) => el('div', {}, icon('check'), p)))),
      el('div', { class: 'auth-side' }, el('div', { class: 'auth-card' }, ...card))));
  };
  draw();
}
