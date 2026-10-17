// The agent tab of the Canvas panel: a conversation. Each turn is the message, what the agent did and thought for it,
// its reply, and its plan: a card to approve, then what the plan made, which a click shows on the canvas.
// The agent only proposes. Nothing is queued or charged until Approve is pressed (or the permission says to go on).

import { api, apiLines } from '../api.js';
import { creditMark, el, icon, phaseOf, reel, still } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';
import { openViewer } from './media.js';
import { pickLibraryItem } from './assets.js';
import { chip, clock, fold, markdown, span, workRows } from './conversation.js';

const KEPT = 60;   // how many turns an agent tab keeps
const RECALLED = 40;   // how many earlier turns are sent along (the server keeps the newest that fit its budget)
// A message that only says to go ahead: under a plan that waits for approval it approves it.
const GO = /^\W*(approve|approved|start|go|go ahead|yes|ok|okay|proceed|generate|generate it|make it|do it|run it|confirm)\W*$/i;
const REVIEW_WITHIN = 24 * 3600 * 1000;   // a shot finished longer ago than this is not reviewed when the panel opens
// The studio's default model changed (to a local one, 17 October): a model picked before that is forgotten once, so
// everyone starts on the new default and can still pick another.
try {
  if (localStorage.getItem('scene.agent.model.v') !== '2') {
    localStorage.removeItem('scene.agent.model');
    localStorage.setItem('scene.agent.model.v', '2');
  }
} catch { /* storage may be blocked: the server's default is used anyway */ }
const LONG_REPLY = 700;   // a reply longer than this is folded to a few lines, with Show more
const MARK = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled', waiting: 'Waits for the step before' };
// Whether a plan runs as soon as it arrives or waits for Approve. The choice is this browser's, kept in localStorage.
const PERMISSIONS = [
  { id: 'all', icon: 'forward', label: 'Allow all', about: 'Never asks. The agent decides everything and plans run at once.' },
  { id: 'videos', icon: 'handvideo', label: 'Ask before videos', about: 'Runs images and audio. Asks before videos.' },
  { id: 'always', icon: 'hand', label: 'Always ask', about: 'Asks before every generation.' },
];
// Feel-good words shown under the dots while the agent is just thinking, shuffled every few seconds. A real phase the
// server names ("Looking at new pictures…") takes their place; these fill the plain "Thinking…" wait.
const WHIMSY = [
  'Imagining…', 'Daydreaming…', 'Dreaming up shots…', 'Sketching ideas…', 'Chasing the muse…', 'Brewing something good…',
  'Framing the scene…', 'Finding the light…', 'Scribbling storyboards…', 'Picturing it…', 'Warming up the lens…',
  'Mixing a little magic…', 'Letting it marinate…', 'Rolling the reels…', 'Casting the shot…', 'Painting with pixels…',
  'Humming a tune…', 'Tuning the vibe…', 'Thinking happy thoughts…', 'Connecting the dots…', 'Setting the stage…',
];
const SHAPES = [{ id: 'landscape', label: '16:9' }, { id: 'square', label: '1:1' }, { id: 'portrait', label: '9:16' }];
const SHAPE_NAMES = { landscape: '16:9', portrait: '9:16', square: '1:1' };
const KIND_ICONS = { video: 'video', image: 'image', audio: 'audio' };
const KIND_NAMES = { video: 'Video', image: 'Image', audio: 'Audio' };

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

// The "+" menu of a message box or a reference slot: where to take a file from. rows: [{icon, label, hint, run}].
export function addMenu(anchor, rows) {
  const box = popover(anchor, rows.map((row) => el('button', { type: 'button', class: 'pop-item add-menu-item', role: 'menuitem',
    onclick: () => { box.close(); row.run(); } }, icon(row.icon), el('span', { class: 'grow' }, row.label), row.hint && el('span', { class: 'add-menu-hint' }, row.hint))),
  'add-menu');
  const first = box.querySelector('button');
  if (first) first.focus();
  return box;
}

// What one conversation (or one turn of it) has spent, by what it made: {video, image, audio, llm, total}. A job that
// failed or was cancelled gave its credits back, so it is not counted. The agent's own model costs nothing yet.
export function spentBy(runs, jobs = []) {
  const spent = { video: 0, image: 0, audio: 0, llm: 0, total: 0 };
  const refunded = new Set(jobs.filter((j) => j.status === 'failed' || j.status === 'cancelled').map((j) => j.id));
  for (const run of runs || []) {
    const llm = (run.llm && run.llm.credits) || 0;   // what the messages to the agent's model cost
    spent.llm += llm;
    spent.total += llm;
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

const SPEND_KINDS = [['video', 'Video'], ['image', 'Image'], ['audio', 'Audio'], ['llm', 'LLM']];

// What was spent, by kind, in a card beside (or above) what was pointed at. It goes when the pointer leaves.
export function spendCard(anchor, spent, { above = false } = {}) {
  document.querySelectorAll('.agent-spend-card').forEach((c) => c.remove());
  const card = el('div', { class: 'agent-spend-card', role: 'tooltip' },
    ...SPEND_KINDS.map(([k, label]) => el('div', { class: spent[k] ? '' : 'none' }, el('span', {}, label), el('b', {}, (spent[k] || 0) + ' cr'))));
  document.body.append(card);
  const at = anchor.getBoundingClientRect();
  if (above) {
    Object.assign(card.style, { top: Math.max(8, at.top - card.offsetHeight - 8) + 'px',
      left: Math.max(8, Math.min(at.left, window.innerWidth - card.offsetWidth - 8)) + 'px' });
  } else {
    const right = at.right + 10 + card.offsetWidth < window.innerWidth;
    Object.assign(card.style, { top: Math.max(8, at.top + at.height / 2 - card.offsetHeight / 2) + 'px',
      left: (right ? at.right + 10 : Math.max(8, at.left - card.offsetWidth - 10)) + 'px' });
  }
  const gone = () => card.remove();
  anchor.addEventListener('pointerleave', gone, { once: true });
  anchor.addEventListener('blur', gone, { once: true });
}

// projectId(): the current project or 0. onJobs(ids): jobs the agent started. onMemory(): show the Shared memory tab.
// session: the agent tab this panel holds (its conversation is kept on its own). onSaved({spent, updated}): the
// conversation was saved, with what it has spent so far. onFocus(itemId): show that item on the canvas.
// locate(itemId): where the canvas has it, {shot, take}, or null.
// The page calls attach(item) when a frame is clicked: the item goes into the message as a chip, where the cursor is.
export function agentPanel({ projectId = () => 0, onJobs = () => {}, onMemory = null, session = null, onSaved = () => {},
  onFocus = () => {}, locate = () => null, selection = () => [], items = () => [], pickCanvas = null, onUploaded = () => {} } = {}) {
  let runs = [];       // the turns: {instruction, parts, reply, thought, activity, chips, steps, total, state, work, ui}
  let busy = false;       // a message is with the model
  let pending = null;     // the message being answered: {instruction, parts, stop, events, status, started}
  let working = false;    // an approved plan is being carried out, which can take minutes when steps wait for each other
  let noteFocus = null;   // the plan (by its time) whose "what to change" box has the cursor, kept across redraws
  let deferred = false;   // a redraw waits until a box being typed in is left

  const status = el('span', { class: 'agent-status slate-text' }, 'checking…');   // the model's name, or why it is offline
  // Which model answers, and what a message to it costs. The choice is this browser's, kept in localStorage.
  let models = { list: [], current: null, prices: {}, shown: (name) => name };
  const modelPicker = el('button', { type: 'button', class: 'agent-model-btn hidden', 'aria-haspopup': 'menu', title: 'The model the agent uses',
    onclick: () => openModels() });
  const priceText = (name) => (models.prices[name] ? `${models.prices[name]} cr a message` : 'Free');
  const drawModel = () => {
    modelPicker.replaceChildren(el('span', { class: 'agent-model-name' }, models.shown(models.current || '')), icon('down'));
    modelPicker.title = `The model the agent uses: ${models.shown(models.current || '')} · ${priceText(models.current)}`;
  };
  function openModels() {
    const box = popover(modelPicker, [el('div', { class: 'pop-title' }, 'Agent model'),
      ...models.list.map((name) => el('button', { type: 'button', class: 'pop-item', role: 'menuitemradio', 'aria-checked': String(name === models.current),
        onclick: () => { models.current = name; localStorage.setItem('scene.agent.model', name); drawModel(); box.close(); } },
        el('span', {}, el('b', {}, models.shown(name)), el('span', { class: 'muted small' }, priceText(name))),
        name === models.current ? icon('check') : el('span')))], 'pop-perm');
  }
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

  // Skills: the square box opens a picker with a search field; typing /name in the message filters the same list
  // inline. Choosing one puts /<id> at the start of the message, where the agent reads it. Fetched once.
  let skillList = null;
  let skillMenu = null;    // the floating panel element, or null while closed
  let skillMode = null;    // 'box' (opened from the button, has its own search) or 'slash' (filtered by the message)
  let skillSearch = '';    // the box's search text
  let skillRows = [];      // the skills shown now, in order, for moving with the keyboard
  let skillAt = 0;         // the highlighted row
  const RECENT_KEY = 'scene.agent.skills.recent';
  const recentIds = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; } };
  const pushRecent = (id) => { try { localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...recentIds().filter((x) => x !== id)].slice(0, 5))); } catch { /* storage off */ } };

  const skillsButton = el('button', { type: 'button', class: 'icon-btn agent-skills', 'aria-haspopup': 'listbox',
    title: 'Skills — or type /name', 'aria-label': 'Skills', onclick: () => toggleSkillBox() }, icon('skill'));

  async function ensureSkills() {
    if (!skillList) { try { skillList = (await api('/api/skills')).skills || []; } catch { skillList = []; } }
    return skillList;
  }
  // What the user is typing after a leading "/", or null when the message is not (any longer) a skill command.
  function slashQuery() {
    const m = /^\s*\/(\S*)$/.exec(input.textContent || '');   // a slash, some non-space, nothing after: still choosing
    return m ? m[1].toLowerCase() : null;
  }
  // The skills to show for a query, in groups. No query: recently used, then the rest.
  function skillGroups(query) {
    const all = skillList || [];
    const q = (query || '').trim().toLowerCase();
    if (q) {
      const hit = (s) => s.id.includes(q) || s.title.toLowerCase().includes(q) || (s.desc || '').toLowerCase().includes(q);
      return [{ label: 'Results', skills: all.filter(hit) }];
    }
    const recent = recentIds().map((id) => all.find((s) => s.id === id)).filter(Boolean);
    const groups = recent.length ? [{ label: 'Recently used', skills: recent }] : [];
    groups.push({ label: 'All skills', skills: all.filter((s) => !recent.includes(s)) });
    return groups;
  }
  function skillMenuBody(query) {
    const groups = skillGroups(query);
    skillRows = groups.flatMap((g) => g.skills);
    if (skillAt >= skillRows.length) skillAt = Math.max(0, skillRows.length - 1);
    const body = [];
    let i = 0;
    for (const g of groups) {
      body.push(el('div', { class: 'skillmenu-label' }, g.label));
      if (!g.skills.length) body.push(el('div', { class: 'skillmenu-empty muted small' }, 'No matches.'));
      for (const s of g.skills) {
        const idx = i++;
        body.push(el('button', { type: 'button', class: 'skillmenu-item' + (idx === skillAt ? ' on' : ''), role: 'option',
          'data-idx': String(idx), 'aria-selected': String(idx === skillAt),
          onmouseenter: () => { skillAt = idx; markSkill(); },
          onmousedown: (e) => { e.preventDefault(); activateSkill(s.id); } },
          el('span', { class: 'skillmenu-mark' }, icon('skill')),
          el('span', { class: 'skillmenu-text' }, el('b', {}, s.title), el('span', { class: 'skillmenu-desc' }, s.desc || ('/' + s.id))),
          el('code', { class: 'skillmenu-id' }, '/' + s.id)));
      }
    }
    body.push(el('a', { class: 'skillmenu-item skillmenu-foot', href: '#/skills',
      onmousedown: (e) => { e.preventDefault(); location.hash = '#/skills'; hideSkillMenu(); } },
      el('span', { class: 'skillmenu-mark' }, icon('grid')), el('span', { class: 'skillmenu-text' }, el('b', {}, 'See all skills'))));
    return body;
  }
  function markSkill() {
    if (!skillMenu) return;
    skillMenu.querySelectorAll('.skillmenu-item').forEach((n) => {
      const on = Number(n.dataset.idx) === skillAt;
      n.classList.toggle('on', on);
      n.setAttribute('aria-selected', String(on));
      if (on) n.scrollIntoView({ block: 'nearest' });
    });
  }
  function skillKey(e) {   // arrows, Enter/Tab, Escape while the menu is open; true when it handled the key
    if (!skillMenu) return false;
    if (e.key === 'ArrowDown') { e.preventDefault(); skillAt = Math.min(skillRows.length - 1, skillAt + 1); markSkill(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); skillAt = Math.max(0, skillAt - 1); markSkill(); return true; }
    if ((e.key === 'Enter' || e.key === 'Tab') && skillRows[skillAt]) { e.preventDefault(); activateSkill(skillRows[skillAt].id); return true; }
    if (e.key === 'Escape') { e.preventDefault(); hideSkillMenu(); return true; }
    return false;
  }
  const skillOutside = (e) => {
    if (skillMenu && !skillMenu.contains(e.target) && !skillsButton.contains(e.target) && !input.contains(e.target)) hideSkillMenu();
  };
  function openSkillMenu(mode) {
    hideSkillMenu();
    skillMode = mode;
    skillAt = 0;
    const list = el('div', { class: 'skillmenu-list' });
    // The search field is in both modes. In the box it is where you type; with /name the message drives it, and the
    // field shows and mirrors that text (still editable here too). skillSearch is the one filter either way.
    const search = el('input', { class: 'skillmenu-search', type: 'text', placeholder: 'Search all skills…', value: skillSearch,
      oninput: (e) => { skillSearch = e.target.value; skillAt = 0; list.replaceChildren(...skillMenuBody(skillSearch)); },
      onkeydown: (e) => skillKey(e) });
    const redraw = () => { if (search.value !== skillSearch) search.value = skillSearch; list.replaceChildren(...skillMenuBody(skillSearch)); };
    skillMenu = el('div', { class: 'agent-skillmenu', role: 'listbox' },
      el('div', { class: 'skillmenu-head' }, icon('search'), search), list);
    skillMenu._redraw = redraw;
    composer.prepend(skillMenu);
    redraw();
    if (mode === 'box') search.focus();   // with /name the message keeps focus, so you go on typing there
    document.addEventListener('pointerdown', skillOutside, true);
  }
  function hideSkillMenu() {
    if (!skillMenu) return;
    skillMenu.remove();
    skillMenu = null;
    skillMode = null;
    document.removeEventListener('pointerdown', skillOutside, true);
  }
  async function toggleSkillBox() {
    if (skillMenu && skillMode === 'box') { hideSkillMenu(); return; }
    await ensureSkills();
    skillSearch = '';
    openSkillMenu('box');
  }
  // Called as the message changes: open or refresh the inline menu while it reads like "/name", close it otherwise.
  async function onInputChanged() {
    const q = slashQuery();
    if (q === null) { if (skillMode === 'slash') hideSkillMenu(); return; }
    await ensureSkills();
    skillSearch = q;   // the text after the slash is the filter; the menu's search field mirrors it
    if (skillMode === 'slash' && skillMenu) skillMenu._redraw();
    else { skillAt = 0; openSkillMenu('slash'); }
  }
  function activateSkill(id) {
    useSkill(id);
    pushRecent(id);
    hideSkillMenu();
    input.focus();
  }
  // Put "/<id> " at the very start of the message (where the agent reads it) and leave the cursor after it.
  function useSkill(id) {
    const tag = '/' + id + ' ';
    const first = input.firstChild;
    if (first && first.nodeType === Node.TEXT_NODE) first.textContent = first.textContent.replace(/^\s*\/[a-z0-9-]*\s*/i, '');
    input.prepend(document.createTextNode(tag));
    input.focus();
    const range = document.createRange();
    range.setStart(input.firstChild, tag.length);
    range.collapse(true);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    rememberCaret();
  }

  // ------------------------------------------------------------ @name: attach a frame of the project by its name

  let mention = null;   // while "@name" is being typed: {menu, rows, at, node, start, end, query}
  // The "@words" just before the cursor, or null.
  function mentionQuery() {
    const sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return null;
    const { startContainer: node, startOffset: offset } = sel.getRangeAt(0);
    if (node.nodeType !== Node.TEXT_NODE || !input.contains(node)) return null;
    const m = /(?:^|\s)@([^\s@]{0,40})$/.exec(node.textContent.slice(0, offset));
    return m ? { node, start: offset - m[1].length - 1, end: offset, query: m[1].toLowerCase() } : null;
  }
  // The project's frames that fit what was typed, newest first, leaving out what is attached already.
  function mentionRows(query) {
    const taken = new Set(chipsIn().map((c) => Number(c.dataset.id)));
    return [...(items() || [])].reverse().filter((i) => !taken.has(i.id) && (!query || i.name.toLowerCase().includes(query))).slice(0, 8);
  }
  function drawMention() {
    const list = mention.rows.length ? mention.rows.map((item, idx) => el('button', { type: 'button', role: 'option',
      class: 'skillmenu-item mention-item' + (idx === mention.at ? ' on' : ''), 'aria-selected': String(idx === mention.at),
      onmouseenter: () => { mention.at = idx; drawMention(); },
      onmousedown: (e) => { e.preventDefault(); pickMention(item); } },
      el('span', { class: 'attach-thumb mention-thumb' }, still(`/api/library/${item.id}/file`, item.kind)),
      el('span', { class: 'skillmenu-text' }, el('b', {}, item.name), el('span', { class: 'skillmenu-desc' }, item.kind))))
      : [el('div', { class: 'skillmenu-empty muted small' }, 'No frame by that name in this project.')];
    mention.menu.replaceChildren(el('div', { class: 'skillmenu-label' }, 'Attach a frame'), ...list);
  }
  const mentionOutside = (e) => { if (mention && !mention.menu.contains(e.target) && !input.contains(e.target)) hideMention(); };
  function onMention() {
    const found = mentionQuery();
    if (!found) { hideMention(); return; }
    if (!mention) {
      mention = { menu: el('div', { class: 'agent-skillmenu agent-mentionmenu', role: 'listbox' }), at: 0 };
      composer.prepend(mention.menu);
      document.addEventListener('pointerdown', mentionOutside, true);
    }
    const rows = mentionRows(found.query);
    Object.assign(mention, found, { rows, at: Math.min(mention.at, Math.max(0, rows.length - 1)) });
    drawMention();
  }
  function hideMention() {
    if (!mention) return;
    mention.menu.remove();
    mention = null;
    document.removeEventListener('pointerdown', mentionOutside, true);
  }
  // The "@words" give way to the frame's chip, at the same place.
  function pickMention(item) {
    const range = document.createRange();
    range.setStart(mention.node, mention.start);
    range.setEnd(mention.node, mention.end);
    range.deleteContents();
    caret = range;
    hideMention();
    attach(item);
    drawSuggest();
  }
  function mentionKey(e) {   // arrows, Enter/Tab, Escape while the list is open; true when it handled the key
    if (e.key === 'ArrowDown') { e.preventDefault(); mention.at = Math.min(mention.rows.length - 1, mention.at + 1); drawMention(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); mention.at = Math.max(0, mention.at - 1); drawMention(); return true; }
    if ((e.key === 'Enter' || e.key === 'Tab') && mention.rows[mention.at]) { e.preventDefault(); pickMention(mention.rows[mention.at]); return true; }
    if (e.key === 'Escape') { e.preventDefault(); hideMention(); return true; }
    return false;
  }

  const log = el('div', { class: 'agent-log' });
  // A button to the newest message, while the conversation is scrolled up.
  const toEnd = el('button', { type: 'button', class: 'agent-to-end hidden', title: 'Go to the newest', 'aria-label': 'Go to the newest message',
    onclick: () => log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' }) }, icon('down'));
  const atEnd = () => log.scrollHeight - log.scrollTop - log.clientHeight < 48;
  log.addEventListener('scroll', () => toEnd.classList.toggle('hidden', log.scrollHeight - log.scrollTop - log.clientHeight < 160));
  // A drawing put off while a prompt or a name was being typed is done when the box is left.
  log.addEventListener('focusout', () => setTimeout(() => { if (deferred && !log.contains(document.activeElement)) drawLog(); }));

  // The message is typed text with chips in it, one per attached item, so the words around a chip say what it is for.
  const input = el('div', { class: 'agent-input', contenteditable: 'true', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Message',
    'data-placeholder': 'Ask the agent, or tell it what to make. Use + or type @ to attach a file.',
    onkeydown: (e) => {
      if (mention && mentionKey(e)) return;   // while typing @name, the keys drive the list of frames
      if (skillMode === 'slash' && skillKey(e)) return;   // while typing /name, the keys drive the inline menu
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (e.shiftKey) document.execCommand('insertLineBreak'); else send();
    },
    oninput: () => { onInputChanged(); onMention(); },
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
    input.dataset.placeholder = pending ? 'Waiting for response…' : 'Ask the agent, or tell it what to make. Use + or type @ to attach a file.';
  };
  drawSend();
  // What is selected on the canvas, offered as one suggestion: it is not part of the message until it is clicked.
  const suggest = el('button', { type: 'button', class: 'agent-suggest hidden', onclick: () => {
    for (const item of offered()) attach(item);
    drawSuggest();
  } });
  // "+": attach a file from the computer (it joins the project's library and canvas), from the canvas, or from the library.
  const upload = el('input', { type: 'file', accept: 'image/*,video/*,audio/*', multiple: true, hidden: true,
    onchange: async (e) => {
      const files = [...e.target.files];
      e.target.value = '';
      for (const file of files) {
        const data = new FormData();
        data.append('file', file, file.name);
        data.append('project_id', projectId() || '');
        try { attach(await api('/api/library/upload', { method: 'POST', body: data })); }
        catch (error) { alert(`${file.name}: ${error.message}`); }
      }
      if (files.length) { onUploaded(); drawSuggest(); input.focus(); }
    } });
  const addButton = el('button', { type: 'button', class: 'icon-btn agent-add', title: 'Attach', 'aria-label': 'Attach', 'aria-haspopup': 'menu',
    onclick: (e) => addMenu(e.currentTarget, [
      { icon: 'upload', label: 'Upload media or files', run: () => upload.click() },
      ...(pickCanvas ? [{ icon: 'grid', label: 'Select from canvas', run: () => pickCanvas((list) => { list.forEach(attach); drawSuggest(); input.focus(); }) }] : []),
      { icon: 'book', label: 'From library', run: async () => { const item = await pickLibraryItem(); if (item) { attach(item); drawSuggest(); input.focus(); } } },
    ]) }, icon('plus'));
  const composer = el('div', { class: 'agent-composer', onclick: (e) => { if (e.target === e.currentTarget) input.focus(); } }, input, upload,
    el('div', { class: 'agent-composer-bar' }, addButton, suggest, el('span', { style: 'flex:1' }), status, skillsButton, modelPicker, permButton, sendButton));
  // The approval bar of the newest plan waiting for approval sits here, on top of the message box, and does not
  // scroll with the conversation.
  const dock = el('div', { class: 'agent-dock hidden' });
  const node = el('div', { class: 'agent-panel' },
    el('div', { class: 'agent-log-wrap' }, log, toEnd), dock, composer);
  node.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pending) pending.stop(); });

  const board = (kind) => `/api/boards/${kind}?project=${projectId()}`;
  const keep = (kind, data) => api('/api/boards/' + kind, { method: 'PUT', json: { project: projectId() || null, data } });
  const talk = session ? 'agent-' + session : 'agent';   // the board this conversation is kept in
  const saveRuns = () => {
    onSaved({ spent: spentBy(runs, store.jobs), updated: Date.now() });
    return keep(talk, { runs: runs.slice(-KEPT) }).catch(() => {});
  };
  const startedJobs = () => runs.flatMap((r) => r.steps.flatMap((s) => [s.job, s.take2 && s.take2.job])).filter(Boolean);
  // A line of the work done for a plan after it was approved: queued, waited, ready, checked.
  const work = (run, glyph, text) => (run.work = run.work || []).push({ icon: glyph, text, at: Date.now() });
  const redraw = () => drawLog();

  // ------------------------------------------------------------ the message and its attached items

  const chipsIn = () => [...input.querySelectorAll('.attach')];

  // The selected items that are not in the message yet.
  const offered = () => (selection() || []).filter((item) => !chipsIn().some((c) => Number(c.dataset.id) === item.id)).slice(0, 8);
  function drawSuggest() {
    const list = offered();
    suggest.classList.toggle('hidden', !list.length || busy);
    if (!list.length) return;
    suggest.title = 'Add to the message: ' + list.map((i) => i.name).join(', ');
    suggest.replaceChildren(icon('plus'),
      el('span', { class: 'agent-suggest-thumbs' }, list.slice(0, 3).map((item) => el('span', { class: 'attach-thumb' }, still(`/api/library/${item.id}/file`, item.kind)))),
      el('span', {}, list.length === 1 ? `Use “${list[0].name}”` : `Use ${list.length} selected`));
  }

  // Put an item into the message as a chip, where the cursor was. An item that is already there is not added twice.
  function attach(item) {
    if (chipsIn().some((c) => Number(c.dataset.id) === item.id)) return;
    const tag = el('span', { class: 'attach', contenteditable: 'false', 'data-id': item.id, 'data-name': item.name, 'data-kind': item.kind, title: item.name },
      el('span', { class: 'attach-thumb' }, still(`/api/library/${item.id}/file`, item.kind)),
      el('span', { class: 'attach-name' }, item.name),
      el('button', { type: 'button', class: 'attach-drop', title: 'Remove', 'aria-label': `Remove ${item.name}`, tabindex: '-1',
        onclick: () => { tag.remove(); input.focus(); drawSuggest(); } }, '×'));
    const range = caret && input.contains(caret.startContainer) ? caret : null;
    const space = document.createTextNode(' ');
    if (range) {
      range.deleteContents();
      range.insertNode(space);
      range.insertNode(tag);
    } else input.append(tag, space);
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

  // The message as it is sent: each chip becomes its tag (@1, @2… in the order they appear), and the ids go along in
  // that order. shown is the same message with the names of the items, for the history the model reads; parts is the
  // message as the conversation shows it: words, and the items as small pictures.
  function message() {
    const ids = [];
    const parts = [];
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
    const walk = (nodes) => {
      for (const n of nodes) {
        if (n.nodeType === Node.TEXT_NODE) parts.push({ text: n.textContent.replace(/ /g, ' ') });
        else if (n.classList && n.classList.contains('attach')) parts.push({ id: Number(n.dataset.id), name: n.dataset.name, kind: n.dataset.kind || 'image' });
        else if (n.nodeName === 'BR') parts.push({ text: '\n' });
        else { walk(n.childNodes); if (n.nodeName === 'DIV') parts.push({ text: '\n' }); }
      }
    };
    walk(input.childNodes);
    const tidy = (text) => text.replace(/ /g, ' ').replace(/[ \t]+/g, ' ').trim();
    return { text: tidy(read(input.childNodes, false)), shown: tidy(read(input.childNodes, true)), ids, parts };
  }

  // ------------------------------------------------------------ the approval card: a plan's steps before they run

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
      const text = el('textarea', { class: 'agent-prompt-edit', rows: Math.min(18, Math.max(8, String(step.prompt).split('\n').length + 3)), 'aria-label': 'Prompt' }, step.prompt);
      setTimeout(() => text.focus());
      return el('div', { class: 'agent-prompt' }, text, el('div', { class: 'row' }, el('span', { style: 'flex:1' }),
        el('button', { class: 'btn small quiet', onclick: () => { step.editing = false; drawLog(); } }, 'Cancel'),
        el('button', { class: 'btn small primary', onclick: () => {
          step.editing = false;
          if (text.value.trim() && text.value.trim() !== step.prompt) changeStep(run, run.steps.indexOf(step), { prompt: text.value.trim() });
          else drawLog();
        } }, 'Save')));
    }
    return el('div', { class: 'agent-prompt' + (step.open ? ' open' : '') },
      step.open ? promptSections(step.prompt) : el('p', { class: 'small muted clamp' }, step.prompt),
      step.prompt && el('span', { class: 'agent-prompt-tools' },
        editable && el('button', { type: 'button', class: 'icon-btn small', title: 'Edit the prompt', 'aria-label': 'Edit the prompt',
          onclick: () => { step.editing = true; drawLog(); } }, icon('pencil')),
        el('button', { type: 'button', class: 'icon-btn small', title: step.open ? 'Show less' : 'Show the whole prompt',
          'aria-label': step.open ? 'Show less' : 'Show the whole prompt', onclick: () => { step.open = !step.open; drawLog(); } }, icon('expand'))));
  }

  // A whole prompt, opened: each part of its structure (SCENE CONTEXT, REFERENCES, ACTION, CAMERA…) on its own, its
  // heading picked out. A prompt that does not follow the structure is shown as it is.
  function promptSections(prompt) {
    const parts = [];
    for (const line of String(prompt || '').split('\n')) {
      const head = line.match(/^\s*([A-Z][A-Z &/]{2,40}):\s*(.*)$/);
      if (head) parts.push({ head: head[1], text: head[2] });
      else if (parts.length) parts[parts.length - 1].text += (parts[parts.length - 1].text ? '\n' : '') + line;
      else parts.push({ head: '', text: line });
    }
    return el('div', { class: 'prompt-sections' }, parts.filter((p) => p.head || p.text.trim()).map((p) =>
      el('div', { class: 'prompt-section' }, p.head && el('b', {}, p.head), el('p', {}, p.text.trim()))));
  }

  // The settings of a step as short words: model, shape, size, length, clips, quality.
  const tagsOf = (step) => {
    const current = step.current || {};
    return (step.settings
      ? [step.workflow_title, current.orientation && SHAPE_NAMES[current.orientation], current.resolution && current.resolution + 'p',
        current.duration && current.duration + 's', step.settings.clips > 1 && '× ' + step.settings.clips + ' clips',
        step.settings.options && step.settings.options.quality && step.settings.options.quality + ' quality']
      : [step.workflow_title, step.facts]).filter(Boolean);
  };
  const linksOf = (step) => [step.start && 'starts on ' + step.start.name, step.after && `continues step ${step.after.step + 1}`].filter(Boolean);

  // The assets a step uses, as small pictures with their names and the slot each one fills, so the user sees before
  // approving which character, place or voice goes into the shot. The picture it starts on comes first.
  function usesOf(step) {
    const shown = [
      step.start && { url: `/api/library/${step.start.id}/file`, kind: 'image', name: step.start.name, role: 'first frame' },
      ...(step.uses || []).map((use) => ({ url: use.asset ? `/api/assets/${use.asset}/file` : `/api/library/${use.id}/file`,
        kind: use.kind || 'image', name: use.name, role: use.label.toLowerCase().split(' (')[0] + (use.cast ? ' · cast' : ''), saved: !!use.asset })),
    ].filter(Boolean);
    if (!shown.length) return null;
    return el('div', { class: 'step-uses' }, shown.map((u) => el('div', { class: 'step-use', 'aria-label': `${u.name}: ${u.role}`,
      onmouseenter: (e) => previewUse(e.currentTarget, u), onmouseleave: hidePreview },
      el('span', { class: 'step-use-thumb' }, u.kind === 'image' ? still(u.url, 'image', u.name) : icon(u.kind === 'audio' ? 'audio' : 'video')),
      el('span', { class: 'step-use-words' }, el('b', {}, u.name), el('span', {}, u.role)))));
  }

  // A bigger look at an asset a step uses, while the pointer is on it. It is fixed to the page, so the scrolling log
  // does not cut it off, and it goes when the chip is gone (the log is drawn again while jobs move).
  let preview = null;
  function hidePreview() {
    if (!preview) return;
    preview.node.remove();
    window.removeEventListener('pointermove', preview.check);
    preview = null;
  }
  function previewUse(anchor, u) {
    hidePreview();
    const media = u.kind === 'image' ? el('img', { src: u.url, alt: u.name })
      : u.kind === 'audio' ? el('audio', { src: u.url, controls: true, preload: 'none' })
        : el('img', { src: u.saved ? u.url : u.url.replace(/\/file$/, '/poster'), alt: u.name });
    const node = el('div', { class: 'use-preview', role: 'tooltip' }, media, el('div', { class: 'use-preview-words' }, el('b', {}, u.name), el('span', {}, u.role)));
    document.body.append(node);
    const place = () => {
      const r = anchor.getBoundingClientRect();
      const w = node.offsetWidth, h = node.offsetHeight;
      const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left));
      const top = r.top - h - 8 >= 8 ? r.top - h - 8 : Math.min(window.innerHeight - h - 8, r.bottom + 8);
      node.style.left = left + 'px';
      node.style.top = top + 'px';
    };
    place();
    if (media.tagName === 'IMG' && !media.complete) media.addEventListener('load', place, { once: true });
    const check = () => { if (!anchor.isConnected || !anchor.matches(':hover')) hidePreview(); };
    window.addEventListener('pointermove', check);
    preview = { node, check };
  }

  // A step whose result is kept in shared memory under a name, for every agent tab and project to use.
  const keepOf = (step) => step.keep && el('div', { class: 'step-keep' }, icon('memory'),
    `Kept in shared memory as ${step.keep.tag === 'background' ? 'location' : step.keep.tag} “${step.keep.name}”`);

  // An amount of credits on an approval card: the Scene token and the number, in place of "cr".
  const tokens = (n) => el('span', { class: 'token-amount', title: `${n} credits` },
    creditMark('credits'), String(n));

  // One step of a plan waiting for approval (or one that was turned down): what it makes, its settings and its prompt.
  function drawStep(run, step) {
    const proposed = run.state === 'proposed';
    const chipState = step.updating ? ['running', 'Updating'] : step.error ? ['failed', 'Not changed'] : ['price', step.credits ? tokens(step.credits) : 'Free'];
    const glyph = step.motion ? 'title' : step.sound ? 'audio' : KIND_ICONS[step.kind] || 'video';
    const editable = proposed && step.menu && !step.editing;
    const links = linksOf(step);
    return el('div', { class: 'step-card ' + chipState[0] },
      el('div', { class: 'step-top' }, el('span', { class: 'step-thumb blank' + (step.updating ? ' working' : '') }, icon(glyph)),
        el('div', { class: 'step-title' },
          el('b', {}, step.name),
          !editable && el('div', { class: 'step-tags' }, tagsOf(step).map((t) => el('span', {}, t)))),
        // The price is shown once, in the Approve button; the corner only says when a step is being changed or could not be.
        chipState[0] !== 'price' && el('span', { class: 'step-chip ' + chipState[0] }, chipState[0] === 'running' && el('i', { class: 'cell-mark stepping' }), chipState[1])),
      editable && stepSettings(run, step),
      usesOf(step),
      links.length > 0 && el('div', { class: 'step-links' }, links.join(' · ')),
      keepOf(step),
      stepPrompt(run, step),
      // What the agent decided that the user did not say, and why: the length, the shape, the quality.
      step.why && el('div', { class: 'step-why' }, step.why),
      step.error && el('p', { class: 'small error' }, step.error));
  }

  // ------------------------------------------------------------ results: what an approved plan made

  // Where a step is: made, being made, waiting, failed, or not started.
  function progressOf(take, step) {
    if (take.made) return { state: 'done', text: 'Done' };
    if (take.error && !take.job) return { state: 'failed', text: 'Not made: ' + take.error };
    const job = take.job && store.jobs.find((j) => j.id === take.job);
    if (job) {
      if (job.status === 'running') {
        const share = job.steps ? (Math.max(job.clip, 1) - 1 + job.step / job.steps) / Math.max(job.clips, 1) : 0;
        return { state: 'running', share, text: job.steps ? phaseOf(share) : 'Setting up the shot' };
      }
      if (job.status === 'queued') return { state: 'queued', text: job.position ? `Waiting · ${job.position} in the queue` : 'Waiting' };
      if (job.status === 'failed') return { state: 'failed', text: 'Failed. The credits came back.' };
      if (job.status === 'cancelled') return { state: 'failed', text: 'Cancelled. The credits came back.' };
    }
    if (take.job) return { state: 'running', share: 1, text: 'Finishing' };
    if (step.waiting) return { state: 'queued', text: `Waits for step ${step.after.step + 1}` };
    return { state: 'queued', text: 'Not started' };
  }

  // The shape a result will have, so its place does not jump when it arrives.
  const shapeOf = (take, step) => {
    const made = take.madeInfo || {};
    return made.width && made.height ? [made.width, made.height] : step.shape || [16, 9];
  };
  const aspect = (take, step) => { const [w, h] = shapeOf(take, step); return `aspect-ratio:${w} / ${h}`; };
  // A result on its own is at most RESULT_HEIGHT tall and as wide as its shape makes it: a portrait clip is not
  // stretched across the panel with black on both sides.
  const RESULT_HEIGHT = 300;
  const sized = (take, step) => {
    const [w, h] = shapeOf(take, step);
    return `aspect-ratio:${w} / ${h};width:min(100%, ${Math.round((RESULT_HEIGHT * w) / h)}px)`;
  };

  const filmReel = (share) => { const r = reel(18); r.set(share); return r.node; };

  // What a step made: a picture, a still of a clip, or a sound. Clips are not played here: a click on a picture or a
  // clip shows it on the canvas, where it plays.
  function resultMedia(take, step) {
    const p = progressOf(take, step);
    if (p.state !== 'done') {
      // The animations are set to where they would be by the clock: the log is drawn again on every progress message,
      // and a glow or pulse that started over each time would jump.
      const clock = `--since:-${((Date.now() / 1000) % 12).toFixed(2)}s;`;
      return el('div', { class: 'result-wait ' + p.state, style: clock + (step.kind === 'audio' || p.state === 'failed' ? '' : sized(take, step)) },
        el('div', { class: 'result-wait-inner' },
          p.state === 'running' && filmReel(p.share),
          el('span', {}, p.text)));
    }
    const id = take.made;
    if (step.kind === 'audio') return el('div', { class: 'result-audio' }, el('audio', { src: `/api/library/${id}/file`, controls: true, preload: 'none' }));
    const video = step.kind !== 'image';
    const seconds = video && ((take.madeInfo && take.madeInfo.duration) || (step.current && step.current.duration));
    return el('button', { type: 'button', class: 'result-media', title: 'Show it on the canvas', style: sized(take, step), onclick: () => onFocus(id) },
      el('img', { src: video ? `/api/library/${id}/poster` : `/api/library/${id}/file`, alt: step.name, loading: 'lazy' }),
      video && el('span', { class: 'clip-badge' }, icon('play'), seconds ? `${Math.round(seconds)}s` : 'Video'));
  }

  // Three frames of a clip under it: the start, the middle and the end. A click shows the clip on the canvas.
  function keyframes(take, step) {
    if (!take.made || step.kind !== 'video') return null;
    const seconds = (take.madeInfo && take.madeInfo.duration) || ((step.current && step.current.duration) || 5) * ((step.settings && step.settings.clips) || 1);
    const times = [...new Set([0, seconds / 2, Math.max(0, seconds - 0.2)].map((t) => Math.round(t * 10) / 10))];
    return el('div', { class: 'keyframes' }, times.map((t) => el('button', { type: 'button', class: 'keyframe', title: `At ${clock(t)}: show the clip on the canvas`,
      onclick: () => onFocus(take.made) },
      el('img', { src: `/api/library/${take.made}/frame?at=${t}`, alt: '', loading: 'lazy', onerror: (e) => e.currentTarget.parentNode.remove() }),
      el('span', {}, clock(t)))));
  }

  // Thumbs on a result: saved with the item, and the agent reuses what was liked and never what was turned down.
  async function rate(run, take, value) {
    const before = take.rating || 0;
    take.rating = before === value ? 0 : value;
    drawLog();
    try { await api('/api/library/' + take.made, { method: 'PUT', json: { rating: take.rating } }); saveRuns(); } catch (e) { take.rating = before; drawLog(); }
  }
  const rating = (run, take) => el('span', { class: 'rate' },
    el('button', { type: 'button', class: 'icon-btn small' + (take.rating > 0 ? ' on' : ''), 'aria-pressed': String(take.rating > 0),
      title: 'Good: the agent will reuse it', 'aria-label': 'Thumbs up', onclick: () => rate(run, take, 1) }, icon('thumbup')),
    el('button', { type: 'button', class: 'icon-btn small' + (take.rating < 0 ? ' on bad' : ''), 'aria-pressed': String(take.rating < 0),
      title: 'Not good: the agent will not use it', 'aria-label': 'Thumbs down', onclick: () => rate(run, take, -1) }, icon('thumbdown')));

  // Where the result is on the canvas: "Shot 3 › Take 2", which takes you there.
  function crumb(take) {
    const where = locate(take.made);
    return el('button', { type: 'button', class: 'crumb', title: 'Show it on the canvas', onclick: () => onFocus(take.made) },
      icon(where ? 'branch' : 'target'), where ? `${where.shot} › Take ${where.take}` : 'Show on canvas');
  }

  // The prompt, the references and the settings a step was made with, folded under "Generation information".
  function information(step) {
    const references = [...(step.uses || []).map((use) => ({ url: use.asset ? `/api/assets/${use.asset}/file` : `/api/library/${use.id}/file`,
      kind: use.kind || 'image', name: use.name })), step.start && { url: `/api/library/${step.start.id}/file`, kind: 'image', name: step.start.name }].filter(Boolean);
    step.info = step.info || {};
    return fold({ glyph: 'film', title: 'Generation', sub: 'information', state: step.info, onToggle: redraw, className: 'info',
      body: [step.prompt && el('div', { class: 'agent-prompt' },
        el('p', { class: 'small muted' + (step.open ? '' : ' clamp') }, step.prompt),
        el('span', { class: 'agent-prompt-tools' }, el('button', { type: 'button', class: 'icon-btn small', title: step.open ? 'Show less' : 'Show the whole prompt',
          'aria-label': step.open ? 'Show less' : 'Show the whole prompt', onclick: () => { step.open = !step.open; drawLog(); } }, icon('expand')))),
      references.length > 0 && el('div', { class: 'info-refs' }, references.map((r) => el('span', { class: 'info-ref', title: r.name }, still(r.url, r.kind, r.name)))),
      el('div', { class: 'step-tags' }, tagsOf(step).map((t) => el('span', {}, t))),
      step.why && el('div', { class: 'step-why' }, step.why)] });
  }

  // One result: its information, the clip (or picture, or sound), its frames, where it is, the thumbs and the check.
  function resultBlock(run, step) {
    const p = progressOf(step, step);
    const kind = step.kind === 'image' || step.kind === 'audio' ? step.kind : 'video';
    return el('section', { class: 'result' },
      el('div', { class: 'result-head' }, el('i', { class: 'dot-state ' + p.state }), el('b', {}, KIND_NAMES[kind]),
        el('span', { class: 'muted' }, `· ${p.state === 'done' ? 1 : 0}/1`), el('span', { class: 'result-model' }, step.workflow_title || step.name)),
      information(step),
      el('div', { class: 'result-name' }, step.name),
      resultMedia(step, step),
      // A job that failed or was cancelled gave its credits back: the step can be queued again as it was.
      p.state === 'failed' && step.job && !working && el('div', { class: 'row' },
        el('button', { class: 'btn small', onclick: () => { step.job = null; step.queuedAt = null; step.error = null; approve(run); } }, 'Try again'),
        el('span', { class: 'slate-text' }, `${step.credits || 0} cr`)),
      keyframes(step, step),
      step.made && el('div', { class: 'result-foot' }, crumb(step), el('span', { style: 'flex:1' }), rating(run, step)),
      drawReview(run, step),
      step.take2 && el('div', { class: 'retake' }, el('div', { class: 'result-name' }, 'Take 2: ' + step.name),
        resultMedia(step.take2, step), keyframes(step.take2, step),
        step.take2.made && el('div', { class: 'result-foot' }, crumb(step.take2), el('span', { style: 'flex:1' }), rating(run, step.take2))));
  }

  // Pictures made by the steps of one plan, side by side: each opens on the canvas, ⓘ shows how it was made, ⤢ opens it large.
  function imageGrid(run, steps) {
    const done = steps.filter((s) => s.made).length;
    const states = steps.map((s) => progressOf(s, s).state);
    const state = done === steps.length ? 'done' : states.includes('running') ? 'running' : states.includes('failed') ? 'failed' : 'queued';
    const models = [...new Set(steps.map((s) => s.workflow_title).filter(Boolean))].join(', ');
    return el('section', { class: 'result' },
      el('div', { class: 'result-head' }, el('i', { class: 'dot-state ' + state }), el('b', {}, 'Image'),
        el('span', { class: 'muted' }, `· ${done}/${steps.length}`), models && el('span', { class: 'result-model' }, models)),
      el('div', { class: 'result-grid' + (steps.length === 1 ? ' one' : '') }, steps.map((step) => {
        const p = progressOf(step, step);
        if (p.state !== 'done') {
          return el('div', { class: 'res-tile wait ' + p.state, style: aspect(step, step) },
            p.state === 'running' && filmReel(p.share), el('span', {}, p.text));
        }
        return el('div', { class: 'res-tile', style: aspect(step, step) },
          el('button', { type: 'button', class: 'tile-media', title: `${step.name}: show it on the canvas`, onclick: () => onFocus(step.made) },
            el('img', { src: `/api/library/${step.made}/file`, alt: step.name, loading: 'lazy' })),
          el('button', { type: 'button', class: 'tile-btn info', title: 'How it was made', 'aria-label': 'How it was made',
            onclick: (e) => popover(e.currentTarget, [el('b', {}, step.name), el('p', { class: 'small muted' }, step.prompt),
              el('div', { class: 'step-tags' }, tagsOf(step).map((t) => el('span', {}, t)))], 'pop-info') }, icon('info')),
          el('button', { type: 'button', class: 'tile-btn open', title: 'Open it large', 'aria-label': 'Open it large', onclick: () => openLarge(step.made) }, icon('expand')),
          el('span', { class: 'tile-rate' }, rating(run, step)),
          step.review && el('span', { class: 'tile-check ' + (step.review.passed ? 'passed' : 'failed'),
            title: step.review.passed ? 'Checked: it is what was asked for' : step.review.problem }, step.review.passed ? '✓' : '!'));
      })),
      // What the agent found wrong with a picture, with its retake, under the grid.
      ...steps.filter((s) => s.reviewing || s.reviewError || (s.review && !s.review.passed)).map((s) =>
        el('div', { class: 'grid-review' }, el('b', {}, s.name), drawReview(run, s))));
  }

  async function openLarge(id) {
    try {
      const item = (await api('/api/library' + (projectId() ? '?project=' + projectId() : ''))).items.find((i) => i.id === id);
      if (item) openViewer(item, { actions: [] });
    } catch { /* nothing to open */ }
  }

  // What a plan made, in the order of its steps; pictures that come one after another share a grid.
  function results(run) {
    const blocks = [];
    let grid = null;
    for (const step of run.steps) {
      if (step.kind === 'image' && step.settings) {
        if (!grid) { grid = []; blocks.push(grid); }
        grid.push(step);
      } else {
        grid = null;
        blocks.push(step);
      }
    }
    return el('div', { class: 'results' }, blocks.map((b) => (Array.isArray(b) ? imageGrid(run, b) : resultBlock(run, b))));
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
          title: step.retake.why || 'Make it again with the fixed prompt', onclick: () => retake(run, step) }, `Retake · ${step.retake.credits} cr`),
        el('button', { class: 'btn small quiet', onclick: () => { step.kept = true; saveRuns(); drawLog(); } }, 'Keep it')),
      !verdict.passed && !take && !step.kept && !step.retake && el('span', { class: 'slate-text' }, 'No retake to offer for this one.'),
      step.kept && el('span', { class: 'slate-text' }, 'Kept with a known flaw.'),
      take && el('span', { class: 'slate-text' }, 'Take 2: ' + takeState));
  }

  const minorNotes = (verdict) => (verdict.checks || []).filter((c) => c.level === 'minor' && c.note).map((c) => c.note).join('; ');

  // The library item a job made, or null while it is not in the library yet.
  async function itemOf(jobId) {
    const made = (await api('/api/library' + (projectId() ? '?project=' + projectId() : ''))).items.find((i) => i.job_id === jobId);
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
      const which = take === step ? `“${step.name}”` : `the retake of “${step.name}”`;
      work(run, 'check', found.verdict.passed ? `Checked ${which}: it is what was asked for` : `Checked ${which}: ${found.verdict.problem}`);
      // The retake runs under the same permission the plan ran under: "Allow all" fixes a failed shot on its
      // own; "Ask before videos" fixes stills and audio on its own but asks before a video; "Always ask" shows
      // the Retake button and waits. Still one retake per shot, and never beyond the credits in hand.
      if (allowRetake && !found.verdict.passed && found.retake && !step.kept && !step.take2) {
        const mode = permission().id;
        const auto = mode === 'all' || (mode === 'videos' && step.kind !== 'video');
        // Reviews of a plan's shots run at once, so count credits already promised to other auto-retakes in this
        // burst (reservedCredits) as spent. retake() releases the reservation once it has lowered the real balance.
        const available = Number(store.user.credits ?? 0) - reservedCredits;
        if (auto && found.retake.credits <= available) {
          reservedCredits += found.retake.credits;
          work(run, 'retry', `Retaking ${which} on its own · ${found.retake.credits} cr`);
          retake(run, step, true);
        }
      }
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

  // Finished jobs become their library items: the result shows, with its frames and its place on the canvas.
  let collecting = false;
  async function collectResults() {
    if (collecting) return;
    const open = [];
    for (const run of runs) {
      for (const step of run.steps) {
        for (const take of [step, step.take2]) {
          if (!take || !take.job || take.made || (take.misses || 0) > 3) continue;
          const job = store.jobs.find((j) => j.id === take.job);
          if (!job || job.status === 'done') open.push([run, step, take]);
        }
      }
    }
    if (!open.length) return;
    collecting = true;
    try {
      const items = (await api('/api/library' + (projectId() ? '?project=' + projectId() : ''))).items;
      const byJob = new Map(items.filter((i) => i.job_id).map((i) => [i.job_id, i]));
      let found = false;
      for (const [run, step, take] of open) {
        const item = byJob.get(take.job);
        if (!item) { take.misses = (take.misses || 0) + 1; continue; }
        const c = item.context || {};
        take.made = item.id;
        take.madeInfo = { duration: c.duration ? c.duration * (c.clips || 1) : null, width: c.width || null, height: c.height || null };
        if (item.rating) take.rating = item.rating;
        work(run, 'ready', take === step ? `“${step.name}” is ready` : `The retake of “${step.name}” is ready`);
        found = true;
      }
      if (found) { saveRuns(); drawLog(); }
    } catch { /* the next update tries again */ }
    collecting = false;
  }

  // Credits promised to auto-retakes queued in the current review burst but not yet reflected in store.user.credits.
  let reservedCredits = 0;

  // The retake of a failed shot: the same workflow and settings with the prompt the review fixed. One retake per shot.
  // `reserved` is true when this retake was already counted against reservedCredits by the auto path above.
  async function retake(run, step, reserved = false) {
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
      // The server has now charged for this retake. Drop the local balance by the same amount so that another shot
      // reviewed in the same burst (under "Allow all") sees what is really left and does not over-commit; the next
      // store sync reconciles to the server's figure, and a failed job refunds as usual.
      if (store.user && Number.isFinite(plan.credits)) store.user.credits = Math.max(0, Number(store.user.credits ?? 0) - plan.credits);
      if (reserved && Number.isFinite(plan.credits)) reservedCredits = Math.max(0, reservedCredits - plan.credits);
      work(run, 'retry', `Queued a retake of “${step.name}”`);
      onJobs(startedJobs());
      refreshJobs().catch(() => {});
    } catch (e) {
      step.take2.error = e.message;
      if (reserved && Number.isFinite(plan.credits)) reservedCredits = Math.max(0, reservedCredits - plan.credits);   // queue failed: release the hold
    }
    saveRuns();
    drawLog();
  }

  // ------------------------------------------------------------ the conversation

  const pick = (table, id) => {
    if (table === 'item') return onFocus(id);
    const dialog = el('dialog', { class: 'asset-preview' },
      el('div', { class: 'asset-preview-media' }, el('img', { src: `/api/assets/${id}/file`, alt: '' })),
      el('div', { class: 'asset-preview-words' }, el('div', { class: 'dialog-buttons' },
        el('button', { class: 'btn small primary', onclick: () => dialog.close() }, 'Close'))));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
  };

  // The user's message: their words, and what they attached as small pictures that take you to the item.
  const said = (run) => {
    const parts = run.parts && run.parts.length ? run.parts : [{ text: run.instruction }];
    const length = parts.reduce((n, part) => n + (part.text || '').length, 0);
    const long = length > 320 || parts.reduce((n, part) => n + ((part.text || '').match(/\n/g) || []).length, 0) > 5;
    run.ui = run.ui || {};
    return el('div', { class: 'agent-said' },
      el('p', { class: long && !run.ui.saidMore ? 'clamped' : '' }, parts.map((part) => (part.id ? chip('item', part.id, part, pick) : document.createTextNode(part.text)))),
      long && el('button', { type: 'button', class: 'more-btn', onclick: () => { run.ui.saidMore = !run.ui.saidMore; drawLog(); } },
        run.ui.saidMore ? 'Show less' : 'Show more', el('span', { class: run.ui.saidMore ? 'flip' : '' }, icon('down'))));
  };

  // The words of a reply without the [[item:12]] marks, for copying.
  const plain = (run) => String(run.reply || '').replace(/\[\[(item|asset):(\d+)\]\]/g, (m, t, n) => ((run.chips || {})[`${t}:${n}`] || {}).name || '');

  function reply(run) {
    const long = run.reply.length > LONG_REPLY || run.reply.split('\n').length > 10;
    return el('div', { class: 'turn-reply' + (run.error ? ' error' : '') },
      el('div', { class: 'md' + (long && !run.ui.more ? ' clamped' : '') }, markdown(run.reply, run.chips || {}, pick)),
      long && el('button', { type: 'button', class: 'more-btn', onclick: () => { run.ui.more = !run.ui.more; drawLog(); } },
        run.ui.more ? 'Show less' : 'Show more', el('span', { class: run.ui.more ? 'flip' : '' }, icon('down'))));
  }

  // The newest plan that waits for approval: its bar goes in the dock.
  const docked = () => [...runs].reverse().find((r) => r.state === 'proposed') || null;

  // What to do with a plan: say what to change, Dismiss, or Approve with its price.
  function approveBar(run) {
    const balance = Number(store.user.credits ?? 0);
    const short = run.total > balance;
    // Instead of approving as it is, the user can say what to do differently ("make the cast first") and the agent
    // plans again with that. The draft lives on the run, since the bar is drawn again while jobs move.
    const change = el('button', { class: 'btn small primary' + (run.ui.note ? '' : ' hidden'), disabled: busy || working, onclick: () => revise(run) }, 'Send change');
    const go = el('button', { class: 'btn small primary' + (run.ui.note ? ' hidden' : ''), disabled: working || short, title: `You have ${balance} credits`,
      onclick: () => approve(run) }, 'Approve · ', tokens(run.total));
    const note = el('input', { type: 'text', class: 'approve-note', placeholder: short ? `Needs ${run.total} credits, you have ${balance}. Or say what to change…`
      : 'Want something different? e.g. make the assets first', 'aria-label': 'What to change in this plan', 'data-run': run.at,
      oninput: (e) => { run.ui.note = e.target.value; change.classList.toggle('hidden', !e.target.value.trim()); go.classList.toggle('hidden', !!e.target.value.trim()); },
      onfocus: () => { noteFocus = run.at; }, onblur: () => { if (noteFocus === run.at) noteFocus = null; },
      onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); revise(run); } } });
    note.value = run.ui.note || '';
    if (noteFocus === run.at) requestAnimationFrame(() => { note.focus(); note.setSelectionRange(note.value.length, note.value.length); });
    return el('div', { class: 'agent-approve' }, note,
      el('span', { class: 'row' },
        el('button', { class: 'btn small quiet', onclick: () => { run.state = 'dismissed'; saveRuns(); drawLog(); } }, 'Dismiss'),
        change, go));
  }

  // The dock above the message box: the newest plan waiting for approval, its steps and its bar, or nothing. While the
  // user types in it (the change box, a prompt being edited) it is left as it is, so the redraws that follow jobs do not
  // take the cursor away. A long plan scrolls inside the dock; where it was scrolled to is kept.
  function drawDock() {
    drawSuggest();   // drawn with the log: a tab shown again, a message sent or answered
    const run = pending ? null : docked();
    const typing = document.activeElement && dock.contains(document.activeElement) && document.activeElement.matches('input, textarea');
    if (run && dock.dataset.run === String(run.at) && typing) return;
    const steps = dock.querySelector('.agent-dock-steps');
    const scrolled = run && dock.dataset.run === String(run.at) && steps ? steps.scrollTop : 0;
    dock.dataset.run = run ? String(run.at) : '';
    dock.replaceChildren(...(run ? [el('div', { class: 'agent-dock-steps' }, el('div', { class: 'step-list' }, run.steps.map((step) => drawStep(run, step)))),
      approveBar(run)] : []));
    if (scrolled) dock.querySelector('.agent-dock-steps').scrollTop = scrolled;
    dock.classList.toggle('hidden', !run);
  }

  // The plan of a turn: the card to approve, what it made once approved, or, turned down, a folded "Cancelled".
  function plan(run) {
    if (run.state === 'dismissed') {
      return fold({ glyph: 'film', title: 'Generation', sub: run.revised ? 'Changed' : 'Cancelled', state: (run.ui.cancelled = run.ui.cancelled || {}), onToggle: redraw,
        className: 'cancelled', body: el('div', { class: 'step-list' }, run.steps.map((step) => drawStep(run, step))) });
    }
    if (run.state === 'proposed') {
      // The newest plan waiting for approval is in the dock above the message box, its steps and its bar; an older
      // plan still waiting stays here with its own bar.
      if (run === docked()) return null;
      return el('div', { class: 'agent-plan' }, el('div', { class: 'step-list' }, run.steps.map((step) => drawStep(run, step))), approveBar(run));
    }
    return el('div', { class: 'agent-plan' }, results(run),
      // An approved plan with steps still to carry out: it was interrupted, or a step failed. Resume goes on from there.
      run.state === 'approved' && !working && run.steps.some((step) => !step.job && !step.made) && el('div', { class: 'agent-approve' },
        el('span', { class: 'slate-text' }, 'Not every step was carried out.'),
        el('button', { class: 'btn small primary', onclick: () => approve(run) }, 'Resume')));
  }

  // One turn: the message, what the agent did and thought, its reply, its plan, the work after approval, and its cost.
  function turn(run) {
    run.ui = run.ui || {};
    const ui = run.ui;
    const done = run.activity || [];
    const thoughts = done.filter((e) => e.type === 'thought');
    const thought = thoughts[thoughts.length - 1];
    const before = done.filter((e) => e !== thought);
    const lastStep = [...before].reverse().find((e) => e.type === 'activity');
    const after = run.work || [];
    return el('div', { class: 'turn' },
      said(run),
      before.length > 0 && fold({ glyph: 'wrench', title: `Worked ${span(run.seconds != null ? run.seconds : (lastStep || {}).at)}`, sub: lastStep ? lastStep.text : '',
        state: (ui.work = ui.work || {}), onToggle: redraw, className: 'work', body: workRows(before, (ui.workItems = ui.workItems || {}), redraw) }),
      thought && fold({ glyph: 'bulb', title: `Thought for ${span(thought.seconds)}`, state: (ui.thought = ui.thought || {}), onToggle: redraw,
        className: 'thought', body: thought.text ? el('p', { class: 'fold-text' }, thought.text) : null }),
      run.reply && reply(run),
      run.steps.length > 0 && plan(run),
      after.length > 0 && fold({ glyph: 'wrench', title: `Worked ${span((after[after.length - 1].at - (run.approvedAt || after[0].at)) / 1000)}`,
        sub: after[after.length - 1].text, state: (ui.after = ui.after || {}), onToggle: redraw, className: 'work',
        body: workRows(after.map((w) => ({ type: 'activity', icon: w.icon, text: w.text })), {}, redraw) }),
      run.reply && !run.error && el('div', { class: 'turn-foot' },
        el('button', { type: 'button', class: 'icon-btn small', title: 'Copy the reply', 'aria-label': 'Copy the reply',
          onclick: (e) => { navigator.clipboard.writeText(plain(run)).then(() => { e.currentTarget.classList.add('done'); }).catch(() => {}); } }, icon('copy'))));
  }

  // The word under the dots: a phase the server named, or, for a plain "Thinking" wait, a feel-good word that shuffles.
  let whimsyAt = Math.floor(Math.random() * WHIMSY.length);
  let whimsyTimer = null;
  function thinkingWord(p) {
    if (p.status && !/^thinking/i.test(p.status)) return p.status;   // a real phase the server named wins
    return WHIMSY[whimsyAt % WHIMSY.length];
  }
  function startWhimsy() {
    stopWhimsy();
    whimsyTimer = setInterval(() => { whimsyAt += 1; drawLive(); }, 2600);
  }
  function stopWhimsy() { if (whimsyTimer) { clearInterval(whimsyTimer); whimsyTimer = null; } }

  // The turn being answered: the message, the agent's work as it happens, and what it is doing now.
  let live = null;
  function liveTurn() {
    const p = pending;
    const steps = p.events.filter((e) => e.type === 'activity');
    const thoughts = p.events.filter((e) => e.type === 'thought');
    return el('div', { class: 'turn live' }, said(p),
      steps.length > 0 && el('div', { class: 'fold work open' },
        el('div', { class: 'fold-head' }, icon('wrench'), el('span', { class: 'fold-title' }, 'Working'),
          el('span', { class: 'fold-sub' }, span((Date.now() - p.started) / 1000))),
        el('div', { class: 'fold-body' }, workRows(steps, {}, redraw))),
      ...thoughts.map((t) => fold({ glyph: 'bulb', title: `Thought for ${span(t.seconds)}`, className: 'thought' })),
      el('div', { class: 'agent-thinking', role: 'status', 'aria-live': 'polite' },
        el('span', { class: 'thinking-dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')),
        el('span', { class: 'thinking-word' }, thinkingWord(p).replace(/…$/, ''))));
  }
  function drawLive() {
    if (!pending || !live || !live.isConnected) return;
    const stick = atEnd();
    const next = liveTurn();
    live.replaceWith(next);
    live = next;
    if (stick) log.scrollTop = log.scrollHeight;
  }
  const ticker = setInterval(() => { if (pending) drawLive(); }, 1000);

  // follow: something new arrived (a message, an answer), so the log goes to its end. Otherwise it stays where it is,
  // so opening a fold or changing a setting does not move what is being looked at.
  function drawLog(follow = false) {
    const active = document.activeElement;
    if (!follow && active && log.contains(active) && active.matches('textarea, input')) { deferred = true; return; }
    deferred = false;
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
      drawDock();
      log.replaceChildren(el('div', { class: 'agent-welcome' },
        el('h2', {}, 'What are we making?'),
        el('p', { class: 'muted' }, 'Describe a shot, press + to attach a file, or start from one of these. Nothing runs until you approve.'),
        el('div', { class: 'agent-starters' },
          starter('A 6 second shot of a fox crossing a snowy road at dawn'),
          starter('A product shot of a perfume bottle turning on black glass'),
          starter('Continue the selected shot for 5 more seconds'),
          starter('Plan a 3 shot ad for a coffee shop, portrait for Reels'))));
      return;
    }
    live = pending ? liveTurn() : null;
    drawDock();
    log.replaceChildren(...runs.map(turn), ...(live ? [live] : []));
    log.scrollTop = follow ? log.scrollHeight : kept;
    toEnd.classList.toggle('hidden', log.scrollHeight - log.scrollTop - log.clientHeight < 160);
  }

  // What the user typed under a plan instead of approving it: the plan is set aside and the agent plans again with the
  // change. A note that only says to go ahead is the Approve button.
  function revise(run) {
    const note = String(run.ui.note || '').trim();
    if (!note || busy || working || run.state !== 'proposed') return;
    run.ui.note = '';
    noteFocus = null;
    if (GO.test(note)) {
      if (run.total <= Number(store.user.credits ?? 0)) approve(run);
      return;
    }
    run.state = 'dismissed';
    run.revised = note;
    saveRuns();
    send({ text: `Change the plan you just proposed (it was not run): ${note}`, shown: note, ids: [], parts: [{ text: note }], from: run });
  }

  // `typed`: a message that did not come from the box (a change asked for under a plan); the box is then left alone.
  async function send(typed) {
    const fromBox = !typed;
    const { text, shown: instruction, ids: attached, parts } = typed || message();
    if (!text || busy) return;
    // Nothing attached: the canvas selection goes along, and the server reads it only when the words point at it
    // ("make this darker", "join these").
    const ids = attached.length || !fromBox ? attached : (selection() || []).map((item) => item.id).slice(0, 8);
    // "approve", "start", "go ahead" typed under a plan that waits for approval is the Approve button: the agent can
    // only propose, so asking it again would answer in words and make nothing.
    const waiting = runs[runs.length - 1];
    if (fromBox && waiting && waiting.state === 'proposed' && !working && GO.test(text)) {
      if (waiting.total > Number(store.user.credits ?? 0)) return;   // the button is off too: the cost is shown under the plan
      input.replaceChildren();
      caret = null;
      return approve(waiting);
    }
    busy = true;
    // The message goes into the log at once, with the agent's work under it as it happens; the box empties and waits.
    const boxed = [...input.childNodes].map((n) => n.cloneNode(true));
    const controller = new AbortController();
    pending = { instruction, parts, stop: () => controller.abort(), events: [], status: 'Thinking', started: Date.now() };
    startWhimsy();
    if (fromBox) input.replaceChildren();
    input.contentEditable = 'false';
    caret = null;
    drawSend();
    drawLog(true);
    let made = null;
    try {
      let answer = null;
      await apiLines('/api/agent/plan', { signal: controller.signal, json: { instruction: text, project_id: projectId() || null, selection: ids,
        model: localStorage.getItem('scene.agent.model') || null,
        history: runs.slice(-RECALLED).map((r) => ({ instruction: r.instruction, reply: r.reply,
          steps: r.steps.map((s) => ({ name: s.name, uses: (s.uses || []).map((u) => u.name) })) })) } }, (event) => {
        if (event.type === 'error') throw new Error(event.message);
        if (event.type === 'plan') answer = event;
        else if (event.type === 'status') pending.status = event.text;
        else pending.events.push(event);
        drawLive();
      });
      if (!answer) throw new Error('The agent stopped before it finished. Try again.');
      made = { instruction, parts, reply: answer.reply, thought: answer.thought, activity: answer.activity || [], seconds: answer.seconds,
        chips: answer.chips || {}, steps: answer.steps, total: answer.total, state: answer.steps.length ? 'proposed' : 'answered', at: Date.now(), ui: {},
        llm: answer.llm || null };
      if (store.user && answer.balance != null) { store.user.credits = answer.balance; }   // the message itself may have cost credits
      runs.push(made);
      saveRuns();
    } catch (e) {
      if (e.name === 'AbortError') {   // stopped: the message comes back to be changed or sent again
        if (fromBox) input.replaceChildren(...boxed);
        else if (typed.from) { typed.from.state = 'proposed'; typed.from.revised = null; typed.from.ui.note = instruction; saveRuns(); }
      }
      else runs.push({ instruction, parts, reply: e.message, error: true, activity: pending.events, steps: [], total: 0, state: 'answered', at: Date.now(), ui: {} });
    }
    stopWhimsy();
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
        const made = await itemOf(step.job);
        if (made) return made;
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
    run.approvedAt = run.approvedAt || Date.now();
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
          work(run, 'queue', `Started “${step.name}”`);
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
          work(run, 'wait', `Waited for “${run.steps[step.after.step].name}”`);
          const ref = await api(`/api/library/${earlier}/reference`, { method: 'POST' });
          settings.refs[step.after.slot] = { comfy_name: ref.comfy_name, name: ref.name };
          settings.parent = earlier;
        }
        const data = new FormData();
        data.append('settings', JSON.stringify(settings));
        step.job = (await api('/api/jobs', { method: 'POST', body: data })).id;
        step.queuedAt = Date.now();
        work(run, 'queue', `Queued “${step.name}”`);
        onJobs(startedJobs());
      } catch (e) {
        step.error = e.message;
        work(run, 'warn', `“${step.name}” was not made: ${e.message}`);
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
      for (const run of runs) {
        run.ui = run.ui || {};
        for (const step of run.steps) {   // nothing is under way after a reload
          step.waiting = false; step.rendering = false; step.reviewing = false; step.updating = false; step.editing = false;
          if (step.take2) step.take2.reviewing = false;
        }
      }
      // The models there are, and what a message to each costs; offline, just why.
      const names = state.online ? state.models || [] : [];
      const picked = localStorage.getItem('scene.agent.model');
      const current = names.includes(picked) ? picked : state.model;
      // A hosted model is named "<service>/<name>"; it is shown as its name and the service it is asked of.
      const services = Object.fromEntries((state.hosted || []).map((s) => [s.id, s.name]));
      const shown = (name) => { const [sid, ...rest] = name.split('/'); return rest.length && services[sid] ? `${rest.join('/')} · ${services[sid]}` : name; };
      models = { list: names, current, prices: state.prices || {}, shown };
      drawModel();
      modelPicker.classList.toggle('hidden', !names.length);
      status.classList.toggle('hidden', state.online && names.length > 0);
      status.textContent = state.online ? shown(state.model) : 'offline';
      status.title = state.online ? '' : state.detail;
      status.classList.toggle('error', !state.online);
      onJobs(startedJobs());
    } catch (e) { status.textContent = e.message; }
    drawLog(true);
    collectResults();
  }

  const unsubscribe = subscribe((change) => {
    if (change === 'jobs') {
      collectResults();   // a shot the agent made has finished: it shows, and the agent looks at it
      reviewFinished();
      onSaved({ spent: spentBy(runs, store.jobs), updated: null });   // a job that failed gave its credits back
    }
    if (change === 'jobs' || change === 'credits') drawLog();
  });
  load();
  // selectionChanged(): what is selected on the canvas changed, so the suggestion is drawn again.
  // attach(item): put a library item into the message. reload(): the project changed. redraw(): the canvas moved
  // things, so where each result is ("Shot 3 › Take 2") is drawn again.
  return { node, attach: (item) => { attach(item); drawSuggest(); }, selectionChanged: drawSuggest, reload: load, redraw: () => drawLog(), focus: () => input.focus(),
    destroy: () => { unsubscribe(); clearInterval(ticker); stopWhimsy(); hideSkillMenu(); hideMention(); document.removeEventListener('selectionchange', rememberCaret); } };
}
