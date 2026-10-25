// The landing page: what a visitor who is not signed in sees at the site's address. The first screen is a camera
// monitor on the set: the frame is a scene, with frame lines, a timecode that runs, the lens and light readouts, and a
// slate where the plan of the shot types itself. Picking another scene cuts the whole set. Below it, plain sections in
// the monitor's language: the take report, the agent, what is on the cart, the price, and the cut. Everything it shows
// is something the studio does; the pictures are drawn as SVG (landing-scenes.js), so the page needs no media files.

import { el } from '../dom.js';
import * as scenes from './landing-scenes.js';

// What can be made, with the models that make it. Kept in step with workflows/ (see docs/HANDOVER.md, Workflows).
const KIT = [
  ['Video', 'Clips with sound', 'MiniMax H3', 'Clips of 5 to 15 seconds from a prompt and up to eight references: a character, an outfit, a place, a motion to copy, a voice. Chain clips into longer scenes that pick up where the last one ended.'],
  ['Images', 'Stills and posters', 'FLUX.2 · FLUX 3 Klein · Qwen Image 2.1', 'Stills from a prompt and up to four reference pictures, so a character looks the same in every one.'],
  ['Music', 'Songs and scores', 'MiniMax Music 3', 'From 30 seconds to 5 minutes, with your lyrics or without.'],
  ['Titles', 'Motion graphics', 'Drawn in the studio', 'Title cards, lower thirds and whole videos of animated words, written from a sentence and editable scene by scene.'],
  ['Finish', 'Upscale', 'SeedVR2', 'A finished video made larger and sharper, up to four times its size.'],
];

const STEPS = [
  ['Describe the shot', 'Write what happens and add reference pictures. Pin a cast to the project, and the same face, outfit and place carry from shot to shot.'],
  ['Make takes on the canvas', 'Every result lands on a board, one row per shot. Start the next clip from the last frame of one you like, or roll it again with a new seed.'],
  ['Cut it together', 'Put clips in order on the timeline, trim them, add music, and export one video.'],
];

// The camera's readouts for each scene: lens and stop, sensitivity and shutter, colour temperature.
const READOUT = { rooftop: ['35mm · T2.0', 'ISO 800 · 1/48', '3200K'], neon: ['24mm · T1.4', 'ISO 1600 · 1/48', '5600K'],
  desert: ['85mm · T5.6', 'ISO 100 · 1/96', '6500K'], deep: ['18mm · T2.8', 'ISO 3200 · 1/48', '4300K'] };

// Four takes of one shot for the take report: what each was, and the one that was kept.
const TAKES = [['rooftop', 'Take 1', '6.0 s', 'Rejected · face', 'dull'], ['rooftop', 'Take 2', '6.0 s', 'Soft focus', 'soft'],
  ['rooftop', 'Take 3', '6.0 s', 'Kept', 'kept'], ['neon', 'Take 4', '5.0 s', 'New seed', '']];

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// A picture the studio draws: one of the landing scenes, filling its box. The markup is the page's own, never anyone's input.
function picture(name, cls = '', sketch = false) {
  const node = el('div', { class: cls, 'aria-hidden': 'true' });
  node.innerHTML = scenes.svg(name, { sketch });
  return node;
}

// The frame counter of the camera: hours, minutes, seconds and frames at 24 a second, from one hour in.
function timecode(frames) {
  const two = (n) => String(n).padStart(2, '0');
  return `${two(Math.floor(frames / 86400) % 24)}:${two(Math.floor(frames / 1440) % 60)}:${two(Math.floor(frames / 24) % 60)}:${two(frames % 24)}`;
}

function monitor(join, signupOpen) {
  const frames = [el('div', { class: 'la-frame' }), el('div', { class: 'la-frame out' })];
  let shown = 0, current = -1, touched = false, typing = null;
  const tc = el('span', { class: 'la-rec' }, '01:00:00:00');
  const lens = el('span'), iso = el('span'), wb = el('span');
  const sceneName = el('span');
  const typed = el('div', { class: 'la-typed' });
  const rows = el('ol');
  const buttons = scenes.names.map((name, i) => el('button', { type: 'button', 'aria-pressed': 'false',
    onclick: () => { touched = true; cut(i); } }, `${i + 1} · ${scenes.info(name).title}`));

  function type(text) {
    clearInterval(typing);
    if (still()) { typed.textContent = text; return; }
    let n = 0;
    typing = setInterval(() => { typed.textContent = text.slice(0, ++n); if (n >= text.length) clearInterval(typing); }, 32);
  }
  // Cut to a scene: the new frame fades in over the old, and the readouts, the slate and its plan change with it.
  function cut(i) {
    if (i === current) return;
    current = i;
    const name = scenes.names[i], info = scenes.info(name);
    const next = 1 - shown;
    frames[next].innerHTML = scenes.svg(name);
    frames[next].classList.remove('out');
    frames[shown].classList.add('out');
    shown = next;
    [lens.textContent, iso.textContent, wb.textContent] = READOUT[name];
    sceneName.textContent = `Scene 0${i + 1} · ${info.title}`;
    rows.replaceChildren(...info.shots.map((shot, n) => el('li', {}, el('span', {}, `0${n + 1}`), el('span', {}, shot), el('span', {}, '60 cr'))));
    buttons.forEach((b, n) => b.setAttribute('aria-pressed', String(n === i)));
    type(`${info.shots[0]}. The same runner in every shot.`);
  }

  const node = el('section', { class: 'la-monitor' },
    frames[0], frames[1],
    el('div', { class: 'la-grade' }), el('div', { class: 'la-grain' }),
    el('div', { class: 'la-hud', 'aria-hidden': 'true' }, ['tl', 'tr', 'bl', 'br'].map((c) => el('i', { class: 'la-corner la-' + c })),
      el('div', { class: 'la-thirds' }), el('div', { class: 'la-cross' })),
    el('header', { class: 'la-top' },
      el('a', { class: 'la-brand', href: '/' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), 'Scene.ai'),
      el('div', { class: 'la-readout la-mono', 'aria-hidden': 'true' }, tc, lens, iso, wb),
      el('nav', { class: 'la-doors' },
        signupOpen && el('a', { class: 'la-btn quiet', href: '/signin' }, 'Sign in'),
        join('solid'))),
    el('div', { class: 'la-lower' },
      el('div', {},
        el('h1', {}, 'Direct', el('br'), 'your ', el('b', {}, 'scene.')),
        el('p', { class: 'la-sub' }, 'Write the shot. The studio makes the takes, keeps the same faces from shot to shot, and cuts them together, without a node graph in sight.'),
        join('solid big')),
      el('div', { class: 'la-slate', 'aria-hidden': 'true' },
        el('header', { class: 'la-mono' }, sceneName, el('span', {}, 'Plan')),
        typed, rows,
        el('footer', {}, el('span', { class: 'la-mono' }, 'Nothing is made until you approve'), el('span', { class: 'la-btn solid small' }, 'Approve · 180')))),
    el('div', { class: 'la-scenes', role: 'group', 'aria-label': 'Scene' }, el('span', { class: 'la-mono' }, 'Scene'), buttons),
    el('div', { class: 'la-meters', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')));

  cut(0);
  // The timecode runs at 24 frames a second, as the camera's would; the set cuts to the next scene now and then until
  // the visitor picks one. Both stop once the page is left.
  const started = performance.now();
  const tick = () => {
    if (!node.isConnected && node.dataset.placed) return;
    if (node.isConnected) node.dataset.placed = '1';
    tc.textContent = timecode(Math.floor((performance.now() - started) / (1000 / 24)) + 24 * 3600);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  if (!still()) {
    const timer = setInterval(() => {
      if (node.dataset.placed && !node.isConnected) clearInterval(timer);
      else if (!touched) cut((current + 1) % scenes.names.length);
    }, 8000);
  }
  return node;
}

// A row of a section's label: its number and name on the left, a note on the right.
const label = (left, right) => el('div', { class: 'la-label la-mono' }, el('span', {}, left), el('span', {}, right));

export function renderLanding(root, { signupOpen }) {
  // A new button for each place it appears: one element can only stand in one place on the page.
  const join = (cls = '') => (signupOpen
    ? el('a', { class: 'la-btn ' + cls, href: '/signup' }, 'Create an account')
    : el('a', { class: 'la-btn ' + cls, href: '/signin' }, 'Sign in'));

  const takes = el('div', { class: 'la-strip' }, TAKES.map(([scene, take, length, note, look]) => el('div', { class: 'la-take ' + look },
    picture(scene, 'la-pic'),
    el('dl', {}, el('dt', {}, 'Shot'), el('dd', {}, `01 · ${take}`), el('dt', {}, 'Model'), el('dd', {}, 'MiniMax H3'),
      el('dt', {}, 'Length'), el('dd', {}, length), el('dt', {}, 'Note'), el('dd', {}, note)))));

  const plan = el('div', { class: 'la-screen', 'aria-hidden': 'true' },
    el('div', { class: 'la-bar la-mono' }, el('span', {}, 'Agent 1'), el('span', {}, 'Plans first')),
    el('div', { class: 'la-you' }, 'A 20 second ad for our sneaker drop. Rooftop, golden hour, the same runner in every shot.'),
    el('div', { class: 'la-plan' },
      el('header', {}, el('b', {}, 'Plan · 3 shots'), el('span', {}, 'Nothing is made until you approve')),
      scenes.info('rooftop').shots.map((shot) => el('div', { class: 'la-row' }, picture('rooftop', 'la-thumb'), el('span', {}, shot), el('em', {}, '60 cr'))),
      el('footer', {}, el('span', { class: 'la-mono' }, 'Storyboard first'), el('span', { class: 'la-btn solid small' }, 'Approve · 180'))));

  const page = el('div', { class: 'la' },
    monitor(join, signupOpen),

    el('section', { class: 'la-wrap la-manifesto' },
      label('01 · Why', 'Scene.ai'),
      el('p', {}, 'Most AI video tools give you a slot machine. ', el('em', {}, 'Scene.ai gives you a set:'),
        ' a cast that stays the same, takes you can keep or roll again, and a cut you can trust.')),

    el('section', { class: 'la-wrap la-report' },
      label('02 · The take report', 'Shot 1 · Rooftop at dusk'),
      takes,
      el('div', { class: 'la-steps' }, STEPS.map(([title, text], i) => el('div', {}, el('b', { class: 'la-mono' }, `0${i + 1}`), el('h3', {}, title), el('p', {}, text))))),

    el('section', { class: 'la-wrap la-agent' },
      label('03 · The agent', 'Plans first, makes later'),
      el('div', { class: 'la-split' },
        el('div', {},
          el('h2', {}, 'An assistant director that asks before it spends.'),
          el('p', {}, 'Tell it what you are making, in plain words. It plans the shots, prices them and waits for your nod; then it looks at every take and offers a retake when a face or a place is wrong.'),
          el('p', { class: 'la-note la-mono' }, 'The agent is open to invited accounts for now.')),
        plan)),

    el('section', { class: 'la-wrap la-kit' },
      label('04 · On the cart', 'The models'),
      el('h2', {}, 'Everything on the cart.'),
      el('table', {}, el('tbody', {}, KIT.map(([kind, what, model, text]) => el('tr', {},
        el('td', { class: 'la-mono' }, kind), el('th', { scope: 'row' }, what), el('td', { class: 'la-model' }, model), el('td', {}, text)))))),

    el('section', { class: 'la-wrap la-price' },
      label('05 · Credits', 'Pay for what you make'),
      el('div', { class: 'la-split' },
        el('h2', {}, 'You pay for the take, not the render time.'),
        el('p', {}, 'A flat price for a picture, a price per second for video and music. You see it before you press Generate, and a job that fails or is cancelled is refunded.'))),

    el('section', { class: 'la-cut' },
      el('h2', {}, 'CUT.'),
      el('p', {}, signupOpen ? 'Your first scene is a sentence away.' : 'Welcome back. The set is as you left it.'),
      el('div', { class: 'la-doors center' }, join('solid big'), signupOpen && el('a', { class: 'la-btn big', href: '/signin' }, 'Sign in'))),

    el('footer', { class: 'la-end la-mono' }, el('span', {}, 'Scene.ai'), el('span', {}, 'A studio for video, pictures and music')));

  root.replaceChildren(page);
  window.scrollTo(0, 0);
}
