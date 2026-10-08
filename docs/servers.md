# Servers and folders on the studio PC

Scene.ai talks to a render server and to one or more language model servers. All of it is set in
`config.json` in the repo root. That file is ignored by git, so it has to be set on every machine
the app runs on, and it is where the secret keys are: **do not open, print or copy it**; change single
lines of it, and check it with `scripts/check_models.py`.

| Server | Address | `config.json` key | Where it runs |
|---|---|---|---|
| ComfyUI (rendering) | `http://100.123.221.34:8188` | `comfy_url` | The Windows render PC, reached over Tailscale |
| Ollama (local models for the agent) | `http://localhost:11434` | `ollama_url` | The same machine as the app |
| Google Gemini (hosted models for the agent) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini_url`, `gemini_key` | Google |

The agent's default model is `agent_model`: on the studio PC `gemini/gemini-3.6-flash`. If it is
empty, the app uses the first model there is. Ollama has `qwen3.5:9b`, the largest of its family that
fits the studio PC's 8 GB graphics card, and `qwen3.5:27b`, which needs about 20 GB and takes about a
minute a reply here. Each user can pick another model in the Agent tab.

The agent's model is used for three things: the agent's answers and plans, "Improve prompt", and
the structured caption that Ideogram 4 needs. With no model reachable, those three stop and
everything else works. When a hosted model is busy, the smallest local model answers in its place.

```json
{
  "comfy_url": "http://100.123.221.34:8188",
  "ollama_url": "http://localhost:11434",
  "agent_model": "gemini/gemini-3.6-flash",
  "default_workflow": "video/video_minimax_h3_i2v"
}
```

Write the addresses without a trailing slash.

## Hosted models beside the local ones (Kimi, Gemini)

The agent can also use models over the internet. Each service is offered as soon as its key is set
in `config.json`; with no key it does not appear.

| Service | Keys in `config.json` | Where the key comes from |
|---|---|---|
| Kimi (Moonshot) | `api_url` (`https://api.moonshot.ai/v1`), `api_key`, `api_models` | platform.kimi.ai |
| Google Gemini | `gemini_key`, `gemini_models` | aistudio.google.com |

```json
{
  "api_url": "https://api.moonshot.ai/v1",
  "api_key": "sk-...",
  "api_models": "kimi-k2.6",
  "gemini_key": "...",
  "gemini_models": ""
}
```

- **The keys are secret.** `config.json` is ignored by git, so they are not committed. They can also
  be given as the `SCENE_API_KEY` and `SCENE_GEMINI_KEY` environment variables. A key is never sent
  to the browser and never written to a log.
- **`api_models` and `gemini_models`** are the model names to offer, comma separated. Left empty, the
  studio asks the service: all of Kimi's, and Gemini's Pro and Flash models.
  Set to `"off"`, the service is switched off without taking its key out.
- The first service is not tied to Kimi: `api_url`, `api_key`, `api_models` and `api_name` (the name
  shown in the picker) work for any service that speaks the OpenAI chat API.
- Restart the app after changing any of them.

In the Agent tab the model dropdown lists the local models and the hosted ones, each hosted one
with its service ("kimi-k2.6 · Kimi"). Each user picks in their own browser. To make a hosted model
the default for everyone, set `agent_model` to `<service>/<model>`, for example `"gemini/gemini-3.8-flash"`.

What to know before using one:

- Every message to a hosted model leaves the building: the message, the project's brief and cast
  names, the names and prompts of attached items, and the list of workflows. Pictures and videos
  themselves are never sent.
- It costs money per use, billed by the service to the owner of the key. A service with no balance
  refuses with its own message, which the agent shows.
- With Ollama off, a hosted model keeps the agent, "Improve prompt" and the Ideogram caption working.

**Checking them.** This lists every model source, says whether each key is set (never the key
itself), whether git could publish a key, and sends one small message to each hosted model:

```bash
.venv\Scripts\python.exe scripts\check_models.py
```

## Changing them

- **Restart the app** after editing `config.json`. It is read once, when the app starts.
- The `SCENE_COMFY_URL`, `SCENE_OLLAMA_URL` and `SCENE_AGENT_MODEL` variables override `config.json`.
- The ComfyUI address can also be changed in the admin console (Settings tab). That value is saved
  in the database and **wins over `config.json`** from then on. If a change to `comfy_url` in
  `config.json` seems to have no effect, check the admin console.
- The Ollama address has no setting in the admin console; `config.json` is the only place.

## Checking that they answer

```bash
curl http://100.123.221.34:8188/system_stats
curl http://localhost:11434/api/tags
```

The first needs Tailscale connected and ComfyUI running on the render PC. The second lists the
models Ollama has; `qwen3.5:9b` must be in the list.

# The public address (Cloudflare Tunnel)

`https://developmenttestinghere.in` reaches the app on the studio PC. This section is from yogesh's
hosting notes of 4 October; the tunnel was set up outside this repo.

```
Browser -> developmenttestinghere.in -> Cloudflare (DNS, https) -> tunnel "studio" -> studio PC -> http://localhost:8080
```

The studio PC's internet connection is behind the provider's shared address (CGNAT), so a port cannot
be forwarded to it. The tunnel dials out to Cloudflare instead, and no port is opened on the router.
ComfyUI is not behind the tunnel and must stay that way: the app reaches it over Tailscale.

| Thing | Where |
|---|---|
| Domain | `developmenttestinghere.in`, registered at Hostinger, name servers at Cloudflare (free plan) |
| `cloudflared` | `C:\cloudflared\cloudflared.exe` |
| Tunnel | named `studio`; its settings are in `C:\Users\LUFI\.cloudflared\config.yml`, which sends the domain to `http://localhost:8080` |
| Secrets | `cert.pem` and the tunnel's `.json` credentials file in `C:\Users\LUFI\.cloudflared\`. Never copy them into the repo. |

**After a reboot** nothing starts by itself. Start the app, then the tunnel in a second window:

```
C:\Scene\Scene.ai\scripts\start.bat
C:\cloudflared\cloudflared.exe tunnel run studio
```

The tunnel is up when its window says `Registered tunnel connection`. Do not make the tunnel, the DNS
record or the config again after a reboot: they are kept.

**If the public address does not work**, check in this order: `http://localhost:8080` on the studio PC
(if that fails, the app is not running); `cloudflared.exe tunnel ingress validate` (expects `OK`);
`cloudflared.exe tunnel list`; then the output of `tunnel run studio`.

**Errors in the tunnel's window that are not faults:**

- `stream … canceled by remote with error code 0` followed by `Request failed … /api/library/<n>/file`:
  the visitor's browser closed a download it no longer needed, which a browser does when it has read
  enough of a video, when a video is scrubbed, or when the page is left. Thumbnails used to cause a
  burst of these on every page; they are posters now and no longer do.
- `Failed to dial a quic connection` or `timeout: no recent network activity`, followed by a new
  `Registered tunnel connection`: a short loss of connection that mended itself.

Not done yet: `cloudflared` as a Windows service, the app starting with Windows, and logs kept anywhere.

# Folders

| What | Where | Set by |
|---|---|---|
| The studio (code) | `C:\Scene\Scene.ai` | where the repo is |
| HyperFrames and its packages | `C:\Scene\Scene.ai\motion\node_modules\` | `npm install` in `motion/`; see [motion.md](motion.md) |
| Node.js | `C:\Program Files\nodejs\` | its installer; `node_path` in `config.json` if it is elsewhere |
| Finished images and videos | `C:\Scene\Outputs\<user email>\`, for example `C:\Scene\Outputs\admin@gmail.com\` | `output_dir` in `config.json` |
| Video thumbnails (posters) | `.posters\` inside each user's folder of finished work | made by the app the first time a thumbnail is shown; safe to delete, they are made again |
| Database, saved assets, cache, working files | `C:\Scene\Scene.ai\storage\` | `storage_dir` in `config.json` |

`output_dir` is optional. Without it, finished work goes to `outputs` inside the storage folder.
Restart the app after changing it. The database records only file names, so files already made have
to be moved by hand into the new folder, keeping their sub-folders. A sub-folder still named by user
id (`1`, `2`, …), as they were before 4 October, is renamed to the email the first time it is needed.

**Inputs.** A reference file added to a job is not kept by the studio. It is sent straight to the
render PC and stays in ComfyUI's `input` folder there, named `scene_<hash>_<name>`. Only files saved
as **assets** are kept here, in `storage\assets\<user id>\`.
