# Scene.ai

Scene.ai is a web studio for creating videos and images with AI. People sign in, pick a workflow,
fill in a form and get the result in their library. The rendering is done by a
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server, which users never see.

Video workflows (MiniMax H3) are included today. Image workflows work the same way and only need
workflow files to be added.

## Quick start

You need Python 3.10 or newer and a running ComfyUI server.

| System | Start |
|---|---|
| macOS / Linux | `./scripts/start.sh` |
| Windows | double-click `scripts\start.bat` |

The first start creates `.venv`, installs the packages and copies `config.example.json` to
`config.json`. Then:

1. Open http://localhost:8080.
2. Create the first account. It becomes the admin.
3. Open **Admin**, then its Settings tab, and check the ComfyUI address. The dot in the sidebar turns green when it answers.

Stop the app with `Ctrl+C`.

## Project layout

| Path | Contents |
|---|---|
| `backend/scene/` | The server (FastAPI). `api/` holds the routes, `comfy/` talks to ComfyUI, `jobs.py` is the queue. |
| `backend/tests/` | Tests. Run them with `pytest` from `backend/`. |
| `frontend/` | The web app: plain HTML, CSS and JavaScript modules, no build step. |
| `workflows/video/`, `workflows/image/` | The ComfyUI workflows users can run. `workflows/archive/` is not shown in the app. |
| `scripts/` | Start scripts for each system. |
| `docs/` | [Architecture](docs/architecture.md) and [how to add workflows](docs/workflows.md). |
| `storage/` | Created at run time: the database and every user's files. Not in git. |
| `legacy/` | The earlier command-line script, kept for reference. |

## What users can do

- **Create** videos and images from any workflow in `workflows/`, with reference files.
- **Long videos**: several clips made one after another, each starting on the last frame of the one
  before, joined into one file. A line containing only `---` in the prompt separates per-clip prompts.
- **Assets**: save characters, outfits, backgrounds and voices once and pick them in any reference box.
- **Library**: search by name or prompt, group items in projects, re-run, or continue a video from its last frame.
- **Credits**: every generation costs credits based on its estimated GPU time. A failed or cancelled
  job is refunded. Admins add credits in the admin console. There is no payment system yet.

## Settings

`config.json` in the project root, or a `SCENE_<NAME>` environment variable for any of them.

| Setting | Default | Meaning |
|---|---|---|
| `comfy_url` | `http://127.0.0.1:8188` | ComfyUI address. An admin can also change it in the admin console. |
| `host`, `port` | `0.0.0.0`, `8080` | Where the app listens. Use `127.0.0.1` to keep it to this computer. |
| `default_workflow` | none | Workflow selected for new users, for example `video/h3_director`. |
| `allow_signup` | `true` | Whether visitors can create accounts. The first account can always be created. |
| `secure_cookies` | `false` | Set to `true` when the app is served over https. |
| `signup_credits` | `500` | Credits a new account starts with. An admin can change it in the admin console. |
| `credits_per_minute` | `10` | Credits charged per estimated GPU minute. Also in the admin console. |
| `credits_unknown` | `20` | Credits per clip for a workflow that has no time estimate yet. |
| `storage_dir`, `workflows_dir` | `storage`, `workflows` | Where data and workflows live. |

## Development

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest      # tests
cd backend && ../.venv/bin/python -m scene       # run the app
```

## Before putting it on the public internet

The app is built for a team on a private network. For public use it still needs https in front of it
(then set `secure_cookies`), email verification and password reset, a way to buy credits,
and storage and a database that can grow beyond one machine. See [docs/architecture.md](docs/architecture.md).
