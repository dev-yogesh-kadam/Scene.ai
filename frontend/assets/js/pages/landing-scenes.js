// The drawn film stills of the landing page: four scenes as SVG, each in colour or as a pencil storyboard sketch. They
// are pictures the studio draws itself, so the page needs no media files. svg(name, { sketch, id }) gives an <svg>
// string, viewBox 1600 x 900 (16:9), filled to its box; names lists the scenes; info(name) their title and shots.
const FIGURE = 'M0 -118 a13 13 0 1 1 0.1 0 Z M-14 -102 C-22 -98 -24 -80 -24 -62 L-20 -20 L-12 -20 L-10 -54 L-8 -54 L-9 0 L-1 0 L0 -40 L1 -40 L2 0 L10 0 L9 -54 L11 -54 L13 -20 L21 -20 L24 -62 C24 -80 22 -98 14 -102 Z';
const RUNNER = 'M6 -112 a12 12 0 1 1 0.1 0 Z M-4 -96 C-14 -90 -18 -70 -16 -56 L-34 -40 L-28 -34 L-10 -48 L-14 -22 L-36 6 L-28 12 L-4 -16 L6 -40 L14 -16 L30 0 L36 -6 L22 -24 L18 -56 L34 -48 L38 -56 L14 -72 C14 -86 8 -96 -4 -96 Z';
const DIVER = 'M0 -20 C26 -24 60 -18 86 -6 L120 -14 L126 -4 L94 6 C62 18 26 22 -6 16 C-30 12 -44 4 -44 -4 C-44 -14 -26 -18 0 -20 Z M-44 -4 a14 14 0 1 1 0.1 0 Z';

function skyline(y, seed, h, w) {
  // a row of buildings: a deterministic rhythm, so every page draws the same city
  let x = -20, d = 'M-20 900 ', last = 900;
  let s = seed;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  while (x < 1640) {
    const bw = w * (0.5 + rnd());
    const bh = h * (0.35 + rnd() * 0.9);
    d += `L${x.toFixed(0)} ${last.toFixed(0)} L${x.toFixed(0)} ${(y - bh).toFixed(0)} L${(x + bw).toFixed(0)} ${(y - bh).toFixed(0)} `;
    last = y - bh;
    if (rnd() > 0.8) {   // a mast on the roof
      const m = x + bw * 0.5, top = y - bh;
      d += `L${(m - 3).toFixed(0)} ${top.toFixed(0)} L${(m - 3).toFixed(0)} ${(top - 34 - rnd() * 40).toFixed(0)} L${(m + 3).toFixed(0)} ${(top - 34 - rnd() * 40).toFixed(0)} L${(m + 3).toFixed(0)} ${top.toFixed(0)} `;
    }
    x += bw + rnd() * 6;
  }
  return d + 'L1640 900 Z';
}

function windows(y, seed, h, w, colour) {
  // lit windows on the near buildings: a few warm squares, the same on every page
  let s = seed, out = '';
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  for (let i = 0; i < 90; i += 1) {
    const x = rnd() * 1600, top = y - h * (0.15 + rnd() * 0.6);
    if (rnd() > 0.45) out += `<rect x="${x.toFixed(0)}" y="${top.toFixed(0)}" width="${(w * 0.05 + 4).toFixed(0)}" height="7" fill="${colour}" opacity="${(0.35 + rnd() * 0.6).toFixed(2)}"/>`;
  }
  return out;
}

const scenes = {
  rooftop: {
    title: 'Rooftop at dusk',
    shots: ['Wide shot, rooftop at dusk', 'Close-up, she turns to camera', 'Push in on the skyline'],
    draw: (id) => `
      <defs>
        <linearGradient id="${id}sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b1640"/><stop offset=".45" stop-color="#6b2d5c"/><stop offset=".72" stop-color="#e2694a"/><stop offset=".86" stop-color="#ffb35c"/></linearGradient>
        <radialGradient id="${id}sun" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff3d6"/><stop offset=".25" stop-color="#ffd38a"/><stop offset="1" stop-color="#ff9a4d" stop-opacity="0"/></radialGradient>
        <linearGradient id="${id}haze" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff9a5c" stop-opacity="0"/><stop offset="1" stop-color="#ff9a5c" stop-opacity=".55"/></linearGradient>
      </defs>
      <rect width="1600" height="900" fill="url(#${id}sky)"/>
      <circle cx="1060" cy="560" r="330" fill="url(#${id}sun)"/>
      <circle cx="1060" cy="560" r="62" fill="#fff1d2"/>
      <path d="${skyline(640, 7, 150, 70)}" fill="#7a3a5e" opacity=".55"/>
      <rect y="430" width="1600" height="260" fill="url(#${id}haze)"/>
      <path d="${skyline(700, 21, 190, 95)}" fill="#3b1d3f" opacity=".85"/>
      <path d="${skyline(770, 3, 170, 140)}" fill="#1c1026"/>
      ${windows(770, 11, 150, 140, '#ffc477')}
      <path d="M0 760 L1600 744 L1600 900 L0 900 Z" fill="#0d0811"/>
      <path d="M150 744 L150 560 L250 560 L250 744 M138 560 L262 560 L246 520 L154 520 Z M170 744 L176 600 M230 744 L224 600" fill="#0d0811" stroke="#0d0811" stroke-width="10"/>
      <g transform="translate(560 750) scale(1.7)" fill="#0d0811"><path d="${FIGURE}"/></g>`,
    sketch: (id) => `
      <path d="M0 640 C300 600 1300 610 1600 630"/><circle cx="1060" cy="560" r="62"/>
      <path d="${skyline(700, 21, 190, 95)}"/><path d="${skyline(770, 3, 170, 140)}"/>
      <path d="M0 760 L1600 744"/><path d="M150 744 L150 560 L250 560 L250 744 M138 560 L262 560 L246 520 L154 520 Z"/>
      <g transform="translate(560 750) scale(1.7)"><path d="${FIGURE}"/></g>
      <path d="M480 240 L700 240 L700 360 L480 360 Z" stroke-dasharray="14 10"/><path d="M700 300 L820 300 M800 288 L820 300 L800 312"/>`,
  },
  neon: {
    title: 'Neon alley',
    shots: ['Low angle, rain on a neon alley', 'Track the runner past the signs', 'Close-up, breath in cold air'],
    draw: (id) => `
      <defs>
        <linearGradient id="${id}bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#05070f"/><stop offset=".6" stop-color="#0b1730"/><stop offset="1" stop-color="#050812"/></linearGradient>
        <filter id="${id}glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
        <linearGradient id="${id}wet" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0e1a33"/><stop offset="1" stop-color="#03050b"/></linearGradient>
      </defs>
      <rect width="1600" height="900" fill="url(#${id}bg)"/>
      <path d="M0 0 L620 300 L620 640 L0 900 Z" fill="#0a0f1e"/>
      <path d="M1600 0 L980 300 L980 640 L1600 900 Z" fill="#080c18"/>
      <rect x="620" y="300" width="360" height="340" fill="#101c38"/>
      <g filter="url(#${id}glow)"><rect x="150" y="220" width="210" height="64" fill="#ff2e88"/><rect x="1220" y="300" width="70" height="230" fill="#22e3ff"/><rect x="700" y="360" width="200" height="34" fill="#ffb02e"/></g>
      <rect x="150" y="220" width="210" height="64" fill="none" stroke="#ffd1e6" stroke-width="5"/>
      <rect x="1220" y="300" width="70" height="230" fill="none" stroke="#d6fbff" stroke-width="5"/>
      <rect x="700" y="360" width="200" height="34" fill="none" stroke="#ffe7bf" stroke-width="4"/>
      <path d="M0 900 L620 640 L980 640 L1600 900 Z" fill="url(#${id}wet)"/>
      <g filter="url(#${id}glow)" opacity=".55"><rect x="330" y="700" width="120" height="16" fill="#ff2e88"/><rect x="1080" y="690" width="26" height="120" fill="#22e3ff"/></g>
      <g stroke="#9fb6ff" stroke-width="2" opacity=".35">${Array.from({ length: 70 }, (_, i) => { const x = (i * 233) % 1600, y = (i * 137) % 900; return `<path d="M${x} ${y} l-10 46"/>`; }).join('')}</g>
      <g transform="translate(820 690) scale(1.5)" fill="#02030a"><path d="${RUNNER}"/></g>`,
    sketch: (id) => `
      <path d="M0 0 L620 300 L620 640 L0 900"/><path d="M1600 0 L980 300 L980 640 L1600 900"/><path d="M620 640 L980 640"/>
      <rect x="150" y="220" width="210" height="64"/><rect x="1220" y="300" width="70" height="230"/><rect x="700" y="360" width="200" height="34"/>
      <g transform="translate(820 690) scale(1.5)"><path d="${RUNNER}"/></g>
      <path d="M1000 600 C1100 560 1200 560 1300 600" stroke-dasharray="14 10"/><path d="M1280 586 L1300 600 L1278 610"/>`,
  },
  desert: {
    title: 'Desert chase',
    shots: ['Extreme wide, dust trail at noon', 'Handheld beside the jeep', 'Crane up over the dunes'],
    draw: (id) => `
      <defs>
        <linearGradient id="${id}sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5aa9d6"/><stop offset=".55" stop-color="#bfe0ea"/><stop offset=".7" stop-color="#f7e3c0"/></linearGradient>
        <radialGradient id="${id}dust" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#f3d7a6" stop-opacity=".95"/><stop offset="1" stop-color="#f3d7a6" stop-opacity="0"/></radialGradient>
      </defs>
      <rect width="1600" height="900" fill="url(#${id}sky)"/>
      <circle cx="1240" cy="150" r="60" fill="#fffaf0"/>
      <path d="M0 600 C220 520 420 560 640 530 C900 495 1150 560 1600 510 L1600 900 L0 900 Z" fill="#e9b97a"/>
      <path d="M0 690 C300 610 520 700 820 640 C1080 590 1300 660 1600 620 L1600 900 L0 900 Z" fill="#d79a5a"/>
      <path d="M0 800 C260 730 600 820 900 760 C1200 700 1400 780 1600 750 L1600 900 L0 900 Z" fill="#b7733d"/>
      <ellipse cx="640" cy="640" rx="420" ry="70" fill="url(#${id}dust)"/>
      <ellipse cx="420" cy="620" rx="260" ry="90" fill="url(#${id}dust)" opacity=".8"/>
      <g transform="translate(980 650)" fill="#3a2414"><path d="M-80 0 L-70 -34 L-30 -40 L-10 -62 L44 -62 L56 -36 L84 -32 L88 0 Z"/><circle cx="-50" cy="2" r="17"/><circle cx="58" cy="2" r="17"/></g>`,
    sketch: (id) => `
      <circle cx="1240" cy="150" r="60"/><path d="M0 600 C220 520 420 560 640 530 C900 495 1150 560 1600 510"/>
      <path d="M0 690 C300 610 520 700 820 640 C1080 590 1300 660 1600 620"/><path d="M0 800 C260 730 600 820 900 760 C1200 700 1400 780 1600 750"/>
      <g transform="translate(980 650)"><path d="M-80 0 L-70 -34 L-30 -40 L-10 -62 L44 -62 L56 -36 L84 -32 L88 0 Z"/><circle cx="-50" cy="2" r="17"/><circle cx="58" cy="2" r="17"/></g>
      <path d="M860 640 C700 630 400 640 240 610" stroke-dasharray="10 12"/><path d="M1300 380 L1300 200 M1286 222 L1300 200 L1314 222"/>`,
  },
  deep: {
    title: 'Deep sea',
    shots: ['Wide shot, a lantern in the deep', 'Orbit the diver, bubbles rising', 'Pull back to the whale'],
    draw: (id) => `
      <defs>
        <linearGradient id="${id}sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d4a6b"/><stop offset=".5" stop-color="#062539"/><stop offset="1" stop-color="#01080f"/></linearGradient>
        <linearGradient id="${id}ray" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9fe8ff" stop-opacity=".35"/><stop offset="1" stop-color="#9fe8ff" stop-opacity="0"/></linearGradient>
        <radialGradient id="${id}lamp" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff2c4"/><stop offset=".2" stop-color="#ffd27a" stop-opacity=".8"/><stop offset="1" stop-color="#ffb347" stop-opacity="0"/></radialGradient>
      </defs>
      <rect width="1600" height="900" fill="url(#${id}sea)"/>
      <path d="M380 0 L520 0 L760 900 L520 900 Z M820 0 L900 0 L1100 900 L960 900 Z M1180 0 L1260 0 L1320 900 L1220 900 Z" fill="url(#${id}ray)"/>
      <path d="M1700 520 C1500 430 1200 420 1000 470 C900 495 860 540 900 570 C960 610 1150 640 1360 620 L1520 690 L1560 640 L1700 650 Z" fill="#03131f" opacity=".9"/>
      <circle cx="560" cy="560" r="230" fill="url(#${id}lamp)"/>
      <g transform="translate(600 570) scale(1.3)" fill="#02090f"><path d="${DIVER}"/></g>
      <circle cx="560" cy="555" r="9" fill="#fff6dc"/>
      <g fill="none" stroke="#bfefff" stroke-width="2" opacity=".55">${Array.from({ length: 26 }, (_, i) => `<circle cx="${640 + (i * 37) % 140}" cy="${500 - i * 18}" r="${3 + (i % 4) * 2}"/>`).join('')}</g>`,
    sketch: (id) => `
      <path d="M380 0 L760 900 M520 0 L520 0 M820 0 L1100 900"/>
      <path d="M1700 520 C1500 430 1200 420 1000 470 C900 495 860 540 900 570 C960 610 1150 640 1360 620 L1520 690 L1560 640 L1700 650"/>
      <g transform="translate(600 570) scale(1.3)"><path d="${DIVER}"/></g><circle cx="560" cy="555" r="40"/>
      <path d="M300 300 C500 200 800 200 1000 300" stroke-dasharray="14 10"/><path d="M980 284 L1000 300 L976 308"/>`,
  },
};

function svg(name, { sketch = false, id = name + Math.random().toString(36).slice(2, 7) } = {}) {
  const scene = scenes[name];
  if (sketch) {
    return `<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs><filter id="${id}pencil"><feTurbulence type="fractalNoise" baseFrequency=".02" numOctaves="2" seed="4"/><feDisplacementMap in="SourceGraphic" scale="9"/></filter></defs>
      <rect width="1600" height="900" fill="#f5f2ea"/>
      <g fill="none" stroke="#3b3a36" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" filter="url(#${id}pencil)" opacity=".85">${scene.sketch(id)}</g>
    </svg>`;
  }
  return `<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${scene.draw(id)}</svg>`;
}

export const names = Object.keys(scenes);
export const info = (name) => ({ title: scenes[name].title, shots: scenes[name].shots });
export { svg };
