"""The canvas, the timeline and the agent: arranging finished work, joining clips, and planning new work."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import agent, media
from ..comfy import workflows
from .deps import current_user
from .studio import price

router = APIRouter(prefix="/api", tags=["workspace"])

# canvas: where frames sit. timeline: the cut. brief: what the agent should keep true. agent: its past plans.
KINDS = ("canvas", "timeline", "brief", "agent")
MAX_BOARD_BYTES = 200_000
MAX_CLIPS = 50
EXPORT_WORKFLOW = "edit/timeline"  # what an exported video is filed under; it has no workflow file


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
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise HTTPException(400, "Put between 1 and {} clips on the timeline.".format(MAX_CLIPS))
    project_id = _project_id(request, user, body.get("project_id")) or None
    parts = []
    for clip in clips:
        row = state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'",
                           (clip.get("id"), user["id"]))
        if row is None:
            raise HTTPException(404, "A clip on the timeline is no longer in your library.")
        path = state.output_dir / str(user["id"]) / row["filename"]
        if not path.is_file():
            raise HTTPException(404, "The file of {} is missing from storage.".format(row["name"]))
        parts.append((path, float(clip.get("start") or 0), float(clip.get("end") or 0)))
    started = time.time()
    name = str(body.get("name") or "").strip()[:80] or "Timeline"
    target = state.output_dir / str(user["id"]) / "timeline_{}.mp4".format(time.strftime("%Y%m%d_%H%M%S"))
    target.parent.mkdir(parents=True, exist_ok=True)
    seconds = await media.sequence(parts, target)
    frame = await media.probe(target)
    count = "1 clip" if len(parts) == 1 else "{} clips".format(len(parts))
    item_id = state.db.run(
        "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
        "context, seconds, size, created) VALUES (?, NULL, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], project_id, EXPORT_WORKFLOW, name, target.name, "{} joined · {:.0f} s".format(count, seconds),
         json.dumps({"workflow_title": "Timeline export", "clips": clips}),
         json.dumps({"duration": round(seconds, 1), "width": frame["width"], "height": frame["height"]}),
         round(time.time() - started, 1), target.stat().st_size, time.time()))
    state.notify(user["id"], library_changed=True)
    return {"id": item_id, "name": name, "seconds": round(seconds, 2)}


# ---------------------------------------------------------------- agent

@router.get("/agent/status")
async def agent_status(request: Request, user: dict = Depends(current_user)):
    try:
        return {"online": True, "model": await request.app.state.agent.pick_model()}
    except agent.AgentError as error:
        return {"online": False, "detail": str(error)}


@router.post("/agent/plan")
async def agent_plan(body: dict, request: Request, user: dict = Depends(current_user)):
    """Ask the agent for a plan. Each step comes back as checked, priced job settings; nothing is queued or charged."""
    state = request.app.state
    instruction = str(body.get("instruction") or "").strip()[:2000]
    if not instruction:
        raise HTTPException(400, "Tell the agent what to make.")
    project = _project_id(request, user, body.get("project_id"))
    brief = state.db.one("SELECT data FROM boards WHERE user_id = ? AND project_id = ? AND kind = 'brief'", (user["id"], project))
    selection = []
    for item_id in (body.get("selection") or [])[:8]:
        row = state.db.one("SELECT id, kind, name, settings FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))
        if row:
            selection.append({"id": row["id"], "kind": row["kind"], "name": row["name"],
                              "prompt": str(json.loads(row["settings"]).get("prompt") or "")[:300]})

    schemas = {}
    for listed in await state.catalog.listing():
        if not listed.get("error"):
            schemas[listed["id"]] = workflows.describe(await state.catalog.load(listed["id"]))
    offers = [o for o in map(agent.offer, schemas.values()) if o]
    if not offers:
        raise HTTPException(400, "There is no workflow the agent can use yet.")
    answer = await state.agent.ask(agent.SYSTEM.format(max_steps=agent.MAX_STEPS),
                                   agent.question(instruction, json.loads(brief["data"]).get("text", "") if brief else "", offers, selection,
                                                  state.settings.default_workflow),
                                   [o["id"] for o in offers])

    steps = []
    names = {s["id"]: s["name"] for s in selection}
    for proposed in answer["steps"][:agent.MAX_STEPS]:
        schema = schemas.get(proposed.get("workflow")) if isinstance(proposed, dict) else None
        built = schema and agent.offer(schema) and agent.settings_for(schema, proposed, set(names), project or None)
        if not built:
            continue
        settings, start = built
        quote = price(state, await state.catalog.load(schema["id"]), settings)
        ctx = workflows.context(schema, settings)
        steps.append({"name": settings["name"], "workflow_title": schema["title"], "kind": schema["id"].split("/", 1)[0],
                      "prompt": proposed["prompt"].strip(), "facts": workflows.summary(schema, ctx), "time": quote["text"],
                      "credits": quote["credits"], "settings": settings,
                      "start": {"id": start, "name": names[start], "slot": schema["slots"]["first_frame"]} if start else None})
    return {"reply": answer["reply"] or ("Here is the plan." if steps else "I couldn't plan that. Say what you want to see."),
            "steps": steps, "total": sum(s["credits"] for s in steps), "balance": state.credits.balance(user["id"])}
