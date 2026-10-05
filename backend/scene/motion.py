"""Motion graphics: titles and overlays made from HTML templates and rendered to video by HyperFrames.

HyperFrames (https://github.com/heygen-com/hyperframes) is a Node.js program that plays an HTML page in headless
Chrome frame by frame and encodes the frames with ffmpeg. It is installed into motion/ with `npm install`.
Each folder in motion/templates is one template: index.html (the composition) and template.json (its form).
"""

import asyncio
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from . import media, sequence
from .config import ROOT

MOTION_DIR = ROOT / "motion"
TEMPLATES_DIR = MOTION_DIR / "templates"
CLI = MOTION_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
FONT = ROOT / "frontend" / "assets" / "fonts" / "Archivo-latin.woff2"
SHAPES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
CARD_FPS = 30
RENDER_TIMEOUT = 900            # seconds
MAX_SOURCE_SECONDS = 120        # a longer video is better titled on the timeline
_one_at_a_time = asyncio.Lock()   # every render starts its own Chrome


class MotionError(Exception):
    pass


def node_path(configured=""):
    """The Node.js program: the configured one, the one on the PATH, or where its installer puts it."""
    places = [configured, shutil.which("node"), r"C:\Program Files\nodejs\node.exe", "/usr/local/bin/node", "/opt/homebrew/bin/node"]
    return next((str(p) for p in places if p and Path(p).is_file()), None)


def _ffprobe():
    system = {"Windows": "win32", "Darwin": "darwin"}.get(platform.system(), "linux")
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") and system == "darwin" else "x64"
    path = MOTION_DIR / "node_modules" / "ffprobe-static" / "bin" / system / arch / ("ffprobe.exe" if system == "win32" else "ffprobe")
    return path if path.is_file() else None


def status(configured_node=""):
    """Whether motion graphics can be rendered here, and if not, what is missing."""
    if not node_path(configured_node):
        return {"ready": False, "detail": "Node.js 22 or newer is not installed on the machine that runs Scene.ai."}
    if not CLI.is_file() or not _ffprobe():
        return {"ready": False, "detail": "HyperFrames is not installed. Run `npm install` in the motion folder."}
    return {"ready": True, "detail": ""}


def templates():
    """Every template, as the web page needs it: {"id", "title", "description", "needs", "fields"}."""
    found = []
    # Templates that stand on their own come first, then the ones laid over a video.
    folders = sorted(TEMPLATES_DIR.iterdir(), key=lambda f: (f.name != "title_card", f.name)) if TEMPLATES_DIR.is_dir() else []
    for folder in folders:
        try:
            form = json.loads((folder / "template.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (folder / "index.html").is_file():
            found.append({"id": folder.name, "title": form.get("title", folder.name), "description": form.get("description", ""),
                          "needs": form.get("needs"), "fields": form.get("fields", [])})
    return found


def clean(template, values):
    """The values of a template's form, checked against its fields. Raises MotionError with what is wrong."""
    out = {}
    for field in template["fields"]:
        value = (values or {}).get(field["id"], field.get("default", ""))
        if field["type"] == "choice":
            match = next((c for c in field["choices"] if str(c) == str(value)), None)
            if match is None:
                raise MotionError("'{}' is not a choice for {}.".format(value, field["label"]))
            out[field["id"]] = match
        else:
            text = " ".join(str(value or "").split())[:field.get("max", 200)]
            if field.get("required") and not text:
                raise MotionError("Fill in \"{}\".".format(field["label"]))
            out[field["id"]] = text
    return out


async def render(template_id, values, target, source=None, node="", work_dir=None):
    """Render one template to the video file `target`. source: the video a template is laid over.

    Returns {"seconds", "width", "height"} of the result."""
    template = next((t for t in templates() if t["id"] == template_id), None)
    if template is None:
        raise MotionError("There is no motion template called {}.".format(template_id))
    ready = status(node)
    if not ready["ready"]:
        raise MotionError(ready["detail"])
    values = clean(template, values)

    sound = "muted"
    if template["needs"] == "video":
        if source is None:
            raise MotionError("Select a video on the canvas first: {} is laid over a video.".format(template["title"].lower()))
        found = await media.probe(source)
        if not found["seconds"] or not found["width"]:
            raise MotionError("That video can't be read.")
        if found["seconds"] > MAX_SOURCE_SECONDS:
            raise MotionError("The video is longer than {} s. Trim it first.".format(MAX_SOURCE_SECONDS))
        width, height, seconds, fps = found["width"] // 2 * 2, found["height"] // 2 * 2, round(found["seconds"], 3), media.FPS
        sound = 'data-has-audio="true"' if found["audio"] else "muted"
    else:
        width, height = SHAPES[values.pop("shape", "landscape")]
        seconds, fps = float(values.pop("seconds", 5)), CARD_FPS

    def fill(project):
        shutil.copytree(TEMPLATES_DIR / template_id, project, dirs_exist_ok=True)
        page = (project / "index.html").read_text(encoding="utf-8")
        for mark, value in (("__WIDTH__", width), ("__HEIGHT__", height), ("__DURATION__", seconds), ("__SOUND__", sound)):
            page = page.replace(mark, str(value))
        (project / "index.html").write_text(page, encoding="utf-8")
        if source is not None:
            shutil.copy(source, project / "clip.mp4")

    return await _produce(fill, values, target, fps, template["title"], node, work_dir)


async def render_sequence(scenes, look, shape, target, node="", work_dir=None):
    """Render a video made of scenes of words (see sequence.py) to the video file `target`.

    Returns {"seconds", "width", "height"} of the result."""
    ready = status(node)
    if not ready["ready"]:
        raise MotionError(ready["detail"])
    width, height = SHAPES.get(shape, SHAPES["landscape"])
    page, _ = sequence.page(scenes, look, width, height)
    return await _produce(lambda project: (project / "index.html").write_text(page, encoding="utf-8"), {}, target, CARD_FPS,
                          "Sequence", node, work_dir)


async def _produce(fill, values, target, fps, name, node, work_dir):
    """Build a HyperFrames project in a temporary folder (fill(project) writes its index.html) and render it."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if work_dir:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    async with _one_at_a_time:
        with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
            project = Path(tmp) / "motion"
            project.mkdir()
            fill(project)
            (project / "meta.json").write_text(json.dumps({"id": "motion", "name": name}), encoding="utf-8")
            (project / "variables.json").write_text(json.dumps(values), encoding="utf-8")
            shutil.copy(MOTION_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js", project / "gsap.min.js")
            shutil.copy(FONT, project / "Archivo.woff2")
            await _run([node_path(node), str(CLI), "render", str(project), "--output", str(target), "--fps", str(fps),
                        "--variables-file", str(project / "variables.json"), "--quiet"], project)
    if not target.is_file() or not target.stat().st_size:
        raise MotionError("HyperFrames finished without making a video.")
    made = await media.probe(target)
    return {"seconds": made["seconds"], "width": made["width"], "height": made["height"]}


async def _run(command, folder):
    env = dict(os.environ, HYPERFRAMES_FFMPEG_PATH=media.ffmpeg_path(), HYPERFRAMES_FFPROBE_PATH=str(_ffprobe()),
               # Nothing is sent anywhere and nothing is installed or looked up while rendering.
               HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1", HYPERFRAMES_NO_UPDATE_CHECK="1", HYPERFRAMES_NO_FEEDBACK="1",
               HYPERFRAMES_SKIP_SKILLS="1", HYPERFRAMES_NO_AUTO_INSTALL="1")
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # no console window on Windows
    process = await asyncio.create_subprocess_exec(*command, cwd=str(folder), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **flags)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), RENDER_TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        raise MotionError("The render took longer than {} minutes and was stopped.".format(RENDER_TIMEOUT // 60))
    if process.returncode:
        lines = [line for line in output.decode("utf-8", "replace").splitlines() if line.strip()]
        raise MotionError("HyperFrames could not render this: {}".format(" ".join(lines[-3:])[-400:] or "no message"))
