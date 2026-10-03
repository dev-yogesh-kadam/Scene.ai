"""Saved assets: characters, outfits, backgrounds and voices a user keeps to reuse as references."""

import hashlib
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..references import media_kind, safe_name
from .deps import current_user

router = APIRouter(prefix="/api/assets", tags=["assets"])
TAGS = ("character", "outfit", "background", "prop", "voice", "other")
MAX_BYTES = 200 * 1024 * 1024


def _folder(request, user):
    folder = request.app.state.assets_dir / str(user["id"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _own(request, user, asset_id):
    row = request.app.state.db.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (asset_id, user["id"]))
    if row is None:
        raise HTTPException(404, "No such asset.")
    return row


def _insert(request, user, name, tag, kind, filename, size):
    asset_id = request.app.state.db.run(
        "INSERT INTO assets (user_id, name, tag, kind, filename, size, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["id"], name.strip()[:60] or "Untitled", tag if tag in TAGS else "other", kind, filename, size, time.time()))
    return {"id": asset_id}


@router.get("")
async def list_assets(request: Request, kind: str = "", user: dict = Depends(current_user)):
    sql, params = "SELECT id, name, tag, kind, filename, size, created FROM assets WHERE user_id = ?", [user["id"]]
    if kind == "audio":  # a voice slot also takes the sound of a video
        sql += " AND kind IN ('audio', 'video')"
    elif kind in ("image", "video"):
        sql, params = sql + " AND kind = ?", params + [kind]
    return {"assets": request.app.state.db.all(sql + " ORDER BY tag, name COLLATE NOCASE", params), "tags": TAGS}


@router.post("")
async def create_asset(request: Request, user: dict = Depends(current_user)):
    """Multipart form with "file", "name" and "tag"; or JSON {"generation_id", "name", "tag"} to keep a library image."""
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        item = request.app.state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?",
                                        (body.get("generation_id"), user["id"]))
        source = item and request.app.state.output_dir / str(user["id"]) / item["filename"]
        if not item or not source.is_file():
            raise HTTPException(404, "No such library item.")
        filename = "{}_{}".format(int(time.time()), source.name)
        shutil.copyfile(source, _folder(request, user) / filename)
        return _insert(request, user, str(body.get("name") or item["name"]), str(body.get("tag", "character")),
                       item["kind"], filename, source.stat().st_size)

    form = await request.form()
    upload = form.get("file")
    if not hasattr(upload, "filename"):
        raise HTTPException(400, "Choose a file.")
    kind = media_kind(upload.filename)
    if kind is None:
        raise HTTPException(400, "Use an image, video or audio file.")
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "The file is larger than 200 MB.")
    filename = "{}_{}".format(hashlib.sha1(data).hexdigest()[:10], safe_name(upload.filename))
    (_folder(request, user) / filename).write_bytes(data)
    return _insert(request, user, str(form.get("name") or upload.filename.rsplit(".", 1)[0]),
                   str(form.get("tag", "character")), kind, filename, len(data))


@router.get("/{asset_id}/file")
async def get_file(asset_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, asset_id)
    path = _folder(request, user) / row["filename"]
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    return FileResponse(path)


@router.put("/{asset_id}")
async def update_asset(asset_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, asset_id)
    name = str(body.get("name", row["name"])).strip()[:60] or row["name"]
    tag = body.get("tag", row["tag"])
    request.app.state.db.run("UPDATE assets SET name = ?, tag = ? WHERE id = ?",
                             (name, tag if tag in TAGS else row["tag"], asset_id))
    return {"ok": True}


@router.delete("/{asset_id}")
async def delete_asset(asset_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, asset_id)
    db = request.app.state.db
    db.run("DELETE FROM assets WHERE id = ?", (asset_id,))
    if not db.one("SELECT 1 FROM assets WHERE user_id = ? AND filename = ?", (user["id"], row["filename"])):
        (_folder(request, user) / row["filename"]).unlink(missing_ok=True)
    return {"ok": True}
