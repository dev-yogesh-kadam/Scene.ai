# Motion graphics (HyperFrames)

Motion graphics in Scene.ai (whole videos of animated words, titles and overlays) are drawn as HTML
pages and rendered to video by
[HyperFrames](https://github.com/heygen-com/hyperframes), an open-source program (Apache 2.0) that plays
an HTML page in headless Chrome frame by frame and encodes the frames with ffmpeg. It runs on the
machine that runs Scene.ai and needs no GPU job. It is priced by the second of video (30 credits a second
to start with, set in the admin console's Pricing section), charged before the render and refunded if it fails.

## What it needs

| Need | Where it comes from |
|---|---|
| Node.js 22 or newer | Installed on the machine. On Windows: `winget install OpenJS.NodeJS.LTS`. |
| HyperFrames, GSAP, ffprobe | `npm install` in `motion/` (the start scripts do this when Node.js is there). Versions are in `motion/package.json`; HyperFrames is pinned. |
| Chrome | HyperFrames finds an installed Chrome, or downloads its own. |
| ffmpeg | The one the studio already bundles (`imageio-ffmpeg`). |

Without Node.js the studio still runs. The Motion graphics section then says what is missing.

`node_path` in `config.json` names the Node.js program when it is not in the usual place.

## Where things are

| Path | What |
|---|---|
| `motion/package.json` | The packages: `hyperframes`, `gsap`, `ffprobe-static`. `motion/node_modules/` is not in git. |
| `motion/templates/<id>/` | One template: `index.html` (the composition) and `template.json` (its form). |
| `backend/scene/motion.py` | Lists the templates, checks a form's values, and runs the render. |
| `backend/scene/sequence.py` | A video made of scenes: checks the scenes and writes the page for them. |
| `backend/scene/api/workspace.py` | `GET /api/motion/templates`, `POST /api/motion/scenes`, `POST /api/motion/render`. |
| `frontend/assets/js/components/motion.js` | The two forms in the Quick actions tab: `sequenceForm` for a whole video, `motionForm` for a template. |

A result is filed in the library as a video with the workflow id `edit/motion`. One made over a video
records that video as its `parent`, so it lands on the same row of the canvas.

## The templates

| Id | What it makes | Needs |
|---|---|---|
| `title_card` | A title and a line under it on a plain ground, 3 to 8 s, in any of the three shapes, dark or light. | nothing |
| `lower_third` | A name and a line under it at the bottom left of a video. | a video |
| `title_over_video` | Large words over a video, with the picture dimmed behind them. | a video |

A template laid over a video keeps the video's size, length and sound. The video is the one selected
on the canvas, and may be up to 120 s long.

## A whole motion video, from Quick actions

**Motion video** is the first card of the Motion graphics section. The user types what the video is
about and presses **Write scenes**; `POST /api/motion/scenes` has the agent's model write the video as
scenes (the same scenes as the agent's `motion` tool, below), with a name, a look and a shape. The
scenes come back into the form, where each one can be changed, moved or removed and more can be added;
with the model off the scenes can be written by hand. **Render** sends them to
`POST /api/motion/render`. The form is `sequenceForm` in `components/motion.js`.

A small model makes things up, so the server drops a `stat` scene whose number is not in what the
user typed, and a `quote` scene when the user gave or asked for no quotation (`founded` in `agent.py`).
Other invented details, such as opening hours, can still appear: the scenes are shown before anything
is rendered so they can be corrected.

Tried on 4 October with `qwen3.5:9b`: "a short intro for a coffee shop called Ember, warm and
friendly, three reasons to visit" gave five scenes in about 25 s, and the 24 s video rendered in 9 s.

## Videos made by the agent

The agent has two motion tools beside `generate` and the editing tools. Both are priced by the second and show in the
plan as "Motion graphics" until Approve is pressed.

- **`motion`**: a whole video made of words and shapes. The agent writes it as **scenes**, shown one
  after another, each with a `kind`: `title`, `statement`, `list`, `stat`, `quote` or `end`, plus a
  `heading`, a `text`, `items` for a list, and `seconds`. It also picks a `look` (`dark`, `light`,
  `warm`, `cool`) and the shape. `backend/scene/sequence.py` checks the scenes (at most 12 scenes and
  60 s; each scene 2 to 8 s and never shorter than it takes to read) and writes the HyperFrames page
  for them. Every word is escaped, so nothing the model or the user wrote is read as markup or script.
  The model never writes HTML itself.
- **`overlay`**: words over a video the user selected, through the `title_over_video` or
  `lower_third` template.

On Approve the browser sends the step to `POST /api/motion/render`: `{scenes, look, shape, name}` for
a `motion` step, `{template, values, source}` for an `overlay`. A 16 s video of six scenes rendered in
14 s on the studio PC.

Asked "make a motion graphics video introducing Scene.ai", `qwen3.5:9b` planned a title, two
statements, a list of four items, a quote and an end card, and wrote the words for each.

## Adding a template

Make a folder in `motion/templates/` with two files. It appears in the studio on the next page load.

**`template.json`**

```json
{
  "title": "Title card",
  "description": "One sentence shown in the form.",
  "needs": null,
  "fields": [
    {"id": "title", "label": "Title", "type": "text", "max": 60, "required": true, "placeholder": "Chapter one"},
    {"id": "look", "label": "Look", "type": "choice", "choices": ["dark", "light"], "default": "dark"}
  ]
}
```

- `needs` is `null`, or `"video"` for a template laid over the selected video.
- A field is `text` (with `max`, `required`, `placeholder`) or `choice` (with `choices`, `default`,
  and optionally `unit` for numbers and `names` to rename a choice).
- A template that stands on its own should have a `seconds` choice and a `shape` choice
  (`landscape`, `portrait`, `square`); these set the length and the frame and are not passed on as words.

**`index.html`** is a HyperFrames composition. The studio fills in four marks before the render:

| Mark | Becomes |
|---|---|
| `__WIDTH__`, `__HEIGHT__` | The frame in pixels. |
| `__DURATION__` | The length in seconds. |
| `__SOUND__` | `data-has-audio="true"` or `muted`, for the `<video>` of a template laid over a video. |

Everything the user typed arrives as HyperFrames variables: declare them in
`data-composition-variables` on `<html>` and read them with `window.__hyperframes.getVariables()`.
Put them on the page with `textContent`, never `innerHTML`, so that typed text is never read as
markup. The chosen video is `clip.mp4`, the font is `Archivo.woff2`, and GSAP is `gsap.min.js`, all
next to `index.html`; do not load anything from the internet, or a render stops working offline.

The rules HyperFrames itself sets: one paused GSAP timeline registered as
`window.__timelines["main"]`, every timed element with `data-start`, `data-duration` and
`class="clip"`, and nothing random or time-dependent in the script.

## Trying a template by hand

```bash
cd motion
npx hyperframes doctor                       # what is installed and what is missing
npx hyperframes lint  <a filled-in copy>     # common mistakes in a composition
npx hyperframes preview <a filled-in copy>   # live preview in the browser
```

A filled-in copy is a template folder with the four marks replaced and `gsap.min.js`,
`Archivo.woff2` (and `clip.mp4`) copied in, which is what `motion.py` builds for each render.

## Limits

- A render runs inside the web request, one at a time, and starts its own Chrome. A 5 s card takes
  about 8 s on the studio PC; a title over a 6 s video about 9 s.
- A `motion` video is text on a plain ground in one of four looks. It has no pictures, logos, icons,
  charts, music or voice yet.
- A motion video starts on an empty frame, before its first words come on, so its thumbnail in the
  studio is a plain dark rectangle.
- HyperFrames' telemetry, update check and skill downloads are switched off for every render
  (`motion.py` sets the environment for it).
