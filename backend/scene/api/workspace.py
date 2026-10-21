"""The canvas, the timeline and the agent: arranging finished work, queueing edits and motion graphics, and planning new work."""

import asyncio
import json
import math
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import agent, camera, credits, edits, gpu, kit, media, memory, motion, review, runs, sequence, skills
from ..comfy import workflows
from .deps import agent_user, current_user
from .studio import price

router = APIRouter(prefix="/api", tags=["workspace"])

# canvas: where frames sit. timeline: the cut. agent: its tabs. cast: the project's pinned references.
KINDS = ("canvas", "timeline", "agent", "cast")
SHOT_LENGTHS = list(range(4, 16))
# agent-<id>: the conversation of one agent tab. The "agent" board lists the tabs: their names, ids and credits.
AGENT_TAB = re.compile(r"^agent-[a-z0-9]{1,16}$")


def _board_kind(kind):
    if kind not in KINDS and not AGENT_TAB.match(kind):
        raise HTTPException(404, "No such board.")   # the lengths a shot can be given on an approval card, in seconds
MAX_BOARD_BYTES = 2_000_000   # an agent tab keeps its whole conversation
MAX_CLIPS = 50
CHECKED_SKILL = 4_000        # a skill longer than this, or one the user named with /command, is checked before the agent plans
MOTION_WORKFLOW = credits.MOTION   # what a rendered motion graphic is filed and priced under
STATE_PAGE = 25          # leaves of a run's state the agent is given at a time
LIVE_EVERY = 1.0         # seconds between looks at what the agent's tools did while it works
# A proxy in front of the studio (the Cloudflare tunnel) closes a request that sends nothing for 100 seconds, and a
# local model can be quiet longer than that (loading, reading a long skill, waiting for the GPU). So a slow answer
# sends a sign of life every KEEP_ALIVE seconds; one that comes within PATIENT seconds is sent as it is.
RUN_STOPPED = "I stopped before I planned the next step (what I was thinking is above). Say “go” and I will carry on from there."
KEEP_ALIVE = 15
PATIENT = 20
SLASH = re.compile(r"(?:^|(?<=\s))/([a-z0-9][a-z0-9-]*)(?=\s|$)")   # a /skill-id standing on its own, anywhere in a message
RUN_ITEMS = 5000         # library items a long run's steps may name by id
MAX_SELECTION = 24       # attached items read with one message (a long skill takes a cast, props and places at once)
TEXT_OPENING = 400       # characters of an attached text shown with it, so it can be told for what it is
TEXT_PAGE = 6000         # characters of a document the agent reads at a time
FILM_WAIT = 900          # seconds the agent waits for one film operation (a long film joined, a retime) before giving up
# What the studio can do beside its workflows, for the check of a skill before it starts.
STUDIO_ABILITY = (
    "Editing: trim, split, join, sound on a video, the finished cut (assemble). Motion graphics and titles drawn in the studio. "
    "Frame-exact film operations on this machine, free, as the agent's \"film\" tool: a reference image at 1500 px, a slice of an "
    "audio by frames, a timing track video of blocks, a clip trimmed or stretched to an exact frame count, a clip retimed so lips meet "
    "the master's words, proof sheets, subtitles burned in (house style), clips joined on the master audio, and the spans where speech "
    "is heard in a voice track. A run state store (state_read, state_write, state_check) kept per conversation, written a leaf or a "
    "whole folder at a time. Reading a transcript (a transcription workflow's JSON, or an .srt the user uploads) into the state with "
    "its times exact, and working out every shot's frames from it (transcript, timing). Bringing pictures, clips and sounds in from "
    "links on other sites (import_url). Reading a script or document the user attached (read_text; Word files arrive as "
    "their text). Questions to the user with two to four buttons; tables of pictures in a reply. A run goes on "
    "by itself when its steps are made, and may have a budget the user sets. A permission under the Agent box lets plans run "
    "without waiting for Approve. Looking at pictures and "
    "clips, reviewing results, remembering assets. Not here: running other programs or scripts, other models than the workflows listed.")


def _project_id(request, user, project):
    """0 stands for "no project"; any other id must be one of the user's projects."""
    if not project:
        return 0
    row = request.app.state.db.one("SELECT id FROM projects WHERE id = ? AND user_id = ?", (project, user["id"]))
    if row is None:
        raise HTTPException(404, "No such project.")
    return row["id"]


@router.get("/boards/{kind}")
async def get_board(kind: str, request: Request, project: int = 0, user: dict = Depends(current_user)):
    """The saved canvas layout or timeline of one project (or of the items in no project)."""
    _board_kind(kind)
    row = request.app.state.db.one("SELECT data FROM boards WHERE user_id = ? AND project_id = ? AND kind = ?",
                                   (user["id"], _project_id(request, user, project), kind))
    return {"data": json.loads(row["data"]) if row else {}}


@router.put("/boards/{kind}")
async def save_board(kind: str, body: dict, request: Request, user: dict = Depends(current_user)):
    _board_kind(kind)
    data = json.dumps(body.get("data") or {})
    if len(data) > MAX_BOARD_BYTES:
        raise HTTPException(400, "This is too large to save.")
    request.app.state.db.run(
        "INSERT INTO boards (user_id, project_id, kind, data, updated) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, project_id, kind) DO UPDATE SET data = excluded.data, updated = excluded.updated",
        (user["id"], _project_id(request, user, body.get("project")), kind, data, time.time()))
    return {"ok": True}


@router.delete("/boards/{kind}")
async def delete_board(kind: str, request: Request, project: int = 0, user: dict = Depends(current_user)):
    """Forget the conversation of an agent tab the user deleted. Other boards are not deleted this way."""
    if not AGENT_TAB.match(kind):
        raise HTTPException(404, "No such board.")
    request.app.state.db.run("DELETE FROM boards WHERE user_id = ? AND project_id = ? AND kind = ?",
                             (user["id"], _project_id(request, user, project), kind))
    return {"ok": True}


@router.post("/timeline/export")
async def export_timeline(body: dict, request: Request, user: dict = Depends(current_user)):
    """Queue a job that joins the timeline's clips into one video for the library. Costs no credits: it needs no GPU."""
    state = request.app.state
    clips = body.get("clips") or []
    if not isinstance(clips, list) or not all(isinstance(clip, dict) for clip in clips):
        raise HTTPException(400, "The timeline's clips are not in the expected form.")
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise HTTPException(400, "Put between 1 and {} clips on the timeline.".format(MAX_CLIPS))
    project_id = _project_id(request, user, body.get("project_id")) or None
    parts = []
    for clip in clips:
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'",
                           (clip.get("id"), user["id"]))
        if row is None:
            raise HTTPException(404, "A clip on the timeline is no longer in your library.")
        if not (state.outputs.folder(user["id"]) / row["filename"]).is_file():
            raise HTTPException(404, "The file of {} is missing from storage.".format(row["name"]))
        try:
            parts.append({"id": row["id"], "start": float(clip.get("start") or 0), "end": float(clip.get("end") or 0)})
        except (TypeError, ValueError):
            raise HTTPException(400, "The start and end of {} must be numbers.".format(row["name"]))
    # The item an edit was cut from, if the caller names one of the clips: the canvas puts the result on its row.
    parent = body.get("parent") if body.get("parent") in [part["id"] for part in parts] else None
    name = str(body.get("name") or "").strip()[:80] or "Timeline"
    job_id = state.jobs.add(user["id"], name, edits.TIMELINE, {"workflow_title": "Timeline export", "clips": parts, "parent": parent},
                            "1 clip joined" if len(parts) == 1 else "{} clips joined".format(len(parts)), None, 0, project_id)
    return {"job": job_id, "name": name}


@router.post("/edit/assemble")
async def assemble(body: dict, request: Request, user: dict = Depends(current_user)):
    """Queue the finished cut: the clips in order, a title card and an end card, music under it. Costs no credits.
    Body: {"name"?, "clips": [{"id", "start"?, "end"?}], "music"?: audio item id, "title"?, "end"?: {"heading", "text"},
    "look"?, "shape"?, "project_id"?}."""
    state = request.app.state
    clips = body.get("clips") if isinstance(body.get("clips"), list) else []
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise HTTPException(400, "Put between 1 and {} clips in the cut.".format(MAX_CLIPS))
    folder = state.outputs.folder(user["id"])
    parts = []
    for clip in clips:
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'", (clip.get("id") if isinstance(clip, dict) else None, user["id"]))
        if row is None or not (folder / row["filename"]).is_file():
            raise HTTPException(404, "A shot of the cut is no longer in your library.")
        try:
            parts.append({"id": row["id"], "start": float(clip.get("start") or 0), "end": float(clip.get("end") or 0)})
        except (TypeError, ValueError):
            raise HTTPException(400, "The start and end of {} must be numbers.".format(row["name"]))
    music = None
    if body.get("music"):
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'audio'", (body["music"], user["id"]))
        if row is None or not (folder / row["filename"]).is_file():
            raise HTTPException(404, "The music of the cut is no longer in your library.")
        music = row["id"]

    def card(kind):
        given = body.get(kind) if isinstance(body.get(kind), dict) else None
        scenes = sequence.clean_scenes([{"kind": kind, "heading": given.get("heading"), "text": given.get("text"), "seconds": given.get("seconds") or None}]) if given else []
        return scenes[0] if scenes else None

    settings = {"workflow_title": "Final cut", "clips": parts, "music": music, "title": card("title"), "end": card("end"),
                "look": body.get("look") if body.get("look") in sequence.LOOKS else "dark",
                "shape": body.get("shape") if body.get("shape") in agent.ORIENTATIONS else "landscape", "parent": parts[0]["id"]}
    name = " ".join(str(body.get("name") or "").split())[:80] or "Final cut"
    facts = "{} {}{}{}{}".format(len(parts), "shot" if len(parts) == 1 else "shots", " · title card" if settings["title"] else "",
                                 " · music" if music else "", " · end card" if settings["end"] else "")
    project_id = _project_id(request, user, body.get("project_id")) or None
    return {"job": state.jobs.add(user["id"], name, edits.ASSEMBLE, settings, facts, None, 0, project_id), "name": name}


@router.post("/edit/sound")
async def add_sound(body: dict, request: Request, user: dict = Depends(current_user)):
    """Queue a job that puts one of the user's sounds on one of their videos, for the library. Costs no credits."""
    state = request.app.state
    rows = {}
    for key, kind, what in (("video", "video", "a video"), ("audio", "audio", "a sound")):
        rows[key] = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = ?", (body.get(key), user["id"], kind))
        if rows[key] is None:
            raise HTTPException(400, "Choose {} from your library.".format(what))
    folder = state.outputs.folder(user["id"])
    if not (folder / rows["video"]["filename"]).is_file() or not (folder / rows["audio"]["filename"]).is_file():
        raise HTTPException(404, "A file is missing from storage.")
    replace = body.get("replace") is True
    project_id = _project_id(request, user, body.get("project_id")) or rows["video"]["project_id"]
    name = (" ".join(str(body.get("name") or "").split()) or "{} with sound".format(rows["video"]["name"]))[:80]
    job_id = state.jobs.add(
        user["id"], name, edits.SOUND,
        {"workflow_title": "Sound added", "video": rows["video"]["id"], "audio": rows["audio"]["id"], "replace": replace,
         "prompt": json.loads(rows["video"]["settings"]).get("prompt", ""), "parent": rows["video"]["id"]},
        "{} {} {}".format(rows["audio"]["name"], "in place of the sound of" if replace else "under", rows["video"]["name"]), None, 0, project_id)
    return {"job": job_id, "name": name}


# ---------------------------------------------------------------- the cast of a project

@router.get("/cast")
async def get_cast(request: Request, project: int = 0, workflow: str = "", user: dict = Depends(current_user)):
    """The always-on entries of a project's kit (what the cast was), and, for a workflow, which of its reference slots
    they fill: [{"asset", "name", "slot", "label", "kind", "role", "item_kind", "said_as"}]."""
    state = request.app.state
    on = kit.always(state.db, user["id"], _project_id(request, user, project) or None)
    found = {"always": [memory.kit_row(e) for e in on], "fills": []}
    if workflow and on:
        found["fills"] = kit.fills(workflows.describe(await state.catalog.load(workflow)), on)
    return found


# ---------------------------------------------------------------- motion graphics

@router.get("/motion/templates")
async def motion_templates(request: Request, user: dict = Depends(current_user)):
    """The motion templates and whether this machine can render them."""
    return {**motion.status(request.app.state.settings.node_path), "templates": motion.templates()}


@router.post("/motion/scenes")
async def motion_scenes(body: dict, request: Request, user: dict = Depends(current_user)):
    return await _patient(_motion_scenes(body, request, user))


async def _motion_scenes(body, request, user):
    """Have the agent's model write a whole motion graphics video as scenes, from what it is about. Nothing is
    rendered: the scenes go back to the form, where they can be changed before Render."""
    about = str(body.get("about") or "").strip()[:2000]
    if not about:
        raise HTTPException(400, "Say what the video is about first.")
    project = _project_id(request, user, body.get("project_id"))
    written = await request.app.state.agent.write_scenes(about, **_model(body))
    try:
        written["scenes"] = sequence.clean_scenes(written["scenes"])
    except sequence.SequenceError:
        raise HTTPException(400, "The model wrote no scenes. Try again, or add the scenes yourself.")
    return written


async def _motion_price(state, user, body):
    """(seconds, credits) of the motion graphic this body asks for: it is priced by its length, at one rate when it
    is drawn on its own and at a lower one when it is laid over a video the user has. Refuses, as the render would,
    a body that cannot be rendered."""
    seconds, priced_as = await _motion_seconds(state, user, body)
    return seconds, state.credits.cost(priced_as, seconds)


async def _motion_seconds(state, user, body):
    if "scenes" in body:
        return sum(scene["seconds"] for scene in sequence.clean_scenes(body.get("scenes"))), MOTION_WORKFLOW
    template = next((t for t in motion.templates() if t["id"] == body.get("template")), None)
    if template is None:
        raise HTTPException(404, "There is no such motion template.")
    values = motion.clean(template, body.get("values") if isinstance(body.get("values"), dict) else {})
    if template["needs"] != "video":
        return float(values.get("seconds", 5)), MOTION_WORKFLOW
    row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'", (body.get("source"), user["id"]))
    if row is None:
        raise HTTPException(400, "Select a video on the canvas first: {} is laid over a video.".format(template["title"].lower()))
    source = state.outputs.folder(user["id"]) / row["filename"]
    if not source.is_file():
        raise HTTPException(404, "The file of {} is missing from storage.".format(row["name"]))
    return (await media.probe(source))["seconds"], credits.OVERLAY


@router.post("/motion/estimate")
async def motion_estimate(body: dict, request: Request, user: dict = Depends(current_user)):
    """What a motion graphic would cost. Nothing is rendered or charged."""
    state = request.app.state
    seconds, cost = await _motion_price(state, user, body)
    return {"seconds": round(seconds, 1), "credits": cost, "balance": state.credits.balance(user["id"])}


@router.post("/motion/render")
async def motion_render(body: dict, request: Request, user: dict = Depends(current_user)):
    """Queue the render of a motion graphic for the library. It is charged by its length now, and the queue gives
    the credits back if the render fails or is cancelled."""
    state = request.app.state
    seconds, cost = await _motion_price(state, user, body)   # refuses what can't be rendered
    project_id = _project_id(request, user, body.get("project_id")) or None
    if "scenes" in body:   # a video made of scenes of words, as the agent plans them
        scenes = sequence.clean_scenes(body.get("scenes"))
        words = [scene["heading"] or scene["text"] for scene in scenes]
        name = (" ".join(str(body.get("name") or "").split()) or words[0])[:80]
        settings = {"workflow_title": "Motion graphics", "scenes": scenes,
                    "look": body.get("look") if body.get("look") in sequence.LOOKS else "dark",
                    "shape": body.get("shape") if body.get("shape") in motion.SHAPES else "landscape",
                    "prompt": " / ".join(words)[:600], "parent": None}
        summary = "Motion graphics · {}".format("1 scene" if len(scenes) == 1 else "{} scenes".format(len(scenes)))
    else:                  # one of the templates, on its own or over a video
        template = next(t for t in motion.templates() if t["id"] == body.get("template"))
        values = motion.clean(template, body.get("values") if isinstance(body.get("values"), dict) else {})
        row = state.db.one("SELECT id, name FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'",
                           (body.get("source"), user["id"])) if template["needs"] == "video" else None
        name = (values.get("title") or template["title"])[:80]
        settings = {"workflow_title": "Motion graphics · " + template["title"], "template": template["id"], "values": values,
                    "prompt": " · ".join(str(values[key]) for key in ("title", "subtitle") if values.get(key)),
                    "parent": row["id"] if row else None}
        summary = template["title"] + (" over " + row["name"] if row else "")
    over = state.credits.cap_problem(user["id"], cost)
    if over:
        raise HTTPException(429, over)
    if not state.credits.charge(user["id"], cost, "generation", note="Motion graphics"):
        raise HTTPException(402, "This needs {} credits and you have {}. Ask an admin for more.".format(cost, state.credits.balance(user["id"])))
    job_id = state.jobs.add(user["id"], name, MOTION_WORKFLOW, settings, summary, None, cost, project_id, seconds)
    return {"job": job_id, "name": name, "credits": cost}


# ---------------------------------------------------------------- agent

@router.get("/agent/status")
async def agent_status(request: Request, user: dict = Depends(agent_user)):
    try:
        # "model" is the one used when the user has not picked another; "models" is what they can pick from.
        brain = request.app.state.agent
        models = await brain.models()
        prices = request.app.state.credits.llm_prices()
        return {"online": True, "model": await brain.pick_model(), "models": models, "hosted": brain.hosted(),
                "prices": {m: prices[m] for m in models if m in prices}}   # credits per message; a model not listed is free
    except agent.AgentError as error:
        return {"online": False, "detail": str(error)}


def _model(body):
    """The model the user picked in the agent panel, as a keyword for the agent's calls; nothing when they picked none."""
    picked = body.get("model")
    return {"model": picked[:120]} if isinstance(picked, str) and picked.strip() else {}



# ---------------------------------------------------------------- shared memory

@router.get("/memory")
async def get_memory(request: Request, project: int = 0, user: dict = Depends(current_user)):
    """A project's kit, as the panel of before read it ({"assets": the kit's entries, "uploads": []}); the kit's own
    endpoints are /api/kit. For a user who has the agent, its model first looks at a few pictures it has not described."""
    state = request.app.state
    project = _project_id(request, user, project)
    if user["agent"]:
        await memory.describe_missing(state, user["id"], memory.book(state.db, user["id"], project or None), limit=6)
    found = memory.panel(state.db, user["id"], project or None)
    found["skills"] = [{"id": s["id"], "title": s["title"], "version": s["version"]} for s in skills.load()]
    return found


@router.get("/skills")
async def list_skills(user: dict = Depends(current_user)):
    """Every skill the agent can use, with its recipe, for the Skills section. Read-only: skills are files on the server.

    A skill is triggered on its own when the message matches it, or by the user with /<id> at the start of a message."""
    return {"skills": [{"id": s["id"], "title": s["title"], "version": s["version"], "desc": s["desc"],
                        "text": s["text"], "words": s["words"].pattern} for s in skills.load()]}


# ---------------------------------------------------------------- review

@router.post("/agent/review")
async def agent_review(body: dict, request: Request, user: dict = Depends(agent_user)):
    with gpu.politely():   # a check waits for the renders still queued, so the GPU does not swap models between them
        return await _patient(_agent_review(body, request, user))


async def _agent_review(body, request, user):
    """Have the agent look at a picture or clip it made and check it against its prompt, its reference pictures and
    the shot before. Body: {"item", "prompt"?, "uses"?: [{"id"} or {"asset"}], "previous"?: item id, "retake"?: bool}.
    Returns {"verdict", "retake"}: a failed result comes with a retake, priced but not queued, unless "retake" is false.
    Nothing is charged: a retake is queued only when the user approves it."""
    state = request.app.state
    own = lambda item_id: state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))         if isinstance(item_id, int) else None
    item = own(body.get("item"))
    if item is None:
        raise HTTPException(404, "No such item.")
    references = []
    for use in (body.get("uses") or [])[:review.MAX_REFERENCES * 2] if isinstance(body.get("uses"), list) else []:
        if not isinstance(use, dict):
            continue
        if isinstance(use.get("asset"), int) and use["asset"]:
            row = state.db.one("SELECT name, kind, filename FROM assets WHERE id = ? AND user_id = ?", (use["asset"], user["id"]))
            path = row and state.assets_dir / str(user["id"]) / row["filename"]
        else:
            row = own(use.get("id"))
            path = row and state.outputs.folder(user["id"]) / row["filename"]
        if row and row["kind"] in ("image", "video"):
            references.append((row["name"], path))
    if not references and item["project_id"]:   # checked on its own: the project's always-on kit is what it should look like
        for e in kit.always(state.db, user["id"], item["project_id"]):
            path = state.assets_dir / str(user["id"]) / e["filename"]
            if e["kind"] in ("image", "video") and e["made_from"] != item["id"] and path.is_file():
                references.append((e["name"], path))
    before = own(body.get("previous"))
    previous = (state.outputs.folder(user["id"]) / before["filename"], before["kind"]) if before and before["kind"] in ("image", "video") else None
    try:
        verdict = await review.review_item(state, user["id"], item, str(body.get("prompt") or "")[:4000], references, previous)
    except (review.ReviewError, agent.AgentError) as error:
        raise HTTPException(400, str(error))
    retake = await _retake(state, user, item, verdict, before) if body.get("retake", True) and not verdict["passed"] else None
    return {"verdict": verdict, "retake": retake}


async def _retake(state, user, item, verdict, previous):
    """The job settings of a retake of a failed item: the same workflow and settings with the fixed prompt and a new
    seed, priced. None when the item was not made by a workflow with a prompt, or the review gave no new prompt."""
    fix = verdict.get("fix") or {}
    if not fix.get("prompt"):
        return None
    try:
        wf = await state.catalog.load(item["workflow"])
        schema = workflows.describe(wf)
    except (workflows.WorkflowError, HTTPException):
        return None
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    if "prompt" not in roles:
        return None
    settings = json.loads(item["settings"] or "{}")
    settings["values"] = dict(settings.get("values") or {}, **{roles["prompt"]["id"]: fix["prompt"]})
    settings.update(workflow=schema["id"], seed_mode="random", parent=item["id"], project_id=item["project_id"],
                    name=(item["name"] + " · retake")[:80])
    shot = settings.get("shot")
    if isinstance(shot, dict) and shot.get("id"):
        settings["shot"] = {"id": shot["id"], "take": int(shot.get("take") or 1) + 1}
    start = None
    first_frame = (schema.get("slots") or {}).get("first_frame")
    if fix.get("start_from_previous") and previous and first_frame:
        start = {"id": previous["id"], "name": previous["name"], "slot": first_frame}   # the browser fills the slot on Approve
    try:
        quote = await price(state, wf, settings, user["id"])
    except (workflows.WorkflowError, HTTPException, ValueError, KeyError):
        return None
    return {"settings": settings, "credits": quote["credits"], "time": quote["text"], "prompt": fix["prompt"],
            "why": fix.get("why") or "", "start": start, "workflow_title": schema["title"]}


@router.post("/agent/improve")
async def agent_improve(body: dict, request: Request, user: dict = Depends(current_user)):
    return await _patient(_agent_improve(body, request, user))


async def _agent_improve(body, request, user):
    """Have the agent rewrite a prompt into a fuller one. Nothing is queued or charged."""
    prompt = str(body.get("prompt") or "").strip()[:2000]
    if not prompt:
        raise HTTPException(400, "Write a prompt first, then improve it.")
    kind = body.get("kind") if body.get("kind") in agent.IMPROVE_KINDS else "video"
    project = _project_id(request, user, body.get("project_id"))
    state = request.app.state
    # The chosen workflow's own prompting tips, and the cast when that workflow has slots for it.
    tips, pinned = [], []
    if body.get("workflow"):
        try:
            schema = workflows.describe(await state.catalog.load(str(body["workflow"])))
            tips = schema["hints"]
            full = kit.always(state.db, user["id"], project or None)
            filled = {f["asset"] for f in kit.fills(schema, full)}
            pinned = [e for e in full if e["id"] in filled]
        except (workflows.WorkflowError, HTTPException):
            pass
    return {"prompt": await state.agent.improve(prompt, kind, tips=tips, project_cast=pinned,
                                                structure=agent.PROMPT_STRUCTURE if kind != "audio" else "", **_model(body))}



@router.post("/agent/compact")
async def agent_compact(body: dict, request: Request, user: dict = Depends(current_user)):
    return await _patient(_agent_compact(body, request, user))


async def _agent_compact(body, request, user):
    """Fold a conversation into the Direction, the durable notes the agent reads in place of old turns.
    Body: {"history": [...as for plan], "direction"?: the notes so far}. Returns {"direction"}. Nothing is queued."""
    turns = agent.past_turns(body.get("history"))
    if not turns and not body.get("direction"):
        raise HTTPException(400, "There is nothing to fold yet.")
    try:
        text = await request.app.state.agent.compact(turns, str(body.get("direction") or ""), **_model(body))
    except agent.AgentError as e:
        raise HTTPException(502, str(e))
    return {"direction": text}


STILL_WORKFLOWS = ("z_image", "sdxl")   # cheap picture workflows, in the order the storyboard prefers them


async def _still_workflow(state):
    """The workflow that draws a storyboard still: a cheap picture workflow that is switched on. None when there is none."""
    found = [w for w in await state.catalog.listing() if w["kind"] == "image" and not w.get("error") and state.credits.enabled(w["id"])]
    for word in STILL_WORKFLOWS:
        for w in found:
            if word in w["id"]:
                return w["id"]
    return found[0]["id"] if found else None


def _proposals(shots):
    """The shots of a staged plan as sent by the browser: [(shot id, the model's proposal for it, the shot)], the usable ones."""
    out = []
    for shot in (shots if isinstance(shots, list) else [])[:agent.MAX_STEPS]:
        proposal = shot.get("proposal") if isinstance(shot, dict) else None
        ident = memory.clean_shot({"id": shot.get("shot_id")}) if isinstance(shot, dict) else None
        if isinstance(proposal, dict) and ident and proposal.get("tool", "generate") == "generate" \
                and str(proposal.get("workflow") or "").startswith("video/"):
            out.append((ident["id"], proposal, shot))
    return out


def _as_shot(step, shot_id):
    step["shot_id"] = shot_id
    step["settings"]["shot"] = {"id": shot_id, "take": 1}
    return step


@router.post("/agent/storyboard")
async def agent_storyboard(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Stage one of a long film: a cheap still for each planned video shot, to look at before any clip is made.
    Body: {"shots": [{"shot_id", "proposal"}], "project_id"?}. Returns {"steps": [...], "dropped": [...], "total"};
    nothing is queued or charged: the browser queues the stills on Approve, as for any plan."""
    state = request.app.state
    project = _project_id(request, user, body.get("project_id"))
    wanted = _proposals(body.get("shots"))
    if not wanted:
        raise HTTPException(400, "There are no video shots to draw first.")
    still = await _still_workflow(state)
    if not still:
        raise HTTPException(400, "No picture workflow is switched on to draw the stills with.")
    schemas = {still: workflows.describe(await state.catalog.load(still))}
    pinned, menu = kit.always(state.db, user["id"], project or None), await _menu(state)
    steps, dropped = [], []
    for shot_id, proposal, _ in wanted:
        card = {key: proposal.get(key) for key in ("prompt", "orientation", "shot_size", "angle", "end_state")}
        card.update(tool="generate", workflow=still, name="Still · " + str(proposal.get("name") or "shot")[:70])
        before = len(steps)
        reason = await _plan_step(state, card, "", steps, {}, schemas, {}, {}, [], pinned, project or None, {}, [], menu)
        if len(steps) == before:
            dropped.append((proposal.get("name") or "a shot", reason or "it could not be drawn"))
            continue
        _as_shot(steps[-1], shot_id)
        steps[-1].update(stage="still", proposal=proposal)   # the video proposal travels with the still, to animate it later
    return {"steps": steps, "dropped": dropped, "total": sum(s["credits"] for s in steps)}


@router.post("/agent/animate")
async def agent_animate(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Stage two: each approved still becomes the first frame of its clip. Body: {"shots": [{"shot_id", "item", "proposal"}],
    "project_id"?}, item being the library id of the still. Returns {"steps", "dropped", "total"}, not queued."""
    state = request.app.state
    project = _project_id(request, user, body.get("project_id"))
    steps, dropped, names, kinds, shapes, schemas, wanted = [], [], {}, {}, {}, {}, []
    for shot_id, proposal, shot in _proposals(body.get("shots")):
        row = state.db.one("SELECT id, name, kind, context FROM generations WHERE id = ? AND user_id = ?", (shot.get("item"), user["id"])) \
            if isinstance(shot.get("item"), int) else None
        if row is None or row["kind"] != "image":
            dropped.append((proposal.get("name") or "a shot", "its still is not there"))
            continue
        made = json.loads(row["context"] or "{}")
        names[row["id"]], kinds[row["id"]] = row["name"], {"name": row["name"], "kind": "image"}
        if made.get("width") and made.get("height"):
            shapes[row["id"]] = [made["width"], made["height"]]
        wanted.append((shot_id, proposal, row["id"]))
        if proposal["workflow"] not in schemas:
            try:
                schemas[proposal["workflow"]] = workflows.describe(await state.catalog.load(proposal["workflow"]))
            except (workflows.WorkflowError, HTTPException):
                pass
    pinned, menu = kit.always(state.db, user["id"], project or None), await _menu(state)
    for shot_id, proposal, item in wanted:
        before = len(steps)
        reason = await _plan_step(state, dict(proposal, start_from=item, after=0, uses=[]), "", steps, {}, schemas, names, kinds, [],
                                  pinned, project or None, shapes, [], menu)
        if len(steps) == before:
            dropped.append((proposal.get("name") or "a shot", reason or "it could not be planned"))
            continue
        _as_shot(steps[-1], shot_id)
    return {"steps": steps, "dropped": dropped, "total": sum(s["credits"] for s in steps)}


@router.post("/agent/reroll")
async def agent_reroll(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Another take of a finished shot: the same prompt and settings with a new seed, priced and not queued.
    Body: {"item", "prompt"?}. Returns {"retake"}, as the review does for a failed shot."""
    state = request.app.state
    item = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?", (body.get("item"), user["id"])) \
        if isinstance(body.get("item"), int) else None
    if item is None:
        raise HTTPException(404, "No such item.")
    try:
        schema = workflows.describe(await state.catalog.load(item["workflow"]))
    except (workflows.WorkflowError, HTTPException):
        raise HTTPException(400, "The workflow that made this is gone.")
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    made_with = (json.loads(item["settings"] or "{}").get("values") or {}).get((roles.get("prompt") or {}).get("id"))
    prompt = str(body.get("prompt") or "").strip() or str(made_with or "")
    retake = await _retake(state, user, item, {"fix": {"prompt": prompt, "why": "Another take of the same shot."}}, None) if prompt else None
    if retake is None:
        raise HTTPException(400, "This one cannot be made again.")
    return {"retake": retake}


async def _menu(state):
    """The workflows an approval card can switch a step to: every readable one that is switched on."""
    return [{"id": w["id"], "title": w["title"], "kind": w["kind"]} for w in await state.catalog.listing()
            if w["kind"] in ("video", "image", "audio") and not w.get("error") and state.credits.enabled(w["id"])]


@router.post("/agent/step")
async def agent_step(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Change one step of a plan on its approval card: the workflow, the shape, the size, the length or the prompt.
    The step is built again with the same checks as a planned one and priced. Nothing is queued or charged."""
    state = request.app.state
    step, change = body.get("step") or {}, body.get("change") or {}
    old = step.get("settings") if isinstance(step, dict) else None
    if not isinstance(old, dict) or not old.get("workflow") or not isinstance(change, dict):
        raise HTTPException(400, "Only a generation can be changed here.")
    project = _project_id(request, user, old.get("project_id"))
    try:
        old_schema = workflows.describe(await state.catalog.load(str(old["workflow"])))
        schema = workflows.describe(await state.catalog.load(str(change.get("workflow") or old["workflow"])))
    except workflows.WorkflowError as e:
        raise HTTPException(400, str(e))
    if schema["id"].split("/", 1)[0] != old_schema["id"].split("/", 1)[0]:
        raise HTTPException(400, "A step can only change to a workflow that makes the same kind of thing.")
    if not state.credits.enabled(schema["id"]):
        raise HTTPException(400, "This workflow is switched off for now.")
    try:
        ctx = workflows.context(old_schema, old)
    except workflows.WorkflowError as e:
        raise HTTPException(400, str(e))
    roles = {c["role"]: c for c in old_schema["controls"] if c["role"]}
    if isinstance(change.get("prompt"), str):
        prompt = change["prompt"]
    else:   # a workflow with no prompt (a transcription, a voice separation) has none to keep
        prompt = (old.get("values") or {}).get(roles["prompt"]["id"], "") if "prompt" in roles else ""
    # The step as the model would have proposed it, with the change made: settings_for keeps what the workflow takes.
    proposed = {"prompt": str(prompt).strip(), "name": old.get("name"), "clips": old.get("clips", 1),
                "duration": float(change.get("duration") or ctx.get("duration") or 0),   # a clip timed to its frames keeps its decimals
                "resolution": int(change.get("resolution") or ctx.get("resolution") or 0),
                "orientation": change.get("orientation") or _orientation(old_schema, old, ctx)}
    if not proposed["prompt"]:
        raise HTTPException(400, "The prompt is empty.")
    same = schema["id"] == old_schema["id"]
    first_frame = (schema.get("slots") or {}).get("first_frame")
    start, after = step.get("start"), step.get("after")
    if (start or after) and not first_frame:
        raise HTTPException(400, "{} can't start on a picture, and this shot starts on one.".format(schema["title"]))
    slots = {r["id"] for r in schema["refs"]}
    uses = [u for u in step.get("uses") or [] if isinstance(u, dict) and u.get("slot") in slots and not u.get("cast")]
    if start:
        proposed["start_from"] = start.get("id")
    built = agent.settings_for(schema, proposed, {start.get("id")} if start else set(), project or None,
                               {u["slot"] for u in uses}, {u["id"] for u in uses if u.get("id")}, bool(after))
    if not built:
        raise HTTPException(400, "{} needs reference files this step doesn't have.".format(schema["title"]))
    settings, started = built
    keep = memory.clean_keep(old.get("keep"), schema["id"].split("/", 1)[0])
    if keep:   # a step changed on its card is still kept in shared memory
        settings["keep"] = keep
    if same:   # the workflow's own choices (mode, speed, quality) and other settings stay as they were
        known = {o["id"]: [c["id"] for c in o["choices"]] for o in schema["options"]}
        settings["options"].update({k: v for k, v in (old.get("options") or {}).items() if v in known.get(k, [])})
        kept = {c["id"] for c in schema["controls"] if not c["role"]}
        settings["values"].update({k: v for k, v in (old.get("values") or {}).items() if k in kept})
    if not change.get("orientation") and step.get("shape") and (start or after):
        agent.shape_like(schema, settings, step["shape"])   # a shot that starts on a picture keeps that picture's shape
    elif change.get("orientation") and not schema.get("size"):
        agent.shape_like(schema, settings, {"landscape": (16, 9), "portrait": (9, 16), "square": (1, 1)}.get(change["orientation"]))
    pinned = kit.always(state.db, user["id"], project or None)
    uses = uses + [dict(fill, cast=True) for fill in kit.fills(
        schema, pinned, {u["slot"] for u in uses}, {u["asset"] for u in uses if u.get("asset")}, step.get("leave_out") or (),
        {u["id"] for u in uses if u.get("id")} | ({started} if started else set()))]
    try:
        return await _shown_step(state, schema, settings, await _menu(state), uses,
                                 dict(start, slot=first_frame) if start else None,
                                 dict(after, slot=first_frame) if after else None, step.get("why") or "")
    except workflows.WorkflowError as e:
        raise HTTPException(400, str(e))


@router.post("/agent/plan")
async def agent_plan(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Ask the agent for a plan. Each step comes back as checked, priced job settings; nothing is queued or charged.

    Asked with "Accept: application/x-ndjson", it answers as it works: one JSON line per thing it does ("status" while
    it is busy, "activity" and "thought" for its log), then the plan ({"type": "plan", ...}) or {"type": "error"}.
    Otherwise it answers once, with the plan and its log."""
    instruction = str(body.get("instruction") or "").strip()[:2000]
    if not instruction:
        raise HTTPException(400, "Write a message for the agent.")
    project = _project_id(request, user, body.get("project_id"))
    events = _holding_gpu(request, body, _planning(request, user, body, instruction, project))
    if "application/x-ndjson" in request.headers.get("accept", ""):
        async def lines():
            try:
                async for event in events:
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except Exception as error:   # the stream has started: the error goes in it, not in the status code
                detail = getattr(error, "detail", None) or str(error) or "The agent stopped. Try again."
                yield json.dumps({"type": "error", "message": str(detail)}, ensure_ascii=False) + "\n"
        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    plan = None
    async for event in events:
        if event["type"] == "plan":
            plan = event
    return {k: v for k, v in plan.items() if k != "type"}


async def _patient(work):
    """The answer of `work` (a coroutine that gives a dict). One that comes within PATIENT seconds is sent as it is,
    errors with their status. A slower one is sent as a space every KEEP_ALIVE seconds and then the answer (JSON allows
    spaces before it); the status is sent by then, so an error comes as {"detail", "failed": its status}."""
    task = asyncio.ensure_future(work)
    done, _ = await asyncio.wait([task], timeout=PATIENT)
    if done:
        return task.result()

    async def slowly():
        try:
            while not task.done():
                done, _ = await asyncio.wait([task], timeout=KEEP_ALIVE)
                if not done:
                    yield b" "
            try:
                answer = task.result()
            except HTTPException as error:
                answer = {"detail": error.detail, "failed": error.status_code}
            except Exception as error:   # the status is sent already: the error goes in the answer
                answer = {"detail": str(error) or type(error).__name__, "failed": 500}
            yield json.dumps(answer, ensure_ascii=False).encode("utf-8")
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(slowly(), media_type="application/json", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def _holding_gpu(request, body, events):
    """The events of a plan, with signs of life ({"type": "ping"}) while nothing happens for KEEP_ALIVE seconds, and
    the GPU held for the whole message when a local model answers on a GPU the renders share: its calls come one after
    another, and a render between two of them would make it load its model again.

    The plan runs in a task of its own that holds the GPU, so the calls inside it know they hold it; this generator
    passes on what it does, and pings while it is quiet (waiting for a render, a model loading, a long call)."""
    state = request.app.state
    gate = getattr(state, "gpu", None)
    holds = gate is not None and state.agent.is_local(body.get("model") or state.agent.model)
    queue, end = asyncio.Queue(), object()

    async def work():
        try:
            if holds:
                async with gate.use("llm"):
                    async for event in events:
                        await queue.put(event)
            else:
                async for event in events:
                    await queue.put(event)
            await queue.put(end)
        except Exception as error:
            await queue.put(error)

    if holds and gate.busy()["side"] == "render":
        yield {"type": "status", "text": "Waiting for the render on the GPU to finish…"}
    task = asyncio.ensure_future(work())
    getter = None
    try:
        while True:
            getter = getter or asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait([getter], timeout=KEEP_ALIVE)
            if not done:
                yield {"type": "ping"}
                continue
            event, getter = getter.result(), None
            if event is end:
                return
            if isinstance(event, Exception):
                raise event
            yield event
    finally:
        for waiting in (getter, task):
            if waiting is not None and not waiting.done():
                waiting.cancel()


async def _planning(request, user, body, instruction, project):
    """The work behind a plan, as events: what the agent does, as it does it, and at the end the plan."""
    state = request.app.state
    started = time.monotonic()
    log = []   # what the user sees of the work afterwards: {"type": "activity" | "thought", ...}

    def logged(event):
        event["at"] = round(time.monotonic() - started, 1)
        log.append(event)
        return event

    def activity(icon, text):
        return logged({"type": "activity", "icon": icon, "text": text})

    def status(text):   # what it is doing right now; shown while it works, not kept
        return {"type": "status", "text": text}

    selection, shapes = [], {}   # shapes: item id -> [width, height], for shots that start on an item
    chosen = (body.get("selection") or [])[:MAX_SELECTION] if agent.points_at_selection(instruction) else []
    # A run that follows a long skill keeps every file attached to it: "go", and every message after the one the files
    # came with, still has them, whether or not the model saved them itself. The files of this message come first, so
    # the @1, @2 the user wrote are theirs; the earlier ones follow, in the order they were attached.
    run_id = body.get("run") if isinstance(body.get("run"), str) and runs.RUN.match(body["run"]) else ""
    tagged = len(chosen)   # the files the message's own @1, @2 … stand for
    if run_id and runs.kept_skill(state.db, user["id"], run_id):
        earlier = runs.kept_attached(state.db, user["id"], run_id)
        given = [i for i in body.get("selection") or [] if isinstance(i, int)]
        chosen = (given + [i for i in earlier if i not in given])[:MAX_SELECTION]
        tagged = len(given)
    for item_id in chosen:
        row = state.db.one("SELECT id, kind, name, filename, settings, context, about FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))
        if row:
            # The tag is what the user calls the item in the instruction: the first one attached is @1.
            selection.append({"tag": "@{}".format(len(selection) + 1), "id": row["id"], "kind": row["kind"], "name": row["name"],
                              "prompt": str(json.loads(row["settings"]).get("prompt") or "")[:300]})
            if row["about"]:   # what the agent's model saw in it, when it has looked
                selection[-1]["shows"] = row["about"]
            made = json.loads(row["context"] or "{}")
            if made.get("width") and made.get("height"):
                shapes[row["id"]] = [made["width"], made["height"]]
            path = state.outputs.folder(user["id"]) / row["filename"]
            if row["kind"] in ("video", "audio") and path.is_file():   # the length is what the editing tools cut by
                selection[-1]["seconds"] = round((await media.probe(path))["seconds"], 2)
            elif row["kind"] == "text" and path.is_file():   # a script or a document: how long it is, and how it begins
                words = path.read_text(encoding="utf-8-sig", errors="replace")
                selection[-1]["characters"] = len(words)
                selection[-1]["begins"] = " ".join(words[:TEXT_OPENING].split())
    if selection:
        yield activity("attach", "Read what you attached: " + ", ".join(s["name"] for s in selection))

    # What was made lately here, so "the music you just made" can be put on "this video" without attaching either.
    recent = [{"id": r["id"], "kind": r["kind"], "name": r["name"]} for r in state.db.all(
        "SELECT id, kind, name FROM generations WHERE user_id = ? AND run = '' AND " + ("project_id = ?" if project else "project_id IS NULL")
        + " ORDER BY created DESC LIMIT 8", (user["id"], project) if project else (user["id"],))]
    known = {s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}
    known.update({r["id"]: {"name": r["name"], "kind": r["kind"]} for r in recent if r["id"] not in known})

    # The user can name a skill with /<id> anywhere in the message (at its start, after the files they attached, at its
    # end), or the panel can pass skill ids; those are always used. The rest are picked by what the message says.
    forced = list(body.get("skills") or [])
    instruction = re.sub(r"(@\d+)(?=/)", lambda m: m.group(1) + " ", instruction)   # a command typed straight after an attached file (@1/skill)
    for match in reversed(list(SLASH.finditer(instruction))):
        if skills.find(match.group(1)):
            forced.insert(0, match.group(1))
            # the /command is an instruction to the agent, not shot text
            instruction = (instruction[:match.start()] + " " + instruction[match.end():]).strip()
    instruction = re.sub(r"[ \t]{2,}", " ", instruction)
    # A long run follows the skill its first message named until another is named: "go" and every message after it
    # carry on with that skill, rather than skills picked afresh from their words.
    carried = runs.kept_skill(state.db, user["id"], run_id) if run_id else None   # the skill this run follows already
    if run_id and not any(skills.find(f) for f in forced):
        kept = carried
        if kept and skills.find(kept):
            forced.append(kept)
            yield activity("skill", "Carried on with “{}”, the skill of this run".format(skills.find(kept)["title"]))
    picked = skills.pick(instruction, body.get("history"), force=forced)
    # A long skill the user named is the whole procedure: no other skill picked by the message's words goes beside it,
    # and the run keeps it for the messages that follow.
    if any(s["id"] in forced and len(s["text"]) > CHECKED_SKILL for s in picked):
        picked = [s for s in picked if s["id"] in forced]
        if run_id:
            runs.keep_skill(state.db, user["id"], run_id, next(s["id"] for s in picked if len(s["text"]) > CHECKED_SKILL))
            runs.keep_attached(state.db, user["id"], run_id, [s["id"] for s in selection])
    for skill in picked:
        yield activity("skill", "Read the skill “{}”".format(skill["title"]))
    # A long skill asks the user which models to use, so it is shown every one; and a model named anywhere in the
    # conversation (the message, its notes, the turns before) stays offered for the rest of it.
    long_skill = any(len(s["text"]) > CHECKED_SKILL for s in picked)
    said = " ".join([instruction, str(body.get("direction") or "")] + [
        "{} {}".format(t.get("instruction") or "", t.get("reply") or "") for t in (body.get("history") or [])[-agent.MAX_HISTORY:]
        if isinstance(t, dict)]).lower()

    schemas = {}
    default = state.catalog.current(state.settings.default_workflow)
    menu = await _menu(state)
    for listed in await state.catalog.listing():
        if listed.get("error") or not state.credits.enabled(listed["id"]):
            continue
        # Video is made with the default workflow, which has the cast's slots and the quality choices; the other video
        # workflows are for the Create page, and the agent uses one only when the conversation names it (or a long skill
        # has the user choose).
        if listed["kind"] == "video" and default.startswith("video/") and listed["id"] != default and not long_skill \
                and listed["title"].lower() not in said and listed["id"].lower() not in said:
            continue
        schemas[listed["id"]] = workflows.describe(await state.catalog.load(listed["id"]))
    # The pictures the user names in the message ("Maya - @3", "location - Bonfire Clearing - @10") are kept in the
    # project's kit under those names: every agent tab knows them from then on, by name and by id.
    folder, outputs = state.assets_dir / str(user["id"]), state.outputs.folder(user["id"])
    said_names = memory.named_in(instruction, selection[:tagged])
    named = memory.keep_named(state.db, folder, outputs, user["id"], said_names, project or None)
    if named:
        yield activity("book", "Kept in the kit: " + ", ".join("{} ({})".format(n["name"], n["type"]) for n in named))
    # A long run that starts with pictures nobody named keeps them too, without a name: the agent asks who they are.
    if run_id and long_skill and not carried:
        said_items = {n["item"] for n in said_names}
        unnamed = memory.keep_unnamed(state.db, folder, outputs, user["id"], project or None,
                                      [s["id"] for s in selection[:tagged] if s["kind"] == "image" and s["id"] not in said_items])
        if unnamed:
            yield activity("book", "Kept {} picture{} without a name in the kit".format(len(unnamed), "" if len(unnamed) == 1 else "s"))
    pinned = kit.always(state.db, user["id"], project or None)
    # The asset book: what the agent knows of the project by name. Pictures it has not looked at yet are described now.
    book = memory.book(state.db, user["id"], project, pinned)
    if book:
        yield activity("book", "Opened the asset book: {} {}".format(len(book), "entry" if len(book) == 1 else "entries"))
    yield status("Looking at new pictures…")
    looked = await memory.describe_missing(state, user["id"], book)
    if looked:
        yield activity("look", "Looked at {} new {}".format(looked, "picture" if looked == 1 else "pictures"))
    book_items, book_assets = memory.lookup(book)
    # A workflow that must be given reference files can run when something is attached or the book has a picture.
    can_fill = bool(selection) or any(entry["kind"] in ("image", "video") for entry in book)
    offers = [o for o in (agent.offer(schema, can_fill) for schema in schemas.values()) if o]
    if not offers:
        raise HTTPException(400, "There is no workflow the agent can use yet.")
    hears = agent.takes_sound(offers)   # the workflows that work on a sound file (separate a voice, transcribe)
    # A message costs what the chosen model costs: the user must have it before the model is asked.
    chosen_model = body.get("model") or state.agent.model or ""
    if state.credits.llm_prices():   # only worth asking which model answers when some model has a price
        try:
            chosen_model = await state.agent.pick_model(body.get("model"))
        except agent.AgentError:
            pass   # the model is asked below, and that says what is wrong
    price = state.credits.llm_cost(chosen_model)
    if price:
        if state.credits.balance(user["id"]) < price:
            raise HTTPException(400, "A message to {} costs {} cr, and you have {} cr.".format(chosen_model, price, state.credits.balance(user["id"])))
        problem = state.credits.cap_problem(user["id"], price)
        if problem:
            raise HTTPException(400, problem)
    charged = {"credits": 0, "model": chosen_model}
    # A skill is given whole when the model holds it; a longer one as its opening and a list of its parts, which the
    # model reads with read_skill as it comes to them. A skill is never cut, whatever its length or the model.
    room = state.agent.skill_room(chosen_model)
    limit = skills.MAX_CHARS if room is None else room
    for skill in picked:
        if len(skill["text"]) > limit:
            yield activity("skill", "“{}” is long ({:,} characters): the model reads its opening, and each of its {} parts as it "
                                    "comes to them".format(skill["title"], len(skill["text"]), len(skills.parts(skill["text"])) - 1))
    guides = skills.guide(picked, limit)
    # A long skill is read in parts with a tool and run with the studio's tools: a model that is not given tools (a local
    # one with local_tools off) cannot follow it, and the user is told so at once rather than getting a run that goes wrong.
    unread = next((s for s in picked if s["id"] in forced and len(s["text"]) > CHECKED_SKILL), None) \
        if not state.agent.uses_tools(chosen_model) else None
    if unread:
        said = ("“{}” runs in steps with the studio's tools, and local models are set to work without them. Turn local_tools on "
                "in config.json (or pick a hosted model in the menu under the box) and send the message again: your files stay "
                "attached.").format(unread["title"])
        yield activity("skip", "“{}” needs the studio's tools".format(unread["title"]))
        yield {"type": "plan", "reply": said, "thought": "", "activity": log, "seconds": round(time.monotonic() - started, 1), "chips": {},
               "direction": body.get("direction") or "", "steps": [], "total": 0, "llm": charged,
               "balance": state.credits.balance(user["id"])}
        return
    # A skill the user named, or a long one (they are written by people, and say what they need first), is checked before
    # anything is planned: what it requires that is not here, and what it names that this studio cannot do, is said at once.
    adaptation = ""
    for skill in picked:
        if not (skill["id"] in forced or len(skill["text"]) > CHECKED_SKILL):
            continue
        if skill["id"] == carried:
            continue   # checked when its run began: the run goes on, with what that message had
        yield status("Checking what the skill needs…")
        ability = "\n".join(["Workflows: " + "; ".join("{} ({})".format(o["id"], o.get("title") or o["id"]) for o in offers),
                             STUDIO_ABILITY])
        # What is attached, then what shared memory holds by name (characters, locations, props kept from any tab),
        # then how many other files the project has.
        kept = [e for e in book if "asset" in e]
        others = {}
        for e in book:
            if "asset" not in e:
                others[e["kind"]] = others.get(e["kind"], 0) + 1
        attached = "\n".join([attachment_line(s) for s in selection]
                             + ["in shared memory: {} ({} {})".format(e["name"], e.get("type") or "other", e["kind"]) for e in kept]
                             + ["in the project: {} {}".format(n, k) for k, n in sorted(others.items())]) if selection or book else ""
        try:
            verdict = await state.agent.preflight(skill, instruction, attached, ability, agent.past_turns(body.get("history")), **_model(body))
        except agent.AgentError:
            continue   # a check that cannot run is not a reason to refuse
        # What the check calls missing while the user attached a file of that kind (a sound for "the audio", a text for
        # "the script") is set aside: a model may doubt a file it cannot open, and a run blocked for nothing is worse than
        # one whose skill asks again at its first step.
        covered = [m for m in verdict["missing"] if attached_kind(m, selection)]
        if covered:
            verdict = dict(verdict, missing=[m for m in verdict["missing"] if m not in covered])
            yield activity("check", "Set aside what the check called missing but you attached: {}".format("; ".join(covered)))
            if not verdict["missing"] and not verdict["unsupported"]:
                verdict = dict(verdict, ready=True)
        if verdict["ready"]:
            adaptation = verdict["adaptation"] or adaptation
            continue
        written = verdict["message"] if not covered else ""   # its message was about the files: it no longer stands
        said = written or "Before I start “{}”, {}:\n{}".format(
            skill["title"], "I need" if verdict["missing"] else "this studio cannot do what it asks here",
            "\n".join("- " + m for m in verdict["missing"] or verdict["unsupported"]))
        yield activity("skip", "Checked “{}”: {}".format(skill["title"], "needs " + "; ".join(verdict["missing"]) if verdict["missing"]
                                                         else "cannot be run as written here"))
        yield {"type": "plan", "reply": said, "thought": "", "activity": log, "seconds": round(time.monotonic() - started, 1), "chips": {},
               "direction": body.get("direction") or "", "steps": [], "total": 0, "llm": charged,
               "balance": state.credits.balance(user["id"])}
        return
    if adaptation:
        guides = (guides + "\n\n" if guides else "") + "Agreed with the user about this skill: " + adaptation
    # every prompt follows the studio's one prompt structure
    guides = (guides + "\n\n" if guides else "") + agent.STRUCTURE_GUIDE.format(structure=agent.PROMPT_STRUCTURE)
    names = {s["id"]: s["name"] for s in selection}
    # The items a step may put in its reference slots: the attached ones, and the project's pictures in the book.
    # A long run keeps its state under the conversation's id (see runs.py).
    run = body.get("run") if isinstance(body.get("run"), str) and runs.RUN.match(body["run"]) else ""
    kinds = {**book_items, **{s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}}
    if run:   # a long run names its references by library id from its state: any of the project's items, or the run's own
        kinds = {**{r["id"]: {"name": r["name"], "kind": r["kind"]} for r in state.db.all(
            "SELECT id, name, kind FROM generations WHERE user_id = ? AND (run = ? OR " + ("project_id = ?)" if project else "project_id IS NULL)")
            + " ORDER BY id DESC LIMIT ?", (user["id"], run, *([project] if project else []), RUN_ITEMS))}, **kinds}
    videos = [s for s in selection if s.get("seconds")]

    with_tools = state.agent.uses_tools(chosen_model) and body.get("tools", True) is not False
    # A long run (a long skill) keeps its state under the conversation's id and works in many more tool calls.
    rounds = agent.RUN_ROUNDS if run and any(len(s["text"]) > CHECKED_SKILL for s in picked) else agent.TOOL_ROUNDS
    tool_events = []   # what the tools did, shown as the agent's work once the answer is in
    noted = lambda glyph, text: tool_events.append((glyph, text))
    saved_direction = []

    def entry_of(call):
        return next((e for e in book if (call.get("item") and e.get("item") == call["item"])
                     or (call.get("asset") and e.get("asset") == call["asset"])), None)

    async def find_assets(call):
        query = " ".join(str(call.get("query") or "").lower().split())
        words = query.split()
        hits = [e for e in memory.book_for_model(book) if all(w in json.dumps(e, ensure_ascii=False).lower() for w in words)][:8]
        noted("book", "Looked in the asset book for “{}”: {}".format(query, "{} found".format(len(hits)) if hits else "nothing"))
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in hits) or "Nothing in the book matches. Make it from words."

    async def look(call):
        entry = entry_of(call)
        if entry is None:
            return "That id is not in the asset book."
        if not entry["shows"]:
            await memory.describe_missing(state, user["id"], [entry], limit=1)
        noted("look", "Looked at “{}”".format(entry["name"]))
        return entry["shows"] or "It could not be looked at (the model cannot see it, or the file is gone)."

    async def check_shots(call):
        built, left = await build(call.get("steps"))
        noted("plan", "Checked {} {}{}".format(len(built), "step" if len(built) == 1 else "steps", ", {} left out".format(len(left)) if left else ""))
        lines = ["Step {}: {} on {}, {} credits".format(n, s["name"], s["workflow_title"], s["credits"]) for n, s in enumerate(built, start=1)]
        lines += ["Left out “{}”: {}".format(name, reason) for name, reason in left]
        return "\n".join(lines + ["Total {} credits.".format(sum(s["credits"] for s in built))])

    async def review_it(call):
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?", (call.get("item"), user["id"])) \
            if isinstance(call.get("item"), int) else None
        if row is None:
            return "No such item."
        try:
            verdict = await review.review_item(state, user["id"], row, memory._prompt(json.loads(row["settings"] or "{}")), [], None)
        except (review.ReviewError, agent.AgentError) as error:
            return "It could not be reviewed: {}".format(error)
        noted("look", "Checked “{}”".format(row["name"]))
        return review.summary(verdict)

    async def save_note(call):
        text = agent.clean_direction(call.get("text"))
        if text:
            saved_direction[:] = [text]
            noted("book", "Updated the direction")
        return "Saved." if text else "Nothing to save."

    async def kit_save(call):
        name, said_type = kit.clean_name(call.get("text")), str(call.get("op") or "").strip().lower()
        if not name:
            return "Give the entry its name in text."
        always_on = str(call.get("settings") or "").strip().lower() == "always"
        about = str(call.get("value") or "").strip()
        folder = state.assets_dir / str(user["id"])
        if call.get("asset"):
            changes = {"name": name, "type": said_type, **({"about": about} if about else {}), **({"always": True} if always_on else {})}
            found = kit.update(state.db, user["id"], call["asset"], changes)
            if not found:
                return "There is no kit entry {}.".format(call["asset"])
            asset = found["id"]
        elif call.get("item"):
            asset = kit.add_item(state.db, folder, state.outputs.folder(user["id"]), user["id"], project or None, call["item"],
                                 name, kit.tag_of(said_type), always_on, True, about)
            if not asset:
                return "There is no library item {}.".format(call["item"])
            kit.update(state.db, user["id"], asset, {"name": name, "type": said_type, **({"about": about} if about else {})})
        else:
            return "Give the library id of what to keep in item, or the kit entry to change in asset."
        noted("book", "Kept “{}” ({}) in the kit".format(name, kit.TYPES.get(kit.tag_of(said_type), "other")))
        return json.dumps({"asset": asset, "name": name, "type": kit.TYPES.get(kit.tag_of(said_type), "other"), "always": always_on})

    reminded = []   # the run was reminded once to save its work
    stalled = []    # the model was told once that it announced work it did not do
    since = time.time()   # what the run saved during this message is newer than this

    async def finishing(answer):
        """A hint when the steps it finishes with cannot all run, so the model puts them right; nothing when they can.
        A long skill's run that would finish with nothing saved is reminded once: the next message only knows what
        the run state holds."""
        built, left = await build(answer.get("steps"))
        if not left and run and long_skill and not reminded and not runs.saved_any(state.db, user["id"], run):
            reminded.append(True)
            noted("retry", "Nothing of the run was saved yet, so the model was asked to save its work first")
            return agent.SAVE_FIRST
        reply = str(answer.get("reply") or "")
        if not left and run and long_skill and not stalled and not answer.get("steps") and not agent.clean_question(answer.get("question")) \
                and agent.ABOUT_TO.search(reply) and not runs.saved_since(state.db, user["id"], run, since):
            # A long run's turn that only says what it will do (no steps, no question, nothing saved) does nothing.
            stalled.append(True)
            noted("retry", "The model said what it would do but did not do it, so it was asked to")
            return agent.SAID_NOT_DONE.format(" ".join(reply.split())[:300])
        if not left:
            return None
        noted("retry", "A step could not run, so the model was asked to fix it: {}".format("; ".join(r for _, r in left)[:160]))
        return "These steps cannot run: {}. Fix them or leave them out, and finish again.".format(
            "; ".join("“{}”: {}".format(name, reason) for name, reason in left))

    def no_run():
        return "This conversation keeps no run state: start the skill again from the Agent tab."

    def value_of(call):
        try:
            return json.loads(call.get("value") or "null")
        except ValueError:
            raise ValueError("value must be JSON text")

    async def state_read(call):
        if not run:
            return no_run()
        try:
            found = runs.read(state.db, user["id"], run, call.get("path"), call.get("offset") or 0, STATE_PAGE)
        except runs.RunError as error:
            return str(error)
        noted("book", "Read {} of the run".format(found["path"]))
        if found.get("folder"):
            shown = found["offset"] + len(found["leaves"])
            more = "" if shown >= found["total"] else "\n({} of {} shown: call again with offset {}.)".format(shown, found["total"], shown)
            return "\n".join(json.dumps(leaf, ensure_ascii=False) for leaf in found["leaves"]) + more
        return json.dumps(found, ensure_ascii=False)

    async def state_write(call):
        if not run:
            return no_run()
        path = str(call.get("path") or "")
        try:
            if path.endswith("/*"):   # every leaf of a folder at once
                written = runs.write_many(state.db, user["id"], run, path[:-2], value_of(call), "agent")
                noted("book", "Wrote {} leaves under {}".format(written["written"], written["path"]))
                return "Written: {} leaves under {}".format(written["written"], written["path"])
            written = runs.write(state.db, user["id"], run, path, value_of(call), "agent")
        except (runs.RunError, ValueError) as error:
            return "Not written: {}".format(error)
        noted("book", "Wrote {} of the run".format(written["path"]))
        return "Written: {}".format(written["path"])

    async def read_skill(call):
        named = str(call.get("op") or "").strip()
        skill = next((s for s in picked if s["id"] == named), None) or (picked[0] if len(picked) == 1 else None)
        if skill is None:
            return "Name the skill in op: {}.".format(", ".join(s["id"] for s in picked) or "no skill is in use")
        text, problem = skills.read_part(skill, call.get("query"), call.get("offset") or 0)
        if problem:
            return problem
        noted("skill", "Read “{}” of “{}”".format(" ".join(str(call.get("query") or "").split())[:40], skill["title"]))
        return text

    async def read_text(call):
        if isinstance(call.get("asset"), int) and call["asset"]:   # a script kept in the project's kit
            row = state.db.one("SELECT name, filename FROM assets WHERE id = ? AND user_id = ? AND kind = 'text'", (call["asset"], user["id"]))
            path = state.assets_dir / str(user["id"]) / row["filename"] if row else None
        else:
            row = state.db.one("SELECT name, filename FROM generations WHERE id = ? AND user_id = ? AND kind = 'text'",
                               (call.get("item"), user["id"])) if isinstance(call.get("item"), int) else None
            path = state.outputs.folder(user["id"]) / row["filename"] if row else None
        if not path or not path.is_file():
            return "That is not a text in the library or the kit."
        words = path.read_text(encoding="utf-8-sig", errors="replace")
        if call.get("path"):
            if not run:
                return no_run()
            try:
                runs.write(state.db, user["id"], run, call["path"], words, "read_text")
            except runs.RunError as error:
                return "Not kept: {}".format(error)
            noted("book", "Kept “{}” in {} ({:,} characters)".format(row["name"], call["path"], len(words)))
        offset = max(0, int(call.get("offset") or 0))
        page = words[offset:offset + TEXT_PAGE]
        noted("book", "Read “{}”".format(row["name"]))
        more = "" if offset + len(page) >= len(words) else "\n[{:,} of {:,} characters shown: call again with offset {}.]".format(
            offset + len(page), len(words), offset + len(page))
        return page + more

    async def read_transcript(call):
        if not run:
            return no_run()
        from .. import transcript
        if not call.get("item") and call.get("value"):   # who speaks each line, from the script: only the speakers change
            try:
                names = json.loads(call["value"])
                if not isinstance(names, dict):
                    raise ValueError
                lines = dict(runs.leaves(state.db, user["id"], run, call.get("path")))
                changed = {}
                for n, who in names.items():
                    if isinstance(lines.get(str(n)), dict):
                        changed[str(n)] = dict(lines[str(n)], speaker=" ".join(str(who).split())[:60])
                if not changed:
                    return "None of those lines is at {}.".format(call.get("path"))
                runs.write_many(state.db, user["id"], run, call.get("path"), changed, "speakers")
            except ValueError:
                return "value must be JSON text of {\"<line number>\": \"<speaker>\"}."
            except runs.RunError as error:
                return "Not written: {}".format(error)
            noted("book", "Named the speakers of {} lines".format(len(changed)))
            return json.dumps({"named": len(changed), "speakers": sorted({l["speaker"] for l in changed.values()})}, ensure_ascii=False)
        row = state.db.one("SELECT name, filename FROM generations WHERE id = ? AND user_id = ? AND kind = 'text'", (call.get("item"), user["id"])) \
            if isinstance(call.get("item"), int) else None
        path = state.outputs.folder(user["id"]) / row["filename"] if row else None
        if not path or not path.is_file():
            return "That item is not a transcript in the library."
        try:
            lines = transcript.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
            written = runs.write_many(state.db, user["id"], run, call.get("path"), {str(n): l for n, l in enumerate(lines, start=1)}, "transcript", replace=True)
        except (transcript.TranscriptError, runs.RunError) as error:
            return "Not read: {}".format(error)
        noted("book", "Read {} lines of “{}” into {}".format(len(lines), row["name"], written["path"]))
        speakers = sorted({l["speaker"] for l in lines})
        return json.dumps({"written": len(lines), "path": written["path"], "speakers": speakers, "first": lines[:3], "last": lines[-1]}, ensure_ascii=False)

    async def timing(call):
        if not run:
            return no_run()
        from .. import transcript
        try:
            asked = json.loads(call.get("settings") or "{}")
            length = float(asked["length"])
            units = [dict(value, id=name) for name, value in runs.leaves(state.db, user["id"], run, asked["units"]) if isinstance(value, dict)]
            lines = {int(n): v for n, v in runs.leaves(state.db, user["id"], run, asked["lines"]) if n.isdigit() and isinstance(v, dict)}
            speech = {int(n): v for n, v in runs.leaves(state.db, user["id"], run, asked["speech"]) if n.isdigit()} if asked.get("speech") else {}
        except (ValueError, KeyError, TypeError) as error:
            return "settings must be JSON text with units, lines, length and save_to ({}).".format(type(error).__name__)
        except runs.RunError as error:
            return str(error)
        if not units or not lines:
            return "No units or no lines were found at those paths."
        frames, problems = transcript.grid(units, lines, speech, length)
        if frames:
            try:
                runs.write_many(state.db, user["id"], run, asked.get("save_to") or "", frames, "timing", replace=True)
            except runs.RunError as error:
                return "Not written: {}".format(error)
        noted("clock", "Timed {} shots{}".format(len(frames), ", {} to fix".format(len(problems)) if problems else ""))
        return json.dumps({"timed": len(frames), "frames": sum(f["f_out"] - f["f_in"] for f in frames.values()),
                           "problems": problems[:40]}, ensure_ascii=False)

    async def state_check(call):
        if not run:
            return no_run()
        try:
            found = runs.coverage(state.db, user["id"], run, call.get("path"), call.get("against"))
        except runs.RunError as error:
            return str(error)
        noted("check", "Checked {} against {}: {}".format(call.get("path"), call.get("against"),
                                                         "complete" if found["ok"] else "{} missing".format(len(found["missing"]))))
        return json.dumps(found, ensure_ascii=False)

    async def film_op(call):
        """One film operation, queued and waited for (they are quick, free and made on this machine)."""
        from .film import queue as film_queue   # film.py builds on this module
        if call.get("op") not in edits.FILM:
            return "op must be one of: {}.".format(", ".join(edits.FILM))
        try:
            settings = json.loads(call.get("settings") or "{}")
            if not isinstance(settings, dict):
                raise ValueError
        except ValueError:
            return "settings must be JSON text of an object."
        try:
            settings = _resolve_state(state.db, user["id"], run, settings) if run else settings
            queued = film_queue(request, user, dict(settings, op=call["op"], run=run, project_id=project or None))
        except runs.RunError as error:
            return str(error)
        except HTTPException as error:
            return "Not done: {}".format(error.detail)
        noted("wrench", "{} ({})".format(edits.FILM[call["op"]][1], queued["name"]))
        job = await _finished(state, queued["job"])
        if job["status"] != "done":
            return "The {} failed: {}".format(call["op"], job.get("error") or job["status"])
        made = state.db.all("SELECT id, kind, name, context FROM generations WHERE job_id = ? ORDER BY id", (queued["job"],))
        return json.dumps([{"item": r["id"], "kind": r["kind"], **json.loads(r["context"] or "{}")} for r in made],
                          ensure_ascii=False)[:agent.TOOL_RESULT]

    async def import_url(call):
        from .. import fetch
        from .library import IMPORTED, _file_in   # library.py files what is brought in
        url = str(call.get("text") or "").strip()
        try:
            data, kind, final = await fetch.fetch(url)
        except fetch.FetchError as error:
            return "Not brought in: {}".format(error)
        made = await _file_in(request, user, data, fetch.filename_for(final, kind), kind, project or None, "Brought in from a link",
                              workflow=IMPORTED, name=" ".join(str(call.get("query") or "").split())[:80], source=url)
        noted("attach", "Brought in “{}” from a link".format(made["name"]))
        return json.dumps({"item": made["id"], "kind": kind, "name": made["name"], **made["context"]}, ensure_ascii=False)

    tools = {"find_assets": find_assets, "look": look, "check_shots": check_shots, "review": review_it, "save_note": save_note,
             "kit_save": kit_save,
             "state_read": state_read, "state_write": state_write, "state_check": state_check, "film": film_op, "import_url": import_url,
             "transcript": read_transcript, "timing": timing, "read_text": read_text, "read_skill": read_skill}

    async def plan(message):
        """One answer of the model, timed, and the steps of it that can run. Returns (answer, steps, dropped, seconds)."""
        asked = time.monotonic()
        system = agent.SYSTEM.format(max_steps=agent.MAX_STEPS)
        # A long skill goes first, in the system prompt: every call of a run then opens the same way, and a hosted
        # service can read that opening from its cache instead of anew (the rest of the message changes as the run goes).
        first = long_skill and with_tools
        if first:
            system += "\n\n" + agent.skills_part(guides)
        asking = agent.question(message, offers, selection, state.catalog.current(state.settings.default_workflow),
                                agent.past_turns(body.get("history")), pinned, recent, memory.book_for_model(book), "" if first else guides,
                                body.get("direction") or "")
        if with_tools:   # the model works in a loop of tool calls (a local one too, unless local_tools is off)
            answer = await state.agent.ask_with_tools(system, asking, [o["id"] for o in offers], tools, finishing, rounds=rounds, **_model(body))
        else:
            answer = await state.agent.ask(system, asking, [o["id"] for o in offers], **_model(body))
        seconds = time.monotonic() - asked
        # Each answer is charged at the price of the model that gave it (another one may have stood in for a busy one).
        used = answer.get("model") or chosen_model
        cost = state.credits.llm_cost(used)
        if cost and state.credits.charge(user["id"], cost, "agent", note=used):
            charged["credits"] += cost
            charged["model"] = used
        steps, dropped = await build(answer["steps"])
        if answer.get("tools") is not None:
            answer["tools"] = list(answer["tools"])
        if answer.get("empty_sent_back"):
            noted("retry", "The model stopped with nothing to show, so it was asked to carry on")
        agent.add_tokens(tokens, answer.get("tokens"))
        return answer, steps, dropped, seconds

    async def build(raw):
        """The steps of an answer that can be carried out, priced, and the ones left out with the reason. Nothing is queued."""
        steps, dropped = [], []
        made_by = {}   # the number the model gave a step (1 for its first) -> where that step's result is in `steps`
        for number, proposed in enumerate(raw[:agent.MAX_STEPS] if isinstance(raw, list) else [], start=1):
            made_by[number] = len(steps)   # taken back below if the step is dropped
            before = len(steps)
            # Separating a voice or transcribing is work on a sound, and a model often calls it "sound": a sound step
            # that names a workflow made to take a sound file is that workflow's step, not a sound put on a video.
            if isinstance(proposed, dict) and proposed.get("tool") == agent.SOUND_TOOL and proposed.get("workflow") in hears:
                proposed = dict(proposed, tool="generate")
            if isinstance(proposed, dict) and proposed.get("tool") == agent.SOUND_TOOL:
                made = agent.sound_for(proposed, known)
                if made:   # a sound on a video: queued on Approve through the sound endpoint, which costs nothing
                    steps.append({"name": made["name"], "workflow_title": "Sound", "kind": "video", "prompt": "", "facts": made["facts"],
                                  "time": "a few seconds", "credits": 0, "settings": None, "start": None, "sound": made["sound"]})
                reason = None if made else agent.NO_SOUND_EDIT
            elif isinstance(proposed, dict) and proposed.get("tool") == agent.ASSEMBLE_TOOL:
                planned = [n for n, s in enumerate(steps) if s["kind"] == "video" and s.get("settings")]
                music_at = made_by.get(proposed.get("after"))
                music_planned = music_at is not None and music_at < len(steps) and steps[music_at]["kind"] == "audio" and bool(steps[music_at].get("settings"))
                made = agent.assemble_for(proposed, planned, videos, known, music_planned,
                                          ((steps[planned[0]].get("current") or {}).get("orientation") if planned else None))
                if made:   # the finished cut: queued on Approve once the shots (and music) are made
                    made["assemble"]["music_step"] = music_at if music_planned else None
                    steps.append({"name": made["name"], "workflow_title": "Final cut", "kind": "video", "prompt": "", "facts": made["facts"],
                                  "time": "under a minute", "credits": 0, "settings": None, "start": None, "assemble": made["assemble"]})
                reason = None if made else "there were no shots or selected videos to put together"
            else:
                reason = await _plan_step(state, proposed, instruction, steps, made_by, schemas, names, kinds, videos, pinned, project, shapes, book_assets, menu)
            if len(steps) == before:
                del made_by[number]
                if reason:
                    dropped.append(((proposed.get("name") if isinstance(proposed, dict) else "") or "a step", reason))
        return steps, dropped

    def thought(answer, seconds):
        return logged({"type": "thought", "text": str(answer.get("thought") or ""), "seconds": round(seconds, 1)})

    tokens = {}   # what the model read and wrote for this message, every call added up
    message = agent.carry_over(instruction, body.get("history"))
    yield status("Thinking…")
    # The model is asked in a task, so what its tools do is shown while it works (a long run makes dozens of calls),
    # and the stream keeps moving. A closed stream (the user pressed Stop) stops the work too.
    async def live(asking):
        task = asyncio.ensure_future(plan(asking))
        try:
            while True:
                done, _ = await asyncio.wait([task], timeout=LIVE_EVERY)
                while tool_events:
                    yield activity(*tool_events.pop(0))
                if done:
                    break
                yield status("Working…" if run else "Thinking…")
        finally:
            if not task.done():
                task.cancel()
        result[:] = [task.result()]

    result = []
    async for event in live(message):
        yield event
    answer, steps, dropped, seconds = result[0]
    if saved_direction and not answer.get("direction"):
        answer["direction"] = saved_direction[0]
    yield thought(answer, seconds)
    # A reply that says it is making something while no step survived would leave the user waiting for nothing:
    # the model is asked once more, and if it still plans nothing, the reply says plainly that nothing was made.
    if not steps and agent.claims_work(instruction, answer["reply"]):
        yield activity("retry", "The first answer said it was making something but planned nothing, so I asked again")
        yield status("Thinking again…")
        async for event in live(message + "\n" + agent.NO_STEPS):
            yield event
        answer, steps, dropped, seconds = result[0]
        yield thought(answer, seconds)
        if not steps and agent.claims_work(instruction, answer["reply"]):
            answer["reply"] = agent.EMPTY_CLAIM
    for name, reason in dropped:
        yield activity("skip", "Left out “{}”: {}".format(name, reason))
    if not steps and agent.wants_sound(instruction, body.get("history")):
        made = agent.sound_for({}, known)   # the model only talked: make the step that was asked for
        if made:
            steps.append({"name": made["name"], "workflow_title": "Sound", "kind": "video", "prompt": "", "facts": made["facts"],
                          "time": "a few seconds", "credits": 0, "settings": None, "start": None, "sound": made["sound"]})
            answer["reply"] = "I'll put {}. Approve to make it.".format(made["facts"])
    steps = steps[:agent.MAX_STEPS]
    for step in steps:   # every generation is a shot with an id of its own: a retake becomes take 2 of the same shot
        if step.get("settings"):
            step["shot_id"] = uuid.uuid4().hex[:8]
            step["settings"]["shot"] = {"id": step["shot_id"], "take": 1}
            if run:   # counted against the run's budget
                step["settings"]["run_of"] = run
    if steps:
        yield activity("plan", "Checked and priced {} {}".format(len(steps), "step" if len(steps) == 1 else "steps"))
    if tokens.get("prompt"):
        yield activity("info", "Read {:,} tokens{} and wrote {:,}".format(
            tokens["prompt"], " ({:,} from the cache)".format(tokens["cached"]) if tokens.get("cached") else "", tokens.get("answer", 0)))
    # Items the reply names as [[item:12]] or [[asset:3]] are shown as small pictures; the browser gets their names.
    chips, reply = agent.chips_in(answer["reply"], {**book_items, **known}, book_assets)
    if charged["credits"]:
        state.notify(user["id"])   # the open pages show the new balance
    # A reply left empty: in a long run the model stopped mid-step, and "go" carries on; otherwise it has nothing to make.
    nothing = RUN_STOPPED if run and long_skill else "Tell me what you would like to see and I will plan it."
    yield {"type": "plan", "reply": reply or ("Here is the plan." if steps else nothing),
           "thought": str(answer.get("thought") or ""), "activity": log, "seconds": round(time.monotonic() - started, 1),
           "chips": chips, "direction": answer.get("direction") or "", "steps": steps, "total": sum(s["credits"] for s in steps), "llm": charged,
           "balance": state.credits.balance(user["id"]), "question": answer.get("question"), "run": run,
           # a long skill's run goes on by itself: once these steps are made, the Agent tab tells the agent what they made;
           # a turn that made nothing but saved its work (a stage of planning) goes on at once
           "continues": bool(run and long_skill and not answer.get("question")
                             and (steps or runs.saved_since(state.db, user["id"], run, since))),
           "budget": runs.budget(state.db, user["id"], run) if run and long_skill else None, "tokens": tokens}


async def _plan_step(state, proposed, instruction, steps, made_by, schemas, names, kinds, videos, pinned, project, shapes, assets=None, menu=None):
    """Check one step the model proposed and add what can be carried out to `steps`. A step that can't run adds nothing,
    and the reason is returned (None when the step was added, or when leaving it out is not worth saying)."""
    if not isinstance(proposed, dict):
        return "it could not be read"
    if proposed.get("tool") in agent.MOTION_TOOLS:
        # Words and shapes drawn by HyperFrames: queued on Approve through the motion endpoint, which charges by the length.
        made = agent.motion_for(proposed, videos)
        if made:
            scenes = made["motion"].get("scenes")
            seconds = sum(s["seconds"] for s in scenes) if scenes else next(v["seconds"] for v in videos if v["id"] == made["motion"]["source"])
            steps.append({"name": made["name"], "workflow_title": "Motion graphics", "kind": "video", "prompt": made["words"],
                          "facts": made["facts"], "time": "under a minute", "why": agent.why(proposed),
                          "credits": state.credits.cost(MOTION_WORKFLOW if scenes else credits.OVERLAY, seconds),
                          "settings": None, "start": None, "motion": made["motion"]})
            return None
        return "it had no words to show, or no selected video to put them on"
    if proposed.get("tool") == "trim" and agent.parts_asked(instruction):
        if any("edit" in step for step in steps):
            return   # the split is already planned; a second trim of the same video adds nothing
        proposed = dict(proposed, tool="split", parts=agent.parts_asked(instruction))   # the user asked for pieces, not for one cut
    if proposed.get("tool") in agent.EDIT_TOOLS:
        # An edit of videos the user has: the browser runs it through the timeline export, which costs nothing.
        cuts = agent.edits_for(proposed, videos)
        for edit in cuts:
            steps.append({"name": edit["name"], "workflow_title": "Edit", "kind": "video", "prompt": "", "facts": edit["facts"],
                          "time": "a few seconds", "credits": 0, "settings": None, "start": None, "edit": {"clips": edit["clips"]}})
        return None if cuts else "select the video to cut on the canvas first"
    schema = schemas.get(proposed.get("workflow"))
    original = proposed   # kept on the step, so the shot can be made again as a still and then as a clip
    if schema and proposed.get("tool", "generate") == "generate":   # the camera the agent chose is said in the prompt
        proposed = dict(proposed, prompt=camera.apply(proposed.get("prompt"), camera.clean(proposed), schema["id"].split("/", 1)[0]))
    if not schema:
        return "there is no workflow “{}” it can use".format(proposed.get("workflow") or "")
    if not agent.offer(schema):
        return "{} needs reference files, and none were attached".format(schema["title"])
    uses = agent.uses_for(schema, proposed, kinds, assets)
    left_out = [i for i in proposed.get("leave_out") or [] if isinstance(i, int)] if isinstance(proposed.get("leave_out"), list) else []
    # A model that takes no reference pictures keeps the always-on people and places the same from words: what they show.
    special = set((schema.get("slots") or {}).values())
    if pinned and proposed.get("prompt") and schema["id"].split("/", 1)[0] in ("image", "video") \
            and not any(r["kind"] in ("image", "video") for r in schema["refs"] if r["id"] not in special):
        words = kit.in_words(pinned, left_out)
        if words:
            proposed = dict(proposed, prompt=proposed["prompt"].rstrip() + "\n" + words)
    # A step can start on what an earlier step of this plan makes, if that is a picture or a video
    # and this workflow has a first frame to put it in.
    earlier = made_by.get(proposed.get("after"))
    first_frame = (schema.get("slots") or {}).get("first_frame")
    chained = earlier is not None and earlier < len(steps) and bool(first_frame) and steps[earlier]["kind"] != "audio"
    # A song's length is not left to the model, which likes to ask for the longest one (and it is paid by the second):
    # the length the user named, or else the video shots planned before it, rounded up to a length the workflow offers.
    if agent.length_control(schema) and not any(c["role"] == "duration" for c in schema["controls"]):
        wanted = agent.seconds_asked(instruction) or sum(
            (s["settings"] or {}).get("values", {}).get(next((c["id"] for c in schemas[s["settings"]["workflow"]]["controls"] if c["role"] == "duration"), ""), 0)
            * (s["settings"] or {}).get("clips", 1) for s in steps if s.get("settings") and s["kind"] == "video")
        proposed = dict(proposed, duration=math.ceil(wanted)) if wanted else proposed
    built = agent.settings_for(schema, proposed, set(names), project or None,
                               {use["slot"] for use in uses}, {use["id"] for use in uses if use["id"]}, chained)
    if not built:
        return "it had no prompt, or {} needs files it was not given".format(schema["title"])
    settings, start = built
    keep = memory.clean_keep(proposed.get("keep"), schema["id"].split("/", 1)[0])
    if keep:   # kept in shared memory once it is made
        settings["keep"] = keep
    # A shot takes the shape of the picture it starts on: a portrait picture in a landscape video comes out squashed.
    agent.shape_like(schema, settings, steps[earlier].get("shape") if chained else shapes.get(start))
    # The project's always-on entries go into every slot meant for them that the step left empty, but those it leaves out.
    uses = uses + [dict(fill, cast=True) for fill in kit.fills(
        schema, pinned, {use["slot"] for use in uses}, {use["asset"] for use in uses if use.get("asset")}, left_out,
        {use["id"] for use in uses if use["id"]} | ({start} if start else set()))]
    steps.append(await _shown_step(state, schema, settings, menu or [], uses,
                                   {"id": start, "name": names[start], "slot": first_frame} if start else None,
                                   {"step": earlier, "slot": first_frame} if chained else None, agent.why(proposed)))
    steps[-1]["camera"] = camera.clean(proposed)
    steps[-1]["proposal"] = original
    return None


def _orientation(schema, settings, ctx):
    """landscape, portrait or square: what a job's shape is called on its approval card, or None when it has none."""
    if schema.get("size"):
        return ctx["orientation"]
    shape = agent.shape_of(schema, settings, ctx)
    if not shape:
        return None
    ratio = shape[0] / shape[1]
    return "landscape" if ratio > 1.15 else "portrait" if ratio < 0.87 else "square"


async def _shown_step(state, schema, settings, menu, uses, start, after, why=""):
    """One planned generation as the browser shows it: checked and priced, with what its approval card can change."""
    quote = await price(state, await state.catalog.load(schema["id"]), settings)
    ctx = workflows.context(schema, settings)
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    kind = schema["id"].split("/", 1)[0]
    aspect = any(c["input"] == "aspect_ratio" and c.get("choices") for c in schema["controls"])
    resolutions = schema["resolutions"] if schema.get("size") or "resolution" in roles else []
    return {"name": settings["name"], "workflow_title": schema["title"], "kind": kind,
            "prompt": settings["values"][roles["prompt"]["id"]] if "prompt" in roles else "", "facts": workflows.summary(schema, ctx), "time": quote["text"],
            "credits": quote["credits"], "settings": settings, "start": start, "uses": uses, "after": after,
            "shape": agent.shape_of(schema, settings, ctx), "why": why, "keep": settings.get("keep"),
            # What the card offers: the other workflows of the same kind, and this one's shapes, sizes and lengths.
            "menu": {"workflows": [w for w in menu if w["kind"] == kind],
                     "shapes": bool(schema.get("size") or aspect), "resolutions": resolutions,
                     "durations": SHOT_LENGTHS if "duration" in roles else []},
            "current": {"orientation": _orientation(schema, settings, ctx), "resolution": ctx.get("resolution"),
                        "duration": int(ctx["duration"]) if ctx.get("duration") else None}}


def _resolve_state(db, user_id, run, value):
    """Every "$state:/path" in an operation's settings replaced by what is kept there (a library id, most often)."""
    if isinstance(value, str) and value.startswith("$state:"):
        return runs.resolve(db, user_id, run, value)
    if isinstance(value, list):
        return [_resolve_state(db, user_id, run, v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_state(db, user_id, run, v) for k, v in value.items()}
    return value


async def _finished(state, job_id, timeout=FILM_WAIT):
    """The job, once it is no longer waiting or running (or as it is when the time is up)."""
    deadline = time.monotonic() + timeout
    while True:
        job = state.db.one("SELECT id, status, error FROM jobs WHERE id = ?", (job_id,))
        if job["status"] not in ("queued", "running") or time.monotonic() > deadline:
            return job
        await asyncio.sleep(0.4)


def attachment_line(item):
    """One attached item as the check of a skill is told it: its tag, its name and what it is, by its content."""
    what = {"audio": "a sound", "video": "a video", "image": "a picture", "text": "a text"}.get(item["kind"], item["kind"])
    if item.get("seconds"):
        what += ", {:.1f} s long".format(item["seconds"])
    if item["kind"] == "text" and "characters" in item:
        what += " of {:,} characters, which begins: “{}”".format(item["characters"], item.get("begins", ""))
    return "{} {} ({})".format(item["tag"], item["name"], what)


# The kinds of file a missing thing may be, by its words: what the check of a skill calls missing is given when the user
# attached a file of that kind.
KIND_WORDS = {
    "audio": re.compile(r"\b(audio|sound|voice|mix|track|music|song|narration|recording|mp3|wav|stem)\b", re.I),
    "text": re.compile(r"\b(script|text|document|screenplay|story|transcript|srt|lyrics|article|words|doc|docx)\b", re.I),
    "image": re.compile(r"\b(image|images|picture|pictures|photo|photos|still|stills|sheet|sheets|character|characters|location|locations|prop|props)\b", re.I),
    "video": re.compile(r"\b(video|clip|clips|footage)\b", re.I),
}


def attached_kind(missing, selection):
    """The kind of attached file that answers a thing the check called missing, or None."""
    have = {s["kind"] for s in selection}
    return next((kind for kind, words in KIND_WORDS.items() if kind in have and words.search(str(missing))), None)
