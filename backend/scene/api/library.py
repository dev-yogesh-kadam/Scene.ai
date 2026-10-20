"""The library: each user's finished images and videos, organised in projects."""

import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import fetch, media
from ..catalog import KINDS
from ..references import media_kind, read_text_upload, read_upload, safe_name, text_kind, upload_reference
from .deps import current_user

router = APIRouter(prefix="/api", tags=["library"])


def _path(request, row):
    return request.app.state.outputs.folder(row["user_id"]) / row["filename"]


def _own(request, user, item_id):
    row = request.app.state.db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))
    if row is None:
        raise HTTPException(404, "No such item.")
    return row


def _own_project(request, user, project_id):
    row = request.app.state.db.one("SELECT * FROM projects WHERE id = ? AND user_id = ?", (project_id, user["id"]))
    if row is None:
        raise HTTPException(404, "No such project.")
    return row


# ---------------------------------------------------------------- items

@router.get("/library")
async def list_items(request: Request, kind: str = "", q: str = "", project: str = "", run: str = "",
                     user: dict = Depends(current_user)):
    """`project` is a project id, "none" for items in no project, or empty for everything. `run`: the working files of
    that run (slices, trims, references of a long skill), which are otherwise left out."""
    # Each item comes with what its details panel shows: the job's cost and the project's name.
    sql = ("SELECT g.*, j.cost, p.name AS project_name FROM generations g LEFT JOIN jobs j ON j.id = g.job_id "
           "LEFT JOIN projects p ON p.id = g.project_id WHERE g.user_id = ?")
    sql += " AND g.run = ?"
    params = [user["id"], run[:64]]
    if kind in (*KINDS, "text"):
        sql, params = sql + " AND g.kind = ?", params + [kind]
    if project == "none":
        sql += " AND g.project_id IS NULL"
    elif project.isdigit():
        sql, params = sql + " AND g.project_id = ?", params + [int(project)]
    for word in q.split()[:6]:  # every word must appear in the name, the workflow or the settings (prompt)
        like = "%{}%".format(word.replace("%", r"\%").replace("_", r"\_"))
        sql += " AND (g.name LIKE ? ESCAPE '\\' OR g.workflow LIKE ? ESCAPE '\\' OR g.summary LIKE ? ESCAPE '\\' OR g.settings LIKE ? ESCAPE '\\')"
        params += [like] * 4
    items = request.app.state.db.all(sql + " ORDER BY g.created DESC LIMIT 500", params)
    for item in items:
        item["settings"] = json.loads(item["settings"])
        item["context"] = json.loads(item["context"])
        del item["user_id"]
    return {"items": items}


UPLOADED = "upload/file"   # what an item the user brought in is filed under: it was not made with a workflow


@router.post("/library/upload")
async def upload_item(request: Request, user: dict = Depends(current_user)):
    """Multipart form with "file" (an image, a video, a sound, or a transcript: .srt, .json) and "project_id".
    The file joins the library and the project's canvas like a finished generation, so it can be a frame to start on, a
    reference or a clip on the timeline. Nothing is charged."""
    form = await request.form()
    upload = form.get("file")
    if not hasattr(upload, "filename"):
        raise HTTPException(400, "Choose a file.")
    filename = upload.filename
    if text_kind(upload.filename):   # a script or a transcript: kept as its words (a Word file as plain text)
        (data, filename), kind = await read_text_upload(upload), "text"
    else:
        data = await read_upload(upload)   # refuses what is too large or is not the image, video or sound it says it is
        kind = media_kind(upload.filename)
    project = str(form.get("project_id") or "")
    project_id = _own_project(request, user, int(project))["id"] if project.isdigit() and int(project) else None
    return await _file_in(request, user, data, filename, kind, project_id, "Uploaded")


IMPORTED = "upload/link"   # an item brought in from a link on another site


@router.post("/library/import")
async def import_link(body: dict, request: Request, user: dict = Depends(current_user)):
    """{"url", "project_id"?, "name"?}: the picture, clip or sound at a link on another site, brought into the library
    (see fetch.py for what is fetched and what is refused). Nothing is charged."""
    url = str(body.get("url") or "").strip()
    if not url or len(url) > 2000:
        raise HTTPException(400, "Give the link to bring in.")
    project_id = _own_project(request, user, body["project_id"])["id"] if isinstance(body.get("project_id"), int) and body["project_id"] else None
    try:
        data, kind, final = await fetch.fetch(url)
    except fetch.FetchError as error:
        raise HTTPException(400, str(error))
    name = " ".join(str(body.get("name") or "").split())[:80]
    return await _file_in(request, user, data, fetch.filename_for(final, kind), kind, project_id, "Brought in from a link",
                          workflow=IMPORTED, name=name, source=url)


async def _file_in(request, user, data, filename, kind, project_id, summary, workflow=UPLOADED, name="", source=""):
    """A file the user brought in, saved and filed in the library like a finished generation."""
    folder = request.app.state.outputs.folder(user["id"])
    folder.mkdir(parents=True, exist_ok=True)
    name = name or (filename.rsplit(".", 1)[0].strip() or kind)[:80]
    target = folder / "{}_{}_{}".format("upload", time.strftime("%Y%m%d_%H%M%S"), safe_name(filename))
    target.write_bytes(data)
    # A "video" that is only a sound (cover art, or one frame held still: audio exported "as a video") is kept as the
    # sound it is, its codec copied, and filed as audio.
    if kind == "video" and await media.sound_only(target):
        sound = await media.keep_sound(target, target.stem)
        target.unlink(missing_ok=True)
        target, kind, data = sound, "audio", sound.read_bytes()
    context = {}
    if kind in ("video", "image"):
        found = await media.probe(target)
        context = {k: v for k, v in (("width", found["width"]), ("height", found["height"])) if v}
        if kind == "video" and found["seconds"]:
            context["duration"] = round(found["seconds"], 2)
    elif kind == "audio":
        found = await media.probe(target)
        if found["seconds"]:
            context["duration"] = round(found["seconds"], 2)
    db = request.app.state.db
    db.run("INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
           "context, seconds, size, created) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
           (user["id"], project_id, workflow, kind, name, target.name, summary,
            json.dumps({"name": name, "prompt": "", **({"source": source} if source else {})}), json.dumps(context), len(data), time.time()))
    row = db.one("SELECT * FROM generations WHERE user_id = ? AND filename = ?", (user["id"], target.name))
    return dict(row, settings=json.loads(row["settings"]), context=json.loads(row["context"]))


@router.get("/library/{item_id}/file")
async def get_file(item_id: int, request: Request, download: bool = False, user: dict = Depends(current_user)):
    row = _own(request, user, item_id)
    path = _path(request, row)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    return FileResponse(path, filename=path.name if download else None)


async def poster_response(request, path):
    """A video's poster. The browser keeps it and only asks whether it has changed, which costs no download."""
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    try:
        poster = await media.poster(path)
    except media.MediaError as error:
        raise HTTPException(404, str(error))
    response = FileResponse(poster, stat_result=poster.stat(), headers={"Cache-Control": "private, no-cache"})
    if request.headers.get("if-none-match") == response.headers["etag"]:
        return Response(status_code=304, headers={"ETag": response.headers["etag"], "Cache-Control": "private, no-cache"})
    return response


@router.get("/library/{item_id}/poster")
async def get_poster(item_id: int, request: Request, user: dict = Depends(current_user)):
    return await poster_response(request, _path(request, _own(request, user, item_id)))


@router.get("/library/{item_id}/frame")
async def get_frame(item_id: int, request: Request, at: float = 0.0, user: dict = Depends(current_user)):
    """The frame of a video at `at` seconds, for the keyframes the agent shows under a result. Made once and kept,
    per tenth of a second, next to the video's poster."""
    row = _own(request, user, item_id)
    if row["kind"] != "video":
        raise HTTPException(400, "Only a video has frames.")
    path = _path(request, row)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    tenth = max(0, min(int(round(at * 10)), 36000))
    target = media.poster_path(path).with_name("{}.{}.jpg".format(path.name, tenth))
    if not (target.is_file() and target.stat().st_mtime >= path.stat().st_mtime):
        target.parent.mkdir(exist_ok=True)
        if not await media.frame_at(path, tenth / 10, target):
            raise HTTPException(404, "The video has no frame there.")
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.put("/library/{item_id}")
async def update_item(item_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    """Rename an item, move it to a project (project_id null = no project) or rate it (rating 1, -1, or 0 to clear)."""
    _own(request, user, item_id)
    db = request.app.state.db
    if "name" in body and str(body["name"]).strip():
        db.run("UPDATE generations SET name = ? WHERE id = ?", (str(body["name"]).strip()[:80], item_id))
    if "rating" in body:
        if body["rating"] not in (1, -1, 0) or isinstance(body["rating"], bool):
            raise HTTPException(400, "A rating is 1, -1 or 0.")
        db.run("UPDATE generations SET rating = ? WHERE id = ?", (body["rating"], item_id))
    if "project_id" in body:
        if body["project_id"] is not None:
            _own_project(request, user, body["project_id"])
        db.run("UPDATE generations SET project_id = ? WHERE id = ?", (body["project_id"], item_id))
    return {"ok": True}


@router.delete("/library/{item_id}")
async def delete_item(item_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, item_id)
    path = _path(request, row)
    path.unlink(missing_ok=True)
    media.poster_path(path).unlink(missing_ok=True)
    request.app.state.db.run("DELETE FROM generations WHERE id = ?", (item_id,))
    return {"ok": True}


@router.post("/library/{item_id}/reference")
async def as_reference(item_id: int, request: Request, kind: str = "image", user: dict = Depends(current_user)):
    """Make a library item usable as a reference in a new job. kind is what the slot takes: an image slot gets an
    image as it is or a video's last frame; a video slot a video; an audio slot a sound, or a video for its sound."""
    row = _own(request, user, item_id)
    path = _path(request, row)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    comfy = request.app.state.comfy
    if kind == "image" and row["kind"] == "video":
        with tempfile.TemporaryDirectory() as tmp:
            frame = await media.last_frame(path, Path(tmp) / (path.stem + "_last.png"))
            name = await upload_reference(comfy, frame.name, frame.read_bytes(), "image/png", db=request.app.state.db, user_id=user["id"])
        return {"comfy_name": name, "name": "End of " + row["name"]}
    if row["kind"] == kind or (kind == "audio" and row["kind"] == "video"):
        name = await upload_reference(comfy, path.name, path.read_bytes(), db=request.app.state.db, user_id=user["id"])
        return {"comfy_name": name, "name": row["name"]}
    raise HTTPException(400, "{} is {}, and this needs {}.".format(
        row["name"], {"image": "an image", "video": "a video", "audio": "a sound"}.get(row["kind"], "a text"),
        {"image": "an image or a video", "video": "a video", "audio": "a sound"}.get(kind, "something else")))


# ---------------------------------------------------------------- projects

@router.get("/projects")
async def list_projects(request: Request, user: dict = Depends(current_user)):
    return {"projects": request.app.state.db.all(
        "SELECT p.id, p.name, p.created, (SELECT COUNT(*) FROM generations g WHERE g.project_id = p.id AND g.run = '') AS items, "
        # The newest item of a project is its cover on the Home page, and tells when it was last worked on.
        "(SELECT g.id FROM generations g WHERE g.project_id = p.id AND g.run = '' ORDER BY g.created DESC LIMIT 1) AS cover_id, "
        "(SELECT g.kind FROM generations g WHERE g.project_id = p.id AND g.run = '' ORDER BY g.created DESC LIMIT 1) AS cover_kind, "
        "(SELECT MAX(g.created) FROM generations g WHERE g.project_id = p.id) AS updated "
        "FROM projects p WHERE p.user_id = ? ORDER BY lower(p.name)", (user["id"],))}


@router.post("/projects")
async def create_project(body: dict, request: Request, user: dict = Depends(current_user)):
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the project a name.")
    project_id = request.app.state.db.run("INSERT INTO projects (user_id, name, created) VALUES (?, ?, ?)",
                                          (user["id"], name, time.time()))
    return {"id": project_id, "name": name}


@router.put("/projects/{project_id}")
async def rename_project(project_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    _own_project(request, user, project_id)
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the project a name.")
    request.app.state.db.run("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, request: Request, user: dict = Depends(current_user)):
    """Delete a project. Its items stay in the library, in no project."""
    _own_project(request, user, project_id)
    db = request.app.state.db
    db.run("UPDATE generations SET project_id = NULL WHERE project_id = ?", (project_id,))
    db.run("UPDATE jobs SET project_id = NULL WHERE project_id = ?", (project_id,))
    db.run("UPDATE assets SET project_id = NULL WHERE project_id = ?", (project_id,))   # its uploads too
    db.run("DELETE FROM projects WHERE id = ?", (project_id,))
    return {"ok": True}
