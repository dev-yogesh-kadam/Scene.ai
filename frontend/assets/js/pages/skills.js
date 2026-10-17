// The Skills page: every recipe the agent can follow, read-only. Skills are files on the server; this shows what
// each one is for, when it fires, and the steps it gives the agent.

import { api } from '../api.js';
import { el, icon } from '../dom.js';

// A skill's trigger regex, turned into a few plain example words for the card.
function triggerWords(pattern) {
  const inner = (pattern.match(/\(([^)]*)\)/) || [, pattern])[1];
  return inner.replace(/\\b|\\w\*|\?|\.\*/g, '').split('|')
    .map((w) => w.replace(/[^a-z0-9 .-]/gi, '').trim()).filter(Boolean).slice(0, 8);
}

export function render(view) {
  const list = el('div', { class: 'skills-list' }, el('p', { class: 'page-sub' }, 'Loading…'));
  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Skills')),
    el('p', { class: 'page-sub' }, 'Recipes the agent follows for a kind of work. One is used on its own when your '
      + 'message matches it, or you can call one yourself by typing ', el('code', {}, '/skill-id'), ' at the start of '
      + 'a message in the agent panel.'),
    el('div', { class: 'card' }, list));

  (async () => {
    try {
      const { skills } = await api('/api/skills');
      if (!skills.length) { list.replaceChildren(el('p', { class: 'page-sub' }, 'No skills yet.')); return; }
      list.replaceChildren(...skills.map((s) => {
        const words = triggerWords(s.words || '');
        return el('details', { class: 'skill-item' },
          el('summary', {},
            el('span', { class: 'skill-mark', 'aria-hidden': 'true' }, icon('skill')),
            el('span', { class: 'skill-name' }, s.title),
            el('code', { class: 'skill-id' }, '/' + s.id),
            el('span', { class: 'skill-ver slate-text' }, 'v' + s.version)),
          words.length > 0 && el('div', { class: 'skill-triggers' }, el('span', { class: 'slate-text' }, 'Fires on: '),
            ...words.map((w) => el('span', { class: 'tag' }, w))),
          el('pre', { class: 'skill-text' }, s.text));
      }));
    } catch (e) {
      list.replaceChildren(el('p', { class: 'page-sub' }, 'Could not load skills: ' + e.message));
    }
  })();
}
