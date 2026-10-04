# Scene.ai handover

Status on 4 October 2026. Read this first in a new session. It covers where things stand, the rules,
what was added most recently, what is and is not tested, and what to build next.

For how to start the app and its settings, see the [README](../README.md). For how the code is
organised, see [architecture.md](architecture.md). For adding workflows and presets files, see
[workflows.md](workflows.md). This file does not repeat them.

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

Both servers answer only when yogesh has them running. On 3 October the ComfyUI PC dropped off the
network for about an hour and came back by itself. If `/system_stats` or `/api/tags` does not answer,
wait or ask yogesh.

`config.json` and `storage/` are ignored by git on `founder` but tracked on `main`. After switching
from `main` to `founder`, put them back with
`git restore --source=main --worktree -- config.json storage`.

## 3. Rules

1. Never change the workflows saved inside ComfyUI, ComfyUI's Python (`python_embeded`), or its start flags.
2. Never delete files on the ComfyUI PC without asking yogesh.
3. Never test against the real database. `storage/scene.db` holds yogesh's real admin account and
   library. Run a second copy of the app with its own storage (section 6).
4. Workflow files in `workflows/` are never modified by the app. Settings are applied to the copy sent for each job.
5. Do not commit or push unless yogesh asks. `founder` has one commit, pushed. Everything in section 4 is uncommitted.
6. Keep it cross-platform: use `pathlib`, no shell-only tricks in app code, keep both start scripts working.
7. The app starts empty for a new user. No sample projects, sample media or placeholder content.

## 4. What was added on 3 October (uncommitted)

### New look
- A design identity was made for Scene (see section 7) and the front end was restyled twice: first to
  that identity, then softened at yogesh's request ("feels hard", take inspiration from Apple).
- The current look, all in `frontend/assets/css/app.css`: lifted greys instead of near-black, rounded
  shapes, filled buttons and fields without hard outlines, translucent blurred floating panels,
  sentence-case labels. The system font is used where there is one (San Francisco on Apple devices),
  the bundled Archivo elsewhere. Mono type is kept only for timecode and prices.
- Three colour rules carry over from the identity and must stay: **amber** (`--brand`) is only for
  Generate and work in progress; **blue** (`--agent`) is only for the agent; the everyday primary button
  is the text colour.
- The **Gate**: two opposing brackets mark whatever is selected (`.gate`), and the same two circle a
  frame while it is being made (`runningGate()` in `dom.js`). Small waits use a stepping square instead of a spinner.
- The logo (`frontend/assets/img/logo.svg`) is the Scene mark on an amber tile. Icons in `dom.js` were redrawn.
- Fonts ship in `frontend/assets/fonts/` (Latin letters only), so the app needs no font server.
- Credits are written `23 cr`.

### Canvas (`#/canvas`)
- Every finished item is a frame on a board that pans and zooms. Frames can be moved; positions are
  saved per project on the server.
- A selected frame gets Open, Re-run, Add to timeline and Download.
- A job in progress shows as a frame with the running Gate and elapsed time, and its result lands in that spot.
- A **composer** is docked at the bottom: prompt, a strip of the main settings, and Generate with the
  cost in the button. With one frame selected it offers to continue from it. Everything else uses the
  workflow's defaults; the Create page still has the full form.
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
- The **Brief** is a per-project note (style, characters, rules) that is sent with every instruction.
- Past plans are kept per project. Jobs the agent started are drawn in blue on the canvas.
- Limits: steps cannot use each other's results (a longer continuous video is one step with chained
  clips); it only offers workflows that need no reference files, apart from a first frame taken from
  the canvas selection; the model is small and sometimes needs the plan corrected, so the cost is always shown first.

### Backend pieces behind these
- `backend/scene/api/workspace.py`: `/api/boards/{canvas|timeline|brief|agent}` (one saved JSON
  document per user, project and kind, in the new `boards` table), `/api/timeline/export`,
  `/api/agent/status`, `/api/agent/plan`.
- `backend/scene/agent.py`: the Ollama call, the rules given to the model, and the step checker.
- `media.py`: `sequence()` for timeline export; `probe()` now also returns the frame size.
- `config.py`: `ollama_url`, `agent_model`.

### Also in the repo
- `design/logo/`: the mark as SVG (four inks, two app icons, a 16 px favicon).
- `design/previews/`: screenshots. `design/previews/studio/soft-*.png` show the current look; the
  others are from earlier stages and can be deleted.

## 5. What the app already did before this

Unchanged and still working: accounts (first account is admin, scrypt passwords, login throttle);
the Create page with a form built from the workflow, reference boxes, live estimate and warnings;
long videos as chained clips; Assets; the Library with viewer, search and projects; the Queue with
live progress; credits charged on queue and refunded on failure; and the nine-tab admin console
(overview, users, jobs, library, credits, workflows, system, audit log, settings, with CSV export).

Three presets files exist: `h3_director`, `video_minimax_h3_i2v` and `video_minimax_h3_r2v`.

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
SCENE_STORAGE_DIR=/path/to/scratch SCENE_PORT=8099 SCENE_HOST=127.0.0.1 ../.venv/bin/python -m scene
```

Add `SCENE_COMFY_URL=http://127.0.0.1:9` to keep it away from the render PC. Then register a throwaway account.

What worked for browser checks in the last session:

- A temporary page in `frontend/` that signs in with `fetch`, sets `location.hash`, then imports
  `/assets/js/main.js`; screenshot it with headless Chrome
  (`--headless=new --screenshot=... --virtual-time-budget=25000`). Delete the page afterwards.
- Give each Chrome run its own `--user-data-dir` and a time limit; a shared profile hangs.
- Stop the test server by port: `lsof -ti :8099 | xargs kill`. `pkill -f "python -m scene"` misses it on macOS.
- Do not use a bare `wait` in a shell that also started the server; it waits for the server too.
- Video thumbnails sometimes come out black in headless screenshots. They render in a normal browser.
- The shell is zsh: it does not split unquoted variables, and a bare `=====` in a command is an error.
- One "401 on /api/auth/me" in the console on first load is expected.

## 7. The design system and where it stands

The artifact in section 2 holds the brand book, tokens, logo files and 16 component previews.

**It is out of date.** It still describes the first, harder version: sharp 2 px media corners,
uppercase mono labels, wide titles, no translucent panels. The app now follows the softer direction in
section 4. yogesh has been asked whether to update the page and has not answered. Until then, treat
`app.css` as the truth for look, and the artifact as the source for the idea, the logo, the colour
rules and the vocabulary (takes, the Brief, `cr`).

## 8. What was tested, and what was not

| Tested | Result |
|---|---|
| Automated tests | 37 pass, no ComfyUI or Ollama needed |
| Agent plan, approve, real render (fast/medium, 480p, 5 s) | Video in the library in 46 s, 6 credits charged, step shown as Done |
| Agent plans against the real model | Portrait, a 15 s shot as 3 chained clips, and an unclear request answered with a question |
| Timeline export of three real clips of different sizes | 9.2 s video, with sound |
| Canvas with a job in progress, selection, composer | Rendered correctly (job simulated) |
| Create, Canvas, Timeline, Admin in headless Chrome, dark and light | No script errors |
| Earlier: single clip and a 2-clip chain on real ComfyUI; database upgrade on a copy of the real one | Passed |

Not tested:

- Dragging frames, panning and zooming the canvas with a real mouse or trackpad.
- Timeline playback and drag-to-reorder.
- Generating from the canvas composer, and "continue from the selected frame" (composer or agent).
- An agent plan with more than one step run for real.
- The softened look on the Library, Assets, Queue, Settings and sign-in pages (captured, not reviewed).
- Windows and Linux; the system-font fallback to Archivo there.
- Chains with a voice track or more than 2 clips; cancelling a running job on real ComfyUI.
- Any workflow other than H3 Director end to end.

## 9. Known issues and gaps

- **No image workflows.** `workflows/image/` is empty. The code path exists but has never run.
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

### Next up
1. **Try the new pages by hand** and fix what the "not tested" list turns up.
2. **Commit** the work in section 4 when yogesh asks, and tidy `main`.
3. **Update the design system page** to the softer look, if yogesh wants it.
4. **Image workflows.** Blocked on yogesh adding files to `workflows/image/`. Then check the form, run
   one end to end, and test "Use as first frame" from an image.
5. **Agent: steps that build on each other** (shot 2 starts from shot 1), and picking saved assets as references.
6. **Character bundles.** A named character with several files that fills the matching slots in one click.
7. **Variations.** Several low-quality versions with different seeds, then finalise one at high quality.

### Before outside users
8. Payments, email (verification, reset, "your video is ready"), https and a domain, upload and rate limits, a landing page.

### Scaling
9. More than one GPU, Postgres and object storage, Docker, CI, error tracking, backups.
10. A React front end, only once the UI outgrows plain modules.

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
