"""The canvas, the timeline and the agent: arranging finished work, queueing edits and motion graphics, and planning new work."""

import json
import math
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import agent, cast, credits, edits, media, memory, motion, review, sequence, skills
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
MOTION_WORKFLOW = credits.MOTION   # what a rendered motion graphic is filed and priced under


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
    """The references pinned to a project (saved with PUT /api/boards/cast as {role: item id}), and, for a workflow,
    which of its reference slots they fill."""
    state = request.app.state
    pinned = cast.load(state.db, user["id"], _project_id(request, user, project))
    found = {"roles": cast.roles(), "cast": pinned, "fills": []}
    if workflow and pinned:
        found["fills"] = cast.fills(workflows.describe(await state.catalog.load(workflow)), pinned)
    return found


# ---------------------------------------------------------------- motion graphics

@router.get("/motion/templates")
async def motion_templates(request: Request, user: dict = Depends(current_user)):
    """The motion templates and whether this machine can render them."""
    return {**motion.status(request.app.state.settings.node_path), "templates": motion.templates()}


@router.post("/motion/scenes")
async def motion_scenes(body: dict, request: Request, user: dict = Depends(current_user)):
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
    """Everything kept for a project, as the Shared memory tab shows it: saved assets and uploads. For a user who has
    the agent, its model first looks at a few pictures it has not described yet."""
    state = request.app.state
    project = _project_id(request, user, project)
    pinned = cast.load(state.db, user["id"], project)
    if user["agent"]:
        await memory.describe_missing(state, user["id"], memory.book(state.db, user["id"], project, pinned), limit=6)
    found = memory.panel(state.db, user["id"], project, pinned)
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
    if not references and item["project_id"]:   # checked on its own: the project's cast is what it should look like
        for pin in cast.load(state.db, user["id"], item["project_id"]).values():
            row = own(pin["id"]) if pin["kind"] in ("image", "video") and pin["id"] != item["id"] else None
            if row:
                references.append((row["name"], state.outputs.folder(user["id"]) / row["filename"]))
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
    """Have the agent rewrite a prompt into a fuller one. Nothing is queued or charged."""
    prompt = str(body.get("prompt") or "").strip()[:2000]
    if not prompt:
        raise HTTPException(400, "Write a prompt first, then improve it.")
    kind = body.get("kind") if body.get("kind") in agent.IMPROVE_KINDS else "video"
    project = _project_id(request, user, body.get("project_id"))
    state = request.app.state
    # The chosen workflow's own prompting tips, and the cast when that workflow has slots for it.
    tips, pinned = [], {}
    if body.get("workflow"):
        try:
            schema = workflows.describe(await state.catalog.load(str(body["workflow"])))
            tips = schema["hints"]
            full = cast.load(state.db, user["id"], project)
            pinned = {f["role"]: full[f["role"]] for f in cast.fills(schema, full)}
        except (workflows.WorkflowError, HTTPException):
            pass
    return {"prompt": await state.agent.improve(prompt, kind, tips=tips, project_cast=pinned,
                                                structure=agent.PROMPT_STRUCTURE if kind != "audio" else "", **_model(body))}



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
    prompt = change["prompt"] if isinstance(change.get("prompt"), str) else (old.get("values") or {}).get(roles["prompt"]["id"], "")
    # The step as the model would have proposed it, with the change made: settings_for keeps what the workflow takes.
    proposed = {"prompt": str(prompt).strip(), "name": old.get("name"), "clips": old.get("clips", 1),
                "duration": int(change.get("duration") or ctx.get("duration") or 0),
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
    pinned = cast.load(state.db, user["id"], project)
    uses = uses + [dict(fill, cast=True) for fill in cast.fills(
        schema, pinned, {u["slot"] for u in uses}, {u["id"] for u in uses if u.get("id")} | ({started} if started else set()))]
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
    events = _planning(request, user, body, instruction, project)
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
    chosen = (body.get("selection") or [])[:8] if agent.points_at_selection(instruction) else []
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
            if row["kind"] == "video" and path.is_file():   # the length is what the editing tools cut by
                selection[-1]["seconds"] = round((await media.probe(path))["seconds"], 2)
    if selection:
        yield activity("attach", "Read what you attached: " + ", ".join(s["name"] for s in selection))

    # What was made lately here, so "the music you just made" can be put on "this video" without attaching either.
    recent = [{"id": r["id"], "kind": r["kind"], "name": r["name"]} for r in state.db.all(
        "SELECT id, kind, name FROM generations WHERE user_id = ? AND " + ("project_id = ?" if project else "project_id IS NULL")
        + " ORDER BY created DESC LIMIT 8", (user["id"], project) if project else (user["id"],))]
    known = {s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}
    known.update({r["id"]: {"name": r["name"], "kind": r["kind"]} for r in recent if r["id"] not in known})

    schemas = {}
    default = state.catalog.current(state.settings.default_workflow)
    menu = await _menu(state)
    for listed in await state.catalog.listing():
        if listed.get("error") or not state.credits.enabled(listed["id"]):
            continue
        # Video is made with the default workflow, which has the cast's slots and the quality choices; the other video
        # workflows are for the Create page, and the agent uses one only when the message names it.
        if listed["kind"] == "video" and default.startswith("video/") and listed["id"] != default \
                and listed["title"].lower() not in instruction.lower():
            continue
        schemas[listed["id"]] = workflows.describe(await state.catalog.load(listed["id"]))
    pinned = cast.load(state.db, user["id"], project)
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
    # The user can name a skill with /<id> at the start of the message, or the panel can pass skill ids; those are
    # always used. The rest are picked by what the message says, as before.
    forced = list(body.get("skills") or [])
    match = re.match(r"\s*/([a-z0-9][a-z0-9-]*)\s*", instruction)
    if match and skills.find(match.group(1)):
        forced.append(match.group(1))
        instruction = instruction[match.end():].strip()   # the /command is an instruction to the agent, not shot text
    picked = skills.pick(instruction, body.get("history"), force=forced)
    for skill in picked:
        yield activity("skill", "Read the skill “{}”".format(skill["title"]))
    guides = skills.guide(picked)
    # every prompt follows the studio's one prompt structure
    guides = (guides + "\n\n" if guides else "") + agent.STRUCTURE_GUIDE.format(structure=agent.PROMPT_STRUCTURE)
    names = {s["id"]: s["name"] for s in selection}
    # The items a step may put in its reference slots: the attached ones, and the project's pictures in the book.
    kinds = {**book_items, **{s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}}
    videos = [s for s in selection if s.get("seconds")]

    async def plan(message):
        """One answer of the model, timed, and the steps of it that can run. Returns (answer, steps, dropped, seconds)."""
        asked = time.monotonic()
        answer = await state.agent.ask(agent.SYSTEM.format(max_steps=agent.MAX_STEPS),
                                       agent.question(message, offers, selection,
                                                      state.catalog.current(state.settings.default_workflow), agent.past_turns(body.get("history")), pinned, recent,
                                                      memory.book_for_model(book), guides),
                                       [o["id"] for o in offers], **_model(body))
        seconds = time.monotonic() - asked
        # Each answer is charged at the price of the model that gave it (another one may have stood in for a busy one).
        used = answer.get("model") or chosen_model
        cost = state.credits.llm_cost(used)
        if cost and state.credits.charge(user["id"], cost, "agent", note=used):
            charged["credits"] += cost
            charged["model"] = used
        steps, dropped = [], []
        made_by = {}   # the number the model gave a step (1 for its first) -> where that step's result is in `steps`
        for number, proposed in enumerate(answer["steps"][:agent.MAX_STEPS], start=1):
            made_by[number] = len(steps)   # taken back below if the step is dropped
            before = len(steps)
            if isinstance(proposed, dict) and proposed.get("tool") == agent.SOUND_TOOL:
                made = agent.sound_for(proposed, known)
                if made:   # a sound on a video: queued on Approve through the sound endpoint, which costs nothing
                    steps.append({"name": made["name"], "workflow_title": "Sound", "kind": "video", "prompt": "", "facts": made["facts"],
                                  "time": "a few seconds", "credits": 0, "settings": None, "start": None, "sound": made["sound"]})
                reason = None if made else "there was no video and sound to put together"
            else:
                reason = await _plan_step(state, proposed, instruction, steps, made_by, schemas, names, kinds, videos, pinned, project, shapes, book_assets, menu)
            if len(steps) == before:
                del made_by[number]
                if reason:
                    dropped.append(((proposed.get("name") if isinstance(proposed, dict) else "") or "a step", reason))
        return answer, steps, dropped, seconds

    def thought(answer, seconds):
        return logged({"type": "thought", "text": str(answer.get("thought") or ""), "seconds": round(seconds, 1)})

    message = agent.carry_over(instruction, body.get("history"))
    yield status("Thinking…")
    answer, steps, dropped, seconds = await plan(message)
    yield thought(answer, seconds)
    # A reply that says it is making something while no step survived would leave the user waiting for nothing:
    # the model is asked once more, and if it still plans nothing, the reply says plainly that nothing was made.
    if not steps and agent.claims_work(instruction, answer["reply"]):
        yield activity("retry", "The first answer said it was making something but planned nothing, so I asked again")
        yield status("Thinking again…")
        answer, steps, dropped, seconds = await plan(message + "\n" + agent.NO_STEPS)
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
    if steps:
        yield activity("plan", "Checked and priced {} {}".format(len(steps), "step" if len(steps) == 1 else "steps"))
    # Items the reply names as [[item:12]] or [[asset:3]] are shown as small pictures; the browser gets their names.
    chips, reply = agent.chips_in(answer["reply"], {**book_items, **known}, book_assets)
    if charged["credits"]:
        state.notify(user["id"])   # the open pages show the new balance
    yield {"type": "plan", "reply": reply or ("Here is the plan." if steps else "Tell me what you would like to see and I will plan it."),
           "thought": str(answer.get("thought") or ""), "activity": log, "seconds": round(time.monotonic() - started, 1),
           "chips": chips, "steps": steps, "total": sum(s["credits"] for s in steps), "llm": charged,
           "balance": state.credits.balance(user["id"])}


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
    if not schema:
        return "there is no workflow “{}” it can use".format(proposed.get("workflow") or "")
    if not agent.offer(schema):
        return "{} needs reference files, and none were attached".format(schema["title"])
    uses = agent.uses_for(schema, proposed, kinds, assets)
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
    # The project's cast goes into every slot meant for it that the step left empty.
    uses = uses + [dict(fill, cast=True) for fill in cast.fills(
        schema, pinned, {use["slot"] for use in uses}, {use["id"] for use in uses if use["id"]} | ({start} if start else set()))]
    steps.append(await _shown_step(state, schema, settings, menu or [], uses,
                                   {"id": start, "name": names[start], "slot": first_frame} if start else None,
                                   {"step": earlier, "slot": first_frame} if chained else None, agent.why(proposed)))
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
            "prompt": settings["values"][roles["prompt"]["id"]], "facts": workflows.summary(schema, ctx), "time": quote["text"],
            "credits": quote["credits"], "settings": settings, "start": start, "uses": uses, "after": after,
            "shape": agent.shape_of(schema, settings, ctx), "why": why, "keep": settings.get("keep"),
            # What the card offers: the other workflows of the same kind, and this one's shapes, sizes and lengths.
            "menu": {"workflows": [w for w in menu if w["kind"] == kind],
                     "shapes": bool(schema.get("size") or aspect), "resolutions": resolutions,
                     "durations": SHOT_LENGTHS if "duration" in roles else []},
            "current": {"orientation": _orientation(schema, settings, ctx), "resolution": ctx.get("resolution"),
                        "duration": int(ctx["duration"]) if ctx.get("duration") else None}}
