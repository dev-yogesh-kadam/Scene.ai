"""The kit of a project (see kit.py): what it is made from, by name, and what is always on in its shots.

GET    /api/kit?project=          the entries, in order (none outside a project)
POST   /api/kit                   add: a file (multipart "file", "name", "type", "project_id", "always"), a library item
                                  (JSON {"item", "name", "type", "project_id", "always"}) or a script (JSON {"text", "name"})
PUT    /api/kit/{id}              change: name, type, about, use_note, always
POST   /api/kit/order             {"project_id", "ids"}: the entries in this order
DELETE /api/kit/{id}

What the user reads calls it the NeuralCore. Each project has its own; its modules share it; there is none outside a project.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import gpu, kit, memory
from ..references import media_kind, read_text_upload, read_upload, text_kind
from .deps import current_user
from .workspace import _project_id

router = APIRouter(prefix="/api/kit", tags=["kit"])
SCRIPT_CHARS = 200_000   # the most a script typed or pasted into the kit holds


def _folder(request, user):
    return request.app.state.assets_dir / str(user["id"])


def describe_soon(request, user, project):
    """Have the agent's model look at the kit's pictures it has not described yet, in the background: the panel and
    the agent read the cards when they are done. It waits for renders queued on a shared GPU (politely)."""
    state = request.app.state
    if not user.get("agent"):
        return
    entries = [memory._asset_entry(row) for row in kit.entries(state.db, user["id"], project) if not row["about"]]
    if not any(e["kind"] in ("image", "video") for e in entries):
        return

    async def look():
        with gpu.politely():
            await memory.describe_missing(state, user["id"], entries, limit=8, seconds=600)
    asyncio.ensure_future(look()).add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


@router.get("")
async def get_kit(request: Request, project: int = 0, user: dict = Depends(current_user)):
    state = request.app.state
    project = _project_id(request, user, project) or None
    describe_soon(request, user, project)
    return {"entries": [memory.kit_row(e) for e in kit.entries(state.db, user["id"], project)], "project": bool(project),
            "types": [{"id": tag, "label": said} for tag, said in kit.TYPES.items()]}


@router.post("")
async def add_entry(request: Request, user: dict = Depends(current_user)):
    state = request.app.state
    folder = _folder(request, user)
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        project = _project_id(request, user, body.get("project_id")) or None
        if not project:
            raise HTTPException(400, "The NeuralCore belongs to a project. Open a project first.")
        name, tag, always = kit.clean_name(body.get("name")), kit.tag_of(body.get("type")), bool(body.get("always"))
        if body.get("item"):
            asset = kit.add_item(state.db, folder, state.outputs.folder(user["id"]), user["id"], project, body["item"],
                                 name, tag, always, named=bool(name) or True)
            if asset is None:
                raise HTTPException(404, "No such library item.")
            if name or body.get("type"):
                kit.update(state.db, user["id"], asset, {**({"name": name} if name else {}), **({"type": body["type"]} if body.get("type") else {})})
        elif isinstance(body.get("text"), str) and body["text"].strip():
            if not name:
                raise HTTPException(400, "Give the script a name.")
            words = body["text"].strip()[:SCRIPT_CHARS].encode("utf-8")
            asset = kit.add(state.db, folder, user["id"], project, words, name + ".txt", "text", name, body.get("type") or "script", always)
        else:
            raise HTTPException(400, "Send a file, a library item or the text of a script.")
    else:
        form = await request.form()
        upload = form.get("file")
        if not hasattr(upload, "filename"):
            raise HTTPException(400, "Choose a file.")
        project = _project_id(request, user, form.get("project_id")) or None
        if not project:
            raise HTTPException(400, "The NeuralCore belongs to a project. Open a project first.")
        if text_kind(upload.filename):
            data, filename = await read_text_upload(upload)
            kind = "text"
        else:
            kind, filename = media_kind(upload.filename), upload.filename
            if kind is None:
                raise HTTPException(400, "Use a picture, a video, a sound, or a script (.txt, .md, .docx).")
            data = await read_upload(upload)
        tag = form.get("type") or ("script" if kind == "text" else "voice" if kind == "audio" else "other")
        asset = kit.add(state.db, folder, user["id"], project, data, filename, kind,
                        str(form.get("name") or filename.rsplit(".", 1)[0]), tag, str(form.get("always") or "") in ("1", "true", "on"),
                        use_note=str(form.get("use_note") or ""))
    describe_soon(request, user, project)
    return memory.kit_row(kit.entry(state.db, user["id"], asset))


@router.put("/{asset_id}")
async def change_entry(asset_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    found = kit.update(request.app.state.db, user["id"], asset_id, body)
    if found is None:
        raise HTTPException(404, "No such kit entry.")
    return memory.kit_row(found)


@router.post("/order")
async def order_entries(body: dict, request: Request, user: dict = Depends(current_user)):
    project = _project_id(request, user, body.get("project_id")) or None
    ids = [i for i in body.get("ids") or [] if isinstance(i, int)]
    kit.reorder(request.app.state.db, user["id"], project, ids)
    return {"entries": [memory.kit_row(e) for e in kit.entries(request.app.state.db, user["id"], project)]}


@router.delete("/{asset_id}")
async def delete_entry(asset_id: int, request: Request, user: dict = Depends(current_user)):
    if not kit.remove(request.app.state.db, _folder(request, user), user["id"], asset_id):
        raise HTTPException(404, "No such kit entry.")
    return {"ok": True}
