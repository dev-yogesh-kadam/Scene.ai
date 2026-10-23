// The Guide: how the studio works, from a first project to a finished video. Reached from the Guide button at the top
// right of every page but the canvas, and from the menu. One page; its contents list follows as you read.

import { el, icon } from '../dom.js';
import { KIT } from '../components/kit.js';

const SECTIONS = [
  { id: 'start', title: 'Getting started', body: [
    ['p', 'Scene.ai turns what you describe into pictures, videos, music and voice, and puts them together into finished videos. Work happens in projects: each project has its own canvas, timeline, agent conversations and ' + KIT + '.'],
    ['steps', ['Open Projects from the menu at the top left and make a project.',
      'Open its main canvas, or add a module for a separate part of the work, such as an episode.',
      'Ask the agent for what you want, or make something yourself from the panel beside the canvas.',
      'Put the shots in order on the timeline and export the finished video.']],
    ['tip', 'Everything you make costs credits; your balance is at the top right. A job that fails or that you cancel gives its credits back.'],
  ] },
  { id: 'projects', title: 'Projects and modules', body: [
    ['p', 'A project holds one piece of work. Its page shows its modules, what it has spent, and its details.'],
    ['p', 'A module is a canvas of its own inside a project, with its own timeline and agent tabs: use one per episode, scene or version. Every module of a project shares the project\'s ' + KIT + '.'],
    ['list', ['Add module makes a new one; the project\'s own canvas is the main canvas.',
      'View analytics shows what the project spent and made, by day, by kind and by module.',
      'Duplicate project starts a copy with the same modules and ' + KIT + ', but none of what was made.',
      'Deleting a module deletes everything made in it; deleting a project deletes its modules, everything made in them and its ' + KIT + ". It can't be undone, so download what you want to keep first."]],
  ] },
  { id: 'canvas', title: 'The canvas', body: [
    ['p', 'The canvas shows everything made in a module as frames, one row per shot. The panel beside it makes the next thing: pick a frame and continue from it, upscale a video, or start a new shot.'],
    ['list', ['Select a frame to see what it was made from and to use it as a reference.',
      'Quick actions make a picture, a video or a sound in a few clicks, or upscale a video.',
      'Drop a file onto the canvas to bring it in as a reference.']],
  ] },
  { id: 'agent', title: 'The agent', body: [
    ['p', 'The agent plans the work for you. Tell it what you want in plain words, attach frames from the canvas and say what each is for. It answers with a plan: each step, the model it uses and what it costs. Nothing runs until you approve it.'],
    ['list', ['Approve runs the plan; you can change a step or ask again first.',
      'Skills are recipes the agent follows for longer work, such as a whole short film. Type / in the agent\'s box to pick one.',
      'The agent remembers the conversation in each tab; Compact shortens a long one so it stays quick.']],
    ['tip', 'Be specific about the look, the camera and the length. "A 5 second close-up of Anna laughing, warm evening light" works better than "Anna laughing".'],
  ] },
  { id: 'kit', title: KIT, body: [
    ['p', 'The ' + KIT + ' is what a project is made from: its characters, places, props, styles and voices. Keep a picture or a sound there once, give it a name, and use it in any module of the project.'],
    ['list', ['Write @ and a name in a prompt, such as @Anna at @Bonfire Clearing, and the studio puts those references into the job.',
      'An entry marked always attached goes into every shot of the project, so a main character stays the same.',
      'The agent knows every entry by name and describes what it shows to models that can\'t see pictures.']],
  ] },
  { id: 'create', title: 'Making things yourself', body: [
    ['p', 'Create, and the panel beside the canvas, run one model at a time. Choose a workflow, write the prompt, fill the reference slots it asks for and pick the length, size and quality. The price is shown before you start.'],
    ['list', ['For a long video, write one prompt per clip with a line of three dashes (---) between them: each clip starts on the last frame of the one before.',
      'Re-run in the library opens an item with the settings it was made with.',
      'Continue a video from its last frame to make the next shot match.']],
  ] },
  { id: 'timeline', title: 'The timeline', body: [
    ['p', 'The timeline puts videos in order. Drag clips into place, trim their start and end, put music or a voice under them, and export the cut as one video, which goes into your library.'],
  ] },
  { id: 'library', title: 'The library', body: [
    ['p', 'The library holds everything you have made, in every project. Search by name or prompt, filter by kind or project, rate results with a thumbs up or down (the agent learns from them), and download or delete what you no longer need.'],
  ] },
  { id: 'motion', title: 'Motion graphics', body: [
    ['p', 'Motion graphics are videos of animated text and shapes: title cards, lower thirds, captions and whole explainer videos written as scenes. They are drawn on the studio\'s own machine, so they are quick, and you can edit each scene before it is rendered.'],
  ] },
  { id: 'credits', title: 'Credits', body: [
    ['p', 'Each job costs credits for what you asked for: a set price for a picture, a price per second for video, sound and motion graphics. A message to the agent costs what its model costs. The price is always shown before anything runs.'],
    ['list', ['A failed or cancelled job gives its credits back.',
      'A project\'s analytics show where its credits went.',
      'When you run out, ask an admin for more.']],
  ] },
  { id: 'help', title: 'When something goes wrong', body: [
    ['list', ['A job waiting a long time: the render server may be busy with other people\'s jobs; the queue at the top left shows where yours is.',
      'A job failed: its card says why in plain words, and its credits came back. Try a shorter clip or a lower quality.',
      'A banner at the top says the studio is under maintenance: new jobs start again when it is over.']],
  ] },
];

function block([kind, content]) {
  if (kind === 'p') return el('p', {}, content);
  if (kind === 'tip') return el('div', { class: 'guide-tip' }, icon('bulb'), el('span', {}, content));
  if (kind === 'steps') return el('ol', { class: 'guide-steps' }, content.map((c) => el('li', {}, c)));
  return el('ul', { class: 'guide-list' }, content.map((c) => el('li', {}, c)));
}

export function render(view) {
  const links = SECTIONS.map((s) => el('a', { href: '#' + s.id, onclick: (e) => {
    e.preventDefault();
    document.getElementById('guide-' + s.id).scrollIntoView({ behavior: 'smooth', block: 'start' });
  } }, s.title));
  const contents = el('nav', { class: 'guide-toc', 'aria-label': 'Contents' }, el('div', { class: 'nav-label' }, 'Contents'), links);
  const article = el('article', { class: 'guide-body' },
    el('h1', {}, 'Guide'),
    el('p', { class: 'muted guide-lead' }, 'How Scene.ai works, from a first project to a finished video.'),
    SECTIONS.map((s) => el('section', { id: 'guide-' + s.id, class: 'guide-section' }, el('h2', {}, s.title), s.body.map(block))));
  view.replaceChildren(el('div', { class: 'guide-page' }, contents, article));

  // The contents follow the reading: the section in view is marked.
  const seen = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const id = entry.target.id.slice('guide-'.length);
      links.forEach((a) => a.classList.toggle('on', a.getAttribute('href') === '#' + id));
    }
  }, { rootMargin: '-20% 0px -70% 0px' });
  article.querySelectorAll('.guide-section').forEach((s) => seen.observe(s));
  return () => seen.disconnect();
}
