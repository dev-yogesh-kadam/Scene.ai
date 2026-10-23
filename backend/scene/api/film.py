"""The frame-exact work of a film made on its audio, queued as edits: free, made on this machine (see film.py).

POST /api/edit/film takes {"op", "name"?, "project_id"?, "run"?, ...the op's own fields}; every item it names must be
one of the user's library items of the right kind, and every number is checked here, before anything is queued.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import edits, film, runs
from ..media import FPS
from .deps import current_user
from .workspace import _project_id

router = APIRouter(prefix="/api", tags=["film"])

RUN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")   # the run a working file belongs to
MAX_FRAMES = FPS * 3 * 3600                       # three hours: the longest master a slice or a trim may reach
MAX_CLIP_FRAMES = FPS * 60                        # one trimmed clip or one timing track: a minute at most
SIZES = range(64, 2161)


def _number(value, low, high, what, whole=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (whole and value != int(value)) or not low <= value <= high:
        raise HTTPException(400, "{} must be a {} from {} to {}.".format(what, "whole number" if whole else "number", low, high))
    return int(value) if whole else float(value)


def _list(value, most, what):
    if not isinstance(value, list) or not 1 <= len(value) <= most:
        raise HTTPException(400, "Give {} as a list of 1 to {}.".format(what, most))
    return value


def _span(value, what):
    if not isinstance(value, list) or len(value) != 2:
        raise HTTPException(400, "{} must be [start, end] in seconds.".format(what))
    s, e = (_number(v, 0, MAX_FRAMES / FPS, what) for v in value)
    if e < s:
        raise HTTPException(400, "{} ends before it starts.".format(what))
    return [s, e]


def _text(value, most):
    return " ".join(str(value or "").split())[:most]


@router.post("/edit/film")
async def film_edit(body: dict, request: Request, user: dict = Depends(current_user)):
    """Queue one film operation. Costs no credits: it needs no GPU. Returns {"job", "name"}."""
    return queue(request, user, body)


def queue(request, user, body):
    """Check one film operation and queue it (the endpoint above, and the agent's "film" tool). Raises HTTPException
    with the reason when anything in it is wrong; nothing is queued then."""
    state = request.app.state
    op = body.get("op")
    if op not in edits.FILM:
        raise HTTPException(400, "The operation must be one of: {}.".format(", ".join(edits.FILM)))
    workflow, title, _, _ = edits.FILM[op]
    folder = state.outputs.folder(user["id"])

    def own(item_id, kinds, what):
        """The id of one of the user's items of one of these kinds, whose file is there."""
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise HTTPException(400, "Name {} by its library id.".format(what))
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind IN ({})".format(", ".join("?" * len(kinds))),
                           (item_id, user["id"], *kinds))
        if row is None or not (folder / row["filename"]).is_file():
            raise HTTPException(404, "{} is not in your library.".format(what[0].upper() + what[1:]))
        return row["id"]

    def size():
        given = body.get("size", list(film.SQUARE))
        if not isinstance(given, list) or len(given) != 2:
            raise HTTPException(400, "size must be [width, height].")
        w, h = (_number(v, SIZES.start, SIZES.stop - 1, "The frame size", whole=True) for v in given)
        return [w // 2 * 2, h // 2 * 2]

    settings, facts = {"workflow_title": title}, ""
    if op == "reference":
        settings["image"] = own(body.get("image"), ("image",), "the picture")
        facts = "longer side {} px".format(film.REF_SIDE)
    elif op == "slice":
        f_in = _number(body.get("f_in"), 0, MAX_FRAMES - 1, "f_in", whole=True)
        f_out = _number(body.get("f_out"), f_in + 1, MAX_FRAMES, "f_out", whole=True)
        settings.update(audio=own(body.get("audio"), ("audio", "video"), "the master audio"), f_in=f_in, f_out=f_out)
        facts = "frames {}–{} · {:.2f} s".format(f_in, f_out, (f_out - f_in) / FPS)
    elif op == "track":
        frames = [_number(n, 1, MAX_CLIP_FRAMES, "Each block's frames", whole=True) for n in _list(body.get("frames"), 60, "the blocks' frames")]
        if sum(frames) > MAX_CLIP_FRAMES:
            raise HTTPException(400, "A timing track lasts a minute at most.")
        settings["frames"] = frames
        facts = "{} blocks · {} frames".format(len(frames), max(sum(frames), film.MIN_FRAMES))
    elif op in ("trim", "retime"):
        settings.update(video=own(body.get("video"), ("video",), "the clip"),
                        frames=_number(body.get("frames"), 1, MAX_CLIP_FRAMES, "frames", whole=True), size=size())
        if op == "trim":
            settings.update(stretch=_number(body.get("stretch", 1), 0.5, 2.0, "stretch"),
                            max_pad=_number(body.get("max_pad", film.MAX_PAD), 0, FPS, "max_pad", whole=True))
        else:
            settings["lines"] = [{"master": _span(l.get("master"), "A line's master span"), "clip": _span(l.get("clip"), "A line's clip span")}
                                 for l in _list(body.get("lines"), 40, "the lines spoken on screen") if isinstance(l, dict)]
        facts = "{} frames".format(settings["frames"])
    elif op == "proof":
        marks = [{"at": _number(m.get("at"), 0, MAX_FRAMES / FPS, "A mark's time"), "label": _text(m.get("label"), 40)}
                 for m in _list(body.get("marks"), 1200, "the frames to show") if isinstance(m, dict)]
        settings.update(video=own(body.get("video"), ("video",), "the film"), marks=marks)
        facts = "{} frames · {} sheet{}".format(len(marks), -(-len(marks) // film.SHEET_MAX), "" if len(marks) <= film.SHEET_MAX else "s")
    elif op == "subtitles":
        lines = []
        for l in _list(body.get("lines"), 5000, "the transcript's lines"):
            if isinstance(l, dict):
                start, end = _span([l.get("start"), l.get("end")], "A line's start and end")
                lines.append({"start": start, "end": end, "text": _text(l.get("text"), 500), "speaker": _text(l.get("speaker"), 60),
                              "lead": l.get("lead") is True})
        settings.update(video=own(body.get("video"), ("video",), "the film"), lines=lines,
                        narrator=_text(body.get("narrator"), 60) or "narrator")
        facts = "{} lines".format(len(lines))
    elif op == "film":
        clips = [own(c, ("video",), "a trimmed clip") for c in _list(body.get("clips"), 1000, "the trimmed clips")]
        settings.update(clips=clips, audio=own(body.get("audio"), ("audio", "video"), "the master audio"))
        facts = "{} clips on the master".format(len(clips))
    elif op == "speech":
        settings["audio"] = own(body.get("audio"), ("audio", "video"), "the sound")
        if body.get("lines") is not None:
            settings["lines"] = []
            narrator = _text(body.get("narrator"), 60)   # the transcript's label for the narrator, when it is not "narrator"
            for l in _list(body.get("lines"), 10000, "the transcript's lines"):
                if isinstance(l, dict):
                    start, end = _span([l.get("start"), l.get("end")], "A line's start and end")
                    speaker = _text(l.get("speaker"), 60) or "narrator"
                    settings["lines"].append({"n": _number(l.get("n"), 0, 10 ** 6, "A line's number", whole=True), "start": start,
                                              "end": end, "speaker": "narrator" if narrator and speaker == narrator else speaker})
            facts = "{} lines".format(len(settings["lines"]))
            if body.get("save_to"):
                if not body.get("run"):
                    raise HTTPException(400, "save_to keeps the spans in a run: name the run.")
                try:
                    settings["save_to"] = runs.clean_path(body["save_to"])
                except runs.RunError as error:
                    raise HTTPException(400, str(error))
        else:
            settings["windows"] = [_span(w, "A window") for w in _list(body.get("windows"), 400, "the windows to scan")]
            facts = "{} windows".format(len(settings["windows"]))
    run = str(body.get("run") or "")
    if run and not RUN.match(run):
        raise HTTPException(400, "A run is named with lower-case letters, digits and dashes.")
    settings["run"] = run
    project_id = _project_id(request, user, body.get("project_id")) or None
    name = _text(body.get("name"), 80) or title
    job_id = state.jobs.add(user["id"], name, workflow, settings, facts, None, 0, project_id)
    return {"job": job_id, "name": name}
