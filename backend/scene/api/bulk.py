"""Bulk generation, an admin's tool for testing and comparing workflows: prompts down the side, workflows across the
top, each prompt sent to each workflow (as many takes as asked), all of it one run. The compare board of the canvas
shows a run as that grid, as it fills in: what each cell made, how long it took, and why one failed. The results land
on the canvas of the project it was started from too, like any other generation. Free, like a test run. Admins only.

Every job of a run carries its run ("bulk-<id>", in jobs.run) and its place in the grid in its settings: bulk_row (which
prompt), bulk_take, and its workflow. With "same seed" every cell of a take renders on one seed, so the workflows are
compared on equal terms.

GET    /api/bulk/workflows?kind=image   the workflows of a kind, with the pictures each takes
POST   /api/bulk                        multipart: kind, prompts (JSON list), workflows (JSON list), takes, same_seed,
                                        quality, project_id, for videos resolution, orientation and duration, and up
                                        to six "picture" files
GET    /api/bulk/runs                   the runs, newest first
GET    /api/bulk/runs/{run}             one run as its grid
DELETE /api/bulk/runs/{run}             stop it: its waiting jobs are cancelled
POST   /api/bulk/runs/{run}/again       {"job": id}: one cell made again, on a new seed
"""

import json
import random
import re
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit, errors, sharing
from ..comfy import workflows
from ..comfy.workflows import WorkflowError
from ..references import media_kind, read_upload, upload_reference
from .deps import current_user
from .studio import needs_caption

router = APIRouter(prefix="/api/bulk", tags=["bulk"])
KINDS = ("image", "video")
MOST_PICTURES = 6
MOST_PROMPTS = 20
MOST_TAKES = 4
MOST_JOBS = 400   # prompts x workflows x takes in one run
RUN = re.compile(r"^bulk-[0-9a-f]{10}$")


def admin_only(user: dict = Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Bulk generation is for admins.")
    return user


def _needs(wf):
    """Its schema, its picture slots in order, and the files it can't run without that are not pictures."""
    schema = workflows.describe(wf)
    used = workflows.refs_in_use(schema, {"options": {}})
    pictures = [r for r in schema["refs"] if r["kind"] == "image" and r["id"] in used]
    other = [r["label"] for r in schema["refs"] if r["kind"] != "image" and r["id"] in used and r.get("required")]
    return schema, pictures, other


@router.get("/workflows")
async def bulk_workflows(request: Request, kind: str = "image", user: dict = Depends(admin_only)):
    if kind not in KINDS:
        raise HTTPException(400, "Bulk runs are for images or videos.")
    state, found = request.app.state, []
    for item in await state.catalog.listing():
        if not item["id"].startswith(kind + "/"):
            continue
        try:
            schema, pictures, other = _needs(await state.catalog.load(item["id"]))
        except WorkflowError as error:
            found.append({"id": item["id"], "title": item.get("title") or item["id"], "error": str(error)})
            continue
        found.append({"id": item["id"], "title": schema["title"], "pictures": len(pictures),
                      "needs_pictures": sum(1 for r in pictures if r.get("required")), "needs_other": other})
    return {"workflows": found}


def _settings(wf, prompt, pictures, quality, resolution, orientation, duration):
    """The settings of one cell's job, checked: a setting that is wrong fails here, not in the queue."""
    schema, slots, other = _needs(wf)
    title = schema["title"]
    if other:
        raise WorkflowError("It needs {} as well.".format(", ".join(other)))
    needed = sum(1 for r in slots if r.get("required"))
    if needed > len(pictures):
        raise WorkflowError("It needs {} picture{}.".format(needed, "" if needed == 1 else "s"))
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    settings = {"workflow": wf["id"], "name": title, "values": {}, "options": {}, "refs": {}, "seed_mode": "random", "bulk": True}
    if "prompt" in roles:
        settings["values"][roles["prompt"]["id"]] = prompt
    if "duration" in roles and duration:
        settings["values"][roles["duration"]["id"]] = duration
    for option in schema["options"]:
        if option["id"] == "quality" and any(c["id"] == quality for c in option["choices"]):
            settings["options"]["quality"] = quality
    if schema["size"]:
        settings["resolution"] = resolution if resolution in workflows.SHORT_EDGE else schema["size"]["resolution"]
        settings["orientation"] = orientation if orientation in ("landscape", "portrait", "square") else schema["size"]["orientation"]
    settings["refs"] = {slot["id"]: picture for slot, picture in zip(slots, pictures)}
    if "prompt" in roles:
        settings["prompt"] = prompt
        needs_caption(wf, settings, roles["prompt"]["id"])
    settings["details"] = [[c["label"].split(" (")[0], c["default"]] for c in schema["controls"] if not c["role"]]
    settings["workflow_title"] = title
    return schema, settings


def _queue(state, user, wf, schema, settings, project_id):
    _, ctx = workflows.build_prompt(wf, dict(settings, clips=1))
    ctx = dict(workflows.context(schema, settings), seed=ctx.get("seed"))
    estimate = workflows.estimate(wf, settings, state.jobs.history())
    return state.jobs.add(user["id"], settings["workflow_title"], wf["id"], settings, workflows.summary(schema, ctx),
                          estimate["minutes"] * 60 if estimate["minutes"] else None, 0, project_id)


@router.post("")
async def bulk_run(request: Request, user: dict = Depends(admin_only)):
    state = request.app.state
    form = await request.form(max_files=MOST_PICTURES + 2, max_fields=40)
    kind = str(form.get("kind") or "image")
    try:
        prompts = [" ".join(str(p).split())[:4000] for p in json.loads(str(form.get("prompts") or "[]"))]
    except ValueError:
        prompts = []
    if not prompts and form.get("prompt"):   # one prompt, as the panel sent it before the board
        prompts = [str(form.get("prompt"))[:4000]]
    prompts = [p for p in prompts if p.strip()][:MOST_PROMPTS]
    try:
        chosen = list(dict.fromkeys(str(w) for w in json.loads(str(form.get("workflows") or "[]"))))[:60]
    except ValueError:
        chosen = []
    takes = max(1, min(MOST_TAKES, int(form.get("takes") or 1)))
    same_seed = str(form.get("same_seed") or "") in ("1", "true", "on")
    if kind not in KINDS:
        raise HTTPException(400, "Bulk runs are for images or videos.")
    if not chosen:
        raise HTTPException(400, "Pick at least one workflow.")
    if not prompts:
        raise HTTPException(400, "Write at least one prompt.")
    if len(prompts) * len(chosen) * takes > MOST_JOBS:
        raise HTTPException(400, "That is {} renders; one run makes at most {}. Fewer prompts, workflows or takes.".format(
            len(prompts) * len(chosen) * takes, MOST_JOBS))
    project_id = int(form.get("project_id") or 0) or None
    if project_id:
        sharing.require(state.db, user, project_id, "creator")
    quality = str(form.get("quality") or "")
    resolution = int(form.get("resolution") or 0) or None
    orientation = str(form.get("orientation") or "") or None
    duration = float(form.get("duration") or 0) or None
    # The pictures go to the render server once, and every job uses them from there.
    pictures = []
    for upload in [u for k, u in form.multi_items() if k == "picture" and hasattr(u, "filename")][:MOST_PICTURES]:
        if media_kind(upload.filename) != "image":
            raise HTTPException(400, "{} is not a picture.".format(upload.filename))
        data = await read_upload(upload)
        try:
            name = await upload_reference(state.comfy, upload.filename, data, upload.content_type, db=state.db, user_id=user["id"])
        except httpx.HTTPError:
            raise HTTPException(503, "The render server can't be reached, so the pictures can't be sent. Try again when it is on.")
        pictures.append({"comfy_name": name, "name": upload.filename[:200]})

    run = "bulk-" + uuid.uuid4().hex[:10]
    seeds = [random.randrange(1, 2 ** 31) for _ in range(takes)]   # with same_seed: one per take, shared by every cell
    queued, skipped = 0, {}
    # Row by row, so the first prompt's cells are made first and the board fills from the top.
    for row, prompt in enumerate(prompts):
        for take in range(takes):
            for workflow_id in chosen:
                title = workflow_id.split("/", 1)[-1]
                try:
                    wf = await state.catalog.load(workflow_id)
                    if not wf["id"].startswith(kind + "/"):
                        raise WorkflowError("It is not {} workflow.".format("an image" if kind == "image" else "a video"))
                    schema, settings = _settings(wf, prompt, pictures, quality, resolution, orientation, duration)
                    title = schema["title"]
                    settings.update(run=run, bulk_row=row, bulk_take=take)
                    if same_seed:
                        settings.update(seed_mode="fixed", seed=seeds[take])
                    _queue(state, user, wf, schema, settings, project_id)
                    queued += 1
                except (WorkflowError, HTTPException) as error:
                    skipped.setdefault(workflow_id, {"id": workflow_id, "title": title, "why": str(getattr(error, "detail", None) or error)})
    audit.record(request, user, "Bulk run", "{} prompts x {} {} workflows x {} takes".format(len(prompts), len(chosen), kind, takes),
                 "{} queued".format(queued))
    return {"run": run, "queued": queued, "skipped": list(skipped.values())}


def _jobs_of(db, user, run):
    if not RUN.match(run):
        raise HTTPException(404, "There is no such run.")
    rows = db.all("SELECT * FROM jobs WHERE user_id = ? AND run = ? ORDER BY created", (user["id"], run))
    if not rows:
        raise HTTPException(404, "There is no such run.")
    for row in rows:
        row["settings"] = json.loads(row["settings"])
    return rows


@router.get("/runs")
async def bulk_runs(request: Request, user: dict = Depends(admin_only)):
    rows = request.app.state.db.all(
        "SELECT run, MIN(created) AS created, COUNT(*) AS cells, " + ", ".join(
            "SUM(CASE WHEN status = '{0}' THEN 1 ELSE 0 END) AS {0}".format(s) for s in ("queued", "running", "done", "failed", "cancelled"))
        + " FROM jobs WHERE user_id = ? AND run LIKE 'bulk-%' GROUP BY run ORDER BY MIN(created) DESC LIMIT 50", (user["id"],))
    for row in rows:   # what it was about: its first prompt, and how many workflows it compared
        first = request.app.state.db.one("SELECT settings FROM jobs WHERE user_id = ? AND run = ? ORDER BY created LIMIT 1", (user["id"], row["run"]))
        s = json.loads(first["settings"]) if first else {}
        row["prompt"] = str(s.get("prompt") or "")[:140]
        row["kind"] = str(s.get("workflow", "image")).split("/", 1)[0]
    return {"runs": rows}


@router.get("/runs/{run}")
async def bulk_run_grid(run: str, request: Request, user: dict = Depends(admin_only)):
    """The run as its grid: {"run", "kind", "prompts": [...], "workflows": [{"id", "title"}], "takes", "same_seed",
    "cells": [{"job", "row", "take", "workflow", "status", "seconds", "eta", "error", "seed", "items": [{"id", "kind"}]}]}."""
    db = request.app.state.db
    jobs = _jobs_of(db, user, run)
    made = {}
    ids = [j["id"] for j in jobs]
    for i in range(0, len(ids), 200):
        part = ids[i:i + 200]
        for g in db.all("SELECT id, job_id, kind, name FROM generations WHERE user_id = ? AND job_id IN ({}) ORDER BY id".format(
                ", ".join("?" * len(part))), (user["id"], *part)):
            made.setdefault(g["job_id"], []).append({"id": g["id"], "kind": g["kind"], "name": g["name"]})
    prompts, columns, takes, now = {}, {}, 1, time.time()
    cells = []
    for j in jobs:
        s = j["settings"]
        row, take = int(s.get("bulk_row") or 0), int(s.get("bulk_take") or 0)
        prompts.setdefault(row, s.get("prompt") or "")
        columns.setdefault(j["workflow"], s.get("workflow_title") or j["name"])
        takes = max(takes, take + 1)
        ran = (j["finished"] or now) - j["started"] if j["started"] else None
        cells.append({"job": j["id"], "row": row, "take": take, "workflow": j["workflow"], "status": j["status"],
                      "seconds": round(ran, 1) if ran is not None else None, "started": j["started"],
                      "error": errors.for_user(j["error"]) if j["status"] == "failed" else "",
                      "seed": s.get("seed") if s.get("seed_mode") == "fixed" else None, "items": made.get(j["id"], [])})
    first = jobs[0]["settings"]
    return {"run": run, "kind": jobs[0]["workflow"].split("/", 1)[0], "created": jobs[0]["created"],
            "prompts": [prompts[r] for r in sorted(prompts)], "rows": sorted(prompts),
            "workflows": [{"id": w, "title": t} for w, t in columns.items()], "takes": takes,
            "same_seed": first.get("seed_mode") == "fixed", "cells": cells}


@router.delete("/runs/{run}")
async def bulk_stop(run: str, request: Request, user: dict = Depends(admin_only)):
    state = request.app.state
    stopped = 0
    for j in _jobs_of(state.db, user, run):
        if j["status"] == "queued" and state.jobs.remove(user["id"], j["id"]):
            stopped += 1
    audit.record(request, user, "Stopped a bulk run", run, "{} waiting renders cancelled".format(stopped))
    return {"stopped": stopped}


@router.post("/runs/{run}/again")
async def bulk_again(run: str, body: dict, request: Request, user: dict = Depends(admin_only)):
    """One cell made again with what it was given, on a new seed (a cell of a same-seed run keeps its seed)."""
    state = request.app.state
    job = next((j for j in _jobs_of(state.db, user, run) if j["id"] == body.get("job")), None)
    if job is None:
        raise HTTPException(404, "That cell is not in this run.")
    if job["status"] in ("queued", "running"):
        raise HTTPException(400, "It is still being made.")
    try:
        wf = await state.catalog.load(job["workflow"])
        schema = workflows.describe(wf)
        job_id = _queue(state, user, wf, schema, dict(job["settings"]), job["project_id"])
    except WorkflowError as error:
        raise HTTPException(400, str(error))
    # The old job leaves the grid: the new one takes its cell.
    state.db.run("UPDATE jobs SET run = '' WHERE id = ?", (job["id"],))
    return {"job": job_id}
