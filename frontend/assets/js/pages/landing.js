// The landing page: what a visitor who is not signed in sees at the site's address. It says what the studio makes and
// how, in the studio's own look, and leads to Sign in or Create account. Every claim here is something the studio does.

import { el, icon } from '../dom.js';

// What can be made, with the models that make it. Kept in step with workflows/ (see docs/HANDOVER.md, Workflows).
const MAKES = [
  { kind: 'Video', icon: 'video', model: 'MiniMax H3',
    text: 'Clips of 5 to 15 seconds from a prompt and up to eight references: a character, an outfit, a place, a motion to copy, a voice. Chain clips into longer scenes that pick up where the last one ended.' },
  { kind: 'Images', icon: 'image', model: 'Z-Image Turbo, SDXL, Ideogram 4',
    text: 'Stills in a few seconds, and posters with lettering that reads right.' },
  { kind: 'Music', icon: 'audio', model: 'MiniMax Music 3',
    text: 'Songs and scores from 30 seconds to 5 minutes, with your lyrics or without.' },
  { kind: 'Motion graphics', icon: 'title', model: 'Drawn in the studio',
    text: 'Title cards, lower thirds and whole videos of animated words, written from a sentence and editable scene by scene.' },
  { kind: 'Upscale', icon: 'upscale', model: 'SeedVR2',
    text: 'A finished video made larger and sharper, up to four times its size.' },
];

const STEPS = [
  ['Describe the shot', 'Write what happens and add reference pictures. Pin a cast to the project, and the same face, outfit and place carry from shot to shot.'],
  ['Make takes on the canvas', 'Every result lands on a board, one row per shot. Start the next clip from the last frame of one you like, or run it again with a new seed.'],
  ['Cut it together', 'Put clips in order on the timeline, trim them, add music, and export one video.'],
];

// The screen in the hero: a canvas of two shots whose frames develop one after another, like prints in a tray.
function screen() {
  const frame = (shot, take, wide, delay) => el('div', { class: 'lp-frame' + (wide ? ' wide' : ''), style: `--delay:${delay}s` },
    el('div', { class: 'lp-print' }), el('span', {}, `Take ${take}`));
  return el('div', { class: 'lp-screen', 'aria-hidden': 'true' },
    el('div', { class: 'lp-gate' }),
    el('div', { class: 'lp-row' }, el('span', { class: 'lp-shot' }, 'Shot 1'),
      el('div', { class: 'lp-strip' }, frame(1, 1, true, 0.4), frame(1, 2, true, 1.3), el('div', { class: 'lp-frame wide selected', style: '--delay:2.2s' },
        el('div', { class: 'lp-print' }), el('span', {}, 'Take 3')))),
    el('div', { class: 'lp-row' }, el('span', { class: 'lp-shot' }, 'Shot 2'),
      el('div', { class: 'lp-strip' }, frame(2, 1, false, 3.1), frame(2, 2, false, 4), el('div', { class: 'lp-frame developing' },
        el('div', { class: 'lp-print' }), el('span', {}, 'Take 3'), el('b', {}, 'Developing')))));
}

export function renderLanding(root, { signupOpen }) {
  // A new button for each place it appears: one element can only stand in one place on the page.
  const join = () => (signupOpen
    ? el('a', { class: 'btn generate lp-cta', href: '#/signup' }, 'Create an account')
    : el('a', { class: 'btn generate lp-cta', href: '#/signin' }, 'Sign in'));
  root.replaceChildren(el('div', { class: 'lp' },
    el('header', { class: 'lp-top' },
      el('a', { class: 'brand', href: '#/' }, el('img', { src: '/assets/img/logo.svg', alt: '' }), 'Scene.ai'),
      el('nav', { class: 'lp-nav' },
        el('a', { class: 'btn lp-outline', href: '#/signin' }, 'Sign in'),
        signupOpen && el('a', { class: 'btn generate', href: '#/signup' }, 'Create an account'))),

    el('section', { class: 'lp-hero' },
      el('div', { class: 'lp-words' },
        el('h1', {}, 'Direct your scene.'),
        el('p', {}, 'A studio for making video, pictures and music with AI. Describe the shot, make takes, and cut them together, without touching a node graph.'),
        el('div', { class: 'lp-actions' }, join(), signupOpen && el('a', { class: 'btn lp-outline lp-cta', href: '#/signin' }, 'Sign in'))),
      screen()),

    el('section', { class: 'lp-section' },
      el('h2', {}, 'What you can make'),
      el('div', { class: 'lp-makes' }, MAKES.map((m) => el('div', { class: 'lp-make' },
        el('div', { class: 'lp-make-head' }, icon(m.icon), el('b', {}, m.kind), el('span', {}, m.model)),
        el('p', {}, m.text))))),

    el('section', { class: 'lp-section' },
      el('h2', {}, 'From an idea to a cut'),
      el('ol', { class: 'lp-steps' }, STEPS.map(([title, text]) => el('li', {}, el('b', {}, title), el('p', {}, text))))),

    el('section', { class: 'lp-section lp-split' },
      el('div', {},
        el('h2', {}, 'Ask the agent'),
        el('p', {}, 'Tell it what you want in plain words, attach frames from the canvas, and it answers with a plan: each shot, cut, song or title, and what it costs. Nothing is made or charged until you approve it.'),
        el('p', { class: 'lp-note' }, 'The agent is open to invited accounts for now.')),
      el('div', {},
        el('h2', {}, 'Pay for what you make'),
        el('p', {}, 'Credits pay for results, not for computer time: a flat price for a picture, a price per second for video and music. You see the price before you press Generate, and a job that fails or is cancelled is refunded.'))),

    el('section', { class: 'lp-end' },
      el('h2', {}, signupOpen ? 'Make your first scene.' : 'Welcome back.'),
      join()),

    el('footer', { class: 'lp-foot' },
      el('span', {}, 'Scene.ai'), el('a', { href: '#/signin' }, 'Sign in'))));
  window.scrollTo(0, 0);
}
