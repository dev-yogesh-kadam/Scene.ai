// The agent tab of the Canvas panel: say what to make, read the plan and its cost, approve it.
// The agent only proposes. Nothing is queued or charged until Approve is pressed.

import { api } from '../api.js';
import { el, icon, still } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';

const KEPT = 12;   // how many past plans are remembered per project
const RECALLED = 6;   // how many earlier turns are sent along, so the agent can follow the conversation
// A message that only says to go ahead: under a plan that waits for approval it approves it.
const GO = /^\W*(approve|approved|start|go|go ahead|yes|ok|okay|proceed|generate|generate it|make it|do it|run it|confirm)\W*$/i;
const REVIEW_WITHIN = 24 * 3600 * 1000;   // a shot finished longer ago than this is not reviewed when the panel opens
const MARK = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled', waiting: 'Waits for the step before' };
// Whether a plan runs as soon as it arrives or waits for Approve. The choice is this browser's, kept in localStorage.
const PERMISSIONS = [
  { id: 'all', icon: 'forward', label: 'Allow all', about: 'Never asks. The agent decides everything and plans run at once.' },
  { id: 'videos', icon: 'handvideo', label: 'Ask before videos', about: 'Runs images and audio. Asks before videos.' },
  { id: 'always', icon: 'hand', label: 'Always ask', about: 'Asks before every generation.' },
];
const SHAPES = [{ id: 'landscape', label: '16:9' }, { id: 'square', label: '1:1' }, { id: 'portrait', label: '9:16' }];

// A small menu that opens under (or above) a button and closes on a click elsewhere or Escape.
export function popover(anchor, content, className = '') {
  document.querySelectorAll('.pop').forEach((open) => open.close());
  const box = el('div', { class: 'pop ' + className, role: 'menu' }, content);
  const close = () => { box.remove(); document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', escape, true); };
  const outside = (e) => { if (!box.contains(e.target) && !anchor.contains(e.target)) close(); };
  const escape = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); anchor.focus(); } };
  box.close = close;
  document.body.append(box);
  const at = anchor.getBoundingClientRect();
  const room = box.getBoundingClientRect();
  const left = Math.max(8, Math.min(at.left, window.innerWidth - room.width - 8));
  const below = at.bottom + 6 + room.height < window.innerHeight;
  Object.assign(box.style, { left: left + 'px', top: (below ? at.bottom + 6 : Math.max(8, at.top - room.height - 6)) + 'px' });
  document.addEventListener('pointerdown', outside, true);
  document.addEventListener('keydown', escape, true);
  return box;
}

// projectId(): the current project or 0. onJobs(ids): jobs the agent started. onMemory(): show the Shared memory tab.
// The page calls attach(item) when a frame is clicked: the item goes into the message as a chip, where the cursor is.
// What one conversation has spent, by what it made: {video, image, audio, llm, total}. A job that failed or was
// cancelled gave its credits back, so it is not counted.
export function spentBy(runs, jobs = []) {
  const spent = { video: 0, image: 0, audio: 0, llm: 0, total: 0 };
  const refunded = new Set(jobs.filter((j) => j.status === 'failed' || j.status === 'cancelled').map((j) => j.id));
  for (const run of runs || []) {
    for (const step of run.steps || []) {
      const takes = [[step, step.credits], [step.take2, step.retake && step.retake.credits]];
      for (const [take, credits] of takes) {
        if (!take || !take.job || refunded.has(take.job) || !credits) continue;
        const kind = ['image', 'audio'].includes(step.kind) ? step.kind : 'video';   // motion graphics and edits are videos
        spent[kind] += credits;
        spent.total += credits;
      }
    }
  }
  return spent;
}

// session: the agent tab this panel holds (its conversation is kept on its own). onSaved({spent, updated}): the
// conversation was saved, with what it has spent so far.
export function agentPanel({ projectId = () => 0, onJobs = () => {}, onMemory = null, session = null, onSaved = () => {} } = {}) {
  let runs = [];       // {instruction, reply, steps, total, state: 'proposed' | 'approved' | 'dismissed'}
  let busy = false;       // a message is with the model
  let pending = null;     // the message being answered, shown in the log until the answer comes: {instruction, stop}
  let working = false;    // an approved plan is being carried out, which can take minutes when steps wait for each other

  const status = el('span', { class: 'agent-status slate-text' }, 'checking…');   // the model's name, or why it is offline
  // Which model answers: any the Ollama server has. The choice is this browser's, kept in localStorage.
  const modelPicker = el('select', { class: 'agent-model hidden', 'aria-label': 'Model', title: 'The model the agent uses',
    onchange: (e) => localStorage.setItem('scene.agent.model', e.target.value) });
  const permission = () => (PERMISSIONS.find((p) => p.id === localStorage.getItem('scene.agent.permission')) || PERMISSIONS[2]);
  const permButton = el('button', { type: 'button', class: 'icon-btn agent-perm', 'aria-haspopup': 'menu', onclick: () => openPermissions() });
  const drawPermission = () => {
    const p = permission();
    permButton.replaceChildren(icon(p.icon));
    permButton.title = permButton.ariaLabel = 'Generation permission: ' + p.label;
  };
  function openPermissions() {
    const box = popover(permButton, [el('div', { class: 'pop-title' }, 'Generation permission'),
      ...PERMISSIONS.map((p) => el('button', { type: 'button', class: 'pop-item', role: 'menuitemradio', 'aria-checked': String(p.id === permission().id),
        onclick: () => { localStorage.setItem('scene.agent.permission', p.id); drawPermission(); box.close(); } },
        icon(p.icon), el('span', {}, el('b', {}, p.label), el('span', { class: 'muted small' }, p.about)),
        p.id === permission().id ? icon('check') : el('span')))], 'pop-perm');
  }
  drawPermission();
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
  // Send, or Stop while the agent is thinking.
  const sendButton = el('button', { type: 'button', class: 'agent-send', onclick: () => (pending ? pending.stop() : send()) });
  const drawSend = () => {
    sendButton.replaceChildren(pending ? el('span', { class: 'stop-mark' }) : icon('arrowup'));
    sendButton.title = sendButton.ariaLabel = pending ? 'Stop (Esc)' : 'Send (Enter)';
    sendButton.classList.toggle('stopping', !!pending);
    input.dataset.placeholder = pending ? 'Waiting for response…' : 'Ask the agent, or tell it what to make. Click a frame to attach it.';
  };
  drawSend();
  const node = el('div', { class: 'agent-panel' },
    log,
    el('div', { class: 'agent-composer', onclick: (e) => { if (e.target === e.currentTarget) input.focus(); } }, input,
      el('div', { class: 'agent-composer-bar' }, el('span', { style: 'flex:1' }), status, modelPicker, permButton, sendButton)));
  node.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pending) pending.stop(); });

  const board = (kind) => `/api/boards/${kind}?project=${projectId()}`;
  const keep = (kind, data) => api('/api/boards/' + kind, { method: 'PUT', json: { project: projectId() || null, data } });
  const talk = session ? 'agent-' + session : 'agent';   // the board this conversation is kept in
  const saveRuns = () => {
    onSaved({ spent: spentBy(runs, store.jobs), updated: Date.now() });
    return keep(talk, { runs: runs.slice(-KEPT) }).catch(() => {});
  };
  const startedJobs = () => runs.flatMap((r) => r.steps.flatMap((s) => [s.job, s.take2 && s.take2.job])).filter(Boolean);

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

  // ------------------------------------------------------------ plans

  // A setting of a step waiting for approval: a pill that opens a menu of its choices.
  function pill(label, glyph, title, open) {
    const button = el('button', { type: 'button', class: 'agent-pill', title, 'aria-haspopup': 'menu', onclick: () => open(button) },
      glyph && icon(glyph), el('span', {}, label), el('span', { class: 'pill-caret', 'aria-hidden': 'true' }, '⌄'));
    return button;
  }

  // Change one step on its card. The server builds it again with the same checks as a planned step, and prices it.
  async function changeStep(run, index, change) {
    const step = run.steps[index];
    step.updating = true;
    step.error = null;
    drawLog();
    try {
      const made = await api('/api/agent/step', { method: 'POST', json: { step, change } });
      run.steps[index] = { ...made, name: step.name, open: step.open };
      // A shot that starts on this one takes its shape: a different shape would be stretched.
      if (change.orientation) {
        for (const [later, other] of run.steps.entries()) {
          if (other.after && other.after.step === index && other.menu && other.menu.shapes) await changeStep(run, later, { orientation: change.orientation });
        }
      }
    } catch (e) {
      step.error = e.message;
    }
    step.updating = false;
    run.total = run.steps.reduce((sum, s) => sum + (s.credits || 0), 0);
    saveRuns();
    drawLog();
  }

  function stepSettings(run, step) {
    const index = run.steps.indexOf(step);
    const menu = step.menu;
    const current = step.current || {};
    const choose = (button, items, picked, onPick, className = '') => {
      const box = popover(button, items.map((item) => el('button', { type: 'button', role: 'menuitemradio',
        class: 'pop-choice' + (String(item.id) === String(picked) ? ' on' : ''), 'aria-checked': String(String(item.id) === String(picked)),
        onclick: () => { box.close(); if (String(item.id) !== String(picked)) onPick(item.id); } }, item.content || item.label)), className);
    };
    const pills = [];
    if (menu.workflows.length > 1) {
      pills.push(pill(step.workflow_title, 'bars', 'Model', (b) => {
        const box = popover(b, [el('div', { class: 'pop-title' }, 'All models'), ...menu.workflows.map((w) =>
          el('button', { type: 'button', role: 'menuitemradio', class: 'pop-item' + (w.id === step.settings.workflow ? ' on' : ''),
            'aria-checked': String(w.id === step.settings.workflow),
            onclick: () => { box.close(); if (w.id !== step.settings.workflow) changeStep(run, index, { workflow: w.id }); } },
          icon(w.kind === 'image' ? 'image' : w.kind === 'audio' ? 'audio' : 'video'), el('b', {}, w.title)))], 'pop-models');
      }));
    }
    if (menu.shapes && current.orientation) {
      const shape = SHAPES.find((s) => s.id === current.orientation);
      pills.push(pill(shape ? shape.label : current.orientation, 'frame', 'Aspect ratio', (b) => choose(b,
        SHAPES.map((s) => ({ id: s.id, content: [el('i', { class: 'shape-mark ' + s.id }), el('span', {}, s.label)] })),
        current.orientation, (id) => changeStep(run, index, { orientation: id }), 'pop-shapes')));
    }
    if (menu.resolutions.length && current.resolution) {
      pills.push(pill(current.resolution + 'p', 'gem', 'Resolution', (b) => choose(b,
        menu.resolutions.map((r) => ({ id: r, label: r + 'p' })), current.resolution, (r) => changeStep(run, index, { resolution: r }), 'pop-row')));
    }
    if (menu.durations.length && current.duration) {
      pills.push(pill(current.duration + 's', 'clock', 'Duration', (b) => choose(b,
        menu.durations.map((d) => ({ id: d, label: d + 's' })), current.duration, (d) => changeStep(run, index, { duration: d }), 'pop-row')));
    }
    return pills.length ? el('div', { class: 'agent-pills' }, pills) : null;
  }

  // The prompt of a step: three lines and a way to see all of it, and, before approval, a way to edit it.
  function stepPrompt(run, step) {
    const editable = run.state === 'proposed' && step.settings && !step.updating;
    if (step.editing) {
      const text = el('textarea', { class: 'agent-prompt-edit', rows: 6, 'aria-label': 'Prompt' }, step.prompt);
      setTimeout(() => text.focus());
      return el('div', { class: 'agent-prompt' }, text, el('div', { class: 'row' }, el('span', { style: 'flex:1' }),
        el('button', { class: 'btn small quiet', onclick: () => { step.editing = false; drawLog(); } }, 'Cancel'),
        el('button', { class: 'btn small primary', onclick: () => {
          step.editing = false;
          if (text.value.trim() && text.value.trim() !== step.prompt) changeStep(run, run.steps.indexOf(step), { prompt: text.value.trim() });
          else drawLog();
        } }, 'Save')));
    }
    return el('div', { class: 'agent-prompt' },
      el('p', { class: 'small muted' + (step.open ? '' : ' clamp') }, step.prompt),
      step.prompt && el('span', { class: 'agent-prompt-tools' },
        editable && el('button', { type: 'button', class: 'icon-btn small', title: 'Edit the prompt', 'aria-label': 'Edit the prompt',
          onclick: () => { step.editing = true; drawLog(); } }, icon('pencil')),
        el('button', { type: 'button', class: 'icon-btn small', title: step.open ? 'Show less' : 'Show the whole prompt',
          'aria-label': step.open ? 'Show less' : 'Show the whole prompt', onclick: () => { step.open = !step.open; drawLog(); } }, icon('expand'))));
  }

  // One step of a plan as a card: what it makes (its result, once there is one), its settings, its prompt and the
  // agent's check of the result.
  const SHAPE_NAMES = { landscape: '16:9', portrait: '9:16', square: '1:1' };
  const KIND_ICONS = { video: 'video', image: 'image', audio: 'audio' };
  function drawStep(run, step) {
    const job = step.job && store.jobs.find((j) => j.id === step.job);
    const state = step.error ? 'failed' : job ? job.status : (step.job || step.made) ? 'done' : step.rendering || step.updating ? 'running' : step.waiting ? 'waiting' : '';
    const proposed = run.state === 'proposed';
    const chip = step.updating ? ['running', 'Updating'] : state === 'failed' && !step.job ? ['failed', 'Not made']
      : state ? [state, state === 'done' ? 'Done' : state === 'running' ? 'Making' : MARK[state]]
        : ['price', step.credits ? step.credits + ' cr' : 'Free'];
    const glyph = step.motion ? 'title' : step.sound ? 'audio' : KIND_ICONS[step.kind] || 'video';
    const result = step.made ? el('span', { class: 'step-thumb', title: 'What this step made' },
      still(`/api/library/${step.made}/file`, step.kind)) : el('span', { class: 'step-thumb empty' + (chip[0] === 'running' ? ' working' : '') }, icon(glyph));
    // The settings as tags; before approval they are the pills that change them.
    const current = step.current || {};
    const tags = step.settings
      ? [step.workflow_title, current.orientation && SHAPE_NAMES[current.orientation], current.resolution && current.resolution + 'p',
        current.duration && current.duration + 's', step.settings.clips > 1 && '× ' + step.settings.clips + ' clips',
        step.settings.options && step.settings.options.quality && step.settings.options.quality + ' quality']
      : [step.workflow_title, step.facts];
    const links = [step.start && 'starts on ' + step.start.name, step.after && `continues step ${step.after.step + 1}`,
      ...(step.uses || []).map((use) => `${use.name} as ${use.label.toLowerCase().split(' (')[0]}${use.cast ? ' (cast)' : ''}`)].filter(Boolean);
    const editable = proposed && step.menu && !step.editing;
    return el('div', { class: 'step-card ' + chip[0] },
      el('div', { class: 'step-top' }, result,
        el('div', { class: 'step-title' },
          el('b', {}, step.name),
          !editable && el('div', { class: 'step-tags' }, tags.filter(Boolean).map((t) => el('span', {}, t)))),
        el('span', { class: 'step-chip ' + chip[0] }, chip[0] === 'running' && el('i', { class: 'cell-mark stepping' }), chip[1])),
      editable && stepSettings(run, step),
      links.length > 0 && el('div', { class: 'step-links' }, links.join(' · ')),
      stepPrompt(run, step),
      // What the agent decided that the user did not say, and why: the length, the shape, the quality.
      step.why && el('div', { class: 'step-why' }, step.why),
      step.error && el('p', { class: 'small error' }, step.error),
      drawReview(run, step));
  }

  // ------------------------------------------------------------ review: the agent looks at what it made

  // What the agent found when it looked at a finished shot, and, for a failed one, its retake (approved by the user).
  function drawReview(run, step) {
    if (step.reviewing) return el('div', { class: 'agent-review checking' }, el('i', { class: 'cell-mark stepping' }), 'Checking the result…');
    if (step.reviewError) return el('div', { class: 'agent-review' }, 'Not checked: ' + step.reviewError);
    const verdict = step.review;
    if (!verdict) return null;
    const take = step.take2;
    const takeJob = take && take.job && store.jobs.find((j) => j.id === take.job);
    const balance = Number(store.user.credits ?? 0);
    const takeState = !take ? '' : take.reviewing ? 'checking…' : take.review
      ? (take.review.passed ? '✓ passed' : '⚠ ' + take.review.problem + ' Kept: one retake per shot.')
      : takeJob ? MARK[takeJob.status] || takeJob.status : take.error || 'queued';
    return el('div', { class: 'agent-review ' + (verdict.passed ? 'passed' : 'failed') },
      el('div', { class: 'review-line' }, el('span', { class: 'review-mark', 'aria-hidden': 'true' }, verdict.passed ? '✓' : '!'),
        el('span', {}, verdict.passed ? (minorNotes(verdict) ? 'Looks right. Small things: ' + minorNotes(verdict) : 'Checked: it is what was asked for.') : verdict.problem)),
      !verdict.passed && !take && !step.kept && step.retake && el('div', { class: 'row' },
        el('button', { class: 'btn small primary', disabled: working || step.retake.credits > balance,
          title: step.retake.why || 'Make it again with the fixed prompt', onclick: () => retake(step) }, `Retake · ${step.retake.credits} cr`),
        el('button', { class: 'btn small quiet', onclick: () => { step.kept = true; saveRuns(); drawLog(); } }, 'Keep it')),
      !verdict.passed && !take && !step.kept && !step.retake && el('span', { class: 'slate-text' }, 'No retake to offer for this one.'),
      step.kept && el('span', { class: 'slate-text' }, 'Kept with a known flaw.'),
      take && el('span', { class: 'slate-text' }, 'Take 2: ' + takeState));
  }

  const minorNotes = (verdict) => (verdict.checks || []).filter((c) => c.level === 'minor' && c.note).map((c) => c.note).join('; ');

  // The library item a job made, or null while it is not in the library yet.
  async function itemOf(jobId) {
    const made = (await api('/api/library')).items.find((i) => i.job_id === jobId);
    return made ? made.id : null;
  }

  // Look at a finished shot: the server takes its frames and the agent's model checks them against the prompt, the
  // references the shot was made with and, for a shot that continues another, the shot before.
  async function reviewStep(run, take, step, allowRetake) {
    take.reviewing = true;
    drawLog();
    try {
      take.made = take.made || await itemOf(take.job);
      if (!take.made) {   // not in the library yet: look again in a moment, a few times
        take.reviewing = false;
        take.tries = (take.tries || 0) + 1;
        if (take.tries < 5) setTimeout(reviewFinished, 4000); else take.reviewError = 'its result is not in the library.';
        drawLog();
        return;
      }
      const before = step.after ? run.steps[step.after.step] : null;
      const uses = (step.uses || []).map((use) => (use.asset ? { asset: use.asset } : { id: use.id }));
      const found = await api('/api/agent/review', { method: 'POST', json: {
        item: take.made, prompt: take.prompt || step.prompt, uses, previous: before ? before.made || null : null, retake: allowRetake } });
      take.review = found.verdict;
      if (allowRetake) step.retake = found.retake;
    } catch (e) {
      take.reviewError = e.message;
    }
    take.reviewing = false;
    saveRuns();
    drawLog();
  }

  // Review every shot of an approved plan that has just finished, once. Edits, sounds and motion graphics are not
  // reviewed: they are made from what the user already has.
  function reviewFinished() {
    for (const run of runs) {
      if (run.state !== 'approved') continue;
      for (const step of run.steps) {
        if (!step.settings) continue;
        for (const [take, first] of [[step, true], [step.take2, false]]) {
          if (!take || !take.job || take.review || take.reviewing || take.reviewError) continue;
          const job = store.jobs.find((j) => j.id === take.job);
          if (job && job.status === 'done' && Date.now() - (take.queuedAt || 0) < REVIEW_WITHIN) reviewStep(run, take, step, first);
        }
      }
    }
  }

  // The retake of a failed shot, approved by the user: the same workflow and settings with the prompt the review fixed.
  // One retake per shot.
  async function retake(step) {
    const plan = step.retake;
    step.take2 = { prompt: plan.prompt, queuedAt: Date.now() };
    drawLog();
    try {
      const settings = { ...plan.settings, refs: { ...(plan.settings.refs || {}) } };
      if (plan.start) {   // the review found that the cut jumps: the retake starts on the last frame of the shot before
        const ref = await api(`/api/library/${plan.start.id}/reference`, { method: 'POST' });
        settings.refs[plan.start.slot] = { comfy_name: ref.comfy_name, name: ref.name };
      }
      const data = new FormData();
      data.append('settings', JSON.stringify(settings));
      step.take2.job = (await api('/api/jobs', { method: 'POST', body: data })).id;
      onJobs(startedJobs());
      refreshJobs().catch(() => {});
    } catch (e) {
      step.take2.error = e.message;
    }
    saveRuns();
    drawLog();
  }

  const said = (text) => el('div', { class: 'agent-said' }, el('p', {}, text));
  // While the model works: the message, and under it the agent thinking.
  const thinking = () => el('div', { class: 'agent-run' }, said(pending.instruction),
    el('div', { class: 'agent-thinking', role: 'status', 'aria-live': 'polite' },
      el('span', { class: 'thinking-dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')), el('span', { class: 'thinking-word' }, 'Thinking')));

  // follow: something new arrived (a message, an answer), so the log goes to its end. Otherwise it stays where it is,
  // so opening a prompt or changing a setting does not move what is being looked at.
  function drawLog(follow = false) {
    const kept = log.scrollTop;
    if (!runs.length && !pending) {
      // A new conversation: a welcome, and a few ways to start that fill the message box.
      const starter = (text) => el('button', { type: 'button', class: 'agent-starter', onclick: () => {
        input.replaceChildren(document.createTextNode(text));
        input.focus();
        const end = document.createRange();
        end.selectNodeContents(input);
        end.collapse(false);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(end);
      } }, text);
      log.replaceChildren(el('div', { class: 'agent-welcome' },
        el('h2', {}, 'What are we making?'),
        el('p', { class: 'muted' }, 'Describe a shot, click a frame to attach it, or start from one of these. Nothing runs until you approve.'),
        el('div', { class: 'agent-starters' },
          starter('A 6 second shot of a fox crossing a snowy road at dawn'),
          starter('A product shot of a perfume bottle turning on black glass'),
          starter('Continue the selected shot for 5 more seconds'),
          starter('Plan a 3 shot ad for a coffee shop, portrait for Reels'))));
      return;
    }
    log.replaceChildren(...runs.map((run) => el('div', { class: 'agent-run' },
      said(run.instruction),
      el('div', { class: 'agent-turn' }, el('h3', { class: 'agent-label' }, run.steps.length ? `Plan · ${run.steps.length === 1 ? '1 step' : run.steps.length + ' steps'}` : 'Agent'),
        el('p', {}, run.reply),
        run.steps.length > 0 && el('div', { class: 'agent-plan' }, el('div', { class: 'step-list' }, run.steps.map((step) => drawStep(run, step))),
          run.state === 'proposed' && el('div', { class: 'agent-approve' },
            el('span', { class: 'slate-text' }, `${run.total} cr · you have ${Number(store.user.credits ?? 0)} cr`),
            el('span', { class: 'row' },
              el('button', { class: 'btn small quiet', onclick: () => { run.state = 'dismissed'; saveRuns(); drawLog(); } }, 'Dismiss'),
              el('button', { class: 'btn small primary', disabled: working || run.total > Number(store.user.credits ?? 0), onclick: () => approve(run) }, 'Approve'))),
          // An approved plan with steps still to carry out: it was interrupted, or a step failed. Resume goes on from there.
          run.state === 'approved' && !working && run.steps.some((step) => !step.job && !step.made) && el('div', { class: 'agent-approve' },
            el('span', { class: 'slate-text' }, 'Not every step was carried out.'),
            el('button', { class: 'btn small primary', onclick: () => approve(run) }, 'Resume')),
          run.state === 'dismissed' && el('div', { class: 'agent-approve' }, el('span', { class: 'slate-text' }, 'Dismissed. Nothing was made.')))))),
      ...(pending ? [thinking()] : []));
    log.scrollTop = follow ? log.scrollHeight : kept;
  }

  async function send() {
    const { text, shown: instruction, ids } = message();
    if (!text || busy) return;
    // "approve", "start", "go ahead" typed under a plan that waits for approval is the Approve button: the agent can
    // only propose, so asking it again would answer in words and make nothing.
    const waiting = runs[runs.length - 1];
    if (waiting && waiting.state === 'proposed' && !working && GO.test(text)) {
      if (waiting.total > Number(store.user.credits ?? 0)) return;   // the button is off too: the cost is shown under the plan
      input.replaceChildren();
      caret = null;
      return approve(waiting);
    }
    busy = true;
    // The message goes into the log at once, with the agent thinking under it; the box empties and waits.
    const typed = [...input.childNodes].map((n) => n.cloneNode(true));
    const controller = new AbortController();
    pending = { instruction, stop: () => controller.abort() };
    input.replaceChildren();
    input.contentEditable = 'false';
    caret = null;
    drawSend();
    drawLog(true);
    let made = null;
    try {
      const plan = await api('/api/agent/plan', { method: 'POST', signal: controller.signal,
        json: { instruction: text, project_id: projectId() || null, selection: ids, model: localStorage.getItem('scene.agent.model') || null,
          history: runs.slice(-RECALLED).map((r) => ({ instruction: r.instruction, reply: r.reply, steps: r.steps.map((s) => s.name) })) } });
      made = { instruction, reply: plan.reply, steps: plan.steps, total: plan.total, state: plan.steps.length ? 'proposed' : 'answered' };
      runs.push(made);
      saveRuns();
    } catch (e) {
      if (e.name === 'AbortError') input.replaceChildren(...typed);   // stopped: the message comes back to be changed or sent again
      else runs.push({ instruction, reply: e.message, steps: [], total: 0, state: 'answered' });
    }
    busy = false;
    pending = null;
    input.contentEditable = 'true';
    drawSend();
    drawLog(true);
    input.focus();
    // The permission chosen under the box: a plan may run at once, without waiting for Approve.
    if (made && made.steps.length && !working && made.total <= Number(store.user.credits ?? 0)) {
      const mode = permission().id;
      if (mode === 'all' || (mode === 'videos' && !made.steps.some((s) => s.kind === 'video'))) approve(made);
    }
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
          if (use.asset) {   // a saved asset from the agent's memory: the server takes it by its id
            settings.refs[use.slot] = { asset_id: use.asset, name: use.name };
            continue;
          }
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
        step.queuedAt = Date.now();
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
      const [saved, state] = await Promise.all([api(board(talk)), api('/api/agent/status')]);
      runs = saved.data.runs || [];
      onSaved({ spent: spentBy(runs, store.jobs), updated: null });   // what it spent, without counting as use
      for (const run of runs) for (const step of run.steps) {   // nothing is under way after a reload
        step.waiting = false; step.rendering = false; step.reviewing = false; step.updating = false; step.editing = false;
        if (step.take2) step.take2.reviewing = false;
      }
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
    drawLog(true);
  }

  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') reviewFinished();   // a shot the agent made has finished: it looks at it
    if (change === 'jobs' || change === 'credits') drawLog();
  });
  load();
  // attach(item): put a library item into the message. reload(): the project changed.
  return { node, attach, reload: load, focus: () => input.focus(),
    destroy: () => { unsubscribe(); document.removeEventListener('selectionchange', rememberCaret); } };
}
