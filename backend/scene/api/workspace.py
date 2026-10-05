"""The canvas, the timeline and the agent: arranging finished work, joining clips, and planning new work."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import agent, cast, credits, media, motion, sequence
from ..comfy import workflows
from .deps import agent_user, current_user
from .studio import price

router = APIRouter(prefix="/api", tags=["workspace"])

# canvas: where frames sit. timeline: the cut. brief: what the agent should keep true. agent: its past plans.
KINDS = ("canvas", "timeline", "brief", "agent", "cast")
MAX_BOARD_BYTES = 200_000
MAX_CLIPS = 50
EXPORT_WORKFLOW = "edit/timeline"  # what an exported video is filed under; it has no workflow file
MOTION_WORKFLOW = credits.MOTION   # what a rendered motion graphic is filed and priced under
SOUND_WORKFLOW = "edit/sound"      # what a video with a sound put on it is filed under


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
    if kind not in KINDS:
        raise HTTPException(404, "No such board.")
    row = request.app.state.db.one("SELECT data FROM boards WHERE user_id = ? AND project_id = ? AND kind = ?",
                                   (user["id"], _project_id(request, user, project), kind))
    return {"data": json.loads(row["data"]) if row else {}}


@router.put("/boards/{kind}")
async def save_board(kind: str, body: dict, request: Request, user: dict = Depends(current_user)):
    if kind not in KINDS:
        raise HTTPException(404, "No such board.")
    data = json.dumps(body.get("data") or {})
    if len(data) > MAX_BOARD_BYTES:
        raise HTTPException(400, "This is too large to save.")
    request.app.state.db.run(
        "INSERT INTO boards (user_id, project_id, kind, data, updated) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, project_id, kind) DO UPDATE SET data = excluded.data, updated = excluded.updated",
        (user["id"], _project_id(request, user, body.get("project")), kind, data, time.time()))
    return {"ok": True}


@router.post("/timeline/export")
async def export_timeline(body: dict, request: Request, user: dict = Depends(current_user)):
    """Join the timeline's clips into one video and add it to the library. Costs no credits: it needs no GPU."""
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
        path = state.outputs.folder(user["id"]) / row["filename"]
        if not path.is_file():
            raise HTTPException(404, "The file of {} is missing from storage.".format(row["name"]))
        try:
            parts.append((path, float(clip.get("start") or 0), float(clip.get("end") or 0)))
        except (TypeError, ValueError):
            raise HTTPException(400, "The start and end of {} must be numbers.".format(row["name"]))
    # The item an edit was cut from, if the caller names one of the clips: the canvas puts the result on its row.
    parent = body.get("parent") if body.get("parent") in [clip.get("id") for clip in clips] else None
    started = time.time()
    name = str(body.get("name") or "").strip()[:80] or "Timeline"
    target = state.outputs.folder(user["id"]) / "timeline_{}.mp4".format(time.strftime("%Y%m%d_%H%M%S"))
    target.parent.mkdir(parents=True, exist_ok=True)
    seconds = await media.sequence(parts, target)
    frame = await media.probe(target)
    count = "1 clip" if len(parts) == 1 else "{} clips".format(len(parts))
    item_id = state.db.run(
        "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
        "context, seconds, size, created) VALUES (?, NULL, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], project_id, EXPORT_WORKFLOW, name, target.name, "{} joined · {:.0f} s".format(count, seconds),
         json.dumps({"workflow_title": "Timeline export", "clips": clips, "parent": parent}),
         json.dumps({"duration": round(seconds, 1), "width": frame["width"], "height": frame["height"]}),
         round(time.time() - started, 1), target.stat().st_size, time.time()))
    state.notify(user["id"], library_changed=True)
    return {"id": item_id, "name": name, "seconds": round(seconds, 2)}


@router.post("/edit/sound")
async def add_sound(body: dict, request: Request, user: dict = Depends(current_user)):
    """Put one of the user's sounds on one of their videos and add the result to the library. Costs no credits."""
    state = request.app.state
    rows = {}
    for key, kind, what in (("video", "video", "a video"), ("audio", "audio", "a sound")):
        rows[key] = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = ?", (body.get(key), user["id"], kind))
        if rows[key] is None:
            raise HTTPException(400, "Choose {} from your library.".format(what))
    folder = state.outputs.folder(user["id"])
    video, sound = folder / rows["video"]["filename"], folder / rows["audio"]["filename"]
    if not video.is_file() or not sound.is_file():
        raise HTTPException(404, "A file is missing from storage.")
    replace = body.get("replace") is True
    project_id = _project_id(request, user, body.get("project_id")) or rows["video"]["project_id"]
    started = time.time()
    name = (" ".join(str(body.get("name") or "").split()) or "{} with sound".format(rows["video"]["name"]))[:80]
    target = folder / "sound_{}.mp4".format(time.strftime("%Y%m%d_%H%M%S"))
    seconds = await media.add_sound(video, sound, target, replace)
    frame = await media.probe(target)
    item_id = state.db.run(
        "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
        "context, seconds, size, created) VALUES (?, NULL, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], project_id, SOUND_WORKFLOW, name, target.name,
         "{} {} {} · {:.0f} s".format(rows["audio"]["name"], "in place of the sound of" if replace else "under", rows["video"]["name"], seconds),
         json.dumps({"workflow_title": "Sound added", "video": rows["video"]["id"], "audio": rows["audio"]["id"], "replace": replace,
                     "prompt": json.loads(rows["video"]["settings"]).get("prompt", ""), "parent": rows["video"]["id"]}),
         json.dumps({"duration": round(seconds, 1), "width": frame["width"], "height": frame["height"]}),
         round(time.time() - started, 1), target.stat().st_size, time.time()))
    state.notify(user["id"], library_changed=True)
    return {"id": item_id, "name": name, "seconds": round(seconds, 2)}


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
    written = await request.app.state.agent.write_scenes(about, _brief(request, user, project), **_model(body))
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
    """Render a motion graphic and add the video to the library. It is charged by its length before the render
    and refunded if the render fails."""
    state = request.app.state
    _, cost = await _motion_price(state, user, body)
    if not state.credits.charge(user["id"], cost, "generation", note="Motion graphics"):
        raise HTTPException(402, "This needs {} credits and you have {}. Ask an admin for more.".format(cost, state.credits.balance(user["id"])))
    try:
        made = await (_render_sequence if "scenes" in body else _render_template)(body, request, user)
    except BaseException:
        state.credits.add(user["id"], cost, "refund", note="Motion graphics")
        state.notify(user["id"])
        raise
    return dict(made, credits=cost)


async def _render_template(body, request, user):
    """A motion graphic drawn from one of the templates, on its own or over a video."""
    state = request.app.state
    template = next((t for t in motion.templates() if t["id"] == body.get("template")), None)
    if template is None:
        raise HTTPException(404, "There is no such motion template.")
    values = motion.clean(template, body.get("values") if isinstance(body.get("values"), dict) else {})
    project_id = _project_id(request, user, body.get("project_id")) or None
    source = row = None
    if template["needs"] == "video":
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'", (body.get("source"), user["id"]))
        if row is None:
            raise HTTPException(400, "Select a video on the canvas first: {} is laid over a video.".format(template["title"].lower()))
        source = state.outputs.folder(user["id"]) / row["filename"]
        if not source.is_file():
            raise HTTPException(404, "The file of {} is missing from storage.".format(row["name"]))
    started = time.time()
    name = (values.get("title") or template["title"])[:80]
    target = state.outputs.folder(user["id"]) / "motion_{}.mp4".format(time.strftime("%Y%m%d_%H%M%S"))
    made = await motion.render(template["id"], values, target, source, state.settings.node_path, state.storage_dir / "tmp")
    words = " · ".join(str(values[key]) for key in ("title", "subtitle") if values.get(key))
    item_id = state.db.run(
        "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
        "context, seconds, size, created) VALUES (?, NULL, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], project_id, MOTION_WORKFLOW, name, target.name,
         "{}{} · {:.0f} s".format(template["title"], " over " + row["name"] if row else "", made["seconds"]),
         json.dumps({"workflow_title": "Motion graphics · " + template["title"], "template": template["id"], "values": values,
                     "prompt": words, "parent": row["id"] if row else None}),
         json.dumps({"duration": round(made["seconds"], 1), "width": made["width"], "height": made["height"]}),
         round(time.time() - started, 1), target.stat().st_size, time.time()))
    state.notify(user["id"], library_changed=True)
    return {"id": item_id, "name": name, "seconds": round(made["seconds"], 2)}


async def _render_sequence(body, request, user):
    """A motion graphics video made of scenes of words, as the agent plans them."""
    state = request.app.state
    scenes = sequence.clean_scenes(body.get("scenes"))
    look = body.get("look") if body.get("look") in sequence.LOOKS else "dark"
    shape = body.get("shape") if body.get("shape") in motion.SHAPES else "landscape"
    project_id = _project_id(request, user, body.get("project_id")) or None
    started = time.time()
    words = [scene["heading"] or scene["text"] for scene in scenes]
    name = (" ".join(str(body.get("name") or "").split()) or words[0])[:80]
    target = state.outputs.folder(user["id"]) / "motion_{}.mp4".format(time.strftime("%Y%m%d_%H%M%S"))
    made = await motion.render_sequence(scenes, look, shape, target, state.settings.node_path, state.storage_dir / "tmp")
    count = "1 scene" if len(scenes) == 1 else "{} scenes".format(len(scenes))
    item_id = state.db.run(
        "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
        "context, seconds, size, created) VALUES (?, NULL, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], project_id, MOTION_WORKFLOW, name, target.name, "Motion graphics · {} · {:.0f} s".format(count, made["seconds"]),
         json.dumps({"workflow_title": "Motion graphics", "scenes": scenes, "look": look, "shape": shape,
                     "prompt": " / ".join(words)[:600], "parent": None}),
         json.dumps({"duration": round(made["seconds"], 1), "width": made["width"], "height": made["height"]}),
         round(time.time() - started, 1), target.stat().st_size, time.time()))
    state.notify(user["id"], library_changed=True)
    return {"id": item_id, "name": name, "seconds": round(made["seconds"], 2)}


# ---------------------------------------------------------------- agent

@router.get("/agent/status")
async def agent_status(request: Request, user: dict = Depends(agent_user)):
    try:
        # "model" is the one used when the user has not picked another; "models" is what they can pick from.
        brain = request.app.state.agent
        return {"online": True, "model": await brain.pick_model(), "models": await brain.models(), "hosted": brain.hosted()}
    except agent.AgentError as error:
        return {"online": False, "detail": str(error)}


def _model(body):
    """The model the user picked in the agent panel, as a keyword for the agent's calls; nothing when they picked none."""
    picked = body.get("model")
    return {"model": picked[:120]} if isinstance(picked, str) and picked.strip() else {}


def _brief(request, user, project):
    row = request.app.state.db.one("SELECT data FROM boards WHERE user_id = ? AND project_id = ? AND kind = 'brief'", (user["id"], project))
    return json.loads(row["data"]).get("text", "") if row else ""


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
    return {"prompt": await state.agent.improve(prompt, kind, _brief(request, user, project), tips=tips, project_cast=pinned, **_model(body))}


@router.post("/agent/plan")
async def agent_plan(body: dict, request: Request, user: dict = Depends(agent_user)):
    """Ask the agent for a plan. Each step comes back as checked, priced job settings; nothing is queued or charged."""
    state = request.app.state
    instruction = str(body.get("instruction") or "").strip()[:2000]
    if not instruction:
        raise HTTPException(400, "Write a message for the agent.")
    project = _project_id(request, user, body.get("project_id"))
    selection, shapes = [], {}   # shapes: item id -> [width, height], for shots that start on an item
    chosen = (body.get("selection") or [])[:8] if agent.points_at_selection(instruction) else []
    for item_id in chosen:
        row = state.db.one("SELECT id, kind, name, filename, settings, context FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))
        if row:
            # The tag is what the user calls the item in the instruction: the first one attached is @1.
            selection.append({"tag": "@{}".format(len(selection) + 1), "id": row["id"], "kind": row["kind"], "name": row["name"],
                              "prompt": str(json.loads(row["settings"]).get("prompt") or "")[:300]})
            made = json.loads(row["context"] or "{}")
            if made.get("width") and made.get("height"):
                shapes[row["id"]] = [made["width"], made["height"]]
            path = state.outputs.folder(user["id"]) / row["filename"]
            if row["kind"] == "video" and path.is_file():   # the length is what the editing tools cut by
                selection[-1]["seconds"] = round((await media.probe(path))["seconds"], 2)

    # What was made lately here, so "the music you just made" can be put on "this video" without attaching either.
    recent = [{"id": r["id"], "kind": r["kind"], "name": r["name"]} for r in state.db.all(
        "SELECT id, kind, name FROM generations WHERE user_id = ? AND project_id IS ? ORDER BY created DESC LIMIT 8", (user["id"], project or None))]
    known = {s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}
    known.update({r["id"]: {"name": r["name"], "kind": r["kind"]} for r in recent if r["id"] not in known})

    schemas = {}
    for listed in await state.catalog.listing():
        if not listed.get("error") and state.credits.enabled(listed["id"]):
            schemas[listed["id"]] = workflows.describe(await state.catalog.load(listed["id"]))
    offers = [o for o in (agent.offer(schema, bool(selection)) for schema in schemas.values()) if o]
    pinned = cast.load(state.db, user["id"], project)
    if not offers:
        raise HTTPException(400, "There is no workflow the agent can use yet.")
    answer = await state.agent.ask(agent.SYSTEM.format(max_steps=agent.MAX_STEPS),
                                   agent.question(agent.carry_over(instruction, body.get("history")), _brief(request, user, project), offers, selection,
                                                  state.settings.default_workflow, agent.past_turns(body.get("history")), pinned, recent),
                                   [o["id"] for o in offers], **_model(body))

    steps = []
    names = {s["id"]: s["name"] for s in selection}
    kinds = {s["id"]: {"name": s["name"], "kind": s["kind"]} for s in selection}
    videos = [s for s in selection if s.get("seconds")]
    made_by = {}   # the number the model gave a step (1 for its first) -> where that step's result is in `steps`
    for number, proposed in enumerate(answer["steps"][:agent.MAX_STEPS], start=1):
        made_by[number] = len(steps)   # taken back below if the step is dropped
        before = len(steps)
        if isinstance(proposed, dict) and proposed.get("tool") == agent.SOUND_TOOL:
            made = agent.sound_for(proposed, known)
            if made:   # a sound on a video: made on Approve through the sound endpoint, which costs nothing
                steps.append({"name": made["name"], "workflow_title": "Sound", "kind": "video", "prompt": "", "facts": made["facts"],
                              "time": "a few seconds", "credits": 0, "settings": None, "start": None, "sound": made["sound"]})
        else:
            await _plan_step(state, proposed, instruction, steps, made_by, schemas, names, kinds, videos, pinned, project, shapes)
        if len(steps) == before:
            del made_by[number]
    if not steps and agent.wants_sound(instruction, body.get("history")):
        made = agent.sound_for({}, known)   # the model only talked: make the step that was asked for
        if made:
            steps.append({"name": made["name"], "workflow_title": "Sound", "kind": "video", "prompt": "", "facts": made["facts"],
                          "time": "a few seconds", "credits": 0, "settings": None, "start": None, "sound": made["sound"]})
            answer["reply"] = "I'll put {}. Approve to make it.".format(made["facts"])
    return {"reply": answer["reply"] or ("Here is the plan." if steps else "Tell me what you would like to see and I will plan it."),
            "steps": steps[:agent.MAX_STEPS], "total": sum(s["credits"] for s in steps[:agent.MAX_STEPS]), "balance": state.credits.balance(user["id"])}


async def _plan_step(state, proposed, instruction, steps, made_by, schemas, names, kinds, videos, pinned, project, shapes):
    """Check one step the model proposed and add what can be carried out to `steps`. A step that can't run adds nothing."""
    if not isinstance(proposed, dict):
        return
    if proposed.get("tool") in agent.MOTION_TOOLS:
        # Words and shapes drawn by HyperFrames: made on Approve through the motion endpoint, which charges by the length.
        made = agent.motion_for(proposed, videos)
        if made:
            scenes = made["motion"].get("scenes")
            seconds = sum(s["seconds"] for s in scenes) if scenes else next(v["seconds"] for v in videos if v["id"] == made["motion"]["source"])
            steps.append({"name": made["name"], "workflow_title": "Motion graphics", "kind": "video", "prompt": made["words"],
                          "facts": made["facts"], "time": "under a minute",
                          "credits": state.credits.cost(MOTION_WORKFLOW if scenes else credits.OVERLAY, seconds),
                          "settings": None, "start": None, "motion": made["motion"]})
        return
    if proposed.get("tool") == "trim" and agent.parts_asked(instruction):
        if any("edit" in step for step in steps):
            return   # the split is already planned; a second trim of the same video adds nothing
        proposed = dict(proposed, tool="split", parts=agent.parts_asked(instruction))   # the user asked for pieces, not for one cut
    if proposed.get("tool") in agent.EDIT_TOOLS:
        # An edit of videos the user has: the browser runs it through the timeline export, which costs nothing.
        for edit in agent.edits_for(proposed, videos):
            steps.append({"name": edit["name"], "workflow_title": "Edit", "kind": "video", "prompt": "", "facts": edit["facts"],
                          "time": "a few seconds", "credits": 0, "settings": None, "start": None, "edit": {"clips": edit["clips"]}})
        return
    schema = schemas.get(proposed.get("workflow"))
    if not schema or not agent.offer(schema):
        return
    uses = agent.uses_for(schema, proposed, kinds)
    # A step can start on what an earlier step of this plan makes, if that is a picture or a video
    # and this workflow has a first frame to put it in.
    earlier = made_by.get(proposed.get("after"))
    first_frame = (schema.get("slots") or {}).get("first_frame")
    chained = earlier is not None and earlier < len(steps) and bool(first_frame) and steps[earlier]["kind"] != "audio"
    built = agent.settings_for(schema, proposed, set(names), project or None,
                               {use["slot"] for use in uses}, {use["id"] for use in uses}, chained)
    if not built:
        return
    settings, start = built
    # A shot takes the shape of the picture it starts on: a portrait picture in a landscape video comes out squashed.
    agent.shape_like(schema, settings, steps[earlier].get("shape") if chained else shapes.get(start))
    # The project's cast goes into every slot meant for it that the step left empty.
    uses = uses + [dict(fill, cast=True) for fill in cast.fills(
        schema, pinned, {use["slot"] for use in uses}, {use["id"] for use in uses} | ({start} if start else set()))]
    quote = await price(state, await state.catalog.load(schema["id"]), settings)
    ctx = workflows.context(schema, settings)
    steps.append({"name": settings["name"], "workflow_title": schema["title"], "kind": schema["id"].split("/", 1)[0],
                  "prompt": proposed["prompt"].strip(), "facts": workflows.summary(schema, ctx), "time": quote["text"],
                  "credits": quote["credits"], "settings": settings,
                  "start": {"id": start, "name": names[start], "slot": first_frame} if start else None,
                  "uses": uses, "after": {"step": earlier, "slot": first_frame} if chained else None,
                  "shape": agent.shape_of(schema, settings, ctx)})
