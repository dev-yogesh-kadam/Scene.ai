"""Review: the agent looks at what it made and says whether it is what was asked for.

A finished picture or clip is checked by the agent's model against its prompt, the reference pictures it was made
with (a character, a place) and, for a shot that continues another, the last frame of that shot. Five checks, as a
director would make them:

    who          the right people, compared with their reference pictures
    what         the action, the place and the framing the prompt asked for
    clean        no broken hands or faces, no garbled text or watermarks, nothing cut off at the edge
    coherence    the face, the props and the light stay the same through the clip; movement is believable
    continuity   the outfit, the props and the time of day match the shot before; the cut from it is smooth

Each check is "fine", "minor" or "major"; a result passes unless one is major. A failed result comes with a fix: a
corrected prompt, and whether the retake should start on the last frame of the shot before. The verdict is kept with
the item (generations.review), shown under the step, in Shared memory, and to the agent when it plans again.
"""

import base64
import json
import tempfile
import time
from pathlib import Path

from . import media

CHECKS = ("who", "what", "clean", "coherence", "continuity")
LEVELS = ("fine", "minor", "major")
MAX_REFERENCES = 3      # reference pictures shown beside the result
FRAME_WIDTH = 768       # the frames of a clip the model looks at


class ReviewError(Exception):
    pass


def _b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


async def _still(path):
    """A small JPEG of a picture, or of a video's first moments, base64."""
    return _b64(await media.poster(path))


async def result_frames(path, kind):
    """What the model looks at of a result: [(label, base64 JPEG)]. A picture is itself; a clip is four frames,
    half a second in, a third, two thirds and half a second before the end."""
    if kind == "image":
        return [("the result", await _still(path))]
    length = (await media.probe(path))["seconds"]
    if length <= 0:
        raise ReviewError("That video can't be read.")
    moments = sorted({round(t, 2) for t in (min(0.5, length / 4), length / 3, 2 * length / 3, max(0.0, length - 0.5))})
    frames = []
    with tempfile.TemporaryDirectory() as folder:
        for number, moment in enumerate(moments):
            found = await media.frame_at(path, moment, Path(folder) / "f{}.jpg".format(number), FRAME_WIDTH)
            if found:
                frames.append(("the result at {:.1f} s".format(moment), _b64(found)))
    if not frames:
        raise ReviewError("No frame could be taken from that video.")
    return frames


async def last_frame(path, kind):
    """The last frame of a shot (a picture is its own), base64, for the continuity check."""
    if kind == "image":
        return await _still(path)
    with tempfile.TemporaryDirectory() as folder:
        found = await media.last_frame(path, Path(folder) / "last.jpg")
        return _b64(found) if Path(found).is_file() else None


def verdict_from(answer):
    """The model's answer as a verdict we keep: {"passed", "problem", "checks", "fix", "at"}. Unknown checks and levels
    are dropped; a result passes unless a check is major."""
    checks = []
    for check in answer.get("checks") if isinstance(answer.get("checks"), list) else []:
        if isinstance(check, dict) and check.get("check") in CHECKS and check.get("level") in LEVELS:
            checks.append({"check": check["check"], "level": check["level"], "note": " ".join(str(check.get("note") or "").split())[:240]})
    passed = not any(c["level"] == "major" for c in checks)
    fix = answer.get("fix") if isinstance(answer.get("fix"), dict) else {}
    problem = " ".join(str(answer.get("problem") or "").split())[:300]
    if not passed and not problem:
        problem = next(c["note"] for c in checks if c["level"] == "major") or "It is not what was asked for."
    return {"passed": passed, "problem": "" if passed else problem, "checks": checks, "at": time.time(),
            "fix": {} if passed else {"prompt": " ".join(str(fix.get("prompt") or "").split())[:2000],
                                      "start_from_previous": fix.get("start_from_previous") is True,
                                      "why": " ".join(str(fix.get("why") or "").split())[:240]}}


def summary(verdict):
    """One line of a verdict, for Shared memory and the agent's book."""
    if not verdict:
        return ""
    if verdict.get("passed"):
        minor = [c["note"] for c in verdict.get("checks", []) if c["level"] == "minor" and c["note"]]
        return "Passed the review" + (" (minor: {})".format("; ".join(minor)[:160]) if minor else "")
    return "Failed the review: " + verdict.get("problem", "")


def load(row):
    """The verdict kept with a library item, or None."""
    try:
        found = json.loads(row.get("review") or "null")
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


async def review_item(state, user_id, item, prompt, references=(), previous=None):
    """Review one library item. item: its generations row. prompt: what it was asked to show (its own prompt when
    empty). references: [(label, path)] of the reference pictures it was made with. previous: (path, kind) of the
    shot it continues, or None. Keeps the verdict with the item and returns it."""
    path = state.outputs.folder(user_id) / item["filename"]
    if item["kind"] not in ("image", "video"):
        raise ReviewError("Only pictures and videos can be reviewed.")
    if not path.is_file():
        raise ReviewError("The file of {} is missing from storage.".format(item["name"]))
    if not prompt:
        try:
            prompt = str(json.loads(item["settings"] or "{}").get("prompt") or "")
        except ValueError:
            prompt = ""
    pictures = []
    for label, ref in list(references)[:MAX_REFERENCES]:
        if Path(ref).is_file():
            try:
                pictures.append(("reference: " + label, await _still(ref)))
            except media.MediaError:
                continue
    if previous and Path(previous[0]).is_file():
        try:
            before = await last_frame(*previous)
            if before:
                pictures.append(("the last frame of the shot before", before))
        except media.MediaError:
            pass
    try:
        pictures += await result_frames(path, item["kind"])
    except media.MediaError as error:
        raise ReviewError(str(error))
    answer = await state.agent.review([p for _, p in pictures], [label for label, _ in pictures], prompt, item["kind"])
    verdict = verdict_from(answer)
    state.db.run("UPDATE generations SET review = ? WHERE id = ? AND user_id = ?", (json.dumps(verdict), item["id"], user_id))
    return verdict
