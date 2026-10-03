"""Creating: workflows, estimates, jobs and the live event stream."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

import httpx

from ..catalog import KINDS
from ..comfy import workflows
from ..references import UPLOAD_PREFIX, upload_reference
from .deps import COOKIE, current_user, user_for_token

router = APIRouter(prefix="/api", tags=["studio"])


def price(state, wf, settings):
    """Time estimate and credit cost of a job with these settings."""
    schema = workflows.describe(wf)
    estimate = workflows.estimate(wf, settings, state.jobs.history())
    estimate["credits"] = state.credits.cost(estimate["minutes"], workflows.clip_count(schema, settings))
    return estimate


@router.get("/status")
async def status(request: Request, user: dict = Depends(current_user)):
    comfy = request.app.state.comfy
    try:
        stats = await comfy.stats()
        return {"online": True, "version": stats.get("system", {}).get("comfyui_version")}
    except (httpx.HTTPError, ValueError):
        return {"online": False}


@router.get("/workflows")
async def list_workflows(request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    return {"workflows": await state.catalog.listing(), "kinds": KINDS, "default": state.settings.default_workflow}


@router.get("/workflows/{kind}/{name}")
async def get_workflow(kind: str, name: str, request: Request, user: dict = Depends(current_user)):
    return workflows.describe(await request.app.state.catalog.load("{}/{}".format(kind, name)))


@router.post("/estimate")
async def estimate(settings: dict, request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    wf = await state.catalog.load(str(settings.get("workflow", "")))
    return dict(price(state, wf, settings), balance=state.credits.balance(user["id"]))


@router.get("/jobs")
async def list_jobs(request: Request, user: dict = Depends(current_user)):
    return {"jobs": request.app.state.jobs.snapshot(user["id"])}


@router.post("/jobs")
async def create_job(request: Request, user: dict = Depends(current_user)):
    """Multipart form: "settings" (JSON) plus one file per filled reference slot, named "ref:<slot id>".

    A slot can instead reuse a file: {"comfy_name": ...} for one already on the render server,
    or {"asset_id": ...} for one of the user's saved assets.
    """
    state = request.app.state
    form = await request.form()
    try:
        settings = json.loads(form["settings"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "Missing or broken settings.")
    wf = await state.catalog.load(str(settings.get("workflow", "")))
    schema = workflows.describe(wf)
    slots = {r["id"] for r in schema["refs"]}

    project_id = settings.get("project_id") or None
    if project_id and not state.db.one("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user["id"])):
        raise HTTPException(400, "That project doesn't exist.")

    refs = {}
    for slot, ref in (settings.get("refs") or {}).items():
        if slot not in slots or not isinstance(ref, dict):
            continue
        if ref.get("asset_id"):
            asset = state.db.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (ref["asset_id"], user["id"]))
            path = asset and state.assets_dir / str(user["id"]) / asset["filename"]
            if not asset or not path.is_file():
                raise HTTPException(400, "A saved asset used here no longer exists.")
            refs[slot] = {"comfy_name": await upload_reference(state.comfy, asset["filename"], path.read_bytes()),
                          "name": asset["name"]}
        elif str(ref.get("comfy_name", "")).startswith(UPLOAD_PREFIX):
            refs[slot] = {"comfy_name": str(ref["comfy_name"]), "name": str(ref.get("name", ""))}
    for key, upload in form.multi_items():
        if not key.startswith("ref:") or key[4:] not in slots or not hasattr(upload, "filename"):
            continue
        name = await upload_reference(state.comfy, upload.filename, await upload.read(), upload.content_type)
        refs[key[4:]] = {"comfy_name": name, "name": upload.filename}
    settings["refs"] = refs

    _, ctx = workflows.build_prompt(wf, dict(settings, clips=1))  # fails here, not in the queue, if a setting is wrong
    ctx = dict(workflows.context(schema, settings), seed=ctx.get("seed"))
    # What the library's details panel shows later: the prompt and each named setting as it was used.
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    values = settings.get("values") or {}
    if "prompt" in roles:
        settings["prompt"] = str(values.get(roles["prompt"]["id"], roles["prompt"]["default"]) or "")
    settings["details"] = [[c["label"].split(" (")[0], values.get(c["id"], c["default"])] for c in schema["controls"] if not c["role"]]
    settings["workflow_title"] = schema["title"]
    quote = price(state, wf, settings)
    name = str(settings.get("name") or wf["id"].split("/", 1)[1]).strip()[:80]
    if not state.credits.charge(user["id"], quote["credits"], "generation"):
        raise HTTPException(402, "This needs {} credits and you have {}. Ask an admin for more.".format(
            quote["credits"], state.credits.balance(user["id"])))
    job_id = state.jobs.add(user["id"], name, wf["id"], settings, workflows.summary(schema, ctx),
                            quote["minutes"] * 60 if quote["minutes"] else None, quote["credits"], project_id)
    return {"id": job_id, "credits": quote["credits"]}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, user: dict = Depends(current_user)):
    if not request.app.state.jobs.remove(user["id"], job_id):
        raise HTTPException(404, "No such job.")
    return {"ok": True}


@router.get("/ref-preview")
async def ref_preview(name: str, request: Request, user: dict = Depends(current_user)):
    """Show a reference that is already in ComfyUI's input folder (used by "Re-run")."""
    if not name.startswith(UPLOAD_PREFIX) or "/" in name or "\\" in name:
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
    if user is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    state.hub.add(user["id"], ws)
    try:
        await ws.send_text(state.live_message(user["id"]))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.discard(user["id"], ws)
