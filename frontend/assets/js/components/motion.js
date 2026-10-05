// The form of one motion template in the Quick actions tab: its fields, the video it is laid over, and Render.
// Motion graphics are drawn from HTML templates and rendered on the studio's own machine. They are priced by the
// second of video, like everything else that is made.

import { api } from '../api.js';
import { el, icon, field } from '../dom.js';

const capital = (text) => String(text)[0].toUpperCase() + String(text).slice(1);

// The kinds of scene a motion video is made of, and what each one's boxes are for. `first` is the box that comes first.
const SCENE_KINDS = [
  { id: 'title', label: 'Title', heading: 'Heading', text: 'Line under it (optional)' },
  { id: 'statement', label: 'Statement', first: 'text', text: 'One sentence, shown large', heading: 'Small label above it (optional)' },
  { id: 'list', label: 'List', heading: 'Heading', items: true },
  { id: 'stat', label: 'Figure', heading: 'The figure, such as 42%', text: 'What it means' },
  { id: 'quote', label: 'Quote', first: 'text', text: 'The words', heading: 'Who said it (optional)' },
  { id: 'end', label: 'End', heading: 'Closing words', text: 'Line under it (optional)' },
];
const LOOKS = ['dark', 'light', 'warm', 'cool'];
const SHAPES = ['landscape', 'portrait', 'square'];
const MAX_SCENES = 12;

// What a render would cost, shown on its button. body(): what would be sent to the render. The server works the
// price out, because it is the server that sets how long each scene is.
function costMark(body) {
  const node = el('span', { class: 'cost' });
  let timer;
  const refresh = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const quote = await api('/api/motion/estimate', { method: 'POST', json: body() });
        node.textContent = quote.credits ? quote.credits + ' cr' : 'Free';
      } catch { node.textContent = ''; }   // nothing to price yet: the form is not filled in
    }, 300);
  };
  return { node, refresh };
}

// A whole motion graphics video: say what it is about and the agent's model writes it as scenes, which can then be
// changed, added to or written by hand. projectId(): the project the result is filed under. onBack(): leave the form.
export function sequenceForm({ projectId = () => null, onBack = () => {} }) {
  const state = { name: '', look: 'dark', shape: 'landscape', scenes: [] };   // a scene: {kind, heading, text, items}
  const list = el('div');
  const pills = el('div', { class: 'quick-pills' });
  const note = el('p', { class: 'error notice' });
  const label = el('span', {}, 'Render');
  const cost = costMark(() => ({ scenes: state.scenes, look: state.look, shape: state.shape }));
  const button = el('button', { class: 'btn generate', onclick: () => render() }, label, cost.node);
  const writeButton = el('button', { type: 'button', class: 'btn small agent', onclick: () => write() });
  const about = el('textarea', { rows: 4, 'aria-label': 'What the video is about',
    placeholder: 'What is the video about? For example: a short intro for a coffee shop called Ember, warm and friendly',
    onkeydown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) write(); } });
  const say = (text, ok = false) => { note.className = ok ? 'notice ok' : 'error notice'; note.textContent = text; };

  function sceneCard(scene, i) {
    const kind = SCENE_KINDS.find((k) => k.id === scene.kind);
    const box = (key, limit) => kind[key] && el('input', { type: 'text', maxlength: limit, placeholder: kind[key], 'aria-label': kind[key],
      value: scene[key], oninput: (e) => { scene[key] = e.target.value; cost.refresh(); } });
    const move = (by) => { state.scenes.splice(i + by, 0, state.scenes.splice(i, 1)[0]); draw(); };
    return el('div', { class: 'scene-card' },
      el('div', { class: 'scene-top' },
        el('span', { class: 'slate-text' }, i + 1),
        el('select', { class: 'small', 'aria-label': 'Kind of scene', onchange: (e) => { scene.kind = e.target.value; draw(); } },
          SCENE_KINDS.map((k) => el('option', { value: k.id, selected: k.id === scene.kind }, k.label))),
        el('span', { style: 'flex:1' }),
        el('button', { type: 'button', class: 'icon-btn', title: 'Move up', 'aria-label': 'Move up', disabled: i === 0, onclick: () => move(-1) }, '↑'),
        el('button', { type: 'button', class: 'icon-btn', title: 'Move down', 'aria-label': 'Move down', disabled: i === state.scenes.length - 1, onclick: () => move(1) }, '↓'),
        el('button', { type: 'button', class: 'icon-btn', title: 'Remove this scene', 'aria-label': 'Remove this scene',
          onclick: () => { state.scenes.splice(i, 1); draw(); } }, '×')),
      kind.first === 'text' ? [box('text', 170), box('heading', 70)] : [box('heading', 70), box('text', 170)],
      kind.items && el('textarea', { rows: 4, placeholder: 'One item on each line, up to 5', 'aria-label': 'Items',
        oninput: (e) => { scene.items = e.target.value.split('\n'); cost.refresh(); } }, scene.items.join('\n')));
  }

  function draw() {
    const full = state.scenes.length >= MAX_SCENES;
    list.replaceChildren(
      ...(state.scenes.length ? state.scenes.map(sceneCard)
        : [el('p', { class: 'muted small', style: 'margin-top:14px' }, 'No scenes yet. Have them written from what you typed above, or add them yourself.')]),
      el('button', { type: 'button', class: 'btn small', style: 'margin-top:10px', disabled: full,
        title: full ? `A video has at most ${MAX_SCENES} scenes` : 'Add a scene at the end',
        onclick: () => { state.scenes.push({ kind: state.scenes.length ? 'statement' : 'title', heading: '', text: '', items: [] }); draw(); } },
        icon('plus'), 'Add a scene'));
    const pill = (name, key, choices) => el('select', { class: 'opt', title: name, 'aria-label': name, onchange: (e) => { state[key] = e.target.value; } },
      choices.map((c) => el('option', { value: c, selected: c === state[key] }, `${name}: ${capital(c)}`)));
    pills.replaceChildren(pill('Look', 'look', LOOKS), pill('Shape', 'shape', SHAPES));
    writeButton.replaceChildren(state.scenes.length ? 'Write again' : 'Write scenes');
    writeButton.title = state.scenes.length ? 'Have the scenes written again. This replaces the ones below.' : 'Have the agent write the scenes of the video. Writing them costs nothing.';
    button.disabled = !state.scenes.length;
    cost.refresh();
  }

  async function write() {
    say('');
    const typed = about.value.trim();
    if (!typed) return say('Say what the video is about first.');
    if (writeButton.disabled) return;
    writeButton.disabled = true;
    writeButton.replaceChildren(el('i', { class: 'cell-mark stepping' }), 'Writing');
    try {
      const written = await api('/api/motion/scenes', { method: 'POST',
        json: { about: typed, project_id: projectId(), model: localStorage.getItem('scene.agent.model') || null } });
      Object.assign(state, { name: written.name, look: written.look, shape: written.shape,
        scenes: written.scenes.map((s) => ({ kind: s.kind, heading: s.heading, text: s.text, items: s.items })) });
    } catch (e) { say(e.message); }
    writeButton.disabled = false;
    draw();
  }

  async function render() {
    say('');
    if (button.disabled) return;
    button.disabled = true;
    label.replaceChildren(el('i', { class: 'cell-mark stepping' }), ' Rendering…');
    try {
      // The length of each scene is left to the server, which sets it from how much there is to read.
      await api('/api/motion/render', { method: 'POST',
        json: { scenes: state.scenes, look: state.look, shape: state.shape, name: state.name, project_id: projectId() } });
      say('Done. It is on the canvas.', true);
    } catch (e) { say(e.message); }
    label.replaceChildren('Render');
    button.disabled = !state.scenes.length;
  }

  const node = el('div', { class: 'quick' },
    el('div', { class: 'quick-head' },
      el('button', { class: 'icon-btn', title: 'Back to quick actions', 'aria-label': 'Back to quick actions', onclick: onBack }, icon('back')),
      el('b', {}, 'Motion video')),
    el('div', { class: 'quick-body' },
      el('p', { class: 'muted small' }, 'A whole video of animated words: titles, statements, lists, figures and quotes, one scene after another.'),
      el('div', { class: 'field' }, el('div', { class: 'label' }, 'About', el('span', { style: 'flex:1' }), writeButton), about),
      list, note),
    el('div', { class: 'quick-foot' }, pills, button));
  draw();
  return { node, refresh: () => {} };
}

// template: {id, title, description, needs, fields}. source(): the video selected on the canvas, or null.
// projectId(): the project the result is filed under, or null. onBack(): leave the form.
export function motionForm({ template, source = () => null, projectId = () => null, onBack = () => {} }) {
  const values = Object.fromEntries(template.fields.map((f) => [f.id, f.default ?? '']));
  const over = el('div');
  const note = el('p', { class: 'error notice' });
  const label = el('span', {}, 'Render');
  const cost = costMark(() => ({ template: template.id, values, source: template.needs === 'video' && source() ? source().id : null }));
  const button = el('button', { class: 'btn generate', onclick: () => render() }, label, cost.node);

  const input = (f) => (f.type === 'choice'
    ? el('select', { 'aria-label': f.label, onchange: (e) => { values[f.id] = e.target.value; cost.refresh(); } },
      f.choices.map((c) => el('option', { value: c, selected: String(c) === String(values[f.id]) },
        (f.names && f.names[c]) || (typeof c === 'number' ? c + (f.unit || '') : capital(c)))))
    : el('input', { type: 'text', maxlength: f.max || 200, placeholder: f.placeholder || '', value: values[f.id], 'aria-label': f.label,
      oninput: (e) => { values[f.id] = e.target.value; cost.refresh(); },
      onkeydown: (e) => { if (e.key === 'Enter') render(); } }));

  const node = el('div', { class: 'quick' },
    el('div', { class: 'quick-head' },
      el('button', { class: 'icon-btn', title: 'Back to quick actions', 'aria-label': 'Back to quick actions', onclick: onBack }, icon('back')),
      el('b', {}, template.title)),
    el('div', { class: 'quick-body' },
      el('p', { class: 'muted small' }, template.description),
      over,
      template.fields.map((f) => field(f.label, input(f))),
      note),
    el('div', { class: 'quick-foot' }, button));

  // The video the template is laid over is the one selected on the canvas.
  function drawSource() {
    cost.refresh();
    if (template.needs !== 'video') return over.replaceChildren();
    const item = source();
    over.replaceChildren(el('div', { class: 'quick-source' + (item ? '' : ' missing') },
      item ? ['Over ', el('b', {}, item.name)] : 'Select a video on the canvas. This is laid over it.'));
    button.disabled = !item;
  }

  async function render() {
    note.textContent = '';
    if (button.disabled) return;
    const item = template.needs === 'video' ? source() : null;
    button.disabled = true;
    label.replaceChildren(el('i', { class: 'cell-mark stepping' }), ' Rendering…');
    try {
      await api('/api/motion/render', { method: 'POST',
        json: { template: template.id, values, source: item ? item.id : null, project_id: projectId() } });
      note.className = 'notice ok';
      note.textContent = 'Done. It is on the canvas.';
    } catch (e) {
      note.className = 'error notice';
      note.textContent = e.message;
    }
    label.replaceChildren('Render');
    button.disabled = false;
    drawSource();
  }

  drawSource();
  return { node, refresh: drawSource };
}
