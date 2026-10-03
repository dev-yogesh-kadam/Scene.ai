# H3 Director script

Runs the **h3_director_draft_backup** ComfyUI workflow from VS Code or a terminal.
It uploads your reference files, queues the job, waits, and downloads the video.

## Files

| File | What it is |
|---|---|
| `h3_director.py` | The script. Standard library only, nothing to `pip install`. |
| `h3_director_draft_api.json` | The workflow in ComfyUI API format. Keep it next to the script. |
| `prompt_example.txt` | An example prompt you can edit and pass with `--prompt-file`. |
| `.vscode/launch.json` | Ready-made Run configurations for VS Code. |
| `outputs/` | Videos are downloaded here. |

## What you need

1. **ComfyUI running** and reachable at `http://100.123.221.34:8188` (the script's default). Use `--server` for another address.
2. **Python 3.9 or newer** on the computer where you run the script. It does not have to be the ComfyUI machine.
3. On the ComfyUI machine: the custom node file `ComfyUI/custom_nodes/h3_optional_refs.py` and the `ComfyUI-Ref2VA-VSA` node pack (both already installed).

## VS Code setup

1. Install VS Code's **Python** extension (publisher: Microsoft).
2. **File > Open Folder** and pick `C:\ComfyUi\h3_scripts`.
3. Press `Ctrl+Shift+P`, run **Python: Select Interpreter**, and pick your Python 3.
4. Run it one of two ways:
   - **Terminal** (`` Ctrl+` ``): type a command like the examples below.
   - **Run and Debug** (`Ctrl+Shift+D`): pick a configuration from the dropdown and press `F5`. Edit the arguments in `.vscode/launch.json`.

## Step-by-step mode (easiest)

Run the script with no arguments and it asks you everything in order:

```bash
python3 h3_director.py
```

1. The prompt (or the path of a `.txt` prompt file).
2. Resolution, orientation and duration. Press Enter to keep the default shown in brackets.
3. "Add references or options?" Answer `y`, then type them in one line, for example:
   `--character-1 anna.jpg --outfit dress.jpg --background cafe.jpg --voice-track line1.mp3 --seed 7`
   On a Mac you can drag a file from Finder into the terminal to paste its path. If a file isn't found it asks again.
4. A summary, then "Start?".

Mode (fast / normal) and quality (low / medium) are asked right after the duration, with the expected time next to each combination.

On a Mac use `python3` instead of `python` in all the examples below.

## Examples

Text only, 5 s draft (low quality):

```bash
python h3_director.py --quality low --prompt "A woman waves at the camera in a sunny garden. Locked camera."
```

One character, vertical video, 10 s:

```bash
python h3_director.py --prompt-file prompt_example.txt --character-1 "C:\photos\anna.jpg" --orientation portrait --duration 10
```

Character, outfit, background and a voice track, medium quality:

```bash
python h3_director.py --prompt-file prompt_example.txt --character-1 anna.jpg --outfit dress.jpg --background cafe.jpg --voice-track line1.mp3 --quality medium
```

See every option:

```bash
python h3_director.py --help
```

## Options

| Option | Values | Default |
|---|---|---|
| `--prompt` / `--prompt-file` | text, or a text file | required |
| `--resolution` | `480`, `720`, `768`, `1080` (short edge) | `768` |
| `--orientation` | `landscape`, `portrait`, `square` | `landscape` |
| `--duration` | `5`, `10`, `15` seconds | `5` |
| `--seed` | a number, or `-1` for random | `42` |
| `--mode` | `fast` (sparse attention speed-up), `normal` | `fast` |
| `--quality` | `low`, `medium` | `medium` |
| `--final-quality`, `--final-steps` | manual overrides of the quality level | off |
| `--no-vsa` | manual override: VSA off in low quality | VSA on |
| `--sparsity` | `0.5` more detail ... `0.75` faster | `0.6` |
| `--ref-image-size` | `match` or `max` | `match` |
| `--server` | ComfyUI address | `http://100.123.221.34:8188` |
| `--out-dir`, `--name` | where and under what name to save | `outputs`, `h3_director` |
| `--dry-run` | show the settings, don't generate | off |

Video sizes: 480 = 864x480, 720 = 1280x736, 768 = 1344x768, 1080 = 1920x1088 (H3 needs multiples of 32). Portrait swaps the two numbers.

## Reference slots

Each flag matches a node in the workflow. Leave any of them out and that slot is skipped.

| Flag | File type | Node |
|---|---|---|
| `--character-1` | image | CHARACTER 1 (main character) |
| `--character-2` | image | CHARACTER 2 (same person, other angle) |
| `--character-3` | image | CHARACTER 3 (second person) |
| `--outfit` | image | OUTFIT |
| `--background` | image | BACKGROUND / LOCATION |
| `--prop` | image | PROP / PRODUCT |
| `--motion-video` | video | MOTION / CAMERA REFERENCE VIDEO |
| `--voice-sample` | audio or video | VOICE SAMPLE (voice to imitate) |
| `--first-frame` | image | FIRST FRAME |
| `--last-frame` | image | LAST FRAME |
| `--voice-track` | audio or video | VOICE TRACK (lips follow this audio) |

In the prompt, write "the main character", "the outfit", "the background" and so on. The workflow adds the reference numbering for you.

## Mode and quality, and how long they take (RTX 5090, 768p, one clip)

| `--mode` | `--quality` | What it runs | 5 s | 10 s | 15 s |
|---|---|---|---|---|---|
| `fast` | `low` | 4-step draft, turbo LoRA, VSA sparse attention | 0.9 min | 2.0 min | 18 min |
| `fast` (default) | `medium` (default) | full model, 20 steps, Sol-Attn sparse attention | 2.3 min | 6.1 min | ~25 min (est.) |
| `normal` | `low` | 4-step draft, turbo LoRA, no speed-up | 1.2 min | 3.2 min | ~25 min (est.) |
| `normal` | `medium` | full model, 20 steps, no speed-up | 4.3 min | 13.8 min | ~1.5 h (est.) |

- Numbers without "~" are measured. The ones marked "(est.)" are estimates.
- `fast` uses sparse attention. In testing the medium picture was almost identical to `normal`, at about half the time.
- Time grows much faster than length. Three 5 s clips are far quicker than one 15 s clip, and they drift less.
- Other resolutions are estimated from the pixel count (1080p is roughly 3x slower than 768p).
- There is no "high" level. If you want more steps, `--final-quality --final-steps 40` still works as a manual override.

## If something goes wrong

- **"Can't reach ComfyUI"**: start ComfyUI, or check the `--server` address and that the machine is reachable (Tailscale connected).
- **"ComfyUI rejected the workflow"**: a model file or custom node is missing on the server. The message names the node.
- **"File not found"**: check the path of the reference file. Put paths with spaces in quotes.
