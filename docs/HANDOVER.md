# Scene.ai handover

Status on 3 October 2026. Read this first in a new session. It covers what Scene.ai is, what is
built and tested, how the code works, the rules to follow, and what to build next.

## 1. What Scene.ai is

Scene.ai is meant to become a startup product: a web studio where signed-in users create videos and
images with AI. The owner is yogesh (yogesh.k@dashverse.ai).

- The rendering is done by a ComfyUI server. Users never see ComfyUI.
- Video workflows (MiniMax H3) exist today. yogesh will add image workflows later.
- The app must run on macOS, Windows and Linux. Do not write code that only works on one of them.
- Workflows must stay dynamic: yogesh drops ComfyUI workflow files into `workflows/` and they must
  appear in the app with no code change.

## 2. Machines and addresses

| Thing | Value |
|---|---|
| Repo | `/Volumes/Shanks/Scene.ai` on yogesh's MacBook (APFS, git repo, branch `main`) |
| ComfyUI | `http://100.123.221.34:8188`, on a separate Windows PC reached over Tailscale |
| ComfyUI PC | RTX 5090 (32 GB VRAM), 192 GB RAM, ComfyUI portable v0.38.0 at `C:\ComfyUi\ComfyUI_windows_portable` |
| App | `http://localhost:8080` after starting it |
| Python | 3.14 on the Mac, in the repo's `.venv` |

ComfyUI is only reachable when yogesh has started it on the PC. If `/system_stats` does not answer,
ask yogesh to start it.

## 3. Rules

1. Never change the workflows saved inside ComfyUI, ComfyUI's Python (`python_embeded`), or its start flags.
2. Never delete files on the ComfyUI PC without asking yogesh.
3. Never test against the real database. `storage/scene.db` holds yogesh's real admin account and
   library. Run tests with a separate storage folder (section 9).
4. Workflow files in `workflows/` are never modified by the app. Settings are applied to the copy
   sent for each job.
5. Nothing has been committed to git yet. Do not commit or push unless yogesh asks.
6. Keep it cross-platform: use `pathlib`, no shell-only tricks in app code, and keep both start scripts working.

## 4. How to run it

| System | Command |
|---|---|
| macOS / Linux | `./scripts/start.sh` |
| Windows | double-click `scripts\start.bat` |

The start script creates `.venv`, installs `backend/requirements.txt`, copies `config.example.json`
to `config.json` if it is missing, and runs `python -m scene` from `backend/`.

Run the tests:

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest
```

32 tests pass. They need no ComfyUI.

## 5. Folder layout

| Path | Contents |
|---|---|
| `backend/scene/` | The server (FastAPI). See section 7. |
| `backend/tests/` | `test_workflows.py`, `test_api.py`, `conftest.py` |
| `backend/requirements.txt` | fastapi, uvicorn, python-multipart, httpx, websockets, imageio-ffmpeg |
| `frontend/` | Plain HTML, CSS and JavaScript modules. No build step, no framework. |
| `workflows/video/` | Eight video workflows, three with a `.studio.json` presets file |
| `workflows/image/` | Empty. Image workflows go here. |
| `workflows/archive/` | Three backup workflows. Not shown in the app. Two are used by a test. |
| `scripts/` | `start.sh`, `start.bat` |
| `docs/` | `architecture.md`, `workflows.md`, this file |
| `config.json` | Local settings (not in git). `config.example.json` is the template. |
| `storage/` | Created at run time, not in git: `scene.db`, `outputs/<user id>/`, `assets/<user id>/`, `tmp/` |
| `legacy/` | The old command-line script (`h3_director_cli/`) and `Test.py`. Not used by the app. |

## 6. What is built

Everything below works and was tested unless section 10 says otherwise.

### Accounts
- Register, sign in, sign out, change password.
- The first account becomes the admin. Admins can close sign-ups and change user roles.
- Passwords are hashed with scrypt. Sessions are random tokens in an HttpOnly cookie, stored as a hash.
- Five wrong passwords block that email and address for a minute.
- Each user sees only their own jobs, library, assets and projects.

### Create page
- Video and Image tabs, and a workflow dropdown filled from `workflows/<kind>/`.
- The form is built from the workflow itself (section 8).
- Reference boxes with drag and drop, one per loader node.
- Live time estimate and credit cost.
- Warnings that need a click (High quality, 15 s clips), with an alternative button.
- Project field, so the result lands in a project.

### Long videos (chained clips)
- "Long video (number of clips)" makes 2, 3, 4 or 6 clips (the server allows up to 8).
- Each clip starts on the last frame of the one before. The clips are joined into one file.
- One prompt is used for every clip, or per-clip prompts are separated by a line containing only `---`.
- A voice track is cut into one piece per clip.
- A user's last-frame image applies only to the final clip.

### Assets
- An Assets page keeps characters, outfits, backgrounds, props and voices (image, video or audio files).
- Each reference box has a "Saved" button to pick an asset, and "Save" to keep a dropped file.
- A library image can be saved as an asset.

### Library
- Viewer with a details panel: prompt (with Copy), workflow, options, resolution, length, seed, other
  settings, references, project, date, time, render time, credits, file, generation id and job id.
  `detailsOf()` in `components/media.js` builds the list. Jobs store `prompt`, `details` and
  `workflow_title` in their settings at creation; older items fall back to what can be worked out.
- Download, Re-run (refills the Create form), Delete.
- "Use as first frame" for images and "Continue" for videos (uses the video's last frame).
- Search by name, workflow and prompt text. Filter by kind and project.
- Projects: create, rename, delete, move items between them.

### Queue
- One job at a time across all users, in the order they were added.
- Live progress over WebSocket: clip number, step, current node, time left, queue position.
- Cancel for waiting and running jobs. Waiting jobs survive an app restart.

### Credits
- A job costs its estimated GPU minutes times `credits_per_minute` (default 10), rounded up.
- A workflow with no estimate costs `credits_unknown` (default 20) per clip.
- Charged when the job is queued. Refunded when it fails or is cancelled.
- New accounts get `signup_credits` (default 500).
- Admins add or remove credits per user and change both rates on the Settings page.
- Every change is logged in the `credit_events` table.
- There is no payment system. Admins are charged like everyone else.

### Settings page
- Change password. Admins also get a link to the admin console.

### Admin console (`#/admin`, admins only)
Nine tabs. Code: `frontend/assets/js/pages/admin.js` (shell), `pages/admin/overview.js`, `pages/admin/sections.js`,
`pages/admin/shared.js`, `components/charts.js`, and `backend/scene/api/admin.py`.

- **Overview:** a period switch (7, 30, 90 days); a "needs attention" list (server offline, failed jobs, users out of
  credits, unreadable workflows, low disk, jobs waiting over an hour); five headline numbers with a trend line and the
  change against the period before; the live queue; recent activity; four daily charts (items, jobs by result, GPU
  minutes, credits) with hover values and a table view; most active users; workflows used; why jobs failed.
- **Users:** search and filters; select a user for a side panel with their numbers, latest items, jobs and credit
  history. Actions: add or remove credits, set a password, make admin or user, disable or enable.
- **Jobs:** every user's jobs with status filters, search and pages of 50; select a job for its prompt, options,
  references, error, wait and render time, and result. Cancel any active job.
- **Library:** every user's items as a table (no thumbnails), filtered by type, user, project and search.
  Selecting a row opens the viewer with the details panel; an admin can delete the item there.
- **Credits:** totals (held, spent, given at sign-up, given by admins) and the change log with filters.
- **Workflows:** each file, whether it can be read, presets, jobs, success rate, average time.
- **System:** render server (versions, GPU memory, system memory, ComfyUI queue), the app, storage and disk, record counts.
- **Audit log:** sign-ins, failed sign-ins, new accounts and every admin action, with who, what, on whom, details and address.
- **Settings:** ComfyUI address, sign-up switch, credits for a new account, credits per GPU minute.
- **Give or take credits:** a dialog (user, give or take, amount, optional note, new balance) opened from the Users
  table, a user's side panel, or the Credits tab. A balance never goes below zero. The note is stored in
  `credit_events.note` and shown in the credit log and audit log.
- Users, jobs, credits and the audit log can be exported as CSV.
- A disabled account is signed out everywhere and can't sign in.
- Chart colours are the `--series-*` and `--status-*` tokens in `app.css`; they were checked for colour-blind separation.

### Look and feel
- One stylesheet, `frontend/assets/css/app.css`: calm and near-monochrome (in the style of Linear and Vercel).
  Hierarchy comes from spacing and type; colour is kept for status. Primary buttons are solid text-colour.
- Dark and light themes. The theme follows the system unless the user picks one with the button next to their
  name in the sidebar (stored in `localStorage` as `scene.theme`, applied as `data-theme` on `<html>`).
- Icons are inline SVG from `icon()` in `dom.js`.
- On Create, rarely used settings sit under "More settings", and the estimate, cost and Generate button are in a bar
  that stays at the bottom of the form.

## 7. Backend modules (`backend/scene/`)

| Module | Job |
|---|---|
| `main.py` | `create_app()`. Builds everything and puts it on `app.state` (`db`, `comfy`, `catalog`, `credits`, `jobs`, `hub`, `notify`, `live_message`, `output_dir`, `assets_dir`). |
| `__main__.py` | `python -m scene` runs uvicorn. |
| `config.py` | `Settings` dataclass. Order: defaults, `config.json`, `SCENE_*` environment variables. |
| `db.py` | SQLite. Tables: `users`, `sessions`, `jobs`, `generations`, `projects`, `assets`, `credit_events`, `audit_log`, `settings`. The `COLUMNS` list adds new columns to older databases on start. |
| `security.py` | scrypt hashing, session tokens, login throttle. |
| `catalog.py` | Lists `workflows/<kind>/*.json` and loads them. Fetches ComfyUI's `/object_info` when a file alone is not enough. |
| `comfy/workflows.py` | The core. Reads UI-format and API-format workflows, finds controls and reference slots (`describe`), builds the job graph (`build_prompt`), estimates time (`estimate`). |
| `comfy/client.py` | ComfyUI HTTP calls: upload, queue, history, view, cancel. |
| `jobs.py` | `JobManager`: the queue worker, single renders and chains, progress, downloads. |
| `media.py` | ffmpeg helpers: `probe`, `last_frame`, `cut_audio`, `join`. ffmpeg comes from `imageio-ffmpeg`. |
| `credits.py` | `Credits`: cost, charge, add, balance. |
| `references.py` | Uploading reference files to ComfyUI with a `scene_<hash>_` name. |
| `api/auth.py` | `/api/auth/*` |
| `api/studio.py` | `/api/status`, `/api/workflows`, `/api/estimate`, `/api/jobs`, `/api/ref-preview`, WebSocket `/api/events` |
| `api/library.py` | `/api/library`, `/api/projects` |
| `api/assets.py` | `/api/assets` |
| `api/admin.py` | `/api/admin/overview`, `users`, `jobs`, `library`, `credits`, `workflows`, `system`, `audit`, `settings`, `export/<name>.csv` |
| `audit.py` | `record()` writes one row to `audit_log`. |
| `api/deps.py` | `current_user`, `admin_user` |

### Front end (`frontend/assets/js/`)

| File | Job |
|---|---|
| `main.js` | Sign-in gate, sidebar, hash routing (`#/create`, `#/library`, `#/assets`, `#/queue`, `#/settings`, and `#/admin` for admins). |
| `store.js` | Shared state (`user`, `jobs`, `online`, `rerun`, `prefill`) and the live connection. |
| `api.js`, `dom.js` | Fetch wrapper; `el()`, `segmented()`, `field()` and formatters. |
| `pages/create.js` | The largest file: workflow picker, form, references, estimate, warnings, generate. |
| `pages/library.js`, `assets.js`, `queue.js`, `settings.js`, `admin.js`, `auth.js` | One per page. Each exports `render(view)` and may return a cleanup function. |
| `components/jobs.js`, `media.js`, `assets.js` | Queue rows, media cards and viewer, asset dialogs. |

## 8. How the important parts work

### Workflows become forms
`comfy/workflows.py` reads a workflow and returns a schema.

- **Formats:** a normal ComfyUI save (UI format) is converted to API format in `_from_ui`. Widget
  values are mapped to input names from the file's own metadata, or from ComfyUI's `/object_info` if
  the file lacks it. The catalog keeps a copy of `/object_info` in `storage/cache/node_definitions.json`.
- **Subgraphs** are unpacked in `_add_graph`: a node inside instance 105 gets the id `105:<inner id>`,
  values set on the subgraph node are pushed into the inner nodes, and links to its outputs are redirected.
- **Controls:** primitive nodes become fields labelled with the node title. The title gives the
  role: PROMPT, SEED, DURATION or "seconds", RESOLUTION, and titles starting with WIDTH or HEIGHT.
  `prompt`, `width`, `height`, `steps`, `cfg` and `seed` typed straight into a node also become fields.
- **Reference slots:** nodes whose class matches `(Load|Optional)(Image|Video|Audio)`. A bypassed
  loader is an optional slot and is switched on only when a file is given (`finalize`).
- **Special slots:** loader titles containing "first frame", "last frame" or "voice track".
  A workflow can be chained when it has a prompt, a duration and a first-frame slot.
- **Ids:** a control or slot id is `"<node id>:<input>"`, for example `100:value` or `201:image`.
  A workflow id is `"<kind>/<file name>"`, for example `video/h3_director`.

### Presets (`<workflow>.studio.json`)
Optional file next to a workflow. Keys: `title`, `description`, `options`, `rules`, `hide`,
`controls`, `confirm`, `estimate`, `hints`, `slots`. `docs/workflows.md` explains them.
More keys were added for the ComfyUI template workflows: `labels`, `defaults`, `optional_refs`,
  `required_refs`, `extra_refs`, and `primary` / `choices` on `controls`.
There are three presets files: `h3_director`, `video_minimax_h3_i2v` (H3 Image to Video, a subgraph
template; chain-capable) and `video_minimax_h3_r2v` (H3 Reference to Video). Both templates get an
aspect ratio, a size in megapixels and a Standard / Turbo speed option.
`workflows/video/h3_director.studio.json` defines:

- Mode: fast (sparse attention) or normal.
- Quality: low (4 steps, turbo LoRA), medium (20 steps), high (40 steps).
- Rules that set nodes 108, 109, 105 and 113, and add a `BlockSparseAttention` node (id 400) for fast medium/high.
- The measured timing table for the RTX 5090 at 768p.

### Job settings
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

A `refs` entry is `{"asset_id": n}` or `{"comfy_name": "scene_..."}`. Uploaded files are added by the server.

### A chained job (`JobManager._run_chain`)
1. Split the prompt on `---` lines. Pick one seed and use `seed + clip index` per clip.
2. For each clip: set the prompt, the first frame (from the previous clip) and the voice piece, render, download the clip to `storage/tmp/`.
3. Save the clip's last frame with ffmpeg and upload it as `scene_chain_<job>_<n>.png`.
4. Join the clips with ffmpeg (libx264, CRF 16, AAC), dropping the one frame each pair shares.
5. Record one row in `generations`.

### Live updates
`app.state.notify(user_id)` pushes `{jobs, credits, library_changed}` to that user's open pages over `/api/events`.

## 9. How to test safely

Run a second copy of the app with its own storage and port, so the real database is untouched:

```bash
cd backend
SCENE_STORAGE_DIR=/path/to/scratch SCENE_PORT=8082 SCENE_HOST=127.0.0.1 ../.venv/bin/python -m scene
```

Then register a throwaway account and drive the API with a small `httpx` script.

Notes from earlier sessions:

- In Claude Code on this Mac, commands that reach ComfyUI or localhost servers need the sandbox disabled.
- The shell is zsh. It does not split unquoted variables, so do not put curl options in a variable.
- Browser checks were done with headless Chrome through its remote debugging port and the
  `websockets` package (sign in, click, screenshot, collect script errors). Chrome is at
  `/Applications/Google Chrome.app`. There is no `node`-based test setup.
- One "401 on /api/auth/me" in the browser console on first load is expected.
- A fast/low 5 s clip takes about 1 minute on the real server. Use it for end-to-end checks.

## 10. What was tested, and what was not

| Tested | Result |
|---|---|
| Automated tests | 32 pass |
| Single clip on real ComfyUI (fast/low, 5 s, one character image) | Video returned in 66 s, 8.2 MB |
| Chained 2-clip video on real ComfyUI (asset reference, two prompts, project) | 10.3 s video in 102 s, smooth join, 18 credits |
| All six video workflows load with ComfyUI online | Yes |
| Database upgrade on a copy of the real database | User, 2 items and 3 jobs kept; 500 credits granted |
| Pages in headless Chrome | No script errors |

Not tested:

- Windows and Linux.
- Chains with a voice track, and chains longer than 2 clips.
- Cancelling a running job on the real ComfyUI.
- Any workflow other than H3 Director end to end.
- Drag and drop with a real mouse.
- The library and Create pages after the last two display fixes (the project bar and the clip buttons).

## 11. Known issues and gaps

- **No image workflows.** `workflows/image/` is empty. The code path exists but has never run.
- **Assets are single files.** A character is one image, not a bundle of face, outfit and voice.
- **Chains do not carry a voice.** Each clip gets the same references; without a voice sample or
  voice track the voice can change between clips.
- **Chain quality loss.** Each next clip starts from a frame decoded from an encoded video (CRF 16),
  so very long chains may drift.
- **One GPU, one job at a time.**
- **SQLite and local files.** Fine for one machine only.
- **No email.** No verification, no password reset, no "video ready" message.
- **No payments.** Credits come only from an admin.
- **No https.** `secure_cookies` exists but nothing terminates TLS.
- **No upload limits** on reference files, except 200 MB on assets.
- **Test files on the ComfyUI PC.** Earlier test runs left `scene_*` and `studio_*` files in
  ComfyUI's input folder and test videos in its output folder. Ask yogesh before deleting them.
- **Legacy script is broken.** `legacy/h3_director_cli/h3_director.py` has a stray path pasted on
  line 1 and expects `h3_director_draft_api.json` next to it. The app does not use it.
- **Old media in `legacy/`.** Five sample videos and one input image, ignored by git.

## 12. Next plan

In the order yogesh and Claude last discussed. Items 1 to 5 of the earlier list are done except image workflows.

### Next up
1. **Image workflows.** Blocked on yogesh adding files to `workflows/image/`. When they arrive:
   check that the form is detected, run one end to end, add a `.studio.json` if presets are wanted,
   and test "Use as first frame" from an image.
2. **Character bundles.** A named character with several files (face, other angle, outfit, voice)
   that fills the matching slots in one click.
3. **Variations.** "Make 4 versions" at low quality with different seeds, then "Finalise" one at
   high quality with the same seed.
4. **Prompt library and prompt helper.** Saved prompts and templates, and a button that rewrites a
   short idea into the action / camera / sound format H3 wants.
5. **Workflow cards.** Show workflows as cards with a preview and description, and collapse advanced settings.
6. **Finish testing.** The "not tested" list in section 10, starting with a voice-track chain and cancel.

### Before outside users
7. **Payments.** Buying credits with Stripe, and plans with a monthly allowance.
8. **Email.** Verification, password reset, "your video is ready".
9. **Https and a domain**, then set `secure_cookies`.
10. **Limits and moderation.** Upload size limits, rate limits, content rules.
11. **Landing page** with examples and pricing.

### Scaling
12. **More than one GPU.** A worker per ComfyUI server, so the queue spreads across machines.
13. **Postgres and object storage.** Replace `db.py` and the file paths in `jobs.py`,
    `api/library.py` and `api/assets.py`.
14. **Docker, CI, error tracking, backups.**
15. **React front end**, only once the UI outgrows plain modules.

### Housekeeping
- Make the first git commit when yogesh asks.
- Fix or remove the legacy script, if yogesh wants it kept working.
- Time other resolutions and fast/high to replace the estimated numbers in `h3_director.studio.json`.

## 13. Measured timings (RTX 5090, 768p, one clip)

| Mode | Quality | 5 s | 10 s | 15 s |
|---|---|---|---|---|
| fast | low | 0.9 min | 2.0 min | 18 min |
| fast | medium | 2.3 min | 6.1 min | ~25 min (est.) |
| fast | high | ~4.3 min (est.) | ~14 min (est.) | unknown |
| normal | low | 1.2 min | 3.2 min | ~25 min (est.) |
| normal | medium | 4.3 min | 13.8 min | ~1.5 h (est.) |
| normal | high | 8.3 min | 27.0 min | ~3 h (est.) |

A single 15 s clip overflows 32 GB of VRAM, which is why chaining 5 s clips is the recommended way to make long videos.

## 14. Quality lessons for H3 (shown as Tips in the app)

- Low quality is a draft: smudges, soft backgrounds, frozen mouths. Use medium or high for finals.
- Lip sync needs a voice track, with one speaker per clip.
- Use a background image or a first frame to keep the same location.
- Use reference images of at least 1024 px with no watermarks or text.
- Best results come from 5-6 s clips, one action each, and a locked camera.
- Keep CFG at 1.
