// The agent's tabs: several conversations in one project, each kept on its own. A strip of tabs over the panel (rename
// one with a double-click, close it with ×, + for a new one) and a history menu with every conversation, how long ago
// it was used and what it spent; pointing at what it spent shows it by kind.

import { api } from '../api.js';
import { ask, el, icon } from '../dom.js';
import { agentPanel, popover, spendCard } from './agent.js';

const MAX_TABS = 30;   // conversations kept per project; the oldest closed one goes when there are more

const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
function age(time) {
  const s = Math.max(0, (Date.now() - (time || 0)) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const days = Math.round(s / 86400);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

// onFocus(itemId): show an item on the canvas. locate(itemId): where the canvas has it, {shot, take}, or null.
export function agentTabs({ projectId = () => 0, onJobs = () => {}, onMemory = null, onFocus = () => {}, locate = () => null, selection = () => [], items = () => [], pickCanvas = null, onUploaded = () => {} } = {}) {
  let index = { tabs: [], open: [], active: null };   // what the "agent" board keeps for this project
  const panels = new Map();   // tab id -> its agentPanel, made when the tab is first shown
  const jobsOf = new Map();   // tab id -> the jobs its plans started
  let loading = null;

  const historyButton = el('button', { type: 'button', class: 'agent-history-btn', 'aria-haspopup': 'menu', title: 'All conversations',
    'aria-label': 'All conversations', onclick: () => openHistory() }, icon('chat'), icon('menu'));
  const strip = el('div', { class: 'agent-tab-list', role: 'tablist', 'aria-label': 'Agent conversations' });
  const addButton = el('button', { type: 'button', class: 'icon-btn agent-tab-add', title: 'New conversation', 'aria-label': 'New conversation',
    onclick: () => addTab() }, icon('plus'));
  const body = el('div', { class: 'agent-tabs-body' });
  const node = el('div', { class: 'agent-tabs' }, el('div', { class: 'agent-tabs-bar' }, historyButton, strip, addButton), body);

  const tab = (id) => index.tabs.find((t) => t.id === id);
  const saveIndex = () => api('/api/boards/agent', { method: 'PUT', json: { project: projectId() || null, data: index } }).catch(() => {});
  let indexTimer = null;
  const saveSoon = () => { clearTimeout(indexTimer); indexTimer = setTimeout(saveIndex, 600); };

  function panelOf(id) {
    if (!panels.has(id)) {
      const made = agentPanel({ projectId, onMemory, session: id, onFocus, locate, selection, items, pickCanvas, onUploaded,
        onJobs: (ids) => { jobsOf.set(id, ids); onJobs([...new Set([...jobsOf.values()].flat())]); },
        onSaved: ({ spent, updated }) => {
          const t = tab(id);
          if (!t) return;
          if (JSON.stringify(t.spent) === JSON.stringify(spent) && !updated) return;
          t.spent = spent;
          if (updated) t.updated = updated;
          saveSoon();
        } });
      panels.set(id, made);
      body.append(made.node);
    }
    return panels.get(id);
  }

  function show(id) {
    if (!tab(id)) return;
    if (!index.open.includes(id)) index.open.push(id);
    index.active = id;
    for (const [pid, p] of panels) p.node.classList.toggle('hidden', pid !== id);
    panelOf(id).node.classList.remove('hidden');
    drawStrip();
    saveSoon();
    panelOf(id).focus();
  }

  function addTab() {
    const used = new Set(index.tabs.map((t) => t.name));
    let n = index.tabs.length + 1;
    while (used.has(`Agent ${n}`)) n += 1;
    const made = { id: newId(), name: `Agent ${n}`, created: Date.now(), updated: Date.now(), spent: null };
    index.tabs.push(made);
    // Past the limit, the oldest conversation that is not open goes.
    while (index.tabs.length > MAX_TABS) {
      const old = [...index.tabs].filter((t) => !index.open.includes(t.id) && t.id !== made.id).sort((a, b) => a.updated - b.updated)[0];
      if (!old) break;
      forget(old.id);
    }
    show(made.id);
  }

  function close(id) {
    index.open = index.open.filter((o) => o !== id);
    if (!index.open.length) return addTab();   // there is always a conversation to type into
    if (index.active === id) show(index.open[index.open.length - 1]);
    else { drawStrip(); saveSoon(); }
  }

  function forget(id) {
    index.tabs = index.tabs.filter((t) => t.id !== id);
    index.open = index.open.filter((o) => o !== id);
    const p = panels.get(id);
    if (p) { p.destroy(); p.node.remove(); panels.delete(id); }
    jobsOf.delete(id);
    api(`/api/boards/agent-${id}?project=${projectId() || 0}`, { method: 'DELETE' }).catch(() => {});
  }

  // Rename in place: the name becomes a box; Enter or leaving it keeps the new name, Escape keeps the old one.
  function rename(id, holder) {
    const t = tab(id);
    const box = el('input', { type: 'text', class: 'agent-tab-name-edit', value: t.name, maxlength: 40, 'aria-label': 'Name of the conversation' });
    const done = (keep) => {
      if (!box.isConnected) return;
      if (keep && box.value.trim()) { t.name = box.value.trim(); saveSoon(); }
      drawStrip();
    };
    box.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); });
    box.addEventListener('blur', () => done(true));
    box.addEventListener('click', (e) => e.stopPropagation());
    holder.replaceChildren(box);
    box.select();
  }

  function drawStrip() {
    strip.replaceChildren(...index.open.map(tab).filter(Boolean).map((t) => {
      const name = el('span', { class: 'agent-tab-name' }, t.name);
      return el('div', { class: 'agent-tab' + (t.id === index.active ? ' on' : ''), role: 'tab', 'aria-selected': String(t.id === index.active),
        tabindex: t.id === index.active ? '0' : '-1', title: t.name + ' · double-click to rename',
        onclick: () => t.id !== index.active && show(t.id),
        ondblclick: () => rename(t.id, name),
        onkeydown: (e) => { if (e.key === 'F2') rename(t.id, name); } },
        name,
        el('button', { type: 'button', class: 'agent-tab-close', title: 'Close (it stays in the history)', 'aria-label': `Close ${t.name}`,
          onclick: (e) => { e.stopPropagation(); close(t.id); } }, '×'));
    }));
    const on = strip.querySelector('.agent-tab.on');
    if (on) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  // What a conversation spent, by kind, beside its row in the history.
  const breakdown = (anchor, t) => spendCard(anchor, t.spent || { total: 0 });

  function openHistory() {
    const rows = [...index.tabs].sort((a, b) => (b.updated || 0) - (a.updated || 0));
    const box = popover(historyButton, [
      el('button', { type: 'button', class: 'pop-item', onclick: () => { box.close(); addTab(); } }, icon('plus'), el('b', {}, 'New conversation')),
      el('div', { class: 'menu-sep' }),
      el('div', { class: 'pop-title' }, 'History'),
      ...rows.map((t) => {
        const spent = (t.spent && t.spent.total) || 0;
        const credits = el('span', { class: 'agent-spend', tabindex: '0', 'aria-label': `${spent} credits spent`,
          onpointerenter: (e) => breakdown(e.currentTarget, t), onfocus: (e) => breakdown(e.currentTarget, t) }, String(spent), el('i', { class: 'coin', 'aria-hidden': 'true' }));
        const name = el('b', {}, t.name);
        return el('div', { class: 'agent-history-row' + (t.id === index.active ? ' on' : '') },
          el('button', { type: 'button', class: 'agent-history-open', onclick: () => { box.close(); show(t.id); } },
            name, el('span', { class: 'muted small' }, age(t.updated) + (index.open.includes(t.id) ? '' : ' · closed'))),
          el('span', { class: 'agent-history-tools' },
            el('button', { type: 'button', class: 'icon-btn small', title: 'Rename', 'aria-label': `Rename ${t.name}`,
              onclick: () => { box.close(); show(t.id); rename(t.id, strip.querySelector('.agent-tab.on .agent-tab-name')); } }, icon('pencil')),
            el('button', { type: 'button', class: 'icon-btn small', title: 'Delete this conversation', 'aria-label': `Delete ${t.name}`,
              onclick: async () => {
                if (!await ask({ title: `Delete "${t.name}"?`, danger: true, confirm: 'Delete conversation',
                  message: 'Its messages and plans are removed. What it made stays on the canvas and in the library.' })) return;
                box.close();
                document.querySelectorAll('.agent-spend-card').forEach((c) => c.remove());
                const wasActive = t.id === index.active;
                forget(t.id);
                if (!index.tabs.length || !index.open.length) addTab();
                else if (wasActive) show(index.open[index.open.length - 1]);
                else { drawStrip(); saveSoon(); }
              } }, icon('trash'))),
          credits);
      })], 'pop-history');
  }

  // A project's tabs. The single conversation kept before there were tabs becomes "Agent 1".
  async function load() {
    for (const p of panels.values()) { p.destroy(); p.node.remove(); }
    panels.clear();
    jobsOf.clear();
    const wanted = projectId();
    const run = loading = (async () => {
      let saved = {};
      try { saved = (await api(`/api/boards/agent?project=${wanted || 0}`)).data || {}; } catch { /* starts empty */ }
      if (run !== loading) return;
      index = { tabs: Array.isArray(saved.tabs) ? saved.tabs : [], open: Array.isArray(saved.open) ? saved.open : [], active: saved.active || null };
      if (!index.tabs.length) {
        const first = { id: newId(), name: 'Agent 1', created: Date.now(), updated: Date.now(), spent: null };
        if (Array.isArray(saved.runs) && saved.runs.length) {
          await api('/api/boards/agent-' + first.id, { method: 'PUT', json: { project: wanted || null, data: { runs: saved.runs } } }).catch(() => {});
          first.spent = null;
          first.updated = Math.max(...saved.runs.map((r) => r.at || 0), 0) || Date.now();
        }
        index = { tabs: [first], open: [first.id], active: first.id };
        await saveIndex();
      }
      index.open = index.open.filter((id) => tab(id));
      if (!index.open.length) index.open = [index.tabs[0].id];
      show(tab(index.active) ? index.active : index.open[0]);
    })();
    await run;
  }

  load();
  const active = () => panels.get(index.active);
  return {
    node,
    attach: (item) => active() && active().attach(item),
    selectionChanged: () => active() && active().selectionChanged(),
    reload: () => load(),
    redraw: () => active() && active().redraw(),   // the canvas moved things: where each result is is drawn again
    focus: () => active() && active().focus(),
    destroy: () => { clearTimeout(indexTimer); for (const p of panels.values()) p.destroy(); },
  };
}
