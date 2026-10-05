# Scene.ai handover

Status at the end of 4 October 2026. Read this first in a new session. It covers where things stand,
the rules, what the app has, what is and is not tested, and what to build next.

| For | Read |
|---|---|
| Starting the app and its settings | [README](../README.md) |
| How the code is organised | [architecture.md](architecture.md) |
| Server addresses and folders on the studio PC | [servers.md](servers.md) |
| Adding workflows and presets files | [workflows.md](workflows.md) |
| Motion graphics and HyperFrames | [motion.md](motion.md) |
| What the code review of 4 October left open | [code-review.md](code-review.md) |

This file does not repeat them.

## 1. What Scene.ai is

A web studio where signed-in users create videos, images and music with AI. It is meant to become a
startup product. The owner is yogesh (yogesh.k@dashverse.ai).

- Rendering is done by a ComfyUI server. Users never see ComfyUI.
- There are workflows for video (MiniMax H3), images (Z-Image Turbo, SDXL, Ideogram 4) and music
  (MiniMax Music 3), and one that upscales a video (SeedVR2). Motion graphics are drawn by
  HyperFrames on the studio's own machine.
- An agent turns a message into a plan the user approves. Its language model is either local (Ollama)
  or hosted (Google Gemini, Kimi), picked per message.
- The app must run on macOS, Windows and Linux.
- Workflows stay dynamic: a ComfyUI workflow file dropped into `workflows/` appears in the app with no code change.

## 2. Machines, addresses and branches

| Thing | Value |
|---|---|
| Repo | `C:\Scene\Scene.ai` on the studio PC (Windows 11, Ryzen 9 7900X, 32 GB RAM, RTX 4060 Ti 8 GB). Before 4 October it was worked on at `/Volumes/Shanks/Scene.ai` on yogesh's MacBook. |
| Branch | **`founder`** holds the app. `main` holds only compiled `.pyc` files and local data committed by mistake; do not work there. |
| ComfyUI | `http://100.123.221.34:8188`, a second Windows PC reached over Tailscale. RTX 5090 (32 GB VRAM), 192 GB RAM, ComfyUI portable at `C:\ComfyUi\ComfyUI_windows_portable`. |
| The agent's models | Default: `gemini/gemini-3.6-flash`, hosted by Google (`agent_model` in `config.json`). Also offered: `gemini-3.5-flash-lite`, and the local `qwen3.5:9b` and `qwen3.5:27b` on Ollama at `http://localhost:11434`. Kimi is set up but switched off (`api_models: "off"`) until its account has credit. See [servers.md](servers.md). |
| Default workflow | `video/video_minimax_h3_i2v` (H3 Image to Video), set by yogesh on 4 October. |
| App | `http://localhost:8080` after `scripts\start.bat` (or `./scripts/start.sh`). |
| Public address | `https://developmenttestinghere.in`, through a Cloudflare Tunnel named `studio`, reaches the app on the studio PC. Neither the app nor the tunnel starts by itself after a reboot: see [servers.md](servers.md). **It is on the open internet with sign-up open**: see section 9. |
| Finished work | `C:\Scene\Outputs\<user email>\`, set by `output_dir` in `config.json`. See [servers.md](servers.md). |
| Python | 3.14, in the repo's `.venv`. |
| Node.js | 24, installed on the studio PC with winget on 4 October, for motion graphics. |
| Design system | https://claude.ai/artifact/BxrhjyavFKAGFUtkNxZ88U (private to yogesh). See section 7. |

Both servers answer only when yogesh has them running. If `/system_stats` or `/api/tags` does not
answer, say so and carry on with what can be done offline; do not wait.

`config.json` and `storage/` are ignored by git on `founder` but tracked on `main`. They do not travel
with the repo: **the database on the studio PC was started fresh on 4 October** (admin
`admin@gmail.com`), and the account and library on the MacBook were not copied over.

**Git state.** The latest commit on `founder` is yogesh's `version -- 1.0.2`. **Everything in this file marked "4 October" is in the working tree and not
committed**: about seventy changed or new files (most of them staged), including `motion/`, `backend/scene/motion.py`,
`sequence.py`, `cast.py`, `outputs.py`, `components/quick.js`, `components/motion.js`,
`components/cast.js`, `scripts/check_models.py`, the image and audio workflows and three new docs.
`workflows/upscaler/` (yogesh's SeedVR2 workflow and its presets file) is new and not yet added to git.
A commit was tried and stopped: git on the studio PC has no author name and email set, and yogesh
said to leave it.

## 3. Rules

1. Never change the workflows saved inside ComfyUI, ComfyUI's Python (`python_embeded`), or its start flags.
2. Never delete files on the ComfyUI PC without asking yogesh.
3. Never test against the real database. `storage/scene.db` holds yogesh's admin account and
   library. Run a second copy of the app with its own storage (section 6).
4. Do not restart or stop yogesh's running app on port 8080. Tell him when a change needs a restart.
5. Workflow files in `workflows/` are never modified by the app. Settings are applied to the copy sent for each job.
6. Do not commit or push unless yogesh asks.
7. Keep it cross-platform: use `pathlib`, no shell-only tricks in app code, keep both start scripts working.
8. The app starts empty for a new user. No sample projects, sample media or placeholder content.
9. Do exactly what is asked and no more. When yogesh says "only the colours" or "don't do anything
   else", that includes not starting test servers or taking screenshots.
10. Reference screenshots from other products (he uses Frameo) show structure he wants, not something
    to copy. Do not reuse their colours, logo, names, wording or his content in them.

## 4. What the app has

### Look
- One stylesheet, `frontend/assets/css/app.css`. Soft and quiet: rounded shapes, filled buttons and
  fields without hard outlines, translucent blurred floating panels, sentence-case labels. The system
  font is used where there is one, the bundled Archivo elsewhere (`frontend/assets/fonts/`, Latin
  letters only). Mono type is kept only for timecode and prices.
- **Palette:** the design system's colours (section 7). Dark: page `#100f0e`, panels `#181716`, text
  `#f2efea`. Light: page `#f4f4f2`, white panels, text `#171614`. Tungsten amber `#ffa51f` and
  Daylight blue `#8ccbff` (`#0b6bb8` in light). The canvas is neutral `#0a0a0a`.
- **Colour rules that must stay:** amber (`--brand`) is only for Generate, selection and work in
  progress; blue (`--agent`) is only for the agent; the everyday primary button is the text colour.
  Amber as text or a line is `--accent`, which darkens in the light theme.
- **Tried and dropped, do not bring back unasked:** an ink `#031211` / ivory `#E8E4D3` / teal
  `#00AEBB` palette (yogesh: "looking worst"), a refinement of it, and a pure black background.
- The **Gate**: two opposing brackets mark whatever is selected (`.gate`), and the same two circle a
  frame while it is being made (`runningGate()` in `dom.js`). Small waits use a stepping square, not a spinner.
- The logo (`frontend/assets/img/logo.svg`) is the Scene mark on an amber tile. Icons are inline SVG
  from `icon()` in `dom.js`. Thumbnails of library items are made in one place, `still()` in `dom.js`.
  A video's thumbnail is a poster, a small picture the server makes once (`media.poster`,
  `/api/library/{id}/poster`, kept in `.posters` in the user's outputs folder), so a page of
  thumbnails does not start loading every video.
- Theme: Light, Dark or Auto, stored in `localStorage` as `scene.theme`. Credits are written `23 cr`.

### Signing in
- The page always opens on **Sign in**, with "New here? Create an account" under it (yogesh,
  4 October). On an installation with no accounts, creating one makes the admin.

### Sidebar and navigation
- The sidebar is short on purpose: **Home**, then **Workspace** with **All projects** and **Library**.
  yogesh removed everything else from it himself; do not add entries back.
- Clicking the user's name at the bottom opens a menu: Settings, Admin console (admins only), Theme, Sign out.
- The other pages have no sidebar entry. In `main.js`, a page with `under` is reached from the page it
  names, and a page with `menu` is listed in the name menu. Canvas and Timeline are reached from a
  project and link to each other; the full Create form is behind "All settings"; Assets and Queue are
  buttons on the Library page.
- While jobs are active, a "N jobs in the queue" line appears in the sidebar and opens the Queue.
- The "Render server online / offline" line is shown to admins only.
- Signing in lands on **All projects** (yogesh, 4 October; it was Home before), and so does opening
  the site with no page in the address. A reload keeps the page the user was on.

### Home (`#/home`)
- A generate bar (`components/composer.js`, used only here) that stays pinned while the page scrolls;
  then **Recent projects**, left out until a project exists; then **Created on Scene.ai**, the user's
  finished work with an All / Videos / Images / Audio switch.
- "Created on Scene.ai" shows only the signed-in user's own work. yogesh's reference shows a public
  showcase; that needs a way to mark items as public, which does not exist. He has not decided.

### All projects (`#/projects`)
- With no projects: a centred "Create your first project" invitation.
- With projects: cards with the newest item as thumbnail (initials if empty), name, item count and
  "3d ago"; search by name; Rename and Delete appear on hover. A card opens the project on the Canvas.
- New project and Rename use a project window (`components/projects.js`). A new project can be given
  its Brief there and opens straight away on its empty Canvas.

### Canvas (`#/canvas`)
- Every finished item is a frame on a board that pans and zooms.
- **Each row is a shot.** Work made from scratch starts a new row at the bottom. Work made from a
  frame joins that frame's row at the right end: "start on" or "continue from" it, a re-run of it, an
  agent trim or split of it, a motion graphic laid over it, an upscale of it; a join goes on the row
  of its first clip.
  The link is `parent` in the settings of a job or an edit (a library item id, checked by the
  server); old items without it each get their own row.
- Rows are named "Shot 1, Shot 2…" down the left; click a name to rename it. Dragging a frame onto
  another row moves it into that shot, and dropping it below the last row starts a new one. The rows
  are saved per project on the server as `{rows: [{id, name, keys}], count}` in the canvas board.
- A selected frame gets Open, Re-run, Add to timeline and Download.
- A job in progress shows as a frame with the running Gate and elapsed time, and its result lands in that spot.
- Keys: `1` fit, `0` 100%, Esc deselect, Enter open, Ctrl/⌘+J show or hide the panel.

### The panel on the right of the Canvas
- It makes new work. Two icon buttons at its top right switch between **Quick actions** and the
  **Agent** (chat). It is open every time the canvas is entered, even if it was closed last time
  (yogesh, 4 October), on Quick actions unless the agent was chosen. It remembers the tab
  and its width (`scene.panel.tab`, `scene.panel.width` in `localStorage`). Its left
  edge can be dragged, 320 to 960 px; a double-click returns it to 380.
- yogesh asked for the panel in place of a composer docked at the bottom of the canvas; do not bring
  the bottom bar back. Its structure follows his Frameo screenshots; see rule 10.

### The cast of a project (`components/cast.js`, `backend/scene/cast.py`)
- What keeps a face, a costume and a place the same from shot to shot. The **Cast** button in the
  head of the panel opens seven roles: main character, the same character from another angle, a
  second person, outfit, location, prop or product, and a voice to imitate. Select a frame on the
  canvas and pin it to a role. yogesh asked on 4 October for whatever improves quality and
  consistency apart from resolution; this and the prompt rules below are the answer.
- The pins are saved per project as a board of kind `cast` (`{role: library item id}`).
  `GET /api/cast?project=&workflow=` returns the cast and which reference slots of that workflow it
  fills. A role finds its slot by the words in the slot's label, so it works for any workflow whose
  slots are named that way; today that is H3 Director.
- **It is applied everywhere.** Quick actions puts the cast into the Source slots of the form (drawn
  with an amber edge, each removable). The agent's `generate` steps get the cast in every slot they
  left empty, shown in the plan as "(cast)". An item the user attached or put in a slot by hand wins.
- **Prompts name the cast** as "the main character", "the outfit", "the background" instead of
  describing looks, which is how H3 ties words to its reference files.

### Quick actions (`components/quick.js`)
- **Create**: Generate image, Generate video, Generate audio. Each is a form built from the workflow:
  Model (the workflows of that kind), Source (the workflow's reference slots, three in view and the
  rest behind "More references"; click, drop a file, or pick a saved asset), Prompt, any further text
  box a presets file keeps in view (the lyrics of a song), then the settings as a row of small pickers
  and Generate with the cost. With one frame selected it offers to start from it.
- **Upscale video** (the fourth card under Create): the workflows in `workflows/upscaler/`. It has no
  prompt. The video selected on the canvas fills its video slot (a file can be dropped there instead),
  Scale is the one setting in view (1.5, 2, 3 or 4), and the result is named "<video> upscaled" and joins the row of
  the video it is made from. Upscalers are left out of the Create page, the Home bar and the agent.
- **Improve prompt**, next to the Prompt box: the agent's model rewrites what was typed into a fuller
  prompt for an image, a video or music, following the project's Brief. It costs nothing, and Undo
  brings back the original until the prompt is edited. Backend: `POST /api/agent/improve`.
- **Motion graphics**, all rendered by HyperFrames, 30 cr a second. See [motion.md](motion.md).
  - **Motion video** (yogesh, 4 October: "a full video, not a few things"): the user says what the
    video is about, the agent's model writes it as scenes, and each scene can be changed, moved,
    removed or added by hand before Render (at most 12 scenes and 60 s). Open to every user, like
    Improve prompt. The form keeps its scenes while the user looks at other actions. Backend:
    `POST /api/motion/scenes`, then `POST /api/motion/render`.
  - Title card, Lower third and Title over video, drawn from HTML templates. The two laid over a
    video use the frame selected on the canvas. yogesh chose to keep all three beside Motion video.

### Agent (`components/agent.js`, `backend/scene/agent.py`)
- **Who may use it.** Admins always; other users only when an admin gives it to them ("Give agent
  access" on a user in the admin console; the `agent` column of `users`). For everyone else the Agent
  tab says "The agent is coming soon", and `/api/agent/status` and `/api/agent/plan` answer 403
  (`agent_user` in `api/deps.py`). yogesh asked for this on 4 October. "Improve prompt" and the
  Ideogram caption use the same model and stay open to every user.
- The user types a message; the agent answers, and when something is to be made it returns a plan of
  steps, each with what it will do and what it costs. **Nothing is made or charged until Approve is
  pressed.** The model only proposes: the server checks every step against the real workflows and
  the selected items and drops what cannot run.
- Every step has a **tool**:

  | Tool | What it does | Cost | Made on Approve through |
  |---|---|---|---|
  | `generate` | A job on a workflow: video, image or music | credits | `POST /api/jobs` |
  | `trim`, `split`, `join` | Cut or join videos the user has, with ffmpeg | free | `POST /api/timeline/export` |
  | `sound` | Put a sound on a video with ffmpeg: music under its own sound, or in place of it | free | `POST /api/edit/sound` |
  | `motion` | A whole motion graphics video, written as scenes of words | credits | `POST /api/motion/render` |
  | `overlay` | A title or a lower third over a selected video | credits | `POST /api/motion/render` |

- **Steps can build on each other.** A step's `after` names an earlier step of the same plan; it then
  starts on that step's picture, or on the last frame of its video. The agent uses it for "make an
  image, then animate it" and for shots that follow one another in one place. On Approve the browser
  carries the steps out in order and a chained step waits for the one before it ("Waits for the step
  before"), so the canvas has to stay open; a plan that was interrupted shows **Resume**. The chat
  stays usable while a plan is being carried out.
- **A shot takes the shape of the picture it starts on** (`shape_like` in `agent.py`, `follow()` in
  `quick.js`): the orientation, or the nearest aspect ratio, follows the frame it starts from. Without
  this a portrait picture came out squashed in a landscape video.
- **Sound on a video** (`sound` tool, `media.add_sound`): the picture is copied untouched; the sound is
  looped or cut to the video's length and faded out; by default it is mixed under the video's own
  sound at 35%. The video and the sound can be attached, or are the newest of each kind among the
  project's last eight items, which the model is shown as "Recent items" so that "attach the music
  you made to this video" works with nothing attached. yogesh hit the gap on 4 October: the agent
  made a BGM, then said it could not attach it and could not use ffmpeg.
- **No speech.** There is no tool that makes a voice-over or dubs a video. The agent is told to say so
  and not to plan a music step for it (it once made a "Hindi voice track" with the music model).
- **A busy hosted model**: the request is tried twice, then the smallest local model answers and the
  reply says so ("Gemini was busy, so qwen3.5:9b answered").
- **It talks.** A greeting, a question or a request for ideas gets a plain answer with no steps.
- **Attached items.** With the Agent tab open, a click on a frame puts it into the message as a chip
  (a small picture and its name) where the cursor is, so several can be attached with words between
  them. The message box is a `contenteditable`; a chip's × or Backspace removes it. When the message
  is sent each chip becomes a tag, `@1`, `@2`… in the order they appear, and the ids go along in that
  order. Attaching is separate from the canvas selection.
- **What an attached item is for.** The user says it ("use @1 as the background, take the motion from
  @2") and the step lists it in `uses`: the item's id and the reference slot of the workflow. The
  server keeps what fits (`uses_for`: the slot exists, the kind fits, each slot once), and on Approve
  the browser fetches each with `POST /api/library/{id}/reference?kind=<what the slot takes>`. A
  workflow that must be given reference files (H3 Reference to Video) is offered only when items are
  attached.
- **Memory.** The last six turns go to the model inside the message itself ("Conversation so far"),
  not as separate chat turns, which the small model largely ignored. A short "generate it" or "use
  that prompt" after a reply with no plan has that reply spelled out in the message (`carry_over`).
- **Prompt rules for quality.** Each workflow's own tips (the `hints` of its presets file) are given
  to the agent as `prompt_tips` and to "Improve prompt", so prompts are written the way that model
  wants. One shot is one action: a request that lists several actions in a row is planned as one step
  per action. With no cast, the agent is told to plan from words and never ask for a picture.
- **Help for a small model**, all in `agent.py`: when the message asks for a sound on a video and the
  model only answers in words, the server plans that step itself (`wants_sound`); when a message does not point at the attached items
  they are not sent (`points_at_selection`), because the model otherwise asks what to do with them; a
  shortened slot id is matched to the full one; a trim that cuts nothing but names a number of parts
  is treated as a split.
- **Hosted models (Kimi, Gemini).** With a key in `config.json` the agent can use models of a hosted
  service beside Ollama's; they are named `<service>/<model>` (`kimi/kimi-k2.6`). Any service that
  speaks the OpenAI chat API fits (`service()` and `_ask_hosted` in `agent.py`). On 4 October: yogesh's
  Kimi key was accepted but the account had no balance, so no real reply was ever seen; no Gemini key
  was set. `scripts/check_models.py` checks them without printing a key. See [servers.md](servers.md).
  **Never read, print or copy `config.json` or a key** (yogesh, 4 October): edit single lines of it
  blind, and test with that script.
- **Model picker.** When there is more than one model, the head of the Agent tab shows a
  dropdown of them; with one model it shows just the name. The choice is kept in this browser
  (`scene.agent.model`) and sent with each message and each "Improve prompt"; a model the server does
  not have falls back to `agent_model`. The caption for Ideogram always uses `agent_model`.
- The **Brief** is a per-project note (style, characters, rules) sent with every message. Past plans
  are kept per project. Jobs the agent started are drawn in blue on the canvas.
- **Limits.** A later step can start on an earlier one's result but cannot use it in any other slot. With
  the default workflow (H3 Image to Video) the cast is not applied; ask for H3 Director by name. The agent cannot see or hear the items: it knows each one's name, kind, length and
  the prompt it was made with, and is told to say so. Any model slips now and then, the local 9b most;
  the plan always shows what will happen and what it costs before anything runs.

### Timeline (`#/timeline`)
- Put videos in order, trim in and out, reorder by dragging, play the cut, export it as one video.
- A "← Canvas" button at the left of the title goes back to the canvas.
- Export joins clips of any size into the frame of the first one, adds silence where a clip has no
  sound, files the result under the workflow id `edit/timeline`, and costs no credits. Items with an
  `edit/` workflow (timeline exports, agent edits, motion graphics) have no Re-run.

### Workflows

| Workflow | Kind | Notes |
|---|---|---|
| `h3_director` | video | Text and up to 11 references to video. Has a time table. The only one with slots for the cast. |
| `video_minimax_h3_i2v` | video | Image to video, first and last frame; also plain text to video. **The default.** It takes an aspect ratio, not an orientation, and has no cast slots. |
| `video_minimax_h3_r2v` | video | Reference to video; needs a reference image. |
| `image_z_image_turbo` | image | Text to image, 8 steps, a few seconds. |
| `image_sdxl_simple` | image | Text to image with a negative prompt, about 6 s. |
| `image_ideogram4_t2i_int8` | image | Strong at layout and lettering, about 10 s. Needs a structured caption, see below. |
| `audio_minimax_music_3` | audio | Text to music with optional lyrics, 30 s to 5 min. |
| `utility_seedvr2_3b_int8_upscale_video` | upscaler | SeedVR2 3B: a video made larger and sharper, scale 1.5 to 4. Added by yogesh on 4 October; **not yet run from the studio**. |

- All eight have a presets file. Five more video files in `workflows/video/` have none and are
  experiments; see [code-review.md](code-review.md).
- **Audio is a third kind** beside video and image: `workflows/audio/`, results with a sound file,
  an Audio filter in the library, a player in the viewer, and a mark with the name where a thumbnail
  would be. A sound cannot be a first frame and cannot go on the Timeline, which is video only.
- **Ideogram 4 needs a structured JSON caption**; a plain prompt comes back as a grey "Image blocked by
  safety filter" picture. Its presets file has `"caption"`, so `POST /api/jobs` has the agent's model
  write the caption from the plain prompt with the instructions the workflow carries (about 15 s).
  The plain prompt is kept as `settings.prompt`. With Ollama off the job is refused before anything is
  charged. See [workflows.md](workflows.md).
- **Pricing (5 October)** follows what was asked for, not GPU time: image 40 cr, video 20 cr/s, audio
  5 cr/s, motion graphics 30 cr/s (10 cr/s when laid over a video the user has, yogesh's choice),
  upscale 20 cr/s of the source video; ₹100 buys 1,000 cr. A new account gets 1,000 cr (yogesh,
  5 October; `signup_credits`, which a value saved in the admin console's Settings overrides). The
  admin console's Economics section reports what each workflow earned and its electricity. Set in the
  admin console's Pricing section, which also holds each workflow's own rate and on/off switch, the
  credit packages and the servers. See "Credits" in [architecture.md](architecture.md) and
  [Studio_Pricing_Compute_Cost_Handover_v1.1.md](Studio_Pricing_Compute_Cost_Handover_v1.1.md).
  **Motion graphics are no longer free.** Built and covered by tests, with the Pricing section looked
  at in headless Chrome; not yet tried by hand in the running app, which needs a restart to have it.
  Not built: payments, the scheduler across Lufi and Zoro, quality or
  resolution multipliers per choice (each workflow has two plain multipliers, both 1). A video dropped
  into the upscaler as a file is measured by the server when the job is queued and charged by that; a
  video picked from the canvas is charged by the length of the item named as `parent`.

### From before, unchanged and working
Accounts (first account is admin, scrypt passwords, login throttle); the Create page with a form
built from the workflow, reference boxes, live estimate and warnings; long videos as chained clips;
Assets; the Library with viewer, search and projects; the Queue with live progress; credits charged
on queue and refunded on failure; and the admin console (overview, users, jobs, library, credits,
workflows, system, audit log, settings, with CSV export).

### Backend pieces worth knowing
- `api/workspace.py`: `/api/boards/{canvas|timeline|brief|agent}` (one saved JSON document per user,
  project and kind), `/api/timeline/export`, `/api/motion/templates`, `/api/motion/scenes`,
  `/api/motion/render`, `/api/agent/status`, `/api/agent/plan`, `/api/agent/improve`.
- `api/library.py`: besides `/api/library/{id}/file`, `/api/library/{id}/poster` gives a video's
  thumbnail; the admin console has the same under `/api/admin/library/`. The browser keeps a poster
  and only asks whether it changed (an `ETag` and a 304). Deleting an item deletes its poster.
- `catalog.py`: reads `workflows/video`, `image`, `audio` and `upscaler` (`FOLDERS`). `KINDS` stays
  the three kinds of thing that are made, which is what the Create page's tabs and the library's
  filters use.
- `agent.py`: the Ollama call, the rules given to the model (`SYSTEM`, `IMPROVE`, `WRITE_SCENES`),
  the checkers for each kind of step (`settings_for`, `uses_for`, `edits_for`, `motion_for`), and
  `founded`, which drops a figure or a quotation the model made up for a motion video.
- `motion.py` and `sequence.py`: HyperFrames renders, from a template or from scenes of words.
- `outputs.py`: where each user's finished work is kept, a folder named after their email.
- `media.py`: ffmpeg helpers; `probe()` gives the length, frame size and whether there is sound, and
  `poster()` makes a video's thumbnail (a JPEG up to 960 px wide, from 0.1 s in).
- `main.py`: every page file is served with `Cache-Control: no-cache`, so the browser always checks
  for a newer file. That is not enough behind Cloudflare, which tells browsers to keep
  script and style files for four hours whatever the app says. So the page fetches its stylesheet and
  script from under `/v/<time of the last change>/assets/…`; the scripts import each other by relative
  address, so a change to any file gives every one of them a new address. Before this (4 October) a
  browser ran new code against old files twice: an unstyled coming-soon card, and an admin console
  without the "Give agent access" button.

## 5. Job settings

What the browser sends to `POST /api/jobs` (multipart, field `settings` as JSON, plus files named `ref:<slot id>`):

```json
{
  "workflow": "video/h3_director",
  "name": "my video",
  "values": {"100:value": "prompt text"},
  "options": {"mode": "fast", "quality": "low"},
  "resolution": 768,
  "orientation": "landscape",
  "seed_mode": "fixed",
  "clips": 1,
  "project_id": null,
  "parent": null,
  "refs": {"201:image": {"asset_id": 3}}
}
```

A control or slot id is `"<node id>:<input>"`. A `refs` entry is `{"asset_id": n}` or
`{"comfy_name": "scene_..."}`; uploaded files are added by the server. `parent` is the library item
the job is made from, which puts the result on that item's row of the canvas.

## 6. How to test safely

Run a second copy of the app with its own storage, its own outputs folder and its own port, so the
real database and `C:\Scene\Outputs` are untouched:

```bash
cd backend
SCENE_STORAGE_DIR=/path/to/scratch SCENE_OUTPUT_DIR=/path/to/scratch/outputs SCENE_PORT=8099 SCENE_HOST=127.0.0.1 \
  SCENE_COMFY_URL=http://127.0.0.1:9 SCENE_OLLAMA_URL=http://127.0.0.1:9 ../.venv/Scripts/python.exe -m scene
```

- **`SCENE_OUTPUT_DIR` is needed** since `config.json` names the real outputs folder; without it the
  test copy writes into `C:\Scene\Outputs`.
- The two `:9` addresses keep it away from the render PC and the model server. Leave one out only for
  a deliberate real run: a real ComfyUI job leaves its file in ComfyUI's output folder on the render PC.
- On macOS and Linux the Python is `../.venv/bin/python`.
- Register a throwaway account. To have something to look at, put files into the scratch outputs
  folder (in a sub-folder named after the account's email) and insert `generations` rows for them.
- Workflows saved without their node settings (most of the new ones) need node definitions. Copy
  `storage/cache/node_definitions.json` into the scratch storage's `cache/` folder, or the offline
  copy lists them as unreadable.

What worked for browser checks:

- A temporary page in `frontend/` that signs in with `fetch`, sets `location.hash`, then imports
  `/assets/js/main.js`; screenshot it with headless Chrome
  (`--headless=new --screenshot=... --virtual-time-budget=14000`). Clicks and drags can be made in
  that page by dispatching `PointerEvent`s. **Delete the page afterwards.**
- Give each Chrome run its own `--user-data-dir` and a time limit; a shared profile hangs.
- Stop the test server by port. Windows:
  `netstat -ano | grep 127.0.0.1:8099 | grep LISTENING` then `taskkill //PID <pid> //F`. macOS:
  `lsof -ti :8099 | xargs kill`.
- Videos do not decode in headless Chrome, so a video in the viewer or on the Timeline comes out
  blank or black; it is fine in a normal browser. Thumbnails are posters (pictures) and do render.
- The server marks a job left as `running` as failed when it starts, so a simulated running job has to
  be inserted after the server is up.
- An offline job fails and is refunded within seconds, so do not assert on the credit balance after one.
- One "401 on /api/auth/me" in the console on first load is expected.
- On the studio PC the shell tools run in Git Bash. Node.js is at `C:\Program Files\nodejs`, which a
  terminal opened before the install does not have on its PATH.

To try the agent against the real model without the app, build the question with `agent.question()`
from workflow schemas and call `Agent.ask()` directly; it needs only Ollama.

When yogesh reports that a change "is not there": a backend change needs the app restarted, and a
front-end change needs a hard reload (Ctrl + Shift + R).

## 7. The design system and where it stands

The artifact in section 2 holds the brand book, tokens, logo files and 16 component previews. The
logo files are also in `design/logo/`.

**The app follows it for colours and ideas, not for shapes.** The page describes the first, harder
version: sharp 2 px media corners, uppercase mono labels, wide titles, no translucent panels. yogesh
then asked for a softer look, and that is what the app has. Treat `app.css` as the truth for shapes
and type, and the artifact as the source for the palette, the logo, the colour rules and the
vocabulary (takes, the Brief, `cr`). yogesh has been asked whether to update the page to the softer
look and has not answered.

`design/previews/` holds screenshots from every stage, all from before 4 October. None shows the
canvas panel, the rows of shots or the sign-in page as they are now. The `teal-*`, `v2-*` and the
unprefixed component shots are from dropped or earlier stages and can be deleted.

## 8. What was tested, and what was not

| Tested on 4 October | Result |
|---|---|
| Automated tests | 60 pass, with no ComfyUI, Ollama or Node.js needed |
| A chained plan on the real server | An SDXL picture in 6 s, then a 5 s H3 Image to Video clip starting on it in 33 s, in the picture's portrait shape |
| A cast on the real server | One 5 s H3 Director clip with a pinned character and location, 40 s at 480p low |
| Z-Image Turbo, SDXL, Ideogram 4, MiniMax Music 3 on the real server | Each made its file: images in 6 to 10 s, a 25 s music clip in 21 s |
| Ideogram 4 with a plain prompt | Caption written by the local model in 14 s, poster with correct lettering, 26 s in all |
| Motion templates through the API | Title card, lower third and title over video each rendered in 8 to 9 s; a frame of each was looked at |
| A motion video planned by the agent | Six scenes, 16 s, rendered in 14 s; a frame of each scene was looked at |
| A motion video from Quick actions | Through the API on a test copy: `qwen3.5:9b` wrote five scenes in about 25 s, the 24 s video rendered in 9 s, four frames were looked at. The form was opened in headless Chrome and scenes added and changed |
| Video posters | In the test suite with real ffmpeg, and on the rendered motion video: a JPEG, a 304 when asked again, gone when the item is deleted |
| The Upscale video form | In headless Chrome on an offline copy: the card, a selected video filling the slot, and the button sending that video to the render server, where it stopped because the server was off |
| The agent's 16 test requests | `qwen3.5:9b` 28 of 32, `qwen3.5:27b` 15 of 16 (but a minute a reply); see section 9 |
| Gemini through its API | The key works; `gemini-3.5-flash-lite` got six of six on a replay of yogesh's hospital chat; `gemini-3.6-flash` was often "experiencing high demand" and the local model stood in |
| A sound put on a video | In the test suite with real ffmpeg: a 1 s tune looped under a 3 s clip |
| Improve prompt against the real model | English prompts and a brief kept their meaning |
| In headless Chrome on an offline copy | The panel and both tabs, the image, video and audio forms, the motion section, the cast editor and its slots in the video form, the rows of shots, a frame dragged to another row, three items attached inline to a message, the panel dragged wider, the audio viewer, the coming-soon card as a normal user |

Earlier, on the MacBook: an agent plan approved and rendered on real ComfyUI (5 s at 480p in 46 s),
a single clip and a 2-clip chain, a timeline export of three clips, and a database upgrade on a copy
of the real one.

Not tested:

- **The upscaler has never run.** The render PC was off when it was added. The job graph was checked
  (the scale and the uploaded video reach the right nodes), nothing more: how long it takes, and
  whether scale 3 or 4 fits in memory, is unknown.
- **Pressing the last button in a real browser.** Generate from Quick actions, Write scenes and
  Render on a motion form, and Approve on an agent plan with edits, attached items or motion steps were each tested up
  to the request they send and from the endpoint they call, but not by a click in the running app.
- Video posters and the panel opening on every visit, in a real browser.
- A running job taking its place on a row of the canvas and being replaced by its result.
- A song with lyrics; only an instrumental was made.
- Uploading or dropping a reference file and picking a saved asset in the Quick actions form.
- Panning and zooming the canvas with a real mouse or trackpad; renaming a shot (the box opens).
- Timeline playback and drag-to-reorder.
- The colours on every page, the render server line as a non-admin, and the six front-end fixes from
  the code review; all were read through, not looked at.
- macOS and Linux since the move to the studio PC, including the start script's `npm install` step.
- Chains with a voice track or more than 2 clips; cancelling a running job on real ComfyUI.
- `video_minimax_h3_r2v` end to end.

## 9. Known issues and gaps

- **`video_minimax_h3_i2v` works.** The "SaveVideo … 'format'" failure seen from the MacBook did not
  happen on the studio PC: it made two 5 s clips on 4 October, in 33 and 39 s on the Turbo setting.
- **The agent's models.** The default is Gemini 3.6 Flash, which was often "experiencing high demand" on
  4 October; the request is then tried twice and the local `qwen3.5:9b` answers instead. `gemini-3.5-flash-lite`
  answered every time and would be the steadier default; yogesh has been told. Local models compared
  on the same 16 requests: the 9b got 28 of 32 at a median of 9 s a reply; the 27b got 15 of 16 at a
  median of 63 s and up to 183 s, because only 5 of its 19 GB fit the studio PC's 8 GB graphics card,
  and the agent's request times out at 180 s. Kimi: the key is accepted, the account has no balance.
- **The app is on the public internet** at `developmenttestinghere.in` with `allow_signup` true and
  `secure_cookies` false. Anyone who finds it can make an account, gets 1,000 credits, and can queue jobs
  on the render PC and use "Improve prompt" on yogesh's Gemini key. There is no email check and no
  payment. Since 5 October one visitor address can make three accounts a day (`signups_per_day` in
  `config.json`; 0 for no limit), which slows this down and does not stop it. yogesh was told on
  4 October; closing sign-up is one switch in the admin console's Settings tab.
- **The API keys were seen in a chat.** Both keys in `config.json` were shown to the assistant by the
  editor each time yogesh saved the file on 4 October. He was advised to regenerate them. They are not
  in git: `scripts/check_models.py` checks that.
- **No speech.** Nothing in the studio makes a voice-over or dubs a video; the agent says so.
- **Consistency without a cast is weak.** With nothing pinned, each shot of "she" is a different
  woman; the 9b model does not reliably repeat a description across steps. Pinning a cast is the fix.
- **The cast on a real render**: one low-quality 480p H3 clip was made with a pinned character and a
  pinned location. The character came through clearly; the location did not show in that draft. Not
  yet tried at medium quality or with people.
- **Motion graphics are words on a plain ground**: no pictures, logos, icons, charts, music or voice.
- **A motion video's thumbnail is blank.** The poster is taken 0.1 s in, before the first words have
  come on, so its tile is a plain dark rectangle.
- **The model invents details for a motion video.** A made-up figure or quotation is dropped by the
  server; smaller inventions (opening hours, "fresh pastries") are not, which is why the scenes are
  shown for correction before anything is rendered.
- **The tunnel's log shows "stream canceled by remote" errors** for `/api/library/…/file`. They are
  the browser closing a download it no longer needs, not a fault. Posters removed the burst that every
  page of thumbnails caused; opening or scrubbing a video still logs a few. See [servers.md](servers.md).
- **The visitor's address through the tunnel** is read from Cloudflare's `CF-Connecting-IP` header
  since 5 October (`client_address` in `security.py`), for the login throttle, the sign-up limit and the
  audit log. It is believed only when the request comes from this machine. Not tried through the real
  tunnel. The throttle is still per email, so trying many emails from one address is not blocked.
- **Still loading whole videos for a thumbnail**: the clip strip of the Timeline and the Assets page,
  which do not use `still()`.
- **Renders and exports run inside the web request**: a timeline export, an agent edit and a motion
  render each hold their request until done, one motion render at a time.
- **Improve prompt can lose meaning** for a prompt that is not in English: Hindi in Latin letters came
  back in English with a detail dropped.
- **Plain browser prompts remain** for "New project…" on the Create and Library pages, for project
  rename on the Library page, and for warnings before generating in Quick actions.
- **Canvas rows for "All work" and for each project are separate.** A frame moved in one view is not moved in the other.
- **Timeline is one video track.** No audio tracks, transitions, images or titles.
- **Assets are single files**, and saved assets are still kept in folders named by user id.
- **Chains do not carry a voice**, and long chains may drift because each clip starts from a decoded frame.
- **One GPU, one job at a time. SQLite and local files.** Fine for one machine only.
- **No email and no payments.** Credits come only from an admin. https is Cloudflare's, in front of
  the tunnel; the app itself still serves plain http with `secure_cookies` false.
- **Uploads are limited to 200 MB each.** There is no limit on how many.
- **`main` is a mess** (section 2). It should be reset to match `founder` once yogesh agrees.
- **Test files on the ComfyUI PC.** Test runs left `scene_*` files in its input folder and results in
  its output folder: videos from 3 October including "Robot on Bridge", and about seven images and one
  music clip from 4 October. Ask yogesh before deleting them.
- **`legacy/`** holds a broken command-line script and old sample media. The app does not use it.

## 10. Next plan

### Waiting on yogesh
- Committing the 4 October work, and tidying `main`.
- Whether to make `gemini-3.5-flash-lite` the default model, and regenerating the two API keys (section 9).
- Whether "Improve prompt" and the Ideogram caption should also be limited to users with agent access.
- Setting git's author name and email on the studio PC.
- Whether "Created on Scene.ai" should become a showcase shared between users.
- Whether to update the design system page to the softer look.
- Whether to delete the stale screenshots, the experimental workflows and `legacy/`.

### Next up
1. **Try everything by hand in the real app** and fix what the "not tested" list turns up.
2. **Richer motion graphics**: pictures and clips from the library inside a scene, and more scene kinds.
   **Speech**: a text-to-speech workflow, so a voice-over can be made and put on a video with the sound tool.
3. **Editing as quick actions**: trim, speed, reframe and convert on a selected frame, with ffmpeg.
4. **Run renders and exports through the job queue**, so they show progress and do not hold a request.
5. **Run the upscaler once for real**, on a short clip at scale 2, then find what scale and length
   the render PC can take. **Measure the new workflows** and give each a time table, so they are
   priced from the first run.
6. **Agent: saved assets as references**; the cast at medium quality with people; cast slots for
   workflows other than H3 Director.
7. **Use the project window everywhere** a project is created or renamed.
8. **Work through what is left in [code-review.md](code-review.md)**.
9. **Character bundles** and **variations** (several drafts with different seeds, then finalise one).

### Before outside users
10. Payments, email (verification, reset, "your video is ready"), https and a domain, upload and rate limits, a landing page.

### Scaling
yogesh asked on 4 October for a plan to move to PostgreSQL and a NoSQL store, then put it **on hold**
until it is needed (outside users, more than one app process, or more than one GPU). The plan agreed
in outline: PostgreSQL for everything, with the settings and board documents as `JSONB`, not
MongoDB; `db.py` rewritten behind its same three functions (`run`, `one`, `all`; 127 calls in 12
files) with SQLite kept as the fallback for tests; Alembic migrations; a copy-and-verify script for
the data; Redis for the queue, live events and login throttle only when there are several processes;
object storage for files last. Open when it resumes: where PostgreSQL runs (this PC or hosted).
11. More than one GPU, Postgres and object storage, Docker, CI, error tracking, backups.
12. A React front end, only once the UI outgrows plain modules.

## 11. Measured timings

**H3 Director on the RTX 5090, 768p, one clip**

| Mode | Quality | 5 s | 10 s | 15 s |
|---|---|---|---|---|
| fast | low | 0.9 min | 2.0 min | 18 min |
| fast | medium | 2.3 min | 6.1 min | ~25 min (est.) |
| fast | high | ~4.3 min (est.) | ~14 min (est.) | unknown |
| normal | low | 1.2 min | 3.2 min | ~25 min (est.) |
| normal | medium | 4.3 min | 13.8 min | ~1.5 h (est.) |
| normal | high | 8.3 min | 27.0 min | ~3 h (est.) |

A single 15 s clip overflows 32 GB of VRAM, which is why chaining 5 s clips is the way to make long
videos. At 480p, fast/medium, a 5 s clip took 46 s.

**Everything else, each measured once on 4 October**

| What | Where | Time |
|---|---|---|
| Z-Image Turbo, 1344 × 768 | render PC | a few seconds |
| SDXL, 1344 × 768, 25 steps | render PC | 6 s |
| Ideogram 4, Turbo preset | render PC | about 10 s, plus about 15 s for the caption |
| MiniMax Music 3, 25 s of music | render PC | 21 s |
| Motion title card, 5 s at 1920 × 1080 | studio PC | 8 s |
| Motion video of six scenes, 16 s | studio PC | 14 s |
| Motion video of five scenes, 24 s | studio PC | 9 s, after about 25 s for `qwen3.5:9b` to write the scenes |
| An agent reply from `qwen3.5:9b` | studio PC | 6 to 25 s |

## 12. Quality lessons for H3 (shown as Tips in the app)

- Low quality is a draft: smudges, soft backgrounds, frozen mouths. Use medium or high for finals.
- Lip sync needs a voice track, with one speaker per clip.
- Use a background image or a first frame to keep the same location.
- Use reference images of at least 1024 px with no watermarks or text.
- Best results come from 5-6 s clips, one action each, and a locked camera.
- Keep CFG at 1.
