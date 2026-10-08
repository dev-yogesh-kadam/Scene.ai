// The agent tab of the Canvas panel: say what to make, read the plan and its cost, approve it.
// The agent only proposes. Nothing is queued or charged until Approve is pressed.

import { api } from '../api.js';
import { el, still } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';

const KEPT = 12;   // how many past plans are remembered per project
const RECALLED = 6;   // how many earlier turns are sent along, so the agent can follow the conversation
const MARK = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled', waiting: 'Waits for the step before' };

// projectId(): the current project or 0. onJobs(ids): jobs the agent started.
// The page calls attach(item) when a frame is clicked: the item goes into the message as a chip, where the cursor is.
export function agentPanel({ projectId = () => 0, onJobs = () => {} } = {}) {
  let runs = [];       // {instruction, reply, steps, total, state: 'proposed' | 'approved' | 'dismissed'}
  let brief = '';
  let busy = false;       // a message is with the model
  let working = false;    // an approved plan is being carried out, which can take minutes when steps wait for each other

  const status = el('span', { class: 'slate-text' }, 'checking…');
  // Which model answers: any the Ollama server has. The choice is this browser's, kept in localStorage.
  const modelPicker = el('select', { class: 'small agent-model hidden', 'aria-label': 'Model', title: 'The model the agent uses',
    onchange: (e) => localStorage.setItem('scene.agent.model', e.target.value) });
  const chips = el('div', { class: 'row agent-context' });
  const briefBox = el('div', { class: 'agent-brief hidden' });
  const log = el('div', { class: 'agent-log' });
  // The message is typed text with chips in it, one per attached item, so the words around a chip say what it is for.
  const input = el('div', { class: 'agent-input', contenteditable: 'true', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Message',
    'data-placeholder': 'Ask the agent, or tell it what to make. Click a frame to attach it.',
    onkeydown: (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (e.shiftKey) document.execCommand('insertLineBreak'); else send();
    },
    onpaste: (e) => {   // only the words of what is pasted, never its markup
      e.preventDefault();
      document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
    } });
  let caret = null;   // where the cursor last was in the message: a click on the canvas takes the focus away
  const rememberCaret = () => {
    const picked = window.getSelection();
    if (picked.rangeCount && input.contains(picked.anchorNode)) caret = picked.getRangeAt(0).cloneRange();
  };
  document.addEventListener('selectionchange', rememberCaret);
  const sendButton = el('button', { class: 'btn agent', onclick: () => send() }, 'Send');
  const node = el('div', { class: 'agent-panel' },
    el('div', { class: 'agent-head' }, modelPicker, status, el('span', { style: 'flex:1' }),
      el('button', { class: 'btn small quiet', title: 'What the agent keeps true in every shot of this project', onclick: () => toggleBrief() }, 'Brief')),
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

  // ------------------------------------------------------------ the message and its attached items

  const chipsIn = () => [...input.querySelectorAll('.attach')];

  // Put an item into the message as a chip, where the cursor was. An item that is already there is not added twice.
  function attach(item) {
    if (chipsIn().some((chip) => Number(chip.dataset.id) === item.id)) return;
    const chip = el('span', { class: 'attach', contenteditable: 'false', 'data-id': item.id, 'data-name': item.name, title: item.name },
      el('span', { class: 'attach-thumb' }, still(`/api/library/${item.id}/file`, item.kind)),
      el('span', { class: 'attach-name' }, item.name),
      el('button', { type: 'button', class: 'attach-drop', title: 'Remove', 'aria-label': `Remove ${item.name}`, tabindex: '-1',
        onclick: () => { chip.remove(); input.focus(); } }, '×'));
    const range = caret && input.contains(caret.startContainer) ? caret : null;
    const space = document.createTextNode('\u00a0');
    if (range) {
      range.deleteContents();
      range.insertNode(space);
      range.insertNode(chip);
    } else input.append(chip, space);
    // Leave the cursor after the chip, ready for the words that say what the item is for.
    const after = document.createRange();
    after.setStartAfter(space);
    after.collapse(true);
    input.focus();
    const picked = window.getSelection();
    picked.removeAllRanges();
    picked.addRange(after);
    caret = after.cloneRange();
  }

  // The message as it is sent: each chip becomes its tag (@1, @2… in the order they appear), and the ids go along in that order.
  // shown is the same message with the names of the items, for the log.
  function message() {
    const ids = [];
    const read = (nodes, named) => [...nodes].map((n) => {
      if (n.nodeType === Node.TEXT_NODE) return n.textContent;
      if (n.classList && n.classList.contains('attach')) {
        const id = Number(n.dataset.id);
        if (!ids.includes(id)) ids.push(id);
        return named ? `[${n.dataset.name}]` : '@' + (ids.indexOf(id) + 1);
      }
      if (n.nodeName === 'BR') return '\n';
      return read(n.childNodes, named) + (n.nodeName === 'DIV' ? '\n' : '');
    }).join('');
    const tidy = (text) => text.replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').trim();
    return { text: tidy(read(input.childNodes, false)), shown: tidy(read(input.childNodes, true)), ids };
  }

  function drawContext() {
    chips.replaceChildren(el('span', { class: 'chip' }, brief ? 'Brief' : 'No brief yet'));
  }

  // ------------------------------------------------------------ plans

  function drawStep(run, step) {
    const job = step.job && store.jobs.find((j) => j.id === step.job);
    const state = step.error ? 'failed' : job ? job.status : (step.job || step.made) ? 'done' : step.rendering ? 'running' : step.waiting ? 'waiting' : '';
    return el('div', { class: 'agent-step ' + state },
      el('i', { class: 'cell-mark' }),
      el('div', { class: 'agent-step-body' },
        el('b', {}, step.name),
        el('span', { class: 'slate-text' }, [step.workflow_title, step.facts, step.start && 'starts on ' + step.start.name,
          step.after && `starts on the result of step ${step.after.step + 1}`,
          ...(step.uses || []).map((use) => `${use.name} as ${use.label.toLowerCase()}${use.cast ? ' (cast)' : ''}`)].filter(Boolean).join(' · ')),
        el('p', { class: 'small muted' }, step.prompt),
        step.error && el('p', { class: 'small error' }, step.error)),
      el('span', { class: 'slate-text' }, state ? MARK[state] : step.credits ? step.credits + ' cr' : 'Free'));
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
              el('button', { class: 'btn small primary', disabled: working || run.total > Number(store.user.credits ?? 0), onclick: () => approve(run) }, 'Approve'))),
          // An approved plan with steps still to carry out: it was interrupted, or a step failed. Resume goes on from there.
          run.state === 'approved' && !working && run.steps.some((step) => !step.job && !step.made) && el('div', { class: 'agent-approve' },
            el('span', { class: 'slate-text' }, 'Not every step was carried out.'),
            el('button', { class: 'btn small primary', onclick: () => approve(run) }, 'Resume')),
          run.state === 'dismissed' && el('div', { class: 'agent-approve' }, el('span', { class: 'slate-text' }, 'Dismissed. Nothing was made.'))))))
      : [el('p', { class: 'muted small' }, 'Ask a question or say what you want to see. The agent writes the shots, picks the settings and shows the cost. Nothing runs until you approve.')]));
    log.scrollTop = log.scrollHeight;
  }

  async function send() {
    const { text, shown: instruction, ids } = message();
    if (!text || busy) return;
    busy = true;
    sendButton.disabled = true;
    sendButton.replaceChildren(el('i', { class: 'cell-mark stepping' }), 'Thinking');
    try {
      const plan = await api('/api/agent/plan', { method: 'POST',
        json: { instruction: text, project_id: projectId() || null, selection: ids, model: localStorage.getItem('scene.agent.model') || null,
          history: runs.slice(-RECALLED).map((r) => ({ instruction: r.instruction, reply: r.reply, steps: r.steps.map((s) => s.name) })) } });
      runs.push({ instruction, reply: plan.reply, steps: plan.steps, total: plan.total, state: plan.steps.length ? 'proposed' : 'answered' });
      input.replaceChildren();
      caret = null;
      saveRuns();
    } catch (e) {
      runs.push({ instruction, reply: e.message, steps: [], total: 0, state: 'answered' });
    }
    busy = false;
    sendButton.disabled = false;
    sendButton.replaceChildren('Send');
    drawLog();
  }

  // Run the approved steps one by one: generations are queued through the same door as the Create page,
  // edits are made through the timeline export. Stops at the first refusal.
  // The library item a step made, waiting for its job if it is still being rendered. A failed or cancelled job throws.
  async function resultOf(step) {
    if (step.made) return step.made;
    if (step.error || !step.job) throw new Error('The step this one starts on was not made.');
    for (;;) {
      const job = store.jobs.find((j) => j.id === step.job);
      if (job && (job.status === 'failed' || job.status === 'cancelled')) throw new Error('The step this one starts on did not finish.');
      if (!job || job.status === 'done') {
        const made = (await api('/api/library')).items.find((i) => i.job_id === step.job);
        if (made) return made.id;
        if (!job) throw new Error('The step this one starts on has no result in the library.');
      }
      await new Promise((resolve) => setTimeout(resolve, 3000));
      if (!node.isConnected) throw new Error('Stopped: the canvas was left before the earlier step finished. Press Resume to go on.');
    }
  }

  // Carry out the steps of an approved plan, in order. Steps that were already carried out are left alone, so this
  // also resumes a plan that was interrupted while a step was waiting for the one before it.
  async function approve(run) {
    working = true;
    run.state = 'approved';
    drawLog();
    for (const step of run.steps) {
      if (step.job || step.made) continue;
      step.error = null;
      try {
        // Work done on the studio's own machine is queued like a generation, in a lane that does not wait for the GPU.
        const local = step.motion ? ['/api/motion/render', step.motion]                 // words and shapes drawn by HyperFrames, charged by length
          : step.sound ? ['/api/edit/sound', step.sound]                                // a sound put on a video with ffmpeg, free
            : step.edit ? ['/api/timeline/export', { name: step.name, clips: step.edit.clips, parent: step.edit.clips[0].id }] : null;   // a cut or a join, free
        if (local) {
          step.job = (await api(local[0], { method: 'POST', json: { ...local[1], project_id: projectId() || null } })).job;
          saveRuns();
          refreshJobs();
          drawLog();
          continue;
        }
        const uses = step.uses || [];
        const settings = { ...step.settings, refs: {}, parent: step.start ? step.start.id : uses.length ? uses[0].id : null };
        for (const use of uses) {   // each attached item goes into the slot the plan named for it
          const ref = await api(`/api/library/${use.id}/reference?kind=${use.kind}`, { method: 'POST' });
          settings.refs[use.slot] = { comfy_name: ref.comfy_name, name: ref.name };
        }
        if (step.start) {
          const ref = await api(`/api/library/${step.start.id}/reference`, { method: 'POST' });
          settings.refs[step.start.slot] = { comfy_name: ref.comfy_name, name: ref.name };
        }
        if (step.after) {   // this shot starts on what an earlier step of the plan makes: wait for it, then take it as the first frame
          step.waiting = true;
          saveRuns();
          drawLog();
          let earlier;
          try { earlier = await resultOf(run.steps[step.after.step]); } finally { step.waiting = false; }
          const ref = await api(`/api/library/${earlier}/reference`, { method: 'POST' });
          settings.refs[step.after.slot] = { comfy_name: ref.comfy_name, name: ref.name };
          settings.parent = earlier;
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
    working = false;
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
      for (const run of runs) for (const step of run.steps) { step.waiting = false; step.rendering = false; }   // nothing is under way after a reload
      brief = (savedBrief.data.text || '').trim();
      // With more than one model on the server there is a choice; otherwise just its name.
      const models = state.online ? state.models || [] : [];
      const picked = localStorage.getItem('scene.agent.model');
      const current = models.includes(picked) ? picked : state.model;
      // A hosted model is named "<service>/<name>"; it is shown as its name and the service it is asked of.
      const services = Object.fromEntries((state.hosted || []).map((s) => [s.id, s.name]));
      const shown = (name) => { const [sid, ...rest] = name.split('/'); return rest.length && services[sid] ? `${rest.join('/')} · ${services[sid]}` : name; };
      modelPicker.replaceChildren(...models.map((name) => el('option', { value: name, selected: name === current }, shown(name))));
      modelPicker.classList.toggle('hidden', models.length < 2);
      status.classList.toggle('hidden', models.length >= 2);
      status.textContent = state.online ? shown(state.model) : 'offline';
      status.title = state.online ? '' : state.detail;
      status.classList.toggle('error', !state.online);
      onJobs(startedJobs());
    } catch (e) { status.textContent = e.message; }
    drawContext();
    drawLog();
  }

  const unsubscribe = subscribe((change) => { if (change === 'jobs' || change === 'credits') drawLog(); });
  load();
  // attach(item): put a library item into the message. reload(): the project changed.
  return { node, attach, reload: load, focus: () => input.focus(),
    destroy: () => { unsubscribe(); document.removeEventListener('selectionchange', rememberCaret); } };
}
