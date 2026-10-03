/Users/yogesh/Documents/Coding/h3_script_v2/prompt.txt"""Run the h3_director_draft_backup ComfyUI workflow from the command line or VS Code.

Standard library only. ComfyUI must be running and reachable at --server.

Example:
    python h3_director.py --prompt "The main character waves at the camera." ^
        --character-1 "C:\\photos\\anna.jpg" --resolution 768 --orientation landscape --duration 5
"""

import argparse
import contextlib
import io
import json
import mimetypes
import os
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_SERVER = "http://100.123.221.34:8188"
HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_FILE = os.path.join(HERE, "h3_director_draft_api.json")

# Short edge -> long edge for 16:9 / 9:16. All sizes are multiples of 32, as H3 needs.
LONG_EDGE = {480: 864, 720: 1280, 768: 1344, 1080: 1920}
SHORT_EDGE = {480: 480, 720: 736, 768: 768, 1080: 1088}

# flag name -> (node id in the workflow, input name on that node)
REFERENCE_SLOTS = {
    "character_1": ("201", "image"),
    "character_2": ("202", "image"),
    "character_3": ("203", "image"),
    "outfit": ("204", "image"),
    "background": ("205", "image"),
    "prop": ("206", "image"),
    "motion_video": ("207", "video"),
    "voice_sample": ("208", "audio"),
    "first_frame": ("209", "image"),
    "last_frame": ("210", "image"),
    "voice_track": ("211", "audio"),
}

NODE_PROMPT = "100"
NODE_DURATION = "102"
NODE_WIDTH = "103"
NODE_HEIGHT = "104"
NODE_FINAL_STEPS = "105"
NODE_SEED = "106"
NODE_FINAL_QUALITY = "108"
NODE_VSA = "109"
NODE_MODEL_SWITCH = "27"
NODE_DRAFT_STEPS = "113"
NODE_VSA_GATE = "144"
NODE_DIRECTOR = "6"
NODE_SAVE = "16"

# quality level -> (full model?, steps)
QUALITY = {
    "low": (False, 4),
    "medium": (True, 20),
}
QUALITY_TEXT = {
    "low": "4-step draft with the turbo LoRA",
    "medium": "full model, 20 steps",
}
# How "fast" mode speeds each quality level up.
FAST_TEXT = {
    "low": "VSA sparse attention",
    "medium": "Sol-Attn sparse attention",
}
# Minutes for one clip at 768p on the RTX 5090: (mode, quality) -> duration -> (minutes, measured?)
MINUTES_768 = {
    ("fast", "low"): {5: (0.9, True), 10: (2.0, True), 15: (18.0, True)},
    ("normal", "low"): {5: (1.2, True), 10: (3.2, True), 15: (25.0, False)},
    ("fast", "medium"): {5: (2.3, True), 10: (6.1, True), 15: (25.0, False)},
    ("normal", "medium"): {5: (4.3, True), 10: (13.8, True), 15: (90.0, False)},
}
SOL_ATTN_NODE = {
    "class_type": "BlockSparseAttention",
    "inputs": {
        "model": ["1", 0], "selection": "sol-attn", "selection.tau": 1.3, "start_percent": 0.2, "end_percent": 1.0,
        "dense_blocks": "", "min_tokens": 12288, "extra_tokens": 256, "sink_conditioning": "exact_kv_and_rows",
        "verbose": False,
    },
}

def build_parser():
    p = argparse.ArgumentParser(description="Generate a video with the H3 Director (draft) workflow.")
    p.add_argument("--server", default=DEFAULT_SERVER, help="ComfyUI address (default: %(default)s)")

    g = p.add_argument_group("prompt")
    g.add_argument("--prompt", help="What happens in the video: action, camera, sound.")
    g.add_argument("--prompt-file", help="Read the prompt from a text file instead of --prompt.")

    g = p.add_argument_group("video")
    g.add_argument("--resolution", type=int, choices=[480, 720, 768, 1080], default=768,
                   help="Short edge in pixels. 768 is H3's native size (default: %(default)s)")
    g.add_argument("--orientation", choices=["landscape", "portrait", "square"], default="landscape")
    g.add_argument("--duration", type=int, choices=[5, 10, 15], default=5, help="Clip length in seconds.")
    g.add_argument("--seed", type=int, default=42, help="Same seed + same inputs = same video. -1 picks a random seed.")

    g = p.add_argument_group("quality")
    g.add_argument("--mode", choices=["normal", "fast"],
                   help="fast = sparse attention speed-up (default), normal = no speed-up.")
    g.add_argument("--quality", choices=["low", "medium"],
                   help="low = 4-step draft, medium = full model 20 steps (default).")
    g.add_argument("--final-quality", action="store_true",
                   help="Override: use the full model. Combine with --final-steps and --no-vsa.")
    g.add_argument("--final-steps", type=int, help="Override the step count of the full model.")
    g.add_argument("--draft-steps", type=int, default=4, help="Steps used in draft mode (default: %(default)s)")
    g.add_argument("--no-vsa", action="store_true", help="Override: turn the VSA speed-up off in low quality.")
    g.add_argument("--sparsity", type=float, default=0.6, help="VSA sparsity: 0.5 more detail ... 0.75 faster.")
    g.add_argument("--ref-image-size", choices=["match", "max"], default="match",
                   help="'max' keeps references larger for stronger identity, but is slower.")
    g.add_argument("--no-describe-references", action="store_true",
                   help="Don't add the line that tells the model what each reference is.")

    g = p.add_argument_group("references (all optional; any you leave out is skipped)")
    g.add_argument("--character-1", help="Image: the main character.")
    g.add_argument("--character-2", help="Image: the main character from another angle.")
    g.add_argument("--character-3", help="Image: a second character.")
    g.add_argument("--outfit", help="Image: the outfit the main character wears.")
    g.add_argument("--background", help="Image: the location / background.")
    g.add_argument("--prop", help="Image: a prop or product.")
    g.add_argument("--motion-video", help="Video: body motion / camera move to follow.")
    g.add_argument("--voice-sample", help="Audio or video: a voice to imitate.")
    g.add_argument("--first-frame", help="Image: the video starts on this exact image.")
    g.add_argument("--last-frame", help="Image: the video ends on this exact image.")
    g.add_argument("--voice-track", help="Audio or video: the lips follow this audio.")

    g = p.add_argument_group("output")
    g.add_argument("--out-dir", default=os.path.join(HERE, "outputs"), help="Where to save the video (default: %(default)s)")
    g.add_argument("--name", default="h3_director", help="File name prefix on the server (default: %(default)s)")
    g.add_argument("--no-download", action="store_true", help="Leave the video on the server only.")
    g.add_argument("--dry-run", action="store_true", help="Print the settings and stop without generating.")
    return p


def resolve_quality(args):
    """Turn --mode / --quality (defaults: fast, medium) plus the override flags into the actual settings."""
    if args.mode is None:
        args.mode = "fast"
    if args.quality is None and not args.final_quality:
        args.quality = "medium"
    args.sol_attn = False
    if args.quality:
        full_model, steps = QUALITY[args.quality]
        args.final_quality = full_model or args.final_quality
        if args.final_steps is None:
            args.final_steps = steps if full_model else 20
        if args.final_quality:
            args.no_vsa = True
            args.sol_attn = args.mode == "fast"
        elif args.mode == "normal":
            args.no_vsa = True
    else:
        if args.final_steps is None:
            args.final_steps = 20
        args.sol_attn = args.mode == "fast" and args.no_vsa
    return args


def estimate_minutes(mode, quality, duration, resolution, orientation):
    """Expected minutes for one clip, and whether that number was measured."""
    minutes, measured = MINUTES_768[(mode, quality)][duration]
    width, height = video_size(resolution, orientation)
    ratio = (width * height) / float(1344 * 768)
    if abs(ratio - 1.0) > 0.02:
        minutes, measured = minutes * ratio ** 1.5, False
    return minutes, measured


def format_estimate(minutes, measured):
    text = "{:.0f} min".format(minutes) if minutes >= 10 else "{:.1f} min".format(minutes)
    if minutes >= 90:
        text = "{:.1f} h".format(minutes / 60)
    return ("about " if measured else "~") + text + ("" if measured else " (est.)")


def describe_run(args):
    """One line saying which settings will run and how long it should take."""
    if args.quality:
        label = "{} mode, {} quality: {}".format(args.mode, args.quality, QUALITY_TEXT[args.quality])
        if args.mode == "fast":
            label += " + " + FAST_TEXT[args.quality]
        if args.quality == "medium" and args.final_steps != QUALITY["medium"][1]:
            return "{}, {} steps (override)".format(label, args.final_steps)
        minutes, measured = estimate_minutes(args.mode, args.quality, args.duration, args.resolution, args.orientation)
        return "{}, {}".format(label, format_estimate(minutes, measured))
    return "full model, {} steps, {}".format(
        args.final_steps, "Sol-Attn on" if args.sol_attn else ("VSA off" if args.no_vsa else "VSA on"))


def ask_mode_and_quality(duration, resolution, orientation):
    print("Generation mode and quality (expected time for {} s at {}p {}):".format(duration, resolution, orientation))
    for mode in ("fast", "normal"):
        for level in ("low", "medium"):
            minutes, measured = estimate_minutes(mode, level, duration, resolution, orientation)
            print("  {:<6} {:<7}- {}{}, {}".format(
                mode, level, QUALITY_TEXT[level],
                " + " + FAST_TEXT[level] if mode == "fast" else "", format_estimate(minutes, measured)))
    mode = ask("Mode", "fast", ["fast", "normal"])
    quality = ask("Quality", "medium", ["low", "medium"])
    return mode, quality


def ask(question, default=None, choices=None):
    """input() with a default (Enter keeps it) and an optional list of allowed answers."""
    while True:
        hint = ""
        if choices:
            hint += " ({})".format("/".join(str(c) for c in choices))
        if default is not None:
            hint += " [{}]".format(default)
        answer = input("{}{}: ".format(question, hint)).strip()
        if not answer and default is not None:
            return str(default)
        if choices and answer not in [str(c) for c in choices]:
            print("  Please type one of: {}".format(", ".join(str(c) for c in choices)))
            continue
        if answer:
            return answer


def split_flags(line):
    """Split a line of flags like a shell would, so quoted paths and Finder's escaped spaces work."""
    if os.name != "nt":
        return shlex.split(line)
    # Windows paths use backslashes, so keep them and only remove the surrounding quotes.
    return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "'\"" else t for t in shlex.split(line, posix=False)]


def ask_extra_flags(parser, base):
    """Ask for one line of flags (references and options) until it parses and every file exists."""
    example = "--character-1 anna.jpg --outfit dress.jpg --background cafe.jpg --voice-track line1.mp3 --seed 7"
    print("Type the references and options in one line, for example:")
    print("  " + example)
    print("References: " + " ".join("--" + s.replace("_", "-") for s in REFERENCE_SLOTS))
    while True:
        line = input("> ").strip()
        if not line:
            return []
        try:
            extra = split_flags(line)
        except ValueError as e:
            print("  Couldn't read that line ({}). Try again, or press Enter for none.".format(e))
            continue
        errors = io.StringIO()
        try:
            with contextlib.redirect_stderr(errors):
                args = parser.parse_args(base + extra)
        except SystemExit:
            reason = errors.getvalue().strip().splitlines()[-1].split("error: ")[-1] if errors.getvalue().strip() else "unknown flag"
            print("  Couldn't use that line: {}. Try again, or press Enter for none.".format(reason))
            continue
        missing = [(slot, getattr(args, slot)) for slot in REFERENCE_SLOTS
                   if getattr(args, slot) and not os.path.isfile(os.path.expanduser(getattr(args, slot)))]
        if missing:
            for slot, path in missing:
                print("  File not found for --{}: {}".format(slot.replace("_", "-"), path))
            print("  Try again (tip: drag the file from Finder into the terminal), or press Enter for none.")
            continue
        return extra


def interactive(parser):
    """Step-by-step mode used when the script is started with no arguments."""
    print("H3 Director - step by step. Press Enter to keep the value shown in [brackets].")
    print()
    while True:
        print("Prompt (what happens in the video), or the path of a .txt prompt file:")
        prompt = input("> ").strip()
        if prompt:
            break
        print("  The prompt can't be empty.")
    candidate = os.path.expanduser(prompt.strip("'\"").replace("\\ ", " "))
    if candidate.lower().endswith(".txt") and os.path.isfile(candidate):
        base = ["--prompt-file", candidate]
    else:
        base = ["--prompt", prompt]

    base += ["--resolution", ask("Resolution", 768, [480, 720, 768, 1080])]
    base += ["--orientation", ask("Orientation", "landscape", ["landscape", "portrait", "square"])]
    base += ["--duration", ask("Duration in seconds", 5, [5, 10, 15])]
    mode, quality = ask_mode_and_quality(int(base[-1]), int(base[base.index("--resolution") + 1]),
                                         base[base.index("--orientation") + 1])
    base += ["--mode", mode, "--quality", quality]

    extra = []
    if ask("Add references or options?", "n", ["y", "n"]) == "y":
        extra = ask_extra_flags(parser, base)

    args = resolve_quality(parser.parse_args(base + extra))
    width, height = video_size(args.resolution, args.orientation)
    refs = [slot.replace("_", "-") for slot in REFERENCE_SLOTS if getattr(args, slot)]
    print()
    print("Summary")
    print("  Server:     {}".format(args.server))
    print("  Video:      {}x{}, {} s".format(width, height, args.duration))
    print("  Quality:    {}".format(describe_run(args)))
    print("  References: {}".format(", ".join(refs) if refs else "none"))
    if ask("Start?", "y", ["y", "n"]) != "y":
        sys.exit("Cancelled.")
    print()
    return args


def video_size(resolution, orientation):
    short, long_ = SHORT_EDGE[resolution], LONG_EDGE[resolution]
    if orientation == "landscape":
        return long_, short
    if orientation == "portrait":
        return short, long_
    return short, short


def http_json(url, data=None, timeout=60):
    headers = {"Content-Type": "application/json"} if data is not None else {}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def upload_file(server, path):
    """Upload a local file into ComfyUI's input folder and return the name ComfyUI stored it under."""
    if not os.path.isfile(path):
        sys.exit("File not found: {}".format(path))
    boundary = "----h3director" + uuid.uuid4().hex
    filename = os.path.basename(path)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        payload = f.read()
    parts = [
        "--{}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n".format(
            boundary, filename, mime).encode("utf-8"),
        payload,
        "\r\n--{}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{}--\r\n".format(
            boundary, boundary).encode("utf-8"),
    ]
    req = urllib.request.Request(
        server + "/upload/image", data=b"".join(parts),
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=600) as r:
        info = json.loads(r.read().decode("utf-8"))
    name = info["name"]
    if info.get("subfolder"):
        name = info["subfolder"] + "/" + name
    return name


def build_workflow(args, prompt, uploaded):
    with open(WORKFLOW_FILE, encoding="utf-8") as f:
        wf = json.load(f)
    width, height = video_size(args.resolution, args.orientation)
    seed = args.seed if args.seed >= 0 else int.from_bytes(os.urandom(6), "big")

    wf[NODE_PROMPT]["inputs"]["value"] = prompt
    wf[NODE_DURATION]["inputs"]["value"] = float(args.duration)
    wf[NODE_WIDTH]["inputs"]["value"] = width
    wf[NODE_HEIGHT]["inputs"]["value"] = height
    wf[NODE_SEED]["inputs"]["value"] = seed
    wf[NODE_FINAL_QUALITY]["inputs"]["value"] = args.final_quality
    wf[NODE_FINAL_STEPS]["inputs"]["value"] = args.final_steps
    wf[NODE_DRAFT_STEPS]["inputs"]["value"] = args.draft_steps
    wf[NODE_VSA]["inputs"]["value"] = not args.no_vsa
    if args.sol_attn:
        # Sol-Attn sparse attention on the full model (fast mode, medium quality).
        wf["400"] = json.loads(json.dumps(SOL_ATTN_NODE))
        wf[NODE_MODEL_SWITCH]["inputs"]["on_true"] = ["400", 0]
    wf[NODE_VSA_GATE]["inputs"]["sparsity"] = args.sparsity
    wf[NODE_DIRECTOR]["inputs"]["ref_image_size"] = args.ref_image_size
    wf[NODE_DIRECTOR]["inputs"]["describe_references"] = not args.no_describe_references
    wf[NODE_SAVE]["inputs"]["filename_prefix"] = "video/" + args.name

    for slot, (node_id, input_name) in REFERENCE_SLOTS.items():
        wf[node_id]["inputs"][input_name] = uploaded.get(slot, "none")
    return wf, width, height, seed


def wait_for(server, prompt_id, poll=5):
    start = time.time()
    while True:
        history = http_json("{}/history/{}".format(server, prompt_id))
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                for kind, info in status.get("messages", []):
                    if kind == "execution_error":
                        sys.exit("\nComfyUI error in node '{}': {}".format(
                            info.get("node_type"), info.get("exception_message")))
                sys.exit("\nComfyUI reported an error.")
            if status.get("completed"):
                print()
                return entry, time.time() - start
        elapsed = int(time.time() - start)
        print("\r  generating... {:d}:{:02d}".format(elapsed // 60, elapsed % 60), end="", flush=True)
        time.sleep(poll)


def download_outputs(server, entry, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for node_output in entry.get("outputs", {}).values():
        for key in ("images", "gifs", "videos"):
            for item in node_output.get(key, []):
                if item.get("type") != "output":
                    continue
                query = urllib.parse.urlencode(
                    {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": "output"})
                target = os.path.join(out_dir, item["filename"])
                with urllib.request.urlopen("{}/view?{}".format(server, query), timeout=600) as r, open(target, "wb") as f:
                    f.write(r.read())
                saved.append(target)
    return saved


def main():
    parser = build_parser()
    if len(sys.argv) == 1:
        args = interactive(parser)
    else:
        args = resolve_quality(parser.parse_args())
    for slot in REFERENCE_SLOTS:
        if getattr(args, slot):
            setattr(args, slot, os.path.expanduser(getattr(args, slot)))
    server = args.server.rstrip("/")

    if args.prompt_file:
        with open(os.path.expanduser(args.prompt_file), encoding="utf-8") as f:
            prompt = f.read().strip()
    else:
        prompt = (args.prompt or "").strip()
    if not prompt:
        sys.exit("Give a prompt with --prompt \"...\" or --prompt-file prompt.txt")

    try:
        http_json(server + "/system_stats", timeout=10)
    except (urllib.error.URLError, OSError) as e:
        sys.exit("Can't reach ComfyUI at {} ({}). Start ComfyUI or pass --server.".format(server, e))

    given = {slot: getattr(args, slot) for slot in REFERENCE_SLOTS if getattr(args, slot)}
    width, height = video_size(args.resolution, args.orientation)
    print("Server:      {}".format(server))
    print("Video:       {}x{}, {} s".format(width, height, args.duration))
    print("Quality:     {}".format(describe_run(args)))
    print("References:  {}".format(", ".join(given) if given else "none (text to video)"))
    if args.dry_run:
        return

    uploaded = {}
    for slot, path in given.items():
        print("  uploading {} ...".format(slot))
        uploaded[slot] = upload_file(server, path)

    wf, width, height, seed = build_workflow(args, prompt, uploaded)
    try:
        result = http_json(server + "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    except urllib.error.HTTPError as e:
        sys.exit("ComfyUI rejected the workflow:\n" + e.read().decode("utf-8", "replace")[:2000])
    if result.get("node_errors"):
        sys.exit("ComfyUI rejected the workflow:\n" + json.dumps(result["node_errors"], indent=1)[:2000])

    print("Queued (seed {}).".format(seed))
    entry, seconds = wait_for(server, result["prompt_id"])
    print("Done in {:.1f} min.".format(seconds / 60))

    if args.no_download:
        return
    for path in download_outputs(server, entry, args.out_dir):
        print("Saved: {}".format(path))


if __name__ == "__main__":
    main()
