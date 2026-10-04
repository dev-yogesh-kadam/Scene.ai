// The agent panel on the Canvas: say what to make, read the plan and its cost, approve it.
// The agent only proposes. Nothing is queued or charged until Approve is pressed.

import { api } from '../api.js';
import { el } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';

const KEPT = 12;   // how many past plans are remembered per project
const MARK = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };

// selection(): the selected library items. projectId(): the current project or 0. onJobs(ids): jobs the agent started.
export function agentPanel({ selection = () => [], projectId = () => 0, onJobs = () => {}, onClose = () => {} } = {}) {
  let runs = [];       // {instruction, reply, steps, total, state: 'proposed' | 'approved' | 'dismissed'}
  let brief = '';
  let busy = false;

  const status = el('span', { class: 'slate-text' }, 'checking…');
  const chips = el('div', { class: 'row agent-context' });
  const briefBox = el('div', { class: 'agent-brief hidden' });
  const log = el('div', { class: 'agent-log' });
  const input = el('textarea', { rows: 2, 'aria-label': 'Instruction', placeholder: 'Tell the agent what to make',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } } });
  const sendButton = el('button', { class: 'btn agent', onclick: () => send() }, 'Plan');
  const node = el('aside', { class: 'agent-panel', 'aria-label': 'Agent' },
    el('div', { class: 'agent-head' }, el('span', { class: 'agent-name' }, 'Agent'), status, el('span', { style: 'flex:1' }),
      el('button', { class: 'btn small quiet', title: 'What the agent keeps true in every shot of this project', onclick: () => toggleBrief() }, 'Brief'),
      el('button', { class: 'icon-btn', title: 'Close (Ctrl or ⌘ + J)', 'aria-label': 'Close the agent', onclick: onClose }, '×')),
    briefBox, chips, log,
    el('div', { class: 'agent-foot' }, input, sendButton));

  const board = (kind) => `/api/boards/${kind}?project=${projectId()}`;
  const keep = (kind, data) => api('/api/boards/' + kind, { method: 'PUT', json: { project: projectId() || null, data } });
  const saveRuns = () => keep('agent', { runs: runs.slice(-KEPT) }).catch(() => {});
  const startedJobs = () => runs.flatMap((r) => r.steps.map((s) => s.job)).filter(Boolean);

  // ------------------------------------------------------------ the brief

  function toggleBrief(open = briefBox.classList.contains('hidden')) {
    briefBox.classList.toggle('hidden', !open);
    if (!open) return;
    const text = el('textarea', { rows: 6, 'aria-label': 'Brief', placeholder: 'What should stay true across this project? Style, characters, places, rules.' }, brief);
    const note = el('span', { class: 'slate-text' });
    briefBox.replaceChildren(text, el('div', { class: 'row' },
      el('button', { class: 'btn small primary', onclick: async () => {
        try { await keep('brief', { text: text.value }); brief = text.value.trim(); toggleBrief(false); drawContext(); } catch (e) { note.textContent = e.message; }
      } }, 'Save brief'),
      el('button', { class: 'btn small quiet', onclick: () => toggleBrief(false) }, 'Cancel'), note));
    text.focus();
  }

  function drawContext() {
    const chosen = selection();
    chips.replaceChildren(...[
      el('span', { class: 'chip' }, brief ? 'Brief' : 'No brief yet'),
      chosen.length > 0 && el('span', { class: 'chip' }, chosen.length === 1 ? chosen[0].name : `${chosen.length} selected`),
    ].filter(Boolean));
  }

  // ------------------------------------------------------------ plans

  function drawStep(run, step) {
    const job = step.job && store.jobs.find((j) => j.id === step.job);
    const state = step.error ? 'failed' : job ? job.status : step.job ? 'done' : '';
    return el('div', { class: 'agent-step ' + state },
      el('i', { class: 'cell-mark' }),
      el('div', { class: 'agent-step-body' },
        el('b', {}, step.name),
        el('span', { class: 'slate-text' }, [step.workflow_title, step.facts, step.start && 'starts on ' + step.start.name].filter(Boolean).join(' · ')),
        el('p', { class: 'small muted' }, step.prompt),
        step.error && el('p', { class: 'small error' }, step.error)),
      el('span', { class: 'slate-text' }, state ? MARK[state] : step.credits + ' cr'));
  }

  function drawLog() {
    log.replaceChildren(...(runs.length ? runs.map((run) => el('div', { class: 'agent-run' },
      el('div', { class: 'agent-turn' }, el('h3', {}, 'You'), el('p', {}, run.instruction)),
      el('div', { class: 'agent-turn' }, el('h3', { class: 'agent-label' }, run.steps.length ? `Plan · ${run.steps.length === 1 ? '1 step' : run.steps.length + ' steps'}` : 'Agent'),
        el('p', {}, run.reply),
        run.steps.length > 0 && el('div', { class: 'agent-plan' }, run.steps.map((step) => drawStep(run, step)),
          run.state === 'proposed' && el('div', { class: 'agent-approve' },
            el('span', { class: 'slate-text' }, `${run.total} cr · you have ${Number(store.user.credits ?? 0)} cr`),
            el('span', { class: 'row' },
              el('button', { class: 'btn small quiet', onclick: () => { run.state = 'dismissed'; saveRuns(); drawLog(); } }, 'Dismiss'),
              el('button', { class: 'btn small primary', disabled: busy || run.total > Number(store.user.credits ?? 0), onclick: () => approve(run) }, 'Approve'))),
          run.state === 'dismissed' && el('div', { class: 'agent-approve' }, el('span', { class: 'slate-text' }, 'Dismissed. Nothing was made.'))))))
      : [el('p', { class: 'muted small' }, 'Say what you want to see. The agent writes the shots, picks the settings and shows the cost. Nothing runs until you approve.')]));
    log.scrollTop = log.scrollHeight;
  }

  async function send() {
    const instruction = input.value.trim();
    if (!instruction || busy) return;
    busy = true;
    sendButton.disabled = true;
    sendButton.replaceChildren(el('i', { class: 'cell-mark stepping' }), 'Planning');
    try {
      const plan = await api('/api/agent/plan', { method: 'POST',
        json: { instruction, project_id: projectId() || null, selection: selection().map((i) => i.id) } });
      runs.push({ instruction, reply: plan.reply, steps: plan.steps, total: plan.total, state: plan.steps.length ? 'proposed' : 'answered' });
      input.value = '';
      saveRuns();
    } catch (e) {
      runs.push({ instruction, reply: e.message, steps: [], total: 0, state: 'answered' });
    }
    busy = false;
    sendButton.disabled = false;
    sendButton.replaceChildren('Plan');
    drawLog();
  }

  // Queue the approved steps one by one, through the same door as the Create page. Stops at the first refusal.
  async function approve(run) {
    busy = true;
    run.state = 'approved';
    drawLog();
    for (const step of run.steps) {
      try {
        const settings = { ...step.settings, refs: {} };
        if (step.start) {
          const ref = await api(`/api/library/${step.start.id}/reference`, { method: 'POST' });
          settings.refs[step.start.slot] = { comfy_name: ref.comfy_name, name: ref.name };
        }
        const data = new FormData();
        data.append('settings', JSON.stringify(settings));
        step.job = (await api('/api/jobs', { method: 'POST', body: data })).id;
        onJobs(startedJobs());
      } catch (e) {
        step.error = e.message;
        break;
      }
    }
    busy = false;
    saveRuns();
    refreshJobs().catch(() => {});
    drawLog();
  }

  // ------------------------------------------------------------ loading

  async function load() {
    runs = [];
    drawLog();
    try {
      const [saved, savedBrief, state] = await Promise.all([api(board('agent')), api(board('brief')), api('/api/agent/status')]);
      runs = saved.data.runs || [];
      brief = (savedBrief.data.text || '').trim();
      status.textContent = state.online ? state.model : 'offline';
      status.title = state.online ? '' : state.detail;
      status.classList.toggle('error', !state.online);
      onJobs(startedJobs());
    } catch (e) { status.textContent = e.message; }
    drawContext();
    drawLog();
  }

  const unsubscribe = subscribe((change) => { if (change === 'jobs' || change === 'credits') drawLog(); });
  load();
  // refresh(): the selection changed. reload(): the project changed.
  return { node, refresh: drawContext, reload: load, focus: () => input.focus(), destroy: unsubscribe };
}
