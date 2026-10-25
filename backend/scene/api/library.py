"""The library: each user's finished images and videos, organised in projects."""

import contextlib
import csv
import io
import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import audit, fetch, media, kit, sharing
from ..db import as_everyone
from ..catalog import KINDS
from ..outputs import MAIN_CANVAS

FIRST_MODULE = "Module 1"
from ..references import media_kind, read_text_upload, read_upload, safe_name, text_kind, upload_reference
from .deps import current_user

router = APIRouter(prefix="/api", tags=["library"])


def _path(request, row):
    return request.app.state.outputs.folder(row["user_id"]) / row["filename"]


def _own(request, user, item_id, need=None):
    """An item of the user's, or, with `need`, one made in a project shared with them where their role allows that."""
    db = request.app.state.db
    row = db.one("SELECT * FROM generations WHERE id = ? AND user_id = ?", (item_id, user["id"]))
    if row is None and need:
        with as_everyone():
            other = db.one("SELECT * FROM generations WHERE id = ?", (item_id,))
        if other and other["project_id"] and sharing.role_in(db, user["id"], other["project_id"])[0]:
            sharing.require(db, user, other["project_id"], need)
            row = other
    if row is None:
        raise HTTPException(404, "No such item.")
    return row


def _own_project(request, user, project_id, need="owner"):
    """A project or module the user may act on: theirs, or one shared with them where their role allows `need`."""
    return sharing.require(request.app.state.db, user, project_id, need)


# ---------------------------------------------------------------- items

@router.get("/library")
async def list_items(request: Request, kind: str = "", q: str = "", project: str = "", run: str = "", modules: int = 0,
                     user: dict = Depends(current_user)):
    """`project` is a project id, "none" for items in no project, or empty for everything; with `modules=1` a project's
    modules count as part of it. `run`: the working files of that run (slices, trims, references of a long skill), which
    are otherwise left out."""
    # Each item comes with what its details panel shows: the job's cost and the project's name.
    # In a project: what everyone in it made (a shared project's members too), read once the user is found to be in it.
    # Anywhere else: the user's own items.
    shared = project.isdigit() and int(project) > 0 and bool(_own_project(request, user, int(project), "viewer"))
    sql = ("SELECT g.*, j.cost, p.name AS project_name, u.name AS made_by FROM generations g LEFT JOIN jobs j ON j.id = g.job_id "
           "LEFT JOIN projects p ON p.id = g.project_id LEFT JOIN users u ON u.id = g.user_id WHERE " + ("1 = 1" if shared else "g.user_id = ?"))
    sql += " AND g.run = ?"
    params = ([] if shared else [user["id"]]) + [run[:64]]
    if kind in (*KINDS, "text"):
        sql, params = sql + " AND g.kind = ?", params + [kind]
    if project == "none":
        sql += " AND g.project_id IS NULL"
    elif project.isdigit() and modules:
        sql, params = sql + " AND g.project_id IN (SELECT id FROM projects WHERE id = ? OR parent_id = ?)", params + [int(project)] * 2
    elif project.isdigit():
        sql, params = sql + " AND g.project_id = ?", params + [int(project)]
    for word in q.split()[:6]:  # every word must appear in the name, the workflow or the settings (prompt)
        like = "%{}%".format(word.replace("%", r"\%").replace("_", r"\_"))
        sql += " AND (g.name LIKE ? ESCAPE '\\' OR g.workflow LIKE ? ESCAPE '\\' OR g.summary LIKE ? ESCAPE '\\' OR g.settings LIKE ? ESCAPE '\\')"
        params += [like] * 4
    with as_everyone() if shared else contextlib.nullcontext():
        items = request.app.state.db.all(sql + " ORDER BY g.created DESC LIMIT 500", params)
    for item in items:
        item["settings"] = json.loads(item["settings"])
        item["context"] = json.loads(item["context"])
        item["mine"] = item.pop("user_id") == user["id"]
        if item["mine"]:
            del item["made_by"]
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
    project_id = _own_project(request, user, int(project), "creator")["id"] if project.isdigit() and int(project) else None
    return await _file_in(request, user, data, filename, kind, project_id, "Uploaded")


IMPORTED = "upload/link"   # an item brought in from a link on another site


@router.post("/library/import")
async def import_link(body: dict, request: Request, user: dict = Depends(current_user)):
    """{"url", "project_id"?, "name"?}: the picture, clip or sound at a link on another site, brought into the library
    (see fetch.py for what is fetched and what is refused). Nothing is charged."""
    url = str(body.get("url") or "").strip()
    if not url or len(url) > 2000:
        raise HTTPException(400, "Give the link to bring in.")
    project_id = _own_project(request, user, body["project_id"], "creator")["id"] if isinstance(body.get("project_id"), int) and body["project_id"] else None
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
    filed = request.app.state.outputs.settle(user["id"], project_id, target)   # into its project's folder
    db.run("INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
           "context, seconds, size, created) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
           (user["id"], project_id, workflow, kind, name, filed, summary,
            json.dumps({"name": name, "prompt": "", **({"source": source} if source else {})}), json.dumps(context), len(data), time.time()))
    row = db.one("SELECT * FROM generations WHERE user_id = ? AND filename = ?", (user["id"], filed))
    return dict(row, settings=json.loads(row["settings"]), context=json.loads(row["context"]))


@router.get("/library/{item_id}/file")
async def get_file(item_id: int, request: Request, download: bool = False, user: dict = Depends(current_user)):
    row = _own(request, user, item_id, "viewer")
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
    return await poster_response(request, _path(request, _own(request, user, item_id, "viewer")))


@router.get("/library/{item_id}/frame")
async def get_frame(item_id: int, request: Request, at: float = 0.0, user: dict = Depends(current_user)):
    """The frame of a video at `at` seconds, for the keyframes the agent shows under a result. Made once and kept,
    per tenth of a second, next to the video's poster."""
    row = _own(request, user, item_id, "viewer")
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
            _own_project(request, user, body["project_id"], "creator")
        db.run("UPDATE generations SET project_id = ? WHERE id = ?", (body["project_id"], item_id))
        request.app.state.outputs.refile(user["id"], item_id, body["project_id"])   # its file follows it to that project's folder
    return {"ok": True}


@router.delete("/library/{item_id}")
async def delete_item(item_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, item_id)
    media.remove_result(_path(request, row))
    request.app.state.db.run("DELETE FROM generations WHERE id = ?", (item_id,))
    return {"ok": True}


@router.post("/library/{item_id}/reference")
async def as_reference(item_id: int, request: Request, kind: str = "image", user: dict = Depends(current_user)):
    """Make a library item usable as a reference in a new job. kind is what the slot takes: an image slot gets an
    image as it is or a video's last frame; a video slot a video; an audio slot a sound, or a video for its sound."""
    row = _own(request, user, item_id, "creator")   # a picture someone else made in the project, used to make the next
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

# A project and its modules: "p.id = ? OR p.parent_id = ?" in the counts below, so a project counts what its modules hold.
_IN_PROJECT = "g.project_id IN (SELECT q.id FROM projects q WHERE q.id = p.id OR q.parent_id = p.id)"


@router.get("/projects")
async def list_projects(request: Request, user: dict = Depends(current_user)):
    """Every project and module of the user, and those shared with them. A module has "parent_id" and "parent_name"; a
    project has "modules", the number of its modules, and counts (items, cover, updated) over itself and its modules
    together. "role" is the user's in it ("owner" in their own), and a shared one says whose it is ("owner_name")."""
    db = request.app.state.db
    shared = sharing.shared_ids(db, user["id"])
    where = "p.user_id = ?" + (" OR p.id IN ({})".format(", ".join("?" * len(shared))) if shared else "")
    with as_everyone() if shared else contextlib.nullcontext():
        rows = db.all(
        "SELECT p.id, p.name, p.canvas_name, p.created, p.parent_id, p.user_id, pp.name AS parent_name, ow.name AS owner_name, "
        "(SELECT COUNT(*) FROM project_members pm WHERE pm.project_id = COALESCE(p.parent_id, p.id)) AS members, "
        "(SELECT COUNT(*) FROM projects m WHERE m.parent_id = p.id) AS modules, "
        "(SELECT COUNT(*) FROM generations g WHERE " + _IN_PROJECT + " AND g.run = '') AS items, "
        # The newest item of a project is its cover on the Home page, and tells when it was last worked on.
        "(SELECT g.id FROM generations g WHERE " + _IN_PROJECT + " AND g.run = '' ORDER BY g.created DESC LIMIT 1) AS cover_id, "
        "(SELECT g.kind FROM generations g WHERE " + _IN_PROJECT + " AND g.run = '' ORDER BY g.created DESC LIMIT 1) AS cover_kind, "
        "(SELECT MAX(g.created) FROM generations g WHERE " + _IN_PROJECT + ") AS updated "
        "FROM projects p LEFT JOIN projects pp ON pp.id = p.parent_id JOIN users ow ON ow.id = p.user_id "
        "WHERE " + where + " ORDER BY lower(p.name)", (user["id"], *shared))
    for row in rows:
        mine = row.pop("user_id") == user["id"]
        row["role"] = "owner" if mine else sharing.role_in(db, user["id"], row["id"])[0]
        if mine:
            row.pop("owner_name")
    return {"projects": rows}


@router.get("/projects/{project_id}")
async def get_project(project_id: int, request: Request, user: dict = Depends(current_user)):
    """A project's page: the project, its own canvas as the first module ("main"), then its modules, each with its items,
    cover and last change. For a module, the project it is in."""
    db = request.app.state.db
    here = _own_project(request, user, project_id, "viewer")
    top = _own_project(request, user, here["top_id"], "viewer")

    def counted(row, main=False):
        stats = db.one("SELECT COUNT(*) AS items, MAX(created) AS updated FROM generations WHERE project_id = ? AND run = ''", (row["id"],))
        cover = db.one("SELECT id, kind FROM generations WHERE project_id = ? AND run = '' ORDER BY created DESC LIMIT 1", (row["id"],))
        name = (row["canvas_name"] or MAIN_CANVAS) if main else row["name"]   # the project's own canvas goes by its own name
        return {"id": row["id"], "name": name, "created": row["created"], "main": main, "items": stats["items"],
                "updated": stats["updated"], "cover_id": cover and cover["id"], "cover_kind": cover and cover["kind"]}
    with as_everyone():   # what everyone in the project made, now that the user is found to be in it
        modules = [counted(top, True)] + [counted(m) for m in db.all("SELECT * FROM projects WHERE parent_id = ? ORDER BY created", (top["id"],))]
    return {"project": {"id": top["id"], "name": top["name"], "created": top["created"], "role": top["role"], "members": sharing.members(db, top["id"]),
                        "items": sum(m["items"] for m in modules), "updated": max((m["updated"] or 0 for m in modules), default=0) or None,
                        **next(({"cover_id": m["cover_id"], "cover_kind": m["cover_kind"]} for m in sorted(modules, key=lambda m: -(m["updated"] or 0))
                                if m["cover_id"]), {"cover_id": None, "cover_kind": None})},
            "modules": modules}


# ---------------------------------------------------------------- a project's analytics

# What a project's credits went on, by the kind of thing made. A sound is music or a voice by its workflow.
ASSET_TYPES = (("video", "Videos"), ("voiceover", "Voiceover"), ("music", "Music"), ("image", "Images"),
               ("motion", "Motion graphics"), ("edit", "Edits"), ("llm", "Agent"))
PERIODS = ("today", "7", "30", "month")


def _asset_type(workflow, kind):
    if str(workflow).startswith("audio/"):
        return "music" if "music" in str(workflow).lower() else "voiceover"
    return {"video": "video", "upscaler": "video", "image": "image", "motion": "motion"}.get(kind, "edit")


def _period(period, now=None):
    """(start, end) of a period, by this machine's clock: today, the last 7 or 30 days, or this month."""
    now = now or time.time()
    day = time.localtime(now)
    midnight = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0, 0, 0, -1))
    if period == "today":
        return midnight, now
    if period == "month":
        return time.mktime((day.tm_year, day.tm_mon, 1, 0, 0, 0, 0, 0, -1)), now
    return midnight - (int(period) - 1) * 86400, now


def project_analytics_data(db, user, project_id, period):
    sharing.require(db, user, project_id, "viewer")
    with as_everyone():   # the spend and the work of everyone in the project
        return _project_analytics(db, user, project_id, period)


def _project_analytics(db, user, project_id, period):
    row = db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
    root = row["parent_id"] or project_id
    project = db.one("SELECT * FROM projects WHERE id = ?", (root,))
    modules = [dict(project, main=True)] + [dict(m, main=False) for m in db.all(
        "SELECT * FROM projects WHERE parent_id = ? ORDER BY id", (root,))]
    ids = [m["id"] for m in modules]
    marks = ", ".join("?" * len(ids))
    period = period if period in PERIODS else "7"
    start, end = _period(period)
    before = start - (end - start)
    # What a job spent is its price less what was given back: the charge itself is written before the job has an id.
    jobs = db.all("SELECT j.id, j.project_id, j.workflow, j.kind, j.status, j.created, j.user_id, j.cost - j.credits_refunded AS spent "
                  "FROM jobs j WHERE j.user_id = ? AND j.project_id IN ({}) AND j.created >= ? AND j.created < ?".format(marks),
                  (user["id"], *ids, before, end))
    talks = db.all("SELECT project_id, created, -amount AS spent FROM credit_events WHERE user_id = ? AND reason = 'agent' AND project_id IN ({}) "
                   "AND created >= ? AND created < ?".format(marks), (user["id"], *ids, before, end))
    made = db.all("SELECT project_id, kind, workflow, created FROM generations WHERE user_id = ? AND project_id IN ({}) AND run = '' "
                  "AND created >= ? AND created < ?".format(marks), (user["id"], *ids, start, end))
    first = {r["project_id"]: r["first"] for r in db.all(
        "SELECT project_id, MIN(created) AS first FROM generations WHERE user_id = ? AND project_id IN ({}) GROUP BY project_id".format(marks),
        (user["id"], *ids))}
    spends = [(j["project_id"], _asset_type(j["workflow"], j["kind"]), j["created"], j["spent"] or 0) for j in jobs] + \
             [(t["project_id"], "llm", t["created"], t["spent"] or 0) for t in talks]
    now_spend = [x for x in spends if x[2] >= start]
    spent, spent_before = sum(x[3] for x in now_spend), sum(x[3] for x in spends if x[2] < start)

    days, at = [], start
    while at < end and len(days) < 40:
        days.append(time.strftime("%Y-%m-%d", time.localtime(at)))
        at += 86400
    daily = {day: {t: 0 for t, _ in ASSET_TYPES} for day in days}
    for _, kind, when, credits in now_spend:
        day = time.strftime("%Y-%m-%d", time.localtime(when))
        if day in daily:
            daily[day][kind] += credits
    by_type = {t: {"credits": 0, "generations": 0} for t, _ in ASSET_TYPES}
    for _, kind, _, credits in now_spend:
        by_type[kind]["credits"] += credits
    for g in made:
        by_type[_asset_type(g["workflow"], g["kind"])]["generations"] += 1

    rows = []
    for number, m in enumerate(modules, start=1):
        mine = [x for x in now_spend if x[0] == m["id"]]
        items = [g for g in made if g["project_id"] == m["id"]]
        kinds = {x[1] for x in mine} | {_asset_type(g["workflow"], g["kind"]) for g in items}
        types = {t: {"credits": sum(x[3] for x in mine if x[1] == t), "generations": sum(1 for g in items if _asset_type(g["workflow"], g["kind"]) == t)}
                 for t, _ in ASSET_TYPES}
        rows.append({"id": m["id"], "number": number, "name": (m["canvas_name"] or MAIN_CANVAS) if m["main"] else m["name"], "main": m["main"],
                     "first": first.get(m["id"]), "generations": len(items), "asset_types": len(kinds),
                     "credits": sum(x[3] for x in mine), "types": {t: v for t, v in types.items() if v["credits"] or v["generations"]}})
    rows.sort(key=lambda r: (-r["credits"], -r["generations"], r["number"]))
    return {
        "project": {"id": root, "name": project["name"]}, "period": period, "start": start, "end": end, "owner": user["email"],
        "spend": spent, "spend_before": spent_before,
        "change": None if not spent_before else round(100 * (spent - spent_before) / spent_before),
        "generations": len(made), "active_modules": sum(1 for r in rows if r["generations"] or r["credits"]),
        "contributors": len({j["user_id"] for j in jobs if j["created"] >= start}),
        "types": [{"id": t, "label": label, **by_type[t]} for t, label in ASSET_TYPES],
        "days": days, "daily": [daily[d] for d in days], "modules": rows,
    }


@router.get("/projects/{project_id}/analytics")
async def project_analytics(project_id: int, request: Request, period: str = "7", user: dict = Depends(current_user)):
    """What a project (its modules too) spent and made in a period (today, 7, 30 or month): by day and kind of thing
    made, and by module. Credits are what the jobs cost less their refunds, and the agent's messages in the project."""
    return project_analytics_data(request.app.state.db, user, project_id, period)


@router.get("/projects/{project_id}/analytics.csv")
async def project_analytics_csv(project_id: int, request: Request, period: str = "7", user: dict = Depends(current_user)):
    found = project_analytics_data(request.app.state.db, user, project_id, period)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["module", "first generation", "generations", "asset types", "credits"] + [label + " credits" for _, label in ASSET_TYPES])
    for r in found["modules"]:
        writer.writerow([r["name"], time.strftime("%Y-%m-%d", time.localtime(r["first"])) if r["first"] else "", r["generations"],
                         r["asset_types"], r["credits"]] + [r["types"].get(t, {}).get("credits", 0) for t, _ in ASSET_TYPES])
    name = "".join(c if c.isalnum() else "-" for c in found["project"]["name"]).strip("-") or "project"
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="{}-{}.csv"'.format(name, found["period"])})


@router.post("/projects/{project_id}/duplicate")
async def duplicate_project(project_id: int, request: Request, user: dict = Depends(current_user)):
    """A copy of a project to start again from: its modules (empty canvases of the same names) and its NeuralCore kit,
    named "<name> copy". What was made stays with the first project."""
    state, db = request.app.state, request.app.state.db
    row = _own_project(request, user, project_id)
    root = db.one("SELECT * FROM projects WHERE id = ?", (row["parent_id"] or project_id,))
    copy = db.run("INSERT INTO projects (user_id, name, created, canvas_name) VALUES (?, ?, ?, ?)",
                  (user["id"], (root["name"] + " copy")[:60], time.time(), root["canvas_name"]))
    for m in db.all("SELECT name FROM projects WHERE parent_id = ? ORDER BY id", (root["id"],)):
        db.run("INSERT INTO projects (user_id, name, created, parent_id) VALUES (?, ?, ?, ?)", (user["id"], m["name"], time.time(), copy))
    kit.copy_entries(db, user["id"], root["id"], copy)
    return {"id": copy, "name": (root["name"] + " copy")[:60]}


@router.post("/projects")
async def create_project(body: dict, request: Request, user: dict = Depends(current_user)):
    """{"name", "parent_id"?}: a project, or with parent_id a module inside that project (a module holds no modules)."""
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the project a name.")
    parent = None
    if body.get("parent_id"):
        parent = _own_project(request, user, body["parent_id"], "creator") if isinstance(body["parent_id"], int) else None
        if parent is None or parent["parent_id"]:
            raise HTTPException(400, "A module goes inside a project, not inside another module.")
    # A new project's own canvas is its first module, "Module 1"; the modules added to it go on from "Module 2".
    # A module of a shared project is the project owner's, like the project: everyone in it works there.
    with as_everyone():
        project_id = request.app.state.db.run("INSERT INTO projects (user_id, name, created, parent_id, canvas_name) VALUES (?, ?, ?, ?, ?)",
                                              (parent["owner_id"] if parent else user["id"], name, time.time(), parent and parent["id"],
                                               "" if parent else FIRST_MODULE))
    return {"id": project_id, "name": name, "parent_id": parent and parent["id"]}


@router.put("/projects/{project_id}")
async def rename_project(project_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    _own_project(request, user, project_id, "manager")
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the project a name.")
    outputs = request.app.state.outputs
    before = outputs.folder_of(project_id)
    request.app.state.db.run("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    outputs.rename(user["id"], before, outputs.folder_of(project_id))   # its folder (with its modules') takes the new name
    return {"ok": True}


@router.put("/projects/{project_id}/canvas")
async def rename_canvas(project_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    """Rename a project's own canvas (shown as "Main canvas" until it is named). Its folder of results takes the name."""
    here = _own_project(request, user, project_id, "manager")
    if here["parent_id"]:
        raise HTTPException(400, "A module is renamed as a module.")
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the canvas a name.")
    outputs = request.app.state.outputs
    before = outputs.relative(project_id)
    request.app.state.db.run("UPDATE projects SET canvas_name = ? WHERE id = ?", ("" if name == MAIN_CANVAS else name, project_id))
    outputs.rename(user["id"], before, outputs.relative(project_id))
    return {"ok": True, "name": name}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, request: Request, user: dict = Depends(current_user)):
    """Delete a project, or a module, and everything in it, so nothing that can no longer be used stays in storage: what
    was made in it (the files, their posters and keyframes), its jobs still waiting or running (their credits given
    back), and its canvases, timelines and agent tabs. A project takes its modules and its NeuralCore with it. The jobs'
    records stay, in no project, for the credit history."""
    probe = _own_project(request, user, project_id, "viewer")
    here = _own_project(request, user, project_id, "manager" if probe["parent_id"] else "owner")   # a module: a manager; a project: its owner
    state, db = request.app.state, request.app.state.db
    people = sharing.people_of(db, project_id)   # whose work is in it: the owner's and every member's
    owner = here["owner_id"]
    with as_everyone():
        gone = [project_id] if here["parent_id"] else [m["id"] for m in db.all("SELECT id FROM projects WHERE parent_id = ?", (project_id,))] + [project_id]
        its_folder = state.outputs.folder_of(project_id)   # a project's folder holds its modules' folders: all of it
        marks = ", ".join("?" * len(gone))
        for job in db.all("SELECT id, user_id FROM jobs WHERE status IN ('queued', 'running') AND project_id IN ({})".format(marks), gone):
            state.jobs.remove(job["user_id"], job["id"])   # a running one stops at its next check; its result is not kept (jobs._record)
        removed = db.all("SELECT id, user_id, filename FROM generations WHERE project_id IN ({})".format(marks), gone)
        for row in removed:
            media.remove_result(state.outputs.folder(row["user_id"]) / row["filename"])
        db.run("DELETE FROM generations WHERE project_id IN ({})".format(marks), gone)
        for one in gone:
            db.run("UPDATE jobs SET project_id = NULL WHERE project_id = ?", (one,))
            # Its canvas, timeline and agent tabs go with it: a project made later must not open with them.
            db.run("DELETE FROM boards WHERE project_id = ?", (one,))
            if not here["parent_id"]:   # the NeuralCore is the project's: its modules share it, so it goes only with the project
                for row in db.all("SELECT id FROM assets WHERE project_id = ? AND user_id = ?", (one, owner)):
                    kit.remove(db, state.assets_dir / str(owner), owner, row["id"])   # files too
            db.run("DELETE FROM projects WHERE id = ?", (one,))
    for person in people:
        state.outputs.remove_folder(person, its_folder)   # whatever is left in their folder of it; never the backup's copy
        state.notify(person, library_changed=True)
    return {"ok": True, "items_deleted": len(removed)}


# ---------------------------------------------------------------- people in a project

@router.get("/projects/{project_id}/members")
async def project_members(project_id: int, request: Request, user: dict = Depends(current_user)):
    """Everyone in a project and their roles, the user's own role, and the roles there are to give."""
    here = _own_project(request, user, project_id, "viewer")
    return {"members": sharing.members(request.app.state.db, here["top_id"]), "role": here["role"],
            "roles": [{"id": r, "label": sharing.LABELS[r], "about": sharing.ABOUT[r]} for r in sharing.ROLES]}


@router.post("/projects/{project_id}/members")
async def add_members(project_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    """{"people": [{"email", "role"}]}: add people to the whole project (all its modules). Someone already in it gets
    the role given. Each email that could not be added comes back with why."""
    here = _own_project(request, user, project_id, "manager")
    people = body.get("people") if isinstance(body.get("people"), list) else []
    if not people or len(people) > 50:
        raise HTTPException(400, "Add between 1 and 50 people at a time.")
    db = request.app.state.db
    added, problems = sharing.add(db, here, user, people)
    if added:
        audit.record(request, user, "Shared a project", "project {}".format(here["top_id"]), ", ".join("{} as {}".format(a["email"], a["role"]) for a in added))
    for person in added:
        request.app.state.notify(person["user_id"], library_changed=True)   # the project appears in their list
    return {"added": added, "problems": problems, "members": sharing.members(db, here["top_id"])}


@router.put("/projects/{project_id}/members/{member_id}")
async def change_member(project_id: int, member_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    here = _own_project(request, user, project_id, "manager")
    sharing.change(request.app.state.db, here, member_id, str(body.get("role") or ""))
    return {"members": sharing.members(request.app.state.db, here["top_id"])}


@router.delete("/projects/{project_id}/members/{member_id}")
async def remove_member(project_id: int, member_id: int, request: Request, user: dict = Depends(current_user)):
    """Take someone out of a project, or, for their own id, leave it. What they made there stays in it."""
    here = _own_project(request, user, project_id, "viewer" if member_id == user["id"] else "manager")
    if member_id == user["id"] and here["role"] == "owner":
        raise HTTPException(400, "The owner can't leave their own project. Delete it instead.")
    sharing.change(request.app.state.db, dict(here, role="owner") if member_id == user["id"] else here, member_id, None)
    request.app.state.notify(member_id, library_changed=True)
    return {"members": sharing.members(request.app.state.db, here["top_id"])}
