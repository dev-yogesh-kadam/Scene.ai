"""The library: each user's finished images and videos, organised in projects."""

import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import media
from ..references import upload_reference
from .deps import current_user

router = APIRouter(prefix="/api", tags=["library"])


def _path(request, row):
    return request.app.state.output_dir / str(row["user_id"]) / row["filename"]


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
async def list_items(request: Request, kind: str = "", q: str = "", project: str = "",
                     user: dict = Depends(current_user)):
    """`project` is a project id, "none" for items in no project, or empty for everything."""
    # Each item comes with what its details panel shows: the job's cost and the project's name.
    sql = ("SELECT g.*, j.cost, p.name AS project_name FROM generations g LEFT JOIN jobs j ON j.id = g.job_id "
           "LEFT JOIN projects p ON p.id = g.project_id WHERE g.user_id = ?")
    params = [user["id"]]
    if kind in ("video", "image"):
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


@router.get("/library/{item_id}/file")
async def get_file(item_id: int, request: Request, download: bool = False, user: dict = Depends(current_user)):
    row = _own(request, user, item_id)
    path = _path(request, row)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    return FileResponse(path, filename=path.name if download else None)


@router.put("/library/{item_id}")
async def update_item(item_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    """Rename an item or move it to a project (project_id null = no project)."""
    _own(request, user, item_id)
    db = request.app.state.db
    if "name" in body and str(body["name"]).strip():
        db.run("UPDATE generations SET name = ? WHERE id = ?", (str(body["name"]).strip()[:80], item_id))
    if "project_id" in body:
        if body["project_id"] is not None:
            _own_project(request, user, body["project_id"])
        db.run("UPDATE generations SET project_id = ? WHERE id = ?", (body["project_id"], item_id))
    return {"ok": True}


@router.delete("/library/{item_id}")
async def delete_item(item_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, item_id)
    _path(request, row).unlink(missing_ok=True)
    request.app.state.db.run("DELETE FROM generations WHERE id = ?", (item_id,))
    return {"ok": True}


@router.post("/library/{item_id}/reference")
async def as_reference(item_id: int, request: Request, user: dict = Depends(current_user)):
    """Make a library item usable as a reference in a new job: an image as it is, a video's last frame."""
    row = _own(request, user, item_id)
    path = _path(request, row)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    comfy = request.app.state.comfy
    if row["kind"] == "image":
        name = await upload_reference(comfy, path.name, path.read_bytes())
        return {"comfy_name": name, "name": row["name"]}
    with tempfile.TemporaryDirectory() as tmp:
        frame = await media.last_frame(path, Path(tmp) / (path.stem + "_last.png"))
        name = await upload_reference(comfy, frame.name, frame.read_bytes(), "image/png")
    return {"comfy_name": name, "name": "End of " + row["name"]}


# ---------------------------------------------------------------- projects

@router.get("/projects")
async def list_projects(request: Request, user: dict = Depends(current_user)):
    return {"projects": request.app.state.db.all(
        "SELECT p.id, p.name, p.created, (SELECT COUNT(*) FROM generations g WHERE g.project_id = p.id) AS items, "
        # The newest item of a project is its cover on the Home page, and tells when it was last worked on.
        "(SELECT g.id FROM generations g WHERE g.project_id = p.id ORDER BY g.created DESC LIMIT 1) AS cover_id, "
        "(SELECT g.kind FROM generations g WHERE g.project_id = p.id ORDER BY g.created DESC LIMIT 1) AS cover_kind, "
        "(SELECT MAX(g.created) FROM generations g WHERE g.project_id = p.id) AS updated "
        "FROM projects p WHERE p.user_id = ? ORDER BY p.name COLLATE NOCASE", (user["id"],))}


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
    db.run("DELETE FROM projects WHERE id = ?", (project_id,))
    return {"ok": True}
