// The console's Projects section: every user's projects, their modules and their NeuralCore kit (the entries the
// agent and the canvas use by name), and their latest items.

import { api } from '../api.js';
import { el, still } from '../dom.js';
import { number, bytes, ago, stamp, table, searchBox, drawer, section, facts, person } from './shared.js';
import { thumb } from './sections.js';

const TYPE = { character: 'Character', location: 'Location', prop: 'Prop', voice: 'Voice', style: 'Style', other: 'Other' };

async function openProject(id) {
  const panel = drawer('Project', el('p', { class: 'muted' }, 'Loading…'));
  try {
    const d = await api('/api/admin/projects/' + id);
    const p = d.project;
    const always = d.kit.filter((k) => k.always);
    panel.replace(
      el('div', { class: 'drawer-title' }, el('div', {}, el('b', {}, p.name), el('div', { class: 'muted' }, `${p.user_name} · ${p.user_email}`))),
      section('About it', facts([['Made', stamp(p.created)], ['Modules', number(d.modules.length)], ['Kit entries', `${number(d.kit.length)}${always.length ? ` · ${always.length} always attached` : ''}`]])),
      d.modules.length > 0 && section('Modules', table(['Module', 'Items', 'Jobs', 'Made'], d.modules.map((m) => [m.name, number(m.items), number(m.jobs), ago(m.created)]))),
      section(`NeuralCore kit (${d.kit.length})`, d.kit.length
        ? el('div', { class: 'kit-list' }, d.kit.map((k) => el('div', { class: 'kit-entry' },
          k.kind === 'image' ? still(`/api/admin/assets/${k.id}/file`, 'image', k.name) : el('div', { class: 'kit-kind' }, k.kind),
          el('div', {}, el('b', {}, k.named ? k.name : el('span', { class: 'muted' }, 'Not named yet')),
            el('div', { class: 'muted small' }, [TYPE[k.type] || k.type, k.always && 'always attached', k.origin === 'upload' && 'dropped into a job'].filter(Boolean).join(' · ')),
            k.about && el('div', { class: 'small' }, k.about), k.use_note && el('div', { class: 'muted small' }, 'Use: ' + k.use_note)))))
        : el('p', { class: 'muted' }, 'The kit is empty.')),
      section('Latest items', d.items.length
        ? el('div', { class: 'thumbs' }, d.items.map((i) => el('div', { class: 'thumb-box', title: i.name }, thumb(i))))
        : el('p', { class: 'muted' }, 'Nothing made in it yet.')));
  } catch (e) { panel.replace(el('p', { class: 'error' }, e.message)); }
}

export async function projects(ctx) {
  const s = ctx.state.projects;
  const found = (await api('/api/admin/projects?q=' + encodeURIComponent(s.q))).projects;
  return [
    el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Projects'), searchBox('Project, person or email', s.q, (v) => { s.q = v; ctx.draw(); })),
      table(['Project', 'Owner', 'Modules', 'Kit', 'Items', 'Space', 'Jobs', 'Last job'], found.map((p) => [
        p.name, person(p.user_name, p.user_email), number(p.modules), number(p.kit), number(p.items), bytes(p.bytes), number(p.jobs), p.last_job ? ago(p.last_job) : 'never']),
      { onRow: (i) => openProject(found[i].id), empty: s.q ? 'No project matches.' : 'No projects yet.' }),
      el('p', { class: 'muted small', style: 'margin-top:10px' }, 'Counts take in each project\'s modules, which share its kit. Select a project for its kit and latest items.')),
  ];
}
