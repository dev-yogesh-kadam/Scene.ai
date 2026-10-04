# Scene.ai handover

Status on 4 October 2026. Read this first in a new session. It covers where things stand, the rules,
what the app has, what is and is not tested, and what to build next.

For how to start the app and its settings, see the [README](../README.md). For how the code is
organised, see [architecture.md](architecture.md). For adding workflows and presets files, see
[workflows.md](workflows.md). For the bugs, risks and clean-up found in the code review of 4 October,
see [code-review.md](code-review.md). This file does not repeat them.

## 1. What Scene.ai is

A web studio where signed-in users create videos and images with AI. It is meant to become a startup
product. The owner is yogesh (yogesh.k@dashverse.ai).

- Rendering is done by a ComfyUI server. Users never see ComfyUI.
- Video workflows (MiniMax H3) exist today. yogesh will add image workflows later.
- The app must run on macOS, Windows and Linux.
- Workflows stay dynamic: a ComfyUI workflow file dropped into `workflows/` appears in the app with no code change.

## 2. Machines, addresses and branches

| Thing | Value |
|---|---|
| Repo | `/Volumes/Shanks/Scene.ai` on yogesh's MacBook |
| Branch | **`founder`** holds the app. `main` holds only compiled `.pyc` files and local data committed by mistake; do not work there. |
| ComfyUI | `http://100.123.221.34:8188`, a Windows PC reached over Tailscale. RTX 5090 (32 GB VRAM), 192 GB RAM, ComfyUI portable v0.38.0 at `C:\ComfyUi\ComfyUI_windows_portable` |
| Ollama (the agent's model) | `http://100.71.159.106:11434` over Tailscale, model `qwen3.5:9b`. Set in `config.json` as `ollama_url` and `agent_model`. |
| App | `http://localhost:8080` after `./scripts/start.sh` |
| Python | 3.14 on the Mac, in the repo's `.venv` |
| Design system | https://claude.ai/artifact/BxrhjyavFKAGFUtkNxZ88U (private to yogesh). See section 7. |

Both servers answer only when yogesh has them running, and he often has them off. If `/system_stats`
or `/api/tags` does not answer, say so and carry on with what can be done offline; do not wait.

`config.json` and `storage/` are ignored by git on `founder` but tracked on `main`. After switching
from `main` to `founder`, put them back with
`git restore --source=main --worktree -- config.json storage`.

**Git state.** `founder` has two commits: the first version, and `version -- 1.0.1` (the work of
3 October: new look, Canvas, Timeline, agent). Everything marked "4 October" below is staged by
yogesh but not committed.

## 3. Rules

1. Never change the workflows saved inside ComfyUI, ComfyUI's Python (`python_embeded`), or its start flags.
2. Never delete files on the ComfyUI PC without asking yogesh.
3. Never test against the real database. `storage/scene.db` holds yogesh's real admin account and
   library. Run a second copy of the app with its own storage (section 6).
4. Do not restart or stop yogesh's running app on port 8080. Tell him when a change needs a restart.
5. Workflow files in `workflows/` are never modified by the app. Settings are applied to the copy sent for each job.
6. Do not commit or push unless yogesh asks.
7. Keep it cross-platform: use `pathlib`, no shell-only tricks in app code, keep both start scripts working.
8. The app starts empty for a new user. No sample projects, sample media or placeholder content.
9. Do exactly what is asked and no more. When yogesh says "only the colours" or "don't do anything
   else", that includes not starting test servers or taking screenshots. He twice stopped a command
   that went on to do that.
10. Reference screenshots from other products (he uses Frameo) show structure he wants, not something
    to copy. Do not reuse their colours, logo, names, wording or his content in them.

## 4. What the app has

### Look
- One stylesheet, `frontend/assets/css/app.css`. Soft and quiet: rounded shapes, filled buttons and
  fields without hard outlines, translucent blurred floating panels, sentence-case labels. The system
  font is used where there is one (San Francisco on Apple devices), the bundled Archivo elsewhere
  (`frontend/assets/fonts/`, Latin letters only). Mono type is kept only for timecode and prices.
- **Palette:** the design system's colours (section 7). Dark: page `#100f0e`, panels `#181716`, text
  `#f2efea`. Light: page `#f4f4f2`, white panels, text `#171614`. Tungsten amber `#ffa51f` and
  Daylight blue `#8ccbff` (`#0b6bb8` in light). The canvas is neutral `#0a0a0a`.
- **Colour rules that must stay:** amber (`--brand`) is only for Generate, selection and work in
  progress; blue (`--agent`) is only for the agent; the everyday primary button is the text colour.
  Amber as text or a line is `--accent`, which darkens in the light theme.
- **Tried and dropped on 4 October, do not bring back unasked:** an ink `#031211` / ivory `#E8E4D3` /
  teal `#00AEBB` palette (yogesh: "looking worst"), a refinement of it, and a pure black background.
  He then asked to return to the design system's colours, changing colours only.
- The **Gate**: two opposing brackets mark whatever is selected (`.gate`), and the same two circle a
  frame while it is being made (`runningGate()` in `dom.js`). Small waits use a stepping square, not a spinner.
- The logo (`frontend/assets/img/logo.svg`) is the Scene mark on an amber tile. Icons are inline SVG
  from `icon()` in `dom.js`, with rounded line ends.
- Theme: Light, Dark or Auto (follow the computer), stored in `localStorage` as `scene.theme`.
- Credits are written `23 cr`.

### Sidebar and navigation (4 October)
- The sidebar is short on purpose: **Home**, then **Workspace** with **All projects** and **Library**.
  yogesh removed everything else from it himself; do not add entries back.
- Clicking the user's name at the bottom opens a menu: Settings, Admin console (admins only), Theme, Sign out.
- The other pages have no sidebar entry. In `main.js`, a page with `under` is reached from the page it
  names, and a page with `menu` is listed in the name menu:
  Canvas and Timeline are reached from a project and link to each other; the full Create form is
  behind "All settings" in the generate bar; Assets and Queue are buttons on the Library page.
- While jobs are active, a "N jobs in the queue" line appears in the sidebar and opens the Queue.
- Signing in always lands on Home. A reload keeps the page the user was on.

### Home (`#/home`, 4 October)
- A generate bar (the quick composer) that stays pinned while the page scrolls; then **Recent
  projects**, left out completely until a project exists; then **Created on Scene.ai**, the user's
  finished work at its true proportions with an All / Videos / Images switch.
- "Created on Scene.ai" shows only the signed-in user's own work. yogesh's reference shows a public
  showcase; that would need a way to mark items as public, which does not exist. He has been told and
  has not decided.

### All projects (`#/projects`, 4 October)
- With no projects: a centred "Create your first project" invitation.
- With projects: cards with the newest item as thumbnail (initials if empty), name, item count and
  "3d ago"; search by name; Rename and Delete appear on hover. A card opens the project on the Canvas.
- New project and Rename use a project window (`components/projects.js`). A new project can be given
  its Brief there and opens straight away on its empty Canvas.
- `/api/projects` returns each project's newest item (`cover_id`, `cover_kind`) and `updated`.

### Canvas (`#/canvas`)
- Every finished item is a frame on a board that pans and zooms. Frames can be moved; positions are
  saved per project on the server.
- A selected frame gets Open, Re-run, Add to timeline and Download.
- A job in progress shows as a frame with the running Gate and elapsed time, and its result lands in that spot.
- A **composer** is docked at the bottom: prompt, a strip of the main settings, and Generate with the
  cost in the button. With one frame selected it offers to continue from it. Everything else uses the
  workflow's defaults.
- Keys: `1` fit, `0` 100%, Esc deselect, Enter open, Ctrl/⌘+J agent.

### Timeline (`#/timeline`)
- Put videos in order, trim in and out, reorder by dragging, play the cut, export it as one video.
- Export joins clips of any size into the frame of the first one, adds silence where a clip has no
  sound, files the result in the library under the workflow id `edit/timeline`, and costs no credits.
  Items with an `edit/` workflow have no Re-run.

### Agent (panel on the Canvas)
- The user types an instruction; the agent returns a plan: one step per shot with a written prompt,
  the workflow and settings, and the cost. **Nothing is queued or charged until Approve is pressed.**
- The model only proposes. `backend/scene/agent.py` checks each step against the real workflows and
  drops anything they can't take; the browser then queues approved steps through the normal `POST /api/jobs`.
- The **Brief** is a per-project note (style, characters, rules) sent with every instruction.
- Past plans are kept per project. Jobs the agent started are drawn in blue on the canvas.
- Limits: steps cannot use each other's results (a longer continuous video is one step with chained
  clips); it only offers workflows that need no reference files, apart from a first frame taken from
  the canvas selection; the model is small and sometimes needs the plan corrected, so the cost is always shown first.

### From before, unchanged and working
Accounts (first account is admin, scrypt passwords, login throttle); the Create page with a form
built from the workflow, reference boxes, live estimate and warnings; long videos as chained clips;
Assets; the Library with viewer, search and projects; the Queue with live progress; credits charged
on queue and refunded on failure; and the nine-tab admin console (overview, users, jobs, library,
credits, workflows, system, audit log, settings, with CSV export).

Three presets files exist: `h3_director`, `video_minimax_h3_i2v` and `video_minimax_h3_r2v`.

### Backend pieces worth knowing
- `api/workspace.py`: `/api/boards/{canvas|timeline|brief|agent}` (one saved JSON document per user,
  project and kind, in the `boards` table), `/api/timeline/export`, `/api/agent/status`, `/api/agent/plan`.
- `agent.py`: the Ollama call, the rules given to the model, and the step checker.
- `media.py`: `sequence()` for timeline export; `probe()` also returns the frame size.
- `main.py`: every page file is served with `Cache-Control: no-cache`, so the browser always checks
  for a newer file (added 4 October; needs one restart of the app to take effect).

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
  "refs": {"201:image": {"asset_id": 3}}
}
```

A control or slot id is `"<node id>:<input>"`. A `refs` entry is `{"asset_id": n}` or
`{"comfy_name": "scene_..."}`; uploaded files are added by the server.

## 6. How to test safely

Run a second copy of the app with its own storage and port, so the real database is untouched:

```bash
cd backend
SCENE_STORAGE_DIR=/path/to/scratch SCENE_PORT=8099 SCENE_HOST=127.0.0.1 \
  SCENE_COMFY_URL=http://127.0.0.1:9 SCENE_OLLAMA_URL=http://127.0.0.1:9 ../.venv/bin/python -m scene
```

The two `:9` addresses keep it away from the render PC and the model server; leave them out only for
a deliberate real run. Then register a throwaway account. To have something to look at, copy a few
files from `storage/outputs/` into the scratch storage and insert `generations` rows for them.

What worked for browser checks:

- A temporary page in `frontend/` that signs in with `fetch`, sets `location.hash`, then imports
  `/assets/js/main.js`; screenshot it with headless Chrome
  (`--headless=new --screenshot=... --virtual-time-budget=20000`). **Delete the page afterwards**; if a
  command is interrupted, check that it is gone.
- Give each Chrome run its own `--user-data-dir` and a time limit; a shared profile hangs.
- Stop the test server by port: `lsof -ti :8099 | xargs kill`. `pkill -f "python -m scene"` misses it on macOS.
- Do not use a bare `wait` in a shell that also started the server; it waits for the server too.
- Videos do not decode in headless Chrome, so video thumbnails come out blank or black. Still images
  render. They are fine in a normal browser.
- The server marks a job left as `running` as failed when it starts, so a simulated running job has to
  be inserted after the server is up.
- The shell is zsh: it does not split unquoted variables, and a bare `=====` in a command is an error.
- One "401 on /api/auth/me" in the console on first load is expected.

When yogesh reports that a change "is not there", check his screenshot for the old layout first: until
he restarts the app once (see `main.py` above), his browser can show cached page files, and a hard
reload (Cmd + Shift + R) fixes it.

## 7. The design system and where it stands

The artifact in section 2 holds the brand book, tokens, logo files and 16 component previews. The
logo files are also in `design/logo/`.

**The app follows it for colours and ideas, not for shapes.** The page describes the first, harder
version: sharp 2 px media corners, uppercase mono labels, wide titles, no translucent panels. yogesh
then asked for a softer look, and that is what the app has. Treat `app.css` as the truth for shapes
and type, and the artifact as the source for the palette, the logo, the colour rules and the
vocabulary (takes, the Brief, `cr`). yogesh has been asked whether to update the page to the softer
look and has not answered.

`design/previews/` holds screenshots from every stage. Only these show the current app:
`studio/home-dark.png`, `home-empty.png`, `projects-first.png`, `account-menu.png`, `dialog-first.png`
(layout; the last two were shot in the dropped teal palette) and `studio/soft-*.png` (colours). The
`teal-*`, `v2-*` and the unprefixed component shots are from dropped or earlier stages and can be deleted.

## 8. What was tested, and what was not

| Tested | Result |
|---|---|
| Automated tests | 38 pass, no ComfyUI or Ollama needed |
| Agent plan, approve, real render (fast/medium, 480p, 5 s) | Video in the library in 46 s, 6 credits charged, step shown as Done |
| Agent plans against the real model | Portrait, a 15 s shot as 3 chained clips, and an unclear request answered with a question |
| Timeline export of three real clips of different sizes | 9.2 s video, with sound |
| Canvas with a job in progress, selection, composer | Rendered correctly (job simulated) |
| Home, All projects (empty and filled), account menu, project window | Rendered correctly on an offline copy; a project and its Brief were created through the window |
| Earlier: single clip and a 2-clip chain on real ComfyUI; database upgrade on a copy of the real one | Passed |

Not tested:

- **The current colours on screen.** After the return to the design system's palette nothing was
  rendered, at yogesh's request. The stylesheet was checked for leftover teal values only.
- Generating from the Home bar and from the canvas composer, and "continue from the selected frame"
  (composer or agent). Both servers were off when the Home bar was built.
- Dragging frames, panning and zooming the canvas with a real mouse or trackpad.
- Timeline playback and drag-to-reorder.
- Hover actions, rename, delete and search on All projects; the account menu on a narrow window.
- An agent plan with more than one step run for real.
- The Library, Assets, Queue, Settings and sign-in pages in the soft look (captured, not reviewed).
- Windows and Linux; the system-font fallback to Archivo there.
- Chains with a voice track or more than 2 clips; cancelling a running job on real ComfyUI.
- Any workflow other than H3 Director end to end.

## 9. Known issues and gaps

- **`video_minimax_h3_i2v` fails on the real server** with "SaveVideo.execute() missing 1 required
  positional argument: 'format'" (seen twice in yogesh's queue on 4 October). The job graph does not
  fill the save node's `format` input. Not investigated; needs ComfyUI running.
- **No image workflows.** `workflows/image/` is empty. The code path exists but has never run.
- **Plain browser prompts remain** for "New project…" on the Create and Library pages, and for
  project rename on the Library page. All projects uses the project window.
- **Canvas positions for "All work" and for each project are separate.** An item moved in one view is not moved in the other.
- **Timeline is one video track.** No audio tracks, transitions, images or titles. Export runs inside the request, so a long cut blocks it until done.
- **The agent cannot chain steps or upload references** (see section 4).
- **Assets are single files.** A character is one image, not a bundle of face, outfit and voice.
- **Chains do not carry a voice**, and long chains may drift because each clip starts from a decoded frame.
- **One GPU, one job at a time. SQLite and local files.** Fine for one machine only.
- **No email, no payments, no https.** Credits come only from an admin.
- **No upload limits** on reference files, except 200 MB on assets.
- **`main` is a mess** (section 2). It should be reset to match `founder` once yogesh agrees.
- **Test files on the ComfyUI PC.** Test runs left `scene_*` files in its input folder and test videos in its output folder, including "Robot on Bridge" from 3 October. Ask yogesh before deleting them.
- **`legacy/`** holds a broken command-line script and old sample media. The app does not use it.

## 10. Next plan

### Waiting on yogesh
- Whether "Created on Scene.ai" should become a showcase shared between users.
- Whether to update the design system page to the softer look.
- Committing the 4 October work, and tidying `main`.

### Next up
0. **Work through [code-review.md](code-review.md)**, starting with its six front-end bugs.
1. **Look at the current colours on every page** once yogesh allows a render, and fix what is off.
2. **Try the new pages by hand** and fix what the "not tested" list turns up.
3. **Fix the `video_minimax_h3_i2v` save error** when ComfyUI is on.
4. **Use the project window everywhere** a project is created or renamed.
5. **Image workflows.** Blocked on yogesh adding files to `workflows/image/`. Then check the form, run
   one end to end, and test "Use as first frame" from an image.
6. **Agent: steps that build on each other** (shot 2 starts from shot 1), and picking saved assets as references.
7. **Character bundles.** A named character with several files that fills the matching slots in one click.
8. **Variations.** Several low-quality versions with different seeds, then finalise one at high quality.

### Before outside users
9. Payments, email (verification, reset, "your video is ready"), https and a domain, upload and rate limits, a landing page.

### Scaling
10. More than one GPU, Postgres and object storage, Docker, CI, error tracking, backups.
11. A React front end, only once the UI outgrows plain modules.

## 11. Measured timings (RTX 5090, 768p, one clip)

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

## 12. Quality lessons for H3 (shown as Tips in the app)

- Low quality is a draft: smudges, soft backgrounds, frozen mouths. Use medium or high for finals.
- Lip sync needs a voice track, with one speaker per clip.
- Use a background image or a first frame to keep the same location.
- Use reference images of at least 1024 px with no watermarks or text.
- Best results come from 5-6 s clips, one action each, and a locked camera.
- Keep CFG at 1.
