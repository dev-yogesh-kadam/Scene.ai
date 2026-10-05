# Scene.ai

Scene.ai is a web studio for creating videos, images and music with AI. People sign in, describe what
they want in a form or to an agent, and get the result in their library. The rendering is done by a
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server, which users never see.

Workflows are included for video (MiniMax H3), images (Z-Image Turbo, SDXL, Ideogram 4) and music
(MiniMax Music 3), and for upscaling a video (SeedVR2). Any other ComfyUI workflow only needs its
file to be added.

## Quick start

You need Python 3.10 or newer and a running ComfyUI server. Two things are optional:

- A language model for the agent and for "Improve prompt": a local one on an [Ollama](https://ollama.com)
  server, or a hosted one (Google Gemini, Kimi) with an API key.
- Node.js 22 or newer, for motion graphics. See [docs/motion.md](docs/motion.md).

| System | Start |
|---|---|
| macOS / Linux | `./scripts/start.sh` |
| Windows | double-click `scripts\start.bat` |

The first start creates `.venv`, installs the packages, copies `config.example.json` to `config.json`
and, when Node.js is there, installs HyperFrames into `motion/`. Then:

1. Open http://localhost:8080.
2. Press "Create an account" under the sign-in form. The first account becomes the admin. Signing in
   lands on All projects.
3. Open the menu on your name, then **Admin console** and its Settings tab, and check the ComfyUI
   address. The dot in the sidebar turns green when it answers.

Stop the app with `Ctrl+C`.

## Project layout

| Path | Contents |
|---|---|
| `backend/scene/` | The server (FastAPI). `api/` holds the routes, `comfy/` talks to ComfyUI, `jobs.py` is the queue. |
| `backend/tests/` | Tests. Run them with `pytest` from `backend/`. |
| `frontend/` | The web app: plain HTML, CSS and JavaScript modules, no build step. |
| `workflows/video/`, `workflows/image/`, `workflows/audio/` | The ComfyUI workflows users can run. `workflows/archive/` is not shown in the app. |
| `workflows/upscaler/` | Workflows that make a video the user has larger. They appear as "Upscale video" on the Canvas. |
| `motion/` | Motion graphics: the HyperFrames packages (`package.json`) and the templates. |
| `scripts/` | Start scripts for each system, and `check_models.py`, which checks the agent's models and that no key can reach git. |
| `docs/` | The [handover](docs/HANDOVER.md) (start here), [architecture](docs/architecture.md), [servers and folders](docs/servers.md), [how to add workflows](docs/workflows.md), [motion graphics](docs/motion.md) and the latest [code review](docs/code-review.md). |
| `storage/` | Created at run time: the database and every user's files. Not in git. |
| `legacy/` | The earlier command-line script, kept for reference. |

## What users can do

- **Create** videos, images and music from any workflow in `workflows/`, with reference files.
- **Long videos**: several clips made one after another, each starting on the last frame of the one
  before, joined into one file. A line containing only `---` in the prompt separates per-clip prompts.
- **Canvas**: every finished item as a frame on a board, one row per shot, with a panel beside it that
  makes the next one.
- **Agent**: chat with it, attach frames from the canvas and say what each is for. It answers with a
  priced plan you approve before anything runs: generations, cuts and joins of videos you have, music
  put on a video, and motion graphics. It is open to admins and to the users an admin gives it to.
- **Motion graphics**: whole videos of animated text, written as scenes from a description and
  editable before rendering, plus title cards, lower thirds and titles over a video. All rendered on
  the studio's own machine at no cost.
- **Upscale** a video from the canvas to a larger, sharper one.
- **Timeline**: put videos in order, trim them and export the cut as one video.
- **Assets**: save characters, outfits, backgrounds and voices once and pick them in any reference box.
- **Library**: search by name or prompt, group items in projects, re-run, or continue a video from its last frame.
- **Credits**: every generation costs credits for what was asked for: a flat price for an image, a price per
  second for video, audio, motion graphics and upscales. Rates are set in the admin console (Pricing). A failed or cancelled
  job is refunded. Admins add credits in the admin console. There is no payment system yet.

## Settings

`config.json` in the project root, or a `SCENE_<NAME>` environment variable for any of them.

| Setting | Default | Meaning |
|---|---|---|
| `comfy_url` | `http://127.0.0.1:8188` | ComfyUI address. An admin can also change it in the admin console. |
| `ollama_url` | `http://127.0.0.1:11434` | The Ollama server whose language model the agent uses. It also improves prompts and writes the captions some image models need. |
| `agent_model` | first model there is | The model the agent uses unless the user picks another, for example `qwen3.5:9b`, or `kimi/kimi-k2.6` for a hosted one. |
| `api_url`, `api_key`, `api_models` | none | A hosted model service for the agent beside the local ones, for example Kimi. See [docs/servers.md](docs/servers.md). |
| `gemini_key`, `gemini_models` | none | Google Gemini models for the agent. |
| `host`, `port` | `0.0.0.0`, `8080` | Where the app listens. Use `127.0.0.1` to keep it to this computer. |
| `default_workflow` | none | Workflow selected for new users, for example `video/h3_director`. |
| `allow_signup` | `true` | Whether visitors can create accounts. The first account can always be created. |
| `secure_cookies` | `false` | Set to `true` when the app is served over https. |
| `signup_credits` | `1000` | Credits a new account starts with. An admin can change it in the admin console. |
| `signups_per_day` | `3` | New accounts one visitor address may make in a day. `0` means no limit. |
| `storage_dir`, `workflows_dir` | `storage`, `workflows` | Where data and workflows live. |
| `node_path` | the installed one | The Node.js program that renders motion graphics. See [docs/motion.md](docs/motion.md). |
| `output_dir` | `outputs` inside `storage_dir` | Where finished images and videos are kept. Can be any folder, for example `C:/Scene/Outputs`. |

## Development

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest      # tests
cd backend && ../.venv/bin/python -m scene       # run the app
```

On Windows the Python is `.venv\Scripts\python.exe`. The tests need no ComfyUI, Ollama or Node.js.

## Before putting it on the public internet

The app is built for a team on a private network. For public use it still needs https in front of it
(then set `secure_cookies`), email verification and password reset, a way to buy credits,
and storage and a database that can grow beyond one machine. See [docs/architecture.md](docs/architecture.md).
