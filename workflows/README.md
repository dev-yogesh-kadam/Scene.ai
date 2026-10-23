# Workflows

The ComfyUI workflows the studio offers. It reads this folder fresh on every request, so a file added here appears in
the studio without a restart.

```
image/      24 picture workflows
video/      20 video workflows
audio/       4 sound workflows (music, voice split, transcripts)
upscaler/    1 video upscaler (its own action in the studio, not on the Create page)
archive/    retired workflows and old handovers: never read
reports/    the ComfyUI agent's reports and model lists: never read
```

## One workflow = up to three files, side by side

| File | What it is |
|---|---|
| `<name>.json` | **What runs.** An API export from ComfyUI, or ComfyUI's normal save. The studio reads both. |
| `<name>.studio.json` | Its settings for the studio: title, options (Draft/Final, size), hidden nodes, references, seed targets. |
| `<name>.ui.json` | Only beside an API export: the normal save, to open and edit in ComfyUI. Never run. |

The workflow's id in the studio is `<kind>/<name>`, for example `image/image_t2i_lumina2`. Keep the name when a
workflow is updated: earlier results, saved defaults and prices all refer to it.

## Adding a handover from the ComfyUI agent

The agent hands over `scene_ai_app/<kind>/<name>_api.json`, `<name>.studio.json`, and `workflows/<name>.json`. For each
workflow, put these three files in its kind's folder:

- `<name>_api.json` becomes `<kind>/<name>.json`
- `<name>.studio.json` keeps its name: `<kind>/<name>.studio.json`
- `workflows/<name>.json` becomes `<kind>/<name>.ui.json`

When there is no API export, the ComfyUI save itself is `<kind>/<name>.json` and there is no `.ui.json`.

The console's Workflows page records a new version only when a file's content changes. Seeds are always random
unless a user reuses one; a sidecar's `"seed": {"targets": [...]}` names the seed inputs, and every other seed in the
graph gets the same value. See `docs/workflows.md` for the sidecar's other fields.
