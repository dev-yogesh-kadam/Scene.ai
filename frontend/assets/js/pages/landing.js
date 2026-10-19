// The landing page: what a visitor who is not signed in sees at the site's address. It should feel like walking into a
// working studio: a slate that claps, a set whose mood you can change, takes developing, an agent planning a shot, a
// showreel of what people make. Everything it shows is something the studio does; the pictures are drawn in CSS, so
// the page needs no media files.

import { el, icon } from '../dom.js';

// What can be made, with the models that make it. Kept in step with workflows/ (see docs/HANDOVER.md, Workflows).
const MAKES = [
  { kind: 'Video', icon: 'video', model: 'MiniMax H3', tone: 'amber', wide: true,
    text: 'Clips of 5 to 15 seconds from a prompt and up to eight references: a character, an outfit, a place, a motion to copy, a voice. Chain clips into longer scenes that pick up where the last one ended.' },
  { kind: 'Images', icon: 'image', model: 'Z-Image Turbo, SDXL, Ideogram 4', tone: 'violet',
    text: 'Stills in a few seconds, and posters with lettering that reads right.' },
  { kind: 'Music', icon: 'audio', model: 'MiniMax Music 3', tone: 'teal',
    text: 'Songs and scores from 30 seconds to 5 minutes, with your lyrics or without.' },
  { kind: 'Motion graphics', icon: 'title', model: 'Drawn in the studio', tone: 'coral',
    text: 'Title cards, lower thirds and whole videos of animated words, written from a sentence and editable scene by scene.' },
  { kind: 'Upscale', icon: 'upscale', model: 'SeedVR2', tone: 'amber',
    text: 'A finished video made larger and sharper, up to four times its size.' },
];

const STEPS = [
  ['Describe the shot', 'Write what happens and add reference pictures. Pin a cast to the project, and the same face, outfit and place carry from shot to shot.'],
  ['Make takes on the canvas', 'Every result lands on a board, one row per shot. Start the next clip from the last frame of one you like, or roll it again with a new seed.'],
  ['Cut it together', 'Put clips in order on the timeline, trim them, add music, and export one video.'],
];

const WORDS = ['scene', 'story', 'ad', 'film', 'reel'];
const TICKER = ['Video', 'Images', 'Music', 'Motion graphics', 'Upscale', 'Storyboards', 'Takes', 'A cast that stays the same', 'The agent', 'Timeline'];

// The mood of the set: pick one and the light, the frames and the plan change. Each is a look, not a promise of a result.
const MOODS = [
  { id: 'dusk', label: 'Rooftop at dusk', rows: ['Wide shot, rooftop at dusk', 'Close-up, she turns to camera', 'Push in on the skyline'], caps: ['Shot 1 · Take 3', 'Still · Maya', 'Shot 2 · Take 1', 'Shot 3 · Take 2'] },
  { id: 'neon', label: 'Neon alley', rows: ['Low angle, rain on a neon alley', 'Track the runner past the signs', 'Close-up, breath in cold air'], caps: ['Shot 1 · Take 2', 'Still · Rin', 'Shot 2 · Take 1', 'Shot 3 · Take 4'] },
  { id: 'desert', label: 'Desert chase', rows: ['Extreme wide, dust trail at noon', 'Handheld beside the jeep', 'Crane up over the dunes'], caps: ['Shot 1 · Take 1', 'Still · Kade', 'Shot 2 · Take 3', 'Shot 3 · Take 2'] },
  { id: 'deep', label: 'Deep sea', rows: ['Wide shot, a lantern in the deep', 'Orbit the diver, bubbles rising', 'Pull back to the whale'], caps: ['Shot 1 · Take 2', 'Still · Ione', 'Shot 2 · Take 2', 'Shot 3 · Take 1'] },
];

// What people make, as a showreel: each tile is a frame with its kind and shape.
const REEL = [
  ['Product ad', '15 s · 9:16', 'amber', 'tall'], ['Music video', '3 min', 'violet', 'wide'], ['Short film', '5 shots', 'coral', 'wide'],
  ['Social reel', '9:16', 'teal', 'tall'], ['Character sheet', 'one face, every shot', 'violet', 'sq'], ['Title sequence', 'motion graphics', 'amber', 'wide'],
  ['Storyboard', 'stills first', 'teal', 'sq'], ['Explainer', 'words that move', 'coral', 'wide'],
];

// A frame on the set: a picture drawn in CSS with a caption and, sometimes, a state.
const frame = (cls, tone, label, state) => el('div', { class: `lx-frame ${cls} tone-${tone}` },
  el('div', { class: 'lx-pic' }), el('span', { class: 'lx-cap' }, label), state && el('b', { class: 'lx-state' }, state));

// The hero's set: frames floating at different depths, the agent's plan, and a timeline whose playhead runs.
function set() {
  return el('div', { class: 'lx-set', 'aria-hidden': 'true' },
    el('div', { class: 'lx-layer d1' }, frame('a', 'amber', MOODS[0].caps[0], 'Kept'), frame('b', 'violet', MOODS[0].caps[1])),
    el('div', { class: 'lx-layer d2' }, frame('c', 'coral', MOODS[0].caps[2], 'Rendering'), frame('d', 'teal', MOODS[0].caps[3])),
    el('div', { class: 'lx-plan' },
      el('div', { class: 'lx-plan-head' }, icon('film'), el('b', {}, 'Plan · 3 shots'), el('span', {}, 'Nothing is made until you approve')),
      MOODS[0].rows.map((row) => el('div', { class: 'lx-plan-row' }, el('i', {}), el('span', {}, row), el('em', {}, '60 cr'))),
      el('div', { class: 'lx-plan-bar' }, el('span', {}, 'Stop'), el('button', { type: 'button', tabindex: '-1' }, 'Approve · 180'))),
    el('div', { class: 'lx-timeline' },
      el('div', { class: 'lx-clips' }, el('i', { class: 'c1' }), el('i', { class: 'c2' }), el('i', { class: 'c3' }), el('i', { class: 'c4' })),
      el('div', { class: 'lx-music' }), el('div', { class: 'lx-playhead' })));
}

// A few lines of the agent at work, typed out when the section comes into view.
const CHAT = [
  ['you', 'A 20 second ad for our sneaker drop. Rooftop, golden hour, the same runner in every shot.'],
  ['agent', 'Four shots, one cast: the runner from your assets in every shot. I will draw cheap stills first so you can fix a face before any clip is paid for.'],
];

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function agentDemo() {
  const lines = el('div', { class: 'lx-chat' }, CHAT.map(([who, text]) => el('div', { class: 'lx-line ' + who, 'data-text': text }, el('span', {}))));
  const card = el('div', { class: 'lx-approve' },
    el('div', {}, el('b', {}, 'Storyboard first'), el('span', {}, '4 stills · 40 cr')),
    el('div', { class: 'lx-approve-bar' }, el('span', {}, 'Type something else…'), el('b', {}, 'Approve · 40')));
  const box = el('div', { class: 'lx-agent' }, lines, card);
  let started = false;
  const type = () => {
    if (started) return;
    started = true;
    let at = 0;
    const next = () => {
      const row = lines.children[at];
      if (!row) return card.classList.add('on');
      row.classList.add('on');
      const out = row.firstChild, text = row.dataset.text;
      let i = 0;
      const tick = () => { out.textContent = text.slice(0, (i += 2)); if (i < text.length) setTimeout(tick, 18); else { at += 1; setTimeout(next, 500); } };
      tick();
    };
    next();
  };
  if ('IntersectionObserver' in window && !still()) {
    const watch = new IntersectionObserver((seen) => { if (seen[0].isIntersecting) { watch.disconnect(); type(); } }, { threshold: 0.35 });
    watch.observe(box);
  } else {
    for (const row of lines.children) { row.classList.add('on'); row.firstChild.textContent = row.dataset.text; }
    card.classList.add('on');
  }
  return box;
}

// The slate that claps once when someone first arrives in a session, then gets out of the way (a click skips it).
function slate() {
  let seen = false;
  try { seen = sessionStorage.getItem('scene.slate') === '1'; sessionStorage.setItem('scene.slate', '1'); } catch (e) { /* no storage */ }
  if (seen || still()) return null;
  const node = el('div', { class: 'lx-slate', role: 'presentation', onclick: () => node.remove() },
    el('div', { class: 'lx-board' },
      el('div', { class: 'lx-stick' }),
      el('div', { class: 'lx-board-body' },
        el('div', {}, el('span', {}, 'Scene'), el('b', {}, '01')), el('div', {}, el('span', {}, 'Take'), el('b', {}, '1')),
        el('div', { class: 'lx-board-title' }, el('span', {}, 'Production'), el('b', {}, 'Scene.ai')))));
  setTimeout(() => node.classList.add('out'), 1500);
  setTimeout(() => node.remove(), 2100);
  return node;
}

// A big clapper over the closing call to action; the stick opens and snaps shut.
const clapper = () => el('div', { class: 'lx-clapper', 'aria-hidden': 'true' },
  el('div', { class: 'lx-clapper-stick' }), el('div', { class: 'lx-clapper-body' }, el('span', {}, 'Scene 01 · Take 1'), el('b', {}, 'Action')));

export function renderLanding(root, { signupOpen }) {
  // A new button for each place it appears: one element can only stand in one place on the page.
  const join = (cls = '') => (signupOpen
    ? el('a', { class: 'btn generate lp-cta ' + cls, href: '/signup' }, 'Create an account')
    : el('a', { class: 'btn generate lp-cta ' + cls, href: '/signin' }, 'Sign in'));
  const word = el('span', { class: 'lx-rotor' }, WORDS.map((w, i) => el('span', { style: `--i:${i}` }, w + '.')));
  word.style.setProperty('--n', WORDS.length);

  // The mood chips under the headline: they change the light of the set and what its frames and plan say.
  let mood = 0, touched = false, timer = null;
  const chips = MOODS.map((m, i) => el('button', { type: 'button', class: 'lx-chip' + (i ? '' : ' on'), onclick: () => { touched = true; clearInterval(timer); pick(i); } }, m.label));
  const hero = el('section', { class: 'lx-hero', 'data-mood': MOODS[0].id },
    el('div', { class: 'lx-glow g1' }), el('div', { class: 'lx-glow g2' }), el('div', { class: 'lx-glow g3' }),
    el('div', { class: 'lx-words' },
      el('p', { class: 'lx-live' }, el('i', {}), 'The studio is open · takes are developing'),
      el('h1', {}, 'Direct your ', word),
      el('p', { class: 'lx-lead' }, 'A studio for making video, pictures and music with AI. Describe the shot, make takes, and cut them together, without touching a node graph.'),
      el('div', { class: 'lp-actions' }, join(), signupOpen && el('a', { class: 'btn lp-outline lp-cta', href: '/signin' }, 'Sign in')),
      el('div', { class: 'lx-moods' }, el('span', {}, 'Set the mood'), chips)),
    set());
  function pick(i) {
    mood = i;
    const m = MOODS[i];
    hero.dataset.mood = m.id;
    chips.forEach((chip, n) => chip.classList.toggle('on', n === i));
    hero.querySelectorAll('.lx-plan-row span').forEach((row, n) => { row.textContent = m.rows[n]; });
    hero.querySelectorAll('.lx-cap').forEach((cap, n) => { cap.textContent = m.caps[n]; });
    const board = hero.querySelector('.lx-set');
    board.classList.remove('swap');
    void board.offsetWidth;   // the frames flash as if a new take came in
    board.classList.add('swap');
  }
  if (!still()) {
    timer = setInterval(() => {
      if (!hero.isConnected) clearInterval(timer);
      else if (!touched) pick((mood + 1) % MOODS.length);
    }, 6500);
  }
  // The set leans a little toward the pointer.
  hero.addEventListener('pointermove', (e) => {
    const box = hero.getBoundingClientRect();
    hero.style.setProperty('--px', ((e.clientX - box.left) / box.width - 0.5).toFixed(3));
    hero.style.setProperty('--py', ((e.clientY - box.top) / box.height - 0.5).toFixed(3));
  });

  const ticker = el('div', { class: 'lx-ticker', 'aria-hidden': 'true' },
    el('div', {}, [...TICKER, ...TICKER].map((t) => el('span', {}, el('i', {}), t))));

  const reelRow = (items, back) => el('div', { class: 'lx-reel-row' + (back ? ' back' : '') },
    el('div', {}, [...items, ...items].map(([title, note, tone, shape]) => el('figure', { class: `lx-reel-tile tone-${tone} ${shape}` },
      el('div', { class: 'lx-pic' }), el('figcaption', {}, el('b', {}, title), el('span', {}, note))))));
  const reel = el('section', { class: 'lx-reel lx-reveal', 'aria-label': 'What people make' },
    el('h2', {}, 'Made on Scene.ai'),
    reelRow(REEL.slice(0, 4)), reelRow(REEL.slice(4), true));

  const light = (e) => {
    const b = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty('--cx', (e.clientX - b.left) + 'px');
    e.currentTarget.style.setProperty('--cy', (e.clientY - b.top) + 'px');
  };
  const page = el('div', { class: 'lp lx' },
    el('header', { class: 'lp-top' },
      el('a', { class: 'brand', href: '/' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), 'Scene.ai'),
      el('nav', { class: 'lp-nav' },
        el('a', { class: 'btn lp-outline', href: '/signin' }, 'Sign in'),
        signupOpen && el('a', { class: 'btn generate', href: '/signup' }, 'Create an account'))),

    hero, ticker,

    el('section', { class: 'lp-section lx-section lx-reveal' },
      el('h2', {}, 'What you can make'),
      el('div', { class: 'lx-bento' }, MAKES.map((m) => el('div', { class: `lx-card tone-${m.tone}` + (m.wide ? ' wide' : ''), onpointermove: light },
        el('div', { class: 'lx-card-glow' }),
        el('div', { class: 'lx-card-head' }, icon(m.icon), el('div', {}, el('b', {}, m.kind), el('span', {}, m.model))),
        el('p', {}, m.text))))),

    reel,

    el('section', { class: 'lp-section lx-section lx-reveal' },
      el('h2', {}, 'From an idea to a cut'),
      el('ol', { class: 'lx-steps' }, STEPS.map(([title, text]) => el('li', {}, el('b', {}, title), el('p', {}, text))))),

    el('section', { class: 'lp-section lx-section lx-agent-section lx-reveal' },
      el('div', {},
        el('h2', {}, 'Ask the agent'),
        el('p', { class: 'lx-lead' }, 'Tell it what you want in plain words, attach frames from the canvas, and it answers with a plan: each shot, cut, song or title, and what it costs. It looks at its own results and offers a retake when a face or a place is wrong. Nothing is made or charged until you approve it.'),
        el('p', { class: 'lp-note' }, 'The agent is open to invited accounts for now.')),
      agentDemo()),

    el('section', { class: 'lp-section lx-section lx-pay lx-reveal' },
      el('div', { class: 'lx-pay-card' },
        el('h2', {}, 'Pay for what you make'),
        el('p', { class: 'lx-lead' }, 'Credits pay for results, not for computer time: a flat price for a picture, a price per second for video and music. You see the price before you press Generate, and a job that fails or is cancelled is refunded.'))),

    el('section', { class: 'lx-end lx-reveal' },
      el('div', { class: 'lx-glow g1' }), el('div', { class: 'lx-glow g3' }),
      clapper(),
      el('h2', {}, signupOpen ? 'Make your first scene.' : 'Welcome back.'),
      join()),

    el('footer', { class: 'lp-foot' },
      el('span', {}, 'Scene.ai'), el('a', { href: '/signin' }, 'Sign in')));

  // The light follows the pointer over the whole page; sections rise into view as they are scrolled to.
  page.addEventListener('pointermove', (e) => { page.style.setProperty('--mx', e.clientX + 'px'); page.style.setProperty('--my', e.clientY + 'px'); });
  const rise = page.querySelectorAll('.lx-reveal');
  if ('IntersectionObserver' in window && !still()) {
    const watch = new IntersectionObserver((seen) => seen.forEach((s) => { if (s.isIntersecting) { s.target.classList.add('in'); watch.unobserve(s.target); } }), { threshold: 0.12 });
    rise.forEach((node) => watch.observe(node));
  } else {
    rise.forEach((node) => node.classList.add('in'));
  }
  const intro = slate();
  root.replaceChildren(page, ...(intro ? [intro] : []));
  window.scrollTo(0, 0);
}
