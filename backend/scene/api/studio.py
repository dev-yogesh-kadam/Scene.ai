"""Creating: workflows, estimates, jobs and the live event stream."""

import json
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

import httpx

from .. import media, memory
from ..catalog import KINDS
from ..comfy import workflows
from ..agent import AgentError
from ..references import media_kind, owns_upload, read_upload, upload_reference
from ..security import same_origin
from .deps import COOKIE, current_user, limited, user_for_token

router = APIRouter(prefix="/api", tags=["studio"])
PAGE = re.compile(r"^#/[a-z]{1,20}$")   # a page of the studio, as the browser names it: "#/canvas"


def current_announcement(db):
    try:
        found = json.loads(db.setting("announcement", "{}") or "{}")
    except ValueError:
        return {}
    if not found.get("text") or (found.get("until") and found["until"] < time.time()):
        return {}
    return {"text": found["text"], "level": found.get("level", "info"), "until": found.get("until")}


async def billed_seconds(state, wf, schema, settings, user_id=None):
    """The length of the result these settings ask for, which is what a per-second price is based on. None when
    the workflow does not say."""
    ctx = workflows.context(schema, settings)
    if ctx.get("duration"):
        return ctx["duration"] * ctx.get("clips", 1)
    # A workflow whose length is not a duration control names the control in its presets file.
    named = (wf["profile"].get("pricing") or {}).get("seconds")
    control = next((c for c in schema["controls"] if c["id"] == named), None)
    if control:
        try:
            return max(0.0, float((settings.get("values") or {}).get(control["id"], control["default"])))
        except (TypeError, ValueError):
            return None
    if not wf["id"].startswith("upscaler/"):
        return None
    # An upscale is as long as the video it is made from. For a file the user brought, the browser says how long
    # it is for the estimate, and the job is charged by what the server measures (see create_job).
    given = settings.get("source_seconds")
    if isinstance(given, (int, float)) and not isinstance(given, bool) and 0 < given < 86400:
        return float(given)
    parent = settings.get("parent")
    if user_id and isinstance(parent, int):
        row = state.db.one("SELECT filename, context FROM generations WHERE id = ? AND user_id = ? AND kind = 'video'", (parent, user_id))
        if row:
            known = json.loads(row["context"] or "{}").get("duration")
            path = state.outputs.folder(user_id) / row["filename"]
            return float(known) if known else (await media.probe(path))["seconds"] if path.is_file() else None
    return None


async def price(state, wf, settings, user_id=None):
    """Time estimate and credit cost of a job with these settings. The cost follows what was asked for, not the time."""
    schema = workflows.describe(wf)
    estimate = workflows.estimate(wf, settings, state.jobs.history())
    estimate["seconds"] = await billed_seconds(state, wf, schema, settings, user_id)
    estimate["credits"] = state.credits.cost(wf["id"], estimate["seconds"])
    return estimate


def switched_on(state, workflow_id):
    if not state.credits.enabled(workflow_id):
        raise HTTPException(400, "This workflow is switched off for now.")


@router.get("/status")
async def status(request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    try:
        stats = await state.comfy.stats()
        state.saw_server(True)
        return {"online": True, "version": stats.get("system", {}).get("comfyui_version"), "page": state.page_version()}
    except (httpx.HTTPError, ValueError):
        state.saw_server(False)
        return {"online": False, "page": state.page_version()}   # the version of the page files, for a tab opened before a change


@router.get("/announcement")
async def announcement(request: Request, user: dict = Depends(current_user)):
    """The message an admin wants every user to see, while it lasts. Empty when there is none."""
    return current_announcement(request.app.state.db)


@router.get("/workflows")
async def list_workflows(request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    listed = [w for w in await state.catalog.listing() if state.credits.enabled(w["id"])]
    return {"workflows": listed, "kinds": KINDS, "default": state.catalog.current(state.settings.default_workflow)}


@router.get("/workflows/{kind}/{name}")
async def get_workflow(kind: str, name: str, request: Request, user: dict = Depends(current_user)):
    return workflows.describe(await request.app.state.catalog.load("{}/{}".format(kind, name)))


@router.post("/estimate", dependencies=[limited("estimate", 120, 60)])
async def estimate(settings: dict, request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    wf = await state.catalog.load(str(settings.get("workflow", "")))
    switched_on(state, wf["id"])
    return dict(await price(state, wf, settings, user["id"]), balance=state.credits.balance(user["id"]))


@router.get("/jobs")
async def list_jobs(request: Request, user: dict = Depends(current_user)):
    return {"jobs": request.app.state.jobs.snapshot(user["id"])}


async def _write_caption(state, wf, settings, prompt_id):
    """Some image models only work well with a structured JSON caption (a presets file says so with "caption").
    A prompt in plain words is turned into one by the agent's model, with the instructions the workflow carries.
    The plain prompt stays in settings["prompt"], which is what the library shows."""
    rule = wf["profile"].get("caption")
    plain = settings["prompt"].strip()
    if not rule or not plain:
        return
    try:
        if isinstance(json.loads(plain), dict):
            return   # already a caption
    except ValueError:
        pass
    node, _, name = str(rule.get("template", "")).rpartition(":")
    template = (wf["nodes"].get(node) or {}).get("inputs", {}).get(name)
    if not isinstance(template, str):
        raise HTTPException(400, "{}.studio.json names a caption template that is not in the workflow.".format(wf["id"]))
    values = settings.setdefault("values", {})
    ratio = str(values.get(rule.get("ratio")) or wf["nodes"].get(str(rule.get("ratio", "")).rpartition(":")[0], {})
                .get("inputs", {}).get(str(rule.get("ratio", "")).rpartition(":")[2]) or "auto").split(" ")[0]
    try:
        values[prompt_id] = await state.agent.caption(template, plain, ratio)
    except AgentError as error:
        raise HTTPException(400, "This model needs a structured caption, which the agent writes from your prompt. {} "
                                 "Nothing was charged.".format(error))


async def _video_seconds(state, data, filename):
    """How long a video that arrived as bytes is, or None when it can't be read as one."""
    folder = state.storage_dir / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "measure_{}{}".format(uuid.uuid4().hex, Path(filename or "").suffix[:8])
    try:
        path.write_bytes(data)
        return (await media.probe(path))["seconds"] or None
    except media.MediaError:
        return None
    finally:
        path.unlink(missing_ok=True)


@router.post("/jobs", dependencies=[limited("jobs", 30, 60)])
async def create_job(request: Request, user: dict = Depends(current_user)):
    """Multipart form: "settings" (JSON) plus one file per filled reference slot, named "ref:<slot id>".

    A slot can instead reuse a file: {"comfy_name": ...} for one this user already put on the render server,
    or {"asset_id": ...} for one of the user's saved assets.
    """
    state = request.app.state
    form = await request.form(max_files=24, max_fields=64)
    try:
        settings = json.loads(form["settings"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "Missing or broken settings.")
    wf = await state.catalog.load(str(settings.get("workflow", "")))
    switched_on(state, wf["id"])
    schema = workflows.describe(wf)
    settings["workflow"] = wf["id"]   # the id it goes by now, if it was asked for by the id of a workflow it replaced
    slots = workflows.refs_in_use(schema, settings)   # a file for a slot the chosen mode does not read is not sent on

    project_id = settings.get("project_id") or None
    if project_id and not state.db.one("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user["id"])):
        raise HTTPException(400, "That project doesn't exist.")

    # The library item this is made from, if any: the canvas puts the result on the same row.
    parent = settings.get("parent")
    owned = isinstance(parent, int) and state.db.one("SELECT 1 FROM generations WHERE id = ? AND user_id = ?", (parent, user["id"]))
    settings["parent"] = parent if owned else None
    # A result the agent planned as something to reuse is kept in shared memory when it is done: only a type and a name.
    settings["keep"] = memory.clean_keep(settings.get("keep"), wf["id"].split("/", 1)[0])

    # The length of a video the user brought to an upscaler, measured here: it is what the upscale is charged by.
    videos = {r["id"] for r in schema["refs"] if r["kind"] == "video"} if wf["id"].startswith("upscaler/") else set()
    settings.pop("source_seconds", None)

    async def measure(slot, data, filename):
        if slot in videos:
            settings["source_seconds"] = await _video_seconds(state, data, filename) or settings.get("source_seconds")

    refs = {}
    for slot, ref in (settings.get("refs") or {}).items():
        if slot not in slots or not isinstance(ref, dict):
            continue
        if ref.get("asset_id"):
            asset = state.db.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (ref["asset_id"], user["id"]))
            path = asset and state.assets_dir / str(user["id"]) / asset["filename"]
            if not asset or not path.is_file():
                raise HTTPException(400, "A saved asset used here no longer exists.")
            data = path.read_bytes()
            await measure(slot, data, asset["filename"])
            refs[slot] = {"comfy_name": await upload_reference(state.comfy, asset["filename"], data, db=state.db, user_id=user["id"]),
                          "name": asset["name"]}
        elif ref.get("comfy_name"):
            # Only a file this user put on the render server: another user's file name must not be usable.
            if not owns_upload(state.db, user["id"], ref["comfy_name"]):
                raise HTTPException(400, "A reference file used here is not one of yours. Add it again.")
            refs[slot] = {"comfy_name": str(ref["comfy_name"]), "name": str(ref.get("name", ""))[:200]}
    kinds = {r["id"]: r["kind"] for r in schema["refs"]}
    labels = {r["id"]: r["label"] for r in schema["refs"]}
    for key, upload in form.multi_items():
        if not key.startswith("ref:") or key[4:] not in slots or not hasattr(upload, "filename"):
            continue
        given, wanted = media_kind(upload.filename), kinds.get(key[4:])
        if wanted and given and given != wanted and not (wanted == "audio" and given == "video"):
            raise HTTPException(400, "{} is not {} file.".format(upload.filename, {"image": "an image", "video": "a video", "audio": "a sound"}[wanted]))
        data = await read_upload(upload)
        await measure(key[4:], data, upload.filename)
        name = await upload_reference(state.comfy, upload.filename, data, upload.content_type, db=state.db, user_id=user["id"])
        refs[key[4:]] = {"comfy_name": name, "name": upload.filename[:200]}
        # Shared memory keeps every file dropped into a job, as an upload of this project, so it can be used again by name.
        try:
            memory.keep_upload(state.db, state.assets_dir / str(user["id"]), user["id"], project_id, upload.filename,
                               data, given or wanted or "image", labels.get(key[4:], ""))
        except OSError:
            pass   # the job does not depend on the copy
    settings["refs"] = refs

    _, ctx = workflows.build_prompt(wf, dict(settings, clips=1))  # fails here, not in the queue, if a setting is wrong
    ctx = dict(workflows.context(schema, settings), seed=ctx.get("seed"))
    # What the library's details panel shows later: the prompt and each named setting as it was used.
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    values = settings.get("values") or {}
    if "prompt" in roles:
        settings["prompt"] = str(values.get(roles["prompt"]["id"], roles["prompt"]["default"]) or "")
        await _write_caption(state, wf, settings, roles["prompt"]["id"])
    settings["details"] = [[c["label"].split(" (")[0], values.get(c["id"], c["default"])] for c in schema["controls"] if not c["role"]]
    settings["workflow_title"] = schema["title"]
    quote = await price(state, wf, settings, user["id"])
    name = str(settings.get("name") or wf["id"].split("/", 1)[1]).strip()[:80]
    over = state.credits.cap_problem(user["id"], quote["credits"])
    if over:
        raise HTTPException(429, over)
    if not state.credits.charge(user["id"], quote["credits"], "generation"):
        raise HTTPException(402, "This needs {} credits and you have {}. Ask an admin for more.".format(
            quote["credits"], state.credits.balance(user["id"])))
    job_id = state.jobs.add(user["id"], name, wf["id"], settings, workflows.summary(schema, ctx),
                            quote["minutes"] * 60 if quote["minutes"] else None, quote["credits"], project_id, quote["seconds"])
    return {"id": job_id, "credits": quote["credits"]}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, user: dict = Depends(current_user)):
    if not request.app.state.jobs.remove(user["id"], job_id):
        raise HTTPException(404, "No such job.")
    return {"ok": True}


@router.get("/ref-preview")
async def ref_preview(name: str, request: Request, user: dict = Depends(current_user)):
    """Show a reference of this user's that is already in ComfyUI's input folder (used by "Re-run")."""
    if not owns_upload(request.app.state.db, user["id"], name):
        raise HTTPException(404, "No such file.")
    response = await request.app.state.comfy.view(name, "", "input")
    if response.status_code != 200:
        await response.aclose()
        raise HTTPException(404, "ComfyUI no longer has this file.")

    async def body():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
    return StreamingResponse(body(), media_type=response.headers.get("content-type", "application/octet-stream"))


@router.websocket("/events")
async def events(ws: WebSocket):
    state = ws.app.state
    user = user_for_token(state.db, ws.cookies.get(COOKIE))
    if user is None or not same_origin(ws):   # another site's page must not open a connection with the user's cookie
        await ws.close(code=4401)
        return
    await ws.accept()
    state.hub.add(user["id"], ws, admin=user["role"] == "admin")
    try:
        await ws.send_text(state.live_message(user["id"]))
        while True:
            # The page tells which part of the studio it shows, for the admin's list of who is online.
            try:
                page = str(json.loads(await ws.receive_text()).get("page", ""))
            except (ValueError, AttributeError):
                continue
            if PAGE.match(page):
                state.hub.set_page(ws, page)
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.discard(user["id"], ws)
