// The landing page: what a visitor who is not signed in sees at the site's address. It should feel like walking into a
// working studio: a set with takes developing, an agent planning a shot, a timeline running. Everything it shows is
// something the studio does; the pictures are drawn in CSS, so the page needs no media files.

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

// A frame on the set: a picture drawn in CSS with a caption and, sometimes, a state.
const frame = (cls, tone, label, state) => el('div', { class: `lx-frame ${cls} tone-${tone}` },
  el('div', { class: 'lx-pic' }), el('span', { class: 'lx-cap' }, label), state && el('b', { class: 'lx-state' }, state));

// The hero's set: frames floating at different depths, the agent's plan, and a timeline whose playhead runs.
function set() {
  return el('div', { class: 'lx-set', 'aria-hidden': 'true' },
    el('div', { class: 'lx-layer d1' }, frame('a', 'amber', 'Shot 1 · Take 3', 'Kept'), frame('b', 'violet', 'Still · Maya')),
    el('div', { class: 'lx-layer d2' }, frame('c', 'coral', 'Shot 2 · Take 1', 'Rendering'), frame('d', 'teal', 'Shot 3 · Take 2')),
    el('div', { class: 'lx-plan' },
      el('div', { class: 'lx-plan-head' }, icon('film'), el('b', {}, 'Plan · 3 shots'), el('span', {}, 'Nothing is made until you approve')),
      el('div', { class: 'lx-plan-row' }, el('i', {}), 'Wide shot, rooftop at dusk', el('em', {}, '60 cr')),
      el('div', { class: 'lx-plan-row' }, el('i', {}), 'Close-up, she turns to camera', el('em', {}, '60 cr')),
      el('div', { class: 'lx-plan-row' }, el('i', {}), 'Push in on the skyline', el('em', {}, '60 cr')),
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
  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const watch = new IntersectionObserver((seen) => { if (seen[0].isIntersecting) { watch.disconnect(); type(); } }, { threshold: 0.35 });
    watch.observe(box);
  } else {
    for (const row of lines.children) { row.classList.add('on'); row.firstChild.textContent = row.dataset.text; }
    card.classList.add('on');
  }
  return box;
}

export function renderLanding(root, { signupOpen }) {
  // A new button for each place it appears: one element can only stand in one place on the page.
  const join = (cls = '') => (signupOpen
    ? el('a', { class: 'btn generate lp-cta ' + cls, href: '/signup' }, 'Create an account')
    : el('a', { class: 'btn generate lp-cta ' + cls, href: '/signin' }, 'Sign in'));
  const word = el('span', { class: 'lx-rotor' }, WORDS.map((w, i) => el('span', { style: `--i:${i}` }, w + '.')));
  word.style.setProperty('--n', WORDS.length);
  const hero = el('section', { class: 'lx-hero' },
    el('div', { class: 'lx-glow g1' }), el('div', { class: 'lx-glow g2' }), el('div', { class: 'lx-glow g3' }),
    el('div', { class: 'lx-words' },
      el('p', { class: 'lx-live' }, el('i', {}), 'The studio is open · takes are developing'),
      el('h1', {}, 'Direct your ', word),
      el('p', { class: 'lx-lead' }, 'A studio for making video, pictures and music with AI. Describe the shot, make takes, and cut them together, without touching a node graph.'),
      el('div', { class: 'lp-actions' }, join(), signupOpen && el('a', { class: 'btn lp-outline lp-cta', href: '/signin' }, 'Sign in'))),
    set());
  // The set leans a little toward the pointer.
  hero.addEventListener('pointermove', (e) => {
    const box = hero.getBoundingClientRect();
    hero.style.setProperty('--px', ((e.clientX - box.left) / box.width - 0.5).toFixed(3));
    hero.style.setProperty('--py', ((e.clientY - box.top) / box.height - 0.5).toFixed(3));
  });

  const ticker = el('div', { class: 'lx-ticker', 'aria-hidden': 'true' },
    el('div', {}, [...TICKER, ...TICKER].map((t) => el('span', {}, el('i', {}), t))));

  root.replaceChildren(el('div', { class: 'lp lx' },
    el('header', { class: 'lp-top' },
      el('a', { class: 'brand', href: '/' }, el('img', { src: '/assets/img/logo.svg?v=clapper', alt: '' }), 'Scene.ai'),
      el('nav', { class: 'lp-nav' },
        el('a', { class: 'btn lp-outline', href: '/signin' }, 'Sign in'),
        signupOpen && el('a', { class: 'btn generate', href: '/signup' }, 'Create an account'))),

    hero, ticker,

    el('section', { class: 'lp-section lx-section' },
      el('h2', {}, 'What you can make'),
      el('div', { class: 'lx-bento' }, MAKES.map((m) => el('div', { class: `lx-card tone-${m.tone}` + (m.wide ? ' wide' : '') },
        el('div', { class: 'lx-card-glow' }),
        el('div', { class: 'lx-card-head' }, icon(m.icon), el('div', {}, el('b', {}, m.kind), el('span', {}, m.model))),
        el('p', {}, m.text))))),

    el('section', { class: 'lp-section lx-section' },
      el('h2', {}, 'From an idea to a cut'),
      el('ol', { class: 'lx-steps' }, STEPS.map(([title, text]) => el('li', {}, el('b', {}, title), el('p', {}, text))))),

    el('section', { class: 'lp-section lx-section lx-agent-section' },
      el('div', {},
        el('h2', {}, 'Ask the agent'),
        el('p', { class: 'lx-lead' }, 'Tell it what you want in plain words, attach frames from the canvas, and it answers with a plan: each shot, cut, song or title, and what it costs. It looks at its own results and offers a retake when a face or a place is wrong. Nothing is made or charged until you approve it.'),
        el('p', { class: 'lp-note' }, 'The agent is open to invited accounts for now.')),
      agentDemo()),

    el('section', { class: 'lp-section lx-section lx-pay' },
      el('div', { class: 'lx-pay-card' },
        el('h2', {}, 'Pay for what you make'),
        el('p', { class: 'lx-lead' }, 'Credits pay for results, not for computer time: a flat price for a picture, a price per second for video and music. You see the price before you press Generate, and a job that fails or is cancelled is refunded.'))),

    el('section', { class: 'lx-end' },
      el('div', { class: 'lx-glow g1' }), el('div', { class: 'lx-glow g3' }),
      el('h2', {}, signupOpen ? 'Make your first scene.' : 'Welcome back.'),
      join()),

    el('footer', { class: 'lp-foot' },
      el('span', {}, 'Scene.ai'), el('a', { href: '/signin' }, 'Sign in'))));
  window.scrollTo(0, 0);
}
