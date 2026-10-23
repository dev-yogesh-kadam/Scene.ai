// The console's Moderation section: what was made lately, flagged first when its prompt has a listed word, each item
// marked fine or removed; the verdicts so far; the prompts refused before they were made; and the word list.
// See backend/scene/moderation.py.

import { api } from '../api.js';
import { el, field, segmented } from '../dom.js';
import { number, ago, stamp, table, person } from './shared.js';
import { thumb } from './sections.js';

const MODES = [{ id: 'off', label: 'Off' }, { id: 'flag', label: 'Flag for review' }, { id: 'refuse', label: 'Refuse the job' }];

function wordsCard(d, ctx) {
  const words = el('textarea', { rows: 6, placeholder: 'One word or phrase a line' }, d.words.join('\n'));
  let mode = d.mode;
  const modeBox = el('div');
  const drawMode = () => modeBox.replaceChildren(segmented(MODES, mode, (v) => { mode = v; drawMode(); }));
  drawMode();
  const notice = el('p', { class: 'notice' });
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', {}, 'Words'), el('span', { class: 'pill ' + (d.mode === 'off' ? 'cancelled' : 'running') }, MODES.find((m) => m.id === d.mode).label)),
    el('p', { class: 'muted small' }, 'Prompts with these words (whole words, any case) are flagged, or refused before anything is made: the person is told to change the words and gets the credits back. A refused prompt is listed under Refused.'),
    field('Words and phrases', words),
    el('div', { class: 'field' }, el('div', { class: 'label' }, 'When a prompt has one'), modeBox),
    notice,
    el('button', { class: 'btn primary', style: 'margin-top:12px', onclick: async () => {
      try { await api('/api/admin/moderation/settings', { method: 'PUT', json: { words: words.value, mode } }); ctx.draw(); } catch (e) { notice.className = 'notice error'; notice.textContent = e.message; }
    } }, 'Save'));
}

function itemCard(i, ctx) {
  const decide = async (verdict, button) => {
    if (verdict === 'removed' && !confirm(`Remove "${i.name}" from ${i.user_name}'s library? It can't be brought back.`)) return;
    button.disabled = true;
    try { await api('/api/admin/moderation/' + i.id, { method: 'POST', json: { verdict } }); ctx.draw(); } catch (e) { alert(e.message); button.disabled = false; }
  };
  const fine = el('button', { class: 'btn small', onclick: () => decide('fine', fine) }, 'Fine');
  const remove = el('button', { class: 'btn small quiet danger', onclick: () => decide('removed', remove) }, 'Remove');
  return el('div', { class: 'mod-item' + (i.words.length ? ' flagged' : '') },
    el('a', { class: 'thumb-box', href: `/api/admin/library/${i.id}/file`, target: '_blank', title: 'Open ' + i.name }, thumb(i)),
    el('div', { class: 'mod-body' },
      el('div', { class: 'row' }, el('b', {}, i.name), i.words.map((w) => el('span', { class: 'pill failed' }, w))),
      el('div', { class: 'muted small' }, `${i.user_name} · ${i.user_email} · ${ago(i.created)}`),
      i.prompt && el('p', { class: 'small mod-prompt' }, i.prompt),
      el('div', { class: 'row' }, fine, remove)));
}

export async function moderation(ctx) {
  const s = ctx.state.moderation;
  const d = await api('/api/admin/moderation?show=' + s.show);
  const tabs = segmented([{ id: 'review', label: 'To review' }, { id: 'done', label: 'Decided' }, { id: 'refused', label: 'Refused prompts' }],
    s.show, (v) => { s.show = v; ctx.draw(); });
  let body;
  if (d.show === 'review') {
    body = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, `To review (${number(d.items.length)})`), d.flagged > 0 && el('span', { class: 'pill failed' }, `${d.flagged} flagged`)),
      el('p', { class: 'muted small' }, 'What was made in the last 30 days and has no verdict yet, flagged items first. Fine takes an item off this list; Remove deletes it from its owner\'s library.'),
      d.items.length ? el('div', { class: 'mod-list' }, d.items.map((i) => itemCard(i, ctx))) : el('p', { class: 'muted' }, 'Nothing to review.'));
  } else if (d.show === 'done') {
    body = el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Decided')),
      table(['When', 'Verdict', 'Whose', 'Words', 'Prompt', 'By'], d.items.map((m) => [stamp(m.created),
        el('span', { class: 'pill ' + (m.verdict === 'removed' ? 'failed' : 'done') }, m.verdict === 'removed' ? 'Removed' : 'Fine'),
        m.user_name ? person(m.user_name, m.user_email) : '', m.words, el('span', { class: 'small' }, m.prompt.slice(0, 160)), m.by_name]), { empty: 'No verdicts yet.' }));
  } else {
    body = el('div', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Refused prompts')),
      table(['When', 'Who', 'Words', 'Prompt'], d.items.map((m) => [stamp(m.created), m.user_name ? person(m.user_name, m.user_email) : '',
        el('span', { class: 'pill failed' }, m.words), el('span', { class: 'small' }, m.prompt.slice(0, 200))]), { empty: 'None refused.' }));
  }
  return [el('div', { class: 'toolbar' }, tabs), el('div', { class: 'grid-2 mod-grid' }, body, wordsCard(d, ctx))];
}
