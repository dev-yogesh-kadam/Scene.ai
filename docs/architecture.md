# Architecture

```
Browser (frontend/)  ──HTTP + WebSocket──▶  Scene.ai server (backend/scene)  ──HTTP + WebSocket──▶  ComfyUI      (renders)
                                                 │                            ──HTTP──────────────▶  Ollama, or a hosted service such as Gemini  (the agent's model)
                                                 │                            ──runs────────────────▶  HyperFrames  (motion graphics, via Node.js)
                                                 └── storage/  (SQLite database, saved assets)   and the outputs folder (finished work)
```

## Backend (`backend/scene`)

| Module | Job |
|---|---|
| `main.py` | Builds the app and wires the parts together. |
| `config.py` | Settings from defaults, `config.json` and `SCENE_*` variables. |
| `db.py` | SQLite tables: `users`, `sessions`, `jobs`, `generations`, `projects`, `boards`, `assets`, `credit_events`, `settings`, `workflow_pricing`, `credit_packages`, `servers`. New columns are added to older databases on start. |
| `security.py` | Password hashing (scrypt), session tokens, login throttle. |
| `catalog.py` | Lists the files in `workflows/<kind>/` and loads them. The kinds are video, image and audio; the `upscaler` folder is read too, for workflows that enlarge a video the user has. |
| `comfy/workflows.py` | Reads a workflow, works out its form, builds the graph for one job, estimates time. |
| `comfy/client.py` | Calls ComfyUI: upload, queue, history, download, cancel. |
| `jobs.py` | The queue. One job runs at a time, for all users, in the order they were added. Also runs chained long videos. |
| `media.py` | ffmpeg helpers: last frame of a clip, a video's poster (its thumbnail), joining clips, cutting audio, joining a timeline of any clips. ffmpeg comes with the `imageio-ffmpeg` package. |
| `credits.py` | What a job costs, charging and refunding. Every change is logged in `credit_events`. |
| `references.py` | Uploading reference files to ComfyUI, with a size limit. |
| `cast.py` | The cast of a project: library items pinned to roles (main character, outfit, location…), and which reference slots of a workflow they fill. |
| `outputs.py` | Where each user's finished work is kept: a folder named after their email inside the outputs folder. |
| `api/auth.py` | Register, sign in, sign out, change password. |
| `api/deps.py` | Who is signed in, who is an admin, and who may use the agent. |
| `api/studio.py` | Workflows, estimates, jobs, live events. |
| `api/library.py` | A user's finished images, videos and sounds, their files and video posters, search, projects, and turning an item into a reference for a new job. |
| `agent.py` | The agent: asks a language model, on Ollama or on a hosted service that speaks the OpenAI chat API (Gemini, Kimi), for an answer or a plan, then checks every step against the real workflows and the selected items. It also improves prompts and writes captions. |
| `motion.py` | Motion graphics: lists the templates in `motion/templates/`, checks a form's values and runs HyperFrames. See [motion.md](motion.md). |
| `sequence.py` | A motion video made of scenes of words: checks the scenes and writes the HyperFrames page for them. |
| `api/workspace.py` | The saved canvas layout, timeline, brief and agent plans of each project (`boards`); exporting a timeline as one video; writing the scenes of a motion video and rendering motion graphics; and the agent's answers, plans and improved prompts. The server never carries out a plan: the browser does, step by step, after the user approves. |
| `api/assets.py` | Saved characters, outfits, backgrounds and voices. |
| `api/admin.py` | The admin console: overview, users, all jobs, credit log, pricing (rates, workflow pricing, credit packages, servers), workflow report, settings. |

## How a generation runs

1. The browser posts the form and any reference files to `POST /api/jobs`.
2. The server uploads the references to ComfyUI, checks the settings and stores a `queued` job.
3. The queue worker takes the oldest queued job, builds the graph from the workflow file and the
   settings, and sends it to ComfyUI.
4. Progress arrives over ComfyUI's WebSocket and is pushed to that user's browser over `/api/events`.
5. When ComfyUI finishes, the server downloads the file to the outputs folder (`output_dir`, by default `storage/outputs`), in a sub-folder named after the user's email, and adds a
   row to `generations`. The settings are stored with it, which is what **Re-run** uses.

Workflow files are never changed. Each job gets its own patched copy.

## The agent

1. The browser sends the message, the ids of the attached items and the last few turns to `POST /api/agent/plan`.
2. The server builds one message for the model: the brief, the workflows it may use, the
   conversation so far, the attached items, and the new message.
3. The model answers in a fixed JSON shape: a reply and a list of steps, each with a `tool`.
4. The server checks each step and turns it into something that can be carried out: job settings
   with a price (`generate`), cuts of videos (`trim`, `split`, `join`), a sound put on a video
   (`sound`), or a motion render (`motion`, `overlay`). What cannot run is dropped.
5. Nothing happens until the user presses Approve. The browser then carries out the steps one by
   one, through `POST /api/jobs`, `POST /api/timeline/export`, `POST /api/edit/sound` or
   `POST /api/motion/render`.
   A step that starts on an earlier step's result waits for that result first.

## Long videos (chained clips)

A job with `clips` above 1 renders the clips one after another. After each clip the server saves its
last frame and uploads it as the first-frame reference of the next clip. A voice track is cut into
one piece per clip. At the end the clips are joined with ffmpeg, dropping the one frame each pair
shares. A workflow can be chained when it has a prompt, a duration and a first-frame slot (a loader
node whose title contains "first frame").

## Credits

The price follows what the user asked for, never the GPU time it took (`credits.py`):

    credits = (base + credits per second × seconds asked for) × resolution multiplier × quality multiplier

| Kind | Rate a new installation starts with |
|---|---|
| Image | 40 credits per generation |
| Video | 20 credits per second (a chain: per second of every clip) |
| Audio | 5 credits per second |
| Motion graphics | 30 credits per second |
| Motion graphics over a video the user has | 10 credits per second of that video |
| Upscale | 20 credits per second of the video it is made from |

- The rates, the price of 1,000 credits (₹100) and the price of electricity (₹8/kWh) are rows of `settings`,
  changed in the admin console's **Pricing** section. A workflow can have its own rate, base, multipliers and
  an on/off switch in `workflow_pricing`; without a row it follows its kind. A workflow that is switched off is
  left out of the lists and refused by `/api/estimate` and `/api/jobs`.
- The seconds come from the workflow's duration control, or from the control its presets file names in
  `"pricing": {"seconds": ...}`, or, for an upscale, from the library video named as `parent`. When none of
  these says, 5 seconds are billed.
- A job is charged when it is queued and refunded if it fails or is cancelled. The job keeps
  `credits_required`, `credits_reserved` (held while it waits and runs), `credits_consumed` and
  `credits_refunded`, with `seconds_requested`, `server`, `retries` and `output_size`. `cost` is still its price.
- A motion graphic has no job: `/api/motion/render` charges it before the render and refunds it if the
  render fails. `/api/motion/estimate` gives the price without rendering.
- `credit_packages` and `servers` (hardware, power, depreciation figures) are kept for payments and the
  scheduler. The name of the server marked "renders" is written on each job.
- The admin console's **Economics** section (`GET /api/admin/economics?days=`) reports, per workflow, the jobs
  done and failed, runs per result, average render time, credits used and their value in rupees, and the
  electricity the runs cost: run time × the power of the job's server × the price of electricity. Failed
  runs count towards electricity. Nothing else (cooling, depreciation, storage) is counted. The queue never
  retries a job by itself, so `retries` stays 0 and the overhead is read from failed jobs.

## Accounts and security

- The first account is the admin. The admin console (`#/admin`) manages users, credits, jobs and settings.
- Passwords are hashed with scrypt. Sessions are random tokens in an HttpOnly, SameSite=Lax cookie;
  only their hash is stored.
- Every `/api` route except `/api/auth/*` needs a session. Users only see their own jobs and files.
- Five wrong passwords block that email and address for a minute.

## Front end (`frontend/`)

Plain JavaScript modules, served as static files.

| File | Job |
|---|---|
| `assets/js/main.js` | Sign-in gate, sidebar, routing between pages. |
| `assets/js/store.js` | Shared state and the live connection. |
| `assets/js/pages/` | `auth`, `home`, `projects`, `create`, `canvas`, `timeline`, `library`, `assets`, `queue`, `settings`, `admin`. |
| `assets/js/dom.js` | Small helpers: building elements, icons, thumbnails of library items, formatting. |
| `assets/js/components/` | Queue rows, media cards and the viewer, asset dialogs, the project window, the Home composer, and the three parts of the canvas panel: `agent.js`, `quick.js` (generate and upscale forms) and `motion.js` (the form of a template and the form of a whole motion video). |
| `assets/css/app.css` | Design tokens and layout, dark and light. |
| `assets/fonts/` | Archivo and Martian Mono (Latin), so the app needs no font server. |

## Known limits

- One render server and one job at a time. More GPUs need a worker per server.
- Timeline exports, agent edits and motion renders run inside the web request, not in the job queue.
- SQLite and local files fit one machine. Moving to Postgres and object storage means replacing
  `db.py` and the file paths in `jobs.py` and `api/library.py`.
- No email, so no verification or password reset. An admin has to help a locked-out user.
- Credits are granted by an admin. There is no payment system.
