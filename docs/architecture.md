# Architecture

```
Browser (frontend/)  ──HTTP + WebSocket──▶  Scene.ai server (backend/scene)  ──HTTP + WebSocket──▶  ComfyUI
                                                 │
                                                 └── storage/  (SQLite database, users' files)
```

## Backend (`backend/scene`)

| Module | Job |
|---|---|
| `main.py` | Builds the app and wires the parts together. |
| `config.py` | Settings from defaults, `config.json` and `SCENE_*` variables. |
| `db.py` | SQLite tables: `users`, `sessions`, `jobs`, `generations`, `projects`, `assets`, `credit_events`, `settings`. New columns are added to older databases on start. |
| `security.py` | Password hashing (scrypt), session tokens, login throttle. |
| `catalog.py` | Lists the files in `workflows/<kind>/` and loads them. |
| `comfy/workflows.py` | Reads a workflow, works out its form, builds the graph for one job, estimates time. |
| `comfy/client.py` | Calls ComfyUI: upload, queue, history, download, cancel. |
| `jobs.py` | The queue. One job runs at a time, for all users, in the order they were added. Also runs chained long videos. |
| `media.py` | ffmpeg helpers: last frame of a clip, joining clips, cutting audio. ffmpeg comes with the `imageio-ffmpeg` package. |
| `credits.py` | What a job costs, charging and refunding. Every change is logged in `credit_events`. |
| `references.py` | Uploading reference files to ComfyUI. |
| `api/auth.py` | Register, sign in, sign out, change password. |
| `api/studio.py` | Workflows, estimates, jobs, live events. |
| `api/library.py` | A user's finished images and videos, search and projects. |
| `api/assets.py` | Saved characters, outfits, backgrounds and voices. |
| `api/admin.py` | The admin console: overview, users, all jobs, credit log, workflow report, settings. |

## How a generation runs

1. The browser posts the form and any reference files to `POST /api/jobs`.
2. The server uploads the references to ComfyUI, checks the settings and stores a `queued` job.
3. The queue worker takes the oldest queued job, builds the graph from the workflow file and the
   settings, and sends it to ComfyUI.
4. Progress arrives over ComfyUI's WebSocket and is pushed to that user's browser over `/api/events`.
5. When ComfyUI finishes, the server downloads the file to `storage/outputs/<user id>/` and adds a
   row to `generations`. The settings are stored with it, which is what **Re-run** uses.

Workflow files are never changed. Each job gets its own patched copy.

## Long videos (chained clips)

A job with `clips` above 1 renders the clips one after another. After each clip the server saves its
last frame and uploads it as the first-frame reference of the next clip. A voice track is cut into
one piece per clip. At the end the clips are joined with ffmpeg, dropping the one frame each pair
shares. A workflow can be chained when it has a prompt, a duration and a first-frame slot (a loader
node whose title contains "first frame").

## Credits

The cost of a job is its estimated GPU minutes times `credits_per_minute`, rounded up. It is charged
when the job is queued and refunded if the job fails or is cancelled.

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
| `assets/js/pages/` | `auth`, `create`, `library`, `assets`, `queue`, `settings`, `admin`. |
| `assets/js/components/` | Queue rows, media cards, asset dialogs. |
| `assets/css/app.css` | Design tokens and layout, dark and light. |

## Known limits

- One render server and one job at a time. More GPUs need a worker per server.
- SQLite and local files fit one machine. Moving to Postgres and object storage means replacing
  `db.py` and the file paths in `jobs.py` and `api/library.py`.
- No email, so no verification or password reset. An admin has to help a locked-out user.
- Credits are granted by an admin. There is no payment system.
