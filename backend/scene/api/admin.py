"""The admin console: overview, users, every user's jobs and library, credits, workflows, system, audit log, settings."""

import csv
import io
import json
import platform
import re
import shutil
import time
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import __version__, audit, media
from ..catalog import KINDS
from ..credits import MOTION, OVERLAY, PER_JOB, RATES
from ..security import hash_password
from .auth import MIN_PASSWORD, signup_open
from .deps import admin_user
from .library import poster_response

router = APIRouter(prefix="/api/admin", tags=["admin"])
DAY = 86400
RANGES = (7, 30, 90)
SPEND = "reason IN ('generation', 'refund')"   # a charge and its refund cancel out
LOCAL_DAY = "date({}, 'unixepoch', 'localtime')"


def _settings(state):
    return {"comfy_url": state.comfy.url, "allow_signup": signup_open(state),
            "signup_credits": state.credits.signup}


def _number(body, key, maximum):
    label = key.replace("_", " ").capitalize()
    try:
        value = float(body[key])
    except (TypeError, ValueError):
        raise HTTPException(400, "{} must be a number.".format(label))
    if not 0 <= value <= maximum:
        raise HTTPException(400, "{} must be between 0 and {}.".format(label, maximum))
    return value


def _like(text):
    return "%{}%".format(text.strip().replace("%", r"\%").replace("_", r"\_"))


async def _server(state):
    try:
        stats = await state.comfy.stats()
        return dict(stats, online=True, url=state.comfy.url)
    except (httpx.HTTPError, ValueError):
        return {"online": False, "url": state.comfy.url}


# ---------------------------------------------------------------- overview

def _period(db, start, end):
    """The headline numbers for one stretch of time."""
    def value(sql):
        return db.one(sql, (start, end))["n"] or 0

    done = value("SELECT COUNT(*) n FROM jobs WHERE status = 'done' AND created > ? AND created <= ?")
    failed = value("SELECT COUNT(*) n FROM jobs WHERE status = 'failed' AND created > ? AND created <= ?")
    return {
        "active_users": value("SELECT COUNT(DISTINCT user_id) n FROM jobs WHERE created > ? AND created <= ?"),
        "signups": value("SELECT COUNT(*) n FROM users WHERE created > ? AND created <= ?"),
        "items": value("SELECT COUNT(*) n FROM generations WHERE created > ? AND created <= ?"),
        "jobs": value("SELECT COUNT(*) n FROM jobs WHERE created > ? AND created <= ?"),
        "done": done,
        "failed": failed,
        "success_rate": round(100 * done / (done + failed), 1) if done + failed else None,
        "gpu_seconds": value("SELECT SUM(finished - started) n FROM jobs WHERE status = 'done' AND created > ? AND created <= ?"),
        "credits": -value("SELECT SUM(amount) n FROM credit_events WHERE {} AND created > ? AND created <= ?".format(SPEND)),
        "avg_wait": value("SELECT AVG(started - created) n FROM jobs WHERE started IS NOT NULL AND created > ? AND created <= ?"),
        "avg_run": value("SELECT AVG(finished - started) n FROM jobs WHERE status = 'done' AND created > ? AND created <= ?"),
    }


def _daily(db, days, sql, since):
    """One number per local day, with zeros for days that have no rows. `sql` selects (day, n)."""
    found = {row["day"]: row["n"] or 0 for row in db.all(sql, (since,))}
    return [found.get(day, 0) for day in days]


@router.get("/overview")
async def overview(request: Request, days: int = 30, user: dict = Depends(admin_user)):
    state, db, now = request.app.state, request.app.state.db, time.time()
    days = days if days in RANGES else 30
    since = now - days * DAY
    current, previous = _period(db, since, now), _period(db, since - days * DAY, since)
    calendar = [(date.today() - timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]

    def series(table, extra="", value="COUNT(*)", column="created"):
        return _daily(db, calendar, "SELECT {} AS day, {} AS n FROM {} WHERE {} > ? {} GROUP BY day".format(
            LOCAL_DAY.format(column), value, table, column, extra), since)

    server = await _server(state)
    running = db.one("SELECT j.id, j.name, j.workflow, j.started, j.est_seconds, u.name AS user_name "
                     "FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.status = 'running'")
    if running:
        live = state.jobs.live.get(running["id"], {})
        running.update(step=live.get("step", 0), steps=live.get("steps", 0), clip=live.get("clip", 0),
                       clips=live.get("clips", 0), node=live.get("node", ""))
    waiting = db.all("SELECT j.id, j.name, j.created, j.est_seconds, u.name AS user_name FROM jobs j "
                     "JOIN users u ON u.id = j.user_id WHERE j.status = 'queued' ORDER BY j.created LIMIT 8")

    # Things an admin should act on.
    attention = []
    if not server["online"]:
        attention.append({"level": "critical", "text": "The render server does not answer at {}. No jobs can run.".format(server["url"]), "tab": "system"})
    failed_day = db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'failed' AND created > ?", (now - DAY,))["n"]
    if failed_day:
        attention.append({"level": "serious", "text": "{} job{} failed in the last 24 hours.".format(failed_day, "" if failed_day == 1 else "s"), "tab": "jobs"})
    broke = db.one("SELECT COUNT(*) n FROM users WHERE credits <= 0 AND disabled = 0")["n"]
    if broke:
        attention.append({"level": "warning", "text": "{} user{} out of credits.".format(broke, " is" if broke == 1 else "s are"), "tab": "users"})
    unreadable = [w["title"] for w in await state.catalog.listing() if w.get("error")]
    if unreadable:
        attention.append({"level": "warning", "text": "Workflows that can't be read: {}.".format(", ".join(unreadable)), "tab": "workflows"})
    state.output_dir.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(state.output_dir)   # finished work is what fills a disk
    if disk.free < 10 * 1024 ** 3:
        attention.append({"level": "serious", "text": "Only {:.1f} GB of disk space is left for storage.".format(disk.free / 1024 ** 3), "tab": "system"})
    stuck = db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'queued' AND created < ?", (now - 3600,))["n"]
    if stuck:
        attention.append({"level": "warning", "text": "{} job{} been waiting for over an hour.".format(stuck, " has" if stuck == 1 else "s have"), "tab": "jobs"})

    activity = [
        {"time": a["created"], "who": a["actor_name"] or a["target"], "text": a["action"] + (": " + a["detail"] if a["detail"] else ""), "kind": "audit"}
        for a in db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT 15")
    ] + [
        {"time": j["finished"], "who": j["user_name"], "kind": j["status"],
         "text": "{} \"{}\"".format({"done": "Finished", "failed": "Failed:", "cancelled": "Cancelled"}[j["status"]], j["name"])}
        for j in db.all("SELECT j.name, j.status, j.finished, u.name AS user_name FROM jobs j JOIN users u ON u.id = j.user_id "
                        "WHERE j.status IN ('done', 'failed', 'cancelled') AND j.finished IS NOT NULL ORDER BY j.finished DESC LIMIT 15")
    ]

    return {
        "days": days,
        "current": current,
        "previous": previous,
        "calendar": calendar,
        "series": {
            "videos": series("generations", "AND kind = 'video'"),
            "images": series("generations", "AND kind = 'image'"),
            "done": series("jobs", "AND status = 'done'"),
            "failed": series("jobs", "AND status = 'failed'"),
            "cancelled": series("jobs", "AND status = 'cancelled'"),
            "gpu_minutes": [round(v / 60, 1) for v in series("jobs", "AND status = 'done'", "SUM(finished - started)")],
            "credits": [-v for v in series("credit_events", "AND " + SPEND, "SUM(amount)")],
            "signups": series("users"),
            "active_users": series("jobs", "", "COUNT(DISTINCT user_id)"),
        },
        "top_users": db.all(
            "SELECT u.id, u.name, u.email, COUNT(*) AS jobs, SUM(CASE WHEN j.status = 'done' THEN j.cost ELSE 0 END) AS credits, "
            "SUM(CASE WHEN j.status = 'done' THEN j.finished - j.started ELSE 0 END) AS gpu_seconds "
            "FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.created > ? GROUP BY u.id ORDER BY credits DESC, jobs DESC LIMIT 6", (since,)),
        "top_workflows": db.all(
            "SELECT workflow, COUNT(*) AS jobs, SUM(status = 'done') AS done, SUM(status = 'failed') AS failed, "
            "AVG(CASE WHEN status = 'done' THEN finished - started END) AS avg_seconds "
            "FROM jobs WHERE created > ? GROUP BY workflow ORDER BY jobs DESC LIMIT 6", (since,)),
        "failures": db.all(
            "SELECT substr(error, 1, 140) AS error, COUNT(*) AS jobs, MAX(created) AS last_seen FROM jobs "
            "WHERE status = 'failed' AND created > ? GROUP BY substr(error, 1, 140) ORDER BY jobs DESC, last_seen DESC LIMIT 5", (since,)),
        "queue": {"running": running, "waiting": waiting,
                  "waiting_total": db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'queued'")["n"]},
        "server": {"online": server["online"], "version": server.get("system", {}).get("comfyui_version")},
        "attention": attention,
        "activity": sorted(activity, key=lambda a: a["time"], reverse=True)[:14],
        "totals": {"users": db.one("SELECT COUNT(*) n FROM users")["n"],
                   "items": db.one("SELECT COUNT(*) n FROM generations")["n"],
                   "credits_held": db.one("SELECT SUM(credits) n FROM users")["n"] or 0},
    }


# ---------------------------------------------------------------- users

USER_ROWS = (
    "SELECT u.id, u.email, u.name, u.role, u.credits, u.disabled, u.agent, u.created, "
    "(SELECT COUNT(*) FROM generations g WHERE g.user_id = u.id) AS generations, "
    "(SELECT COUNT(*) FROM jobs j WHERE j.user_id = u.id) AS jobs, "
    "(SELECT MAX(j.created) FROM jobs j WHERE j.user_id = u.id) AS last_job, "
    "(SELECT MAX(s.created) FROM sessions s WHERE s.user_id = u.id) AS last_sign_in, "
    "(SELECT -COALESCE(SUM(c.amount), 0) FROM credit_events c WHERE c.user_id = u.id AND c.{}) AS spent "
    "FROM users u ").format(SPEND)


@router.get("/users")
async def list_users(request: Request, q: str = "", show: str = "", user: dict = Depends(admin_user)):
    """`show` narrows the list: "admins", "disabled" or "no_credits"."""
    where, params = [], []
    if q.strip():
        where.append("(u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [_like(q)] * 2
    if show in ("admins", "disabled", "no_credits"):
        where.append({"admins": "u.role = 'admin'", "disabled": "u.disabled = 1", "no_credits": "u.credits <= 0"}[show])
    sql = USER_ROWS + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY u.created"
    return {"users": request.app.state.db.all(sql, params)}


@router.get("/users/{user_id}")
async def user_detail(user_id: int, request: Request, user: dict = Depends(admin_user)):
    db = request.app.state.db
    found = db.one(USER_ROWS + "WHERE u.id = ?", (user_id,))
    if found is None:
        raise HTTPException(404, "No such user.")
    stats = db.one(
        "SELECT SUM(status = 'done') AS done, SUM(status = 'failed') AS failed, SUM(status = 'cancelled') AS cancelled, "
        "SUM(CASE WHEN status = 'done' THEN finished - started ELSE 0 END) AS gpu_seconds FROM jobs WHERE user_id = ?", (user_id,))
    return {
        "user": found,
        "stats": {k: v or 0 for k, v in stats.items()},
        "storage_bytes": (db.one("SELECT SUM(size) n FROM generations WHERE user_id = ?", (user_id,))["n"] or 0)
        + (db.one("SELECT SUM(size) n FROM assets WHERE user_id = ?", (user_id,))["n"] or 0),
        "assets": db.one("SELECT COUNT(*) n FROM assets WHERE user_id = ?", (user_id,))["n"],
        "projects": db.one("SELECT COUNT(*) n FROM projects WHERE user_id = ?", (user_id,))["n"],
        "jobs": db.all("SELECT id, name, workflow, summary, status, error, cost, created, started, finished FROM jobs "
                       "WHERE user_id = ? ORDER BY created DESC LIMIT 12", (user_id,)),
        "credits": db.all("SELECT c.amount, c.reason, c.note, c.created, j.name AS job_name FROM credit_events c "
                          "LEFT JOIN jobs j ON j.id = c.job_id WHERE c.user_id = ? ORDER BY c.id DESC LIMIT 12", (user_id,)),
        "items": db.all("SELECT id, kind, name, created FROM generations WHERE user_id = ? ORDER BY created DESC LIMIT 8", (user_id,)),
    }


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Change a user's role, add credits (negative takes them away), disable the account, give or take access to
    the agent, or set a new password."""
    state = request.app.state
    target = state.db.one("SELECT email FROM users WHERE id = ?", (user_id,))
    if target is None:
        raise HTTPException(404, "No such user.")
    email = target["email"]
    if ("role" in body or "disabled" in body) and user_id == user["id"]:
        raise HTTPException(400, "You can't change your own role or disable yourself.")
    if "role" in body:
        if body["role"] not in ("admin", "user"):
            raise HTTPException(400, "The role must be admin or user.")
        state.db.run("UPDATE users SET role = ? WHERE id = ?", (body["role"], user_id))
        audit.record(request, user, "Changed role", email, "now " + body["role"])
    if "agent" in body:
        state.db.run("UPDATE users SET agent = ? WHERE id = ?", (1 if body["agent"] else 0, user_id))
        audit.record(request, user, "Gave agent access" if body["agent"] else "Took agent access away", email)
    if "disabled" in body:
        state.db.run("UPDATE users SET disabled = ? WHERE id = ?", (1 if body["disabled"] else 0, user_id))
        if body["disabled"]:
            state.db.run("DELETE FROM sessions WHERE user_id = ?", (user_id,))  # signs them out everywhere
        audit.record(request, user, "Disabled account" if body["disabled"] else "Enabled account", email)
    if "password" in body:
        if len(str(body["password"])) < MIN_PASSWORD:
            raise HTTPException(400, "The password needs at least {} characters.".format(MIN_PASSWORD))
        state.db.run("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(str(body["password"])), user_id))
        if user_id != user["id"]:
            state.db.run("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        audit.record(request, user, "Set a new password", email)
    if "add_credits" in body:
        try:
            amount = int(body["add_credits"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Credits must be a whole number.")
        if amount == 0 or abs(amount) > 10000000:
            raise HTTPException(400, "Enter an amount between 1 and 10,000,000.")
        note = str(body.get("note", "")).strip()[:200]
        changed = state.credits.add(user_id, amount, "admin grant", note=note)
        state.notify(user_id)
        audit.record(request, user, "Gave credits" if changed >= 0 else "Took credits", email,
                     "{:+d}{}".format(changed, " · " + note if note else ""))
    return {"ok": True, "credits": state.credits.balance(user_id)}


# ---------------------------------------------------------------- jobs

@router.get("/jobs")
async def list_jobs(request: Request, status: str = "", q: str = "", offset: int = 0, user: dict = Depends(admin_user)):
    """Every user's jobs, newest first, 50 at a time. `status`: active, done, failed, cancelled or empty for all."""
    state = request.app.state
    where, params = [], []
    if status == "active":
        where.append("j.status IN ('queued', 'running')")
    elif status in ("done", "failed", "cancelled"):
        where.append("j.status = ?")
        params.append(status)
    if q.strip():
        where.append("(j.name LIKE ? ESCAPE '\\' OR j.workflow LIKE ? ESCAPE '\\' OR u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [_like(q)] * 4
    clause = "WHERE " + " AND ".join(where) if where else ""
    total = state.db.one("SELECT COUNT(*) n FROM jobs j JOIN users u ON u.id = j.user_id " + clause, params)["n"]
    jobs = state.db.all(
        "SELECT j.id, j.name, j.workflow, j.summary, j.status, j.error, j.cost, j.created, j.started, j.finished, "
        "u.id AS user_id, u.name AS user_name, u.email AS user_email FROM jobs j JOIN users u ON u.id = j.user_id "
        "{} ORDER BY j.created DESC LIMIT 50 OFFSET ?".format(clause), params + [max(0, offset)])
    for job in jobs:
        live = state.jobs.live.get(job["id"], {})
        job.update(step=live.get("step", 0), steps=live.get("steps", 0), clip=live.get("clip", 0),
                   clips=live.get("clips", 0), node=live.get("node", ""))
    return {"jobs": jobs, "total": total}


@router.get("/jobs/{job_id}")
async def job_detail(job_id: str, request: Request, user: dict = Depends(admin_user)):
    db = request.app.state.db
    job = db.one("SELECT j.*, u.name AS user_name, u.email AS user_email FROM jobs j JOIN users u ON u.id = j.user_id "
                 "WHERE j.id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "No such job.")
    job["settings"] = json.loads(job["settings"])
    job["items"] = db.all("SELECT id, kind, name, filename, size FROM generations WHERE job_id = ?", (job_id,))
    return job


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, request: Request, user: dict = Depends(admin_user)):
    """Cancel any user's waiting or running job. The user gets the credits back."""
    state = request.app.state
    job = state.db.one("SELECT j.user_id, j.status, j.name, u.email FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "No such job.")
    if job["status"] not in ("queued", "running"):
        raise HTTPException(400, "This job has already finished.")
    state.jobs.remove(job["user_id"], job_id)
    audit.record(request, user, "Cancelled a job", job["email"], job["name"])
    return {"ok": True}


# ---------------------------------------------------------------- library (all users)

def _item(request, item_id):
    row = request.app.state.db.one(
        "SELECT g.*, u.name AS user_name, u.email AS user_email FROM generations g JOIN users u ON u.id = g.user_id "
        "WHERE g.id = ?", (item_id,))
    if row is None:
        raise HTTPException(404, "No such item.")
    return row, request.app.state.outputs.folder(row["user_id"]) / row["filename"]


@router.get("/library")
async def list_library(request: Request, kind: str = "", q: str = "", owner: str = "", project: str = "", offset: int = 0,
                       user: dict = Depends(admin_user)):
    """Every user's items. `owner` is a user id; `project` is a project id or "none"."""
    where, params = [], []
    if kind in KINDS:
        where.append("g.kind = ?")
        params.append(kind)
    if owner.isdigit():
        where.append("g.user_id = ?")
        params.append(int(owner))
    if project == "none":
        where.append("g.project_id IS NULL")
    elif project.isdigit():
        where.append("g.project_id = ?")
        params.append(int(project))
    if q.strip():
        where.append("(g.name LIKE ? ESCAPE '\\' OR g.settings LIKE ? ESCAPE '\\' OR u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [_like(q)] * 4
    clause = "WHERE " + " AND ".join(where) if where else ""
    db = request.app.state.db
    total = db.one("SELECT COUNT(*) n FROM generations g JOIN users u ON u.id = g.user_id " + clause, params)["n"]
    items = db.all(
        "SELECT g.id, g.job_id, g.kind, g.name, g.filename, g.workflow, g.summary, g.seconds, g.size, g.created, g.settings, "
        "g.context, g.project_id, p.name AS project_name, j.cost, u.id AS user_id, u.name AS user_name, u.email AS user_email "
        "FROM generations g JOIN users u ON u.id = g.user_id LEFT JOIN projects p ON p.id = g.project_id "
        "LEFT JOIN jobs j ON j.id = g.job_id {} ORDER BY g.created DESC LIMIT 50 OFFSET ?".format(clause),
        params + [max(0, offset)])
    for item in items:
        item["settings"] = json.loads(item["settings"])
        item["context"] = json.loads(item["context"])
    return {
        "items": items, "total": total,
        # What the filters offer: people who have items, and their projects.
        "owners": db.all("SELECT u.id, u.name, u.email, COUNT(*) AS items FROM generations g JOIN users u ON u.id = g.user_id "
                         "GROUP BY u.id ORDER BY u.name COLLATE NOCASE"),
        "projects": db.all("SELECT p.id, p.name, p.user_id, u.name AS user_name FROM projects p JOIN users u ON u.id = p.user_id "
                           "ORDER BY p.name COLLATE NOCASE"),
    }


@router.get("/library/{item_id}/file")
async def library_file(item_id: int, request: Request, download: bool = False, user: dict = Depends(admin_user)):
    _, path = _item(request, item_id)
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    return FileResponse(path, filename=path.name if download else None)


@router.get("/library/{item_id}/poster")
async def library_poster(item_id: int, request: Request, user: dict = Depends(admin_user)):
    return await poster_response(request, _item(request, item_id)[1])


@router.delete("/library/{item_id}")
async def delete_library_item(item_id: int, request: Request, user: dict = Depends(admin_user)):
    """Remove an item from its owner's library (for content that breaks the rules)."""
    row, path = _item(request, item_id)
    path.unlink(missing_ok=True)
    media.poster_path(path).unlink(missing_ok=True)
    request.app.state.db.run("DELETE FROM generations WHERE id = ?", (item_id,))
    request.app.state.notify(row["user_id"], library_changed=True)
    audit.record(request, user, "Deleted a library item", row["user_email"], row["name"])
    return {"ok": True}


# ---------------------------------------------------------------- credits

@router.get("/credits")
async def credit_log(request: Request, reason: str = "", q: str = "", user: dict = Depends(admin_user)):
    db = request.app.state.db
    where, params = [], []
    if reason in ("welcome", "generation", "refund", "admin grant"):
        where.append("c.reason = ?")
        params.append(reason)
    if q.strip():
        where.append("(u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [_like(q)] * 2

    def total(condition):
        return db.one("SELECT SUM(amount) n FROM credit_events WHERE " + condition)["n"] or 0

    return {
        "events": db.all(
            "SELECT c.id, c.amount, c.reason, c.note, c.job_id, c.created, u.name AS user_name, u.email AS user_email, "
            "j.name AS job_name FROM credit_events c JOIN users u ON u.id = c.user_id LEFT JOIN jobs j ON j.id = c.job_id "
            "{} ORDER BY c.id DESC LIMIT 300".format("WHERE " + " AND ".join(where) if where else ""), params),
        "summary": {"welcome": total("reason = 'welcome'"), "granted": total("reason = 'admin grant'"),
                    "charged": -total("reason = 'generation'"), "refunded": total("reason = 'refund'"),
                    "held": db.one("SELECT SUM(credits) n FROM users")["n"] or 0},
    }


# ---------------------------------------------------------------- workflows, system, audit

@router.get("/workflows")
async def workflow_report(request: Request, user: dict = Depends(admin_user)):
    """Each workflow file: whether it can be read, whether it has presets, and how much it is used."""
    state = request.app.state
    usage = {r["workflow"]: r for r in state.db.all(
        "SELECT workflow, COUNT(*) AS jobs, SUM(status = 'done') AS done, SUM(status = 'failed') AS failed, "
        "AVG(CASE WHEN status = 'done' THEN finished - started END) AS avg_seconds, MAX(created) AS last_used "
        "FROM jobs GROUP BY workflow")}
    files = state.catalog.files()
    items = await state.catalog.listing()
    for item in items:
        path = files[item["id"]]
        used = usage.get(item["id"], {})
        item.update(file=path.name, presets=path.with_name(path.stem + ".studio.json").is_file(),
                    jobs=used.get("jobs", 0), done=used.get("done", 0) or 0, failed=used.get("failed", 0) or 0,
                    avg_seconds=used.get("avg_seconds"), last_used=used.get("last_used"))
    return {"workflows": items, "folder": str(state.catalog.directory)}


@router.get("/system")
async def system(request: Request, user: dict = Depends(admin_user)):
    state, db = request.app.state, request.app.state.db
    storage = state.storage_dir
    server = await _server(state)
    if server["online"]:
        try:
            server["queue"] = await state.comfy.queue_state()
        except (httpx.HTTPError, ValueError):
            server["queue"] = None
    disk = shutil.disk_usage(storage)
    try:
        ffmpeg = media.ffmpeg_path()
    except media.MediaError:
        ffmpeg = None
    database = storage / "scene.db"
    return {
        "server": server,
        "app": {"version": __version__, "python": platform.python_version(), "os": "{} {}".format(platform.system(), platform.release()),
                "uptime_seconds": time.time() - state.started, "ffmpeg": bool(ffmpeg),
                "open_connections": sum(len(s) for s in state.hub.sockets.values())},
        "storage": {"folder": str(storage), "disk_total": disk.total, "disk_free": disk.free,
                    "database": database.stat().st_size if database.is_file() else 0,
                    "library": db.one("SELECT SUM(size) n FROM generations")["n"] or 0,
                    "assets": db.one("SELECT SUM(size) n FROM assets")["n"] or 0},
        "counts": {name: db.one("SELECT COUNT(*) n FROM " + name)["n"]
                   for name in ("users", "sessions", "jobs", "generations", "assets", "projects", "credit_events", "audit_log")},
    }


@router.get("/audit")
async def audit_log(request: Request, q: str = "", user: dict = Depends(admin_user)):
    sql, params = "SELECT * FROM audit_log", []
    if q.strip():
        sql += " WHERE actor_name LIKE ? ESCAPE '\\' OR actor_email LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\'"
        params = [_like(q)] * 4
    return {"entries": request.app.state.db.all(sql + " ORDER BY id DESC LIMIT 300", params)}


# ---------------------------------------------------------------- settings

@router.get("/settings")
async def get_settings(request: Request, user: dict = Depends(admin_user)):
    return _settings(request.app.state)


@router.put("/settings")
async def put_settings(body: dict, request: Request, user: dict = Depends(admin_user)):
    state = request.app.state
    before = _settings(state)
    if "comfy_url" in body:
        url = str(body["comfy_url"]).strip().rstrip("/")
        if not re.match(r"^https?://[^\s/]+", url):
            raise HTTPException(400, "The address must look like http://192.168.1.20:8188")
        state.db.set_setting("comfy_url", url)
        state.catalog.forget_nodes()
    if "allow_signup" in body:
        state.db.set_setting("allow_signup", "1" if body["allow_signup"] else "0")
    if "signup_credits" in body:
        state.db.set_setting("signup_credits", int(_number(body, "signup_credits", 1000000)))
    after = _settings(state)
    changed = ["{}: {} to {}".format(k.replace("_", " "), before[k], after[k]) for k in after if after[k] != before[k]]
    if changed:
        audit.record(request, user, "Changed settings", "", "; ".join(changed))
    return after


# ---------------------------------------------------------------- pricing

# What an admin may set on a credit package and on a server: field -> type.
PACKAGE_FIELDS = {"name": str, "price_inr": float, "credits": int, "bonus_credits": int, "active": bool}
SERVER_FIELDS = {"name": str, "cpu": str, "gpu": str, "vram_gb": float, "role": str, "renders": bool, "idle_power_w": float,
                 "generation_power_w": float, "max_power_w": float, "preferred_workflows": str, "supported_workflows": str,
                 "purchase_price_inr": float, "purchase_date": str, "life_months": float, "salvage_value_inr": float,
                 "productive_hours": float, "active": bool}
REQUIRED = ("name", "price_inr", "credits", "bonus_credits")   # a number left empty anywhere else means "not known yet"
TABLES = {"packages": ("credit_packages", PACKAGE_FIELDS, "credit package"), "servers": ("servers", SERVER_FIELDS, "server")}


def _amount(value, label, empty=None, maximum=1e9):
    """A number an admin typed, or `empty` when the box was left blank."""
    if value is None or str(value).strip() == "":
        return empty
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "{} must be a number.".format(label))
    if not 0 <= value <= maximum:
        raise HTTPException(400, "{} must be between 0 and {:g}.".format(label, maximum))
    return value


def _row(body, fields):
    """The fields of `body` that the table has, each as its type."""
    row = {}
    for key, kind in fields.items():
        if key not in body:
            continue
        label = key.replace("_", " ").capitalize()
        if kind is bool:
            row[key] = 1 if body[key] else 0
        elif kind is str:
            row[key] = " ".join(str(body[key] or "").split())[:300]
        else:
            row[key] = _amount(body[key], label, 0 if key in REQUIRED else None)
            if kind is int and row[key] is not None:
                row[key] = int(row[key])
        if key == "name" and not row[key]:
            raise HTTPException(400, "Give it a name.")
    return row


def _pricing(state, items):
    """Everything the Pricing section shows. `items` is the workflow listing."""
    credits, db = state.credits, state.db
    listed = []
    for item in items + [{"id": MOTION, "kind": "motion", "title": "Motion graphics"},
                         {"id": OVERLAY, "kind": "overlay", "title": "Motion graphics over a video"}]:
        own = credits.pricing(item["id"]) or {}
        base, per_second, multiplier = credits.rate_for(item["id"])
        listed.append({
            "id": item["id"], "kind": item["kind"], "title": item["title"], "error": item.get("error"),
            "credits_per_second": own.get("credits_per_second"), "base_credits": own.get("base_credits"),
            "resolution_multiplier": own.get("resolution_multiplier", 1), "quality_multiplier": own.get("quality_multiplier", 1),
            "preferred_server": own.get("preferred_server", ""), "fallback_servers": own.get("fallback_servers", ""),
            "enabled": bool(own.get("enabled", 1)),
            # What it comes to: the rate in force, and the price of one image or of five seconds.
            "base": base, "per_second": per_second, "multiplier": multiplier, "example": credits.cost(item["id"], 5)})
    return {"rates": credits.rates(), "per_job": list(PER_JOB), "inr_per_1000_credits": credits.inr_per_1000,
            "electricity_inr_per_kwh": credits.electricity_rate, "workflows": listed,
            "packages": db.all("SELECT * FROM credit_packages ORDER BY price_inr, id"),
            "servers": db.all("SELECT * FROM servers ORDER BY id")}


@router.get("/pricing")
async def get_pricing(request: Request, user: dict = Depends(admin_user)):
    """The credit rates, each workflow's own pricing, the credit packages and the servers."""
    return _pricing(request.app.state, await request.app.state.catalog.listing())


@router.put("/pricing")
async def put_pricing(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Change the rate of a kind, what credits are worth, or the price of electricity."""
    state = request.app.state
    changed = []
    given = body.get("rates") if isinstance(body.get("rates"), dict) else {}
    values = {"rate_" + kind: given[kind] for kind in RATES if kind in given}
    values.update({key: body[key] for key in ("inr_per_1000_credits", "electricity_inr_per_kwh") if key in body})
    before = {**{"rate_" + k: v for k, v in state.credits.rates().items()},
              "inr_per_1000_credits": state.credits.inr_per_1000, "electricity_inr_per_kwh": state.credits.electricity_rate}
    for key, value in values.items():
        label = key.replace("rate_", "").replace("_", " ")
        value = _amount(value, label.capitalize(), maximum=1e6)
        if value is None:
            raise HTTPException(400, "{} can't be left empty.".format(label.capitalize()))
        if value != before[key]:
            state.db.set_setting(key, value)
            changed.append("{}: {:g} to {:g}".format(label, before[key], value))
    if changed:
        audit.record(request, user, "Changed pricing", "", "; ".join(changed))
    return _pricing(state, await state.catalog.listing())


@router.put("/pricing/workflow")
async def put_workflow_pricing(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Give one workflow its own pricing, or switch it off. A rate left empty follows the rate of the workflow's kind."""
    state = request.app.state
    workflow = str(body.get("workflow") or "")
    if workflow not in (MOTION, OVERLAY) and workflow not in state.catalog.files():
        raise HTTPException(404, "There is no workflow named '{}'.".format(workflow))
    row = {
        "credits_per_second": _amount(body.get("credits_per_second"), "Credits per second", maximum=1e6),
        "base_credits": _amount(body.get("base_credits"), "Base credits", maximum=1e6),
        "resolution_multiplier": _amount(body.get("resolution_multiplier"), "Resolution multiplier", 1, 1000),
        "quality_multiplier": _amount(body.get("quality_multiplier"), "Quality multiplier", 1, 1000),
        "preferred_server": " ".join(str(body.get("preferred_server") or "").split())[:80],
        "fallback_servers": " ".join(str(body.get("fallback_servers") or "").split())[:200],
        "enabled": 0 if body.get("enabled") is False else 1,
    }
    state.db.run("INSERT OR REPLACE INTO workflow_pricing (workflow, {}) VALUES (?, {})".format(", ".join(row), ", ".join("?" * len(row))),
                 (workflow, *row.values()))
    base, per_second, multiplier = state.credits.rate_for(workflow)
    audit.record(request, user, "Changed workflow pricing", workflow, "{:g} cr + {:g} cr/s × {:g}{}".format(
        base, per_second, multiplier, "" if row["enabled"] else " · switched off"))
    return _pricing(state, await state.catalog.listing())


@router.get("/economics")
async def economics(request: Request, days: int = 30, user: dict = Depends(admin_user)):
    """What each workflow earned and what it cost to run, from the jobs of the last `days` days. The cost is
    electricity only: the time a job ran, at the power of the server it ran on."""
    state, db = request.app.state, request.app.state.db
    days = days if days in RANGES else 30
    since = time.time() - days * DAY
    servers = db.all("SELECT name, generation_power_w, renders, active FROM servers ORDER BY id")
    watts = {s["name"]: s["generation_power_w"] for s in servers}
    usual = next((s["generation_power_w"] for s in servers if s["renders"] and s["active"]), None)   # for jobs from before servers were recorded
    per_kwh, per_credit = state.credits.electricity_rate, state.credits.inr_per_1000 / 1000
    titles = {w["id"]: w for w in await state.catalog.listing()}

    found = {}
    for row in db.all(
            "SELECT workflow, server, COUNT(*) AS jobs, SUM(status = 'done') AS done, SUM(status = 'failed') AS failed, "
            "SUM(status = 'cancelled') AS cancelled, SUM(retries) AS retries, SUM(output_size) AS output_bytes, "
            "SUM(CASE WHEN started IS NOT NULL THEN finished - started ELSE 0 END) AS run_seconds, "
            "SUM(CASE WHEN status = 'done' THEN finished - started ELSE 0 END) AS done_seconds, "
            "SUM(CASE WHEN status = 'done' THEN seconds_requested ELSE 0 END) AS seconds_made, "
            "SUM(CASE WHEN status = 'done' THEN cost ELSE 0 END) AS credits, "
            "SUM(CASE WHEN status != 'done' THEN cost ELSE 0 END) AS refunded "
            "FROM jobs WHERE created > ? AND status IN ('done', 'failed', 'cancelled') GROUP BY workflow, server", (since,)):
        item = found.setdefault(row["workflow"], {"id": row["workflow"], "electricity_inr": 0.0, "measured": True})
        for key in ("jobs", "done", "failed", "cancelled", "retries", "output_bytes", "run_seconds", "done_seconds", "seconds_made", "credits", "refunded"):
            item[key] = item.get(key, 0) + (row[key] or 0)
        power = watts.get(row["server"]) or usual
        if power:
            item["electricity_inr"] += (row["run_seconds"] or 0) / 3600 * power / 1000 * per_kwh
        elif row["run_seconds"]:
            item["measured"] = False   # it ran on a server whose power is not known

    # Motion graphics have no job: what was made is in the library, and what was paid is in the credit log.
    motion = db.one("SELECT COUNT(*) AS done, SUM(seconds) AS run_seconds, SUM(size) AS output_bytes, "
                    "SUM(json_extract(context, '$.duration')) AS seconds_made FROM generations WHERE workflow = ? AND created > ?", (MOTION, since))
    paid = -(db.one("SELECT SUM(amount) n FROM credit_events WHERE note = 'Motion graphics' AND created > ?", (since,))["n"] or 0)
    if motion["done"] or paid:
        found[MOTION] = {"id": MOTION, "jobs": motion["done"], "done": motion["done"], "failed": 0, "cancelled": 0, "retries": 0,
                         "output_bytes": motion["output_bytes"] or 0, "run_seconds": motion["run_seconds"] or 0,
                         "done_seconds": motion["run_seconds"] or 0, "seconds_made": motion["seconds_made"] or 0,
                         "credits": paid, "refunded": 0, "electricity_inr": 0.0, "measured": False}   # drawn on the host, whose power is not measured

    rows = []
    for item in found.values():
        known = titles.get(item["id"], {})
        done, runs = item["done"], item["done"] + item["failed"]
        item.update(
            title="Motion graphics" if item["id"] == MOTION else known.get("title") or item["id"],
            kind="motion" if item["id"] == MOTION else item["id"].split("/", 1)[0],
            success_rate=round(100 * done / runs, 1) if runs else None,
            runs_per_success=round(runs / done, 2) if done else None,          # 1.08 means 108 runs for 100 results
            avg_seconds=item["done_seconds"] / done if done else None,
            render_ratio=item["done_seconds"] / item["seconds_made"] if item["seconds_made"] else None,   # seconds of GPU per second made
            revenue_inr=item["credits"] * per_credit,
            electricity_inr=item["electricity_inr"] if item["measured"] else None)
        item["margin_inr"] = item["revenue_inr"] - item["electricity_inr"] if item["measured"] else None
        rows.append(item)
    rows.sort(key=lambda r: (-r["credits"], -r["jobs"]))

    def total(key):
        return sum(r[key] or 0 for r in rows)

    revenue, electricity = total("revenue_inr"), total("electricity_inr")
    runs = total("done") + total("failed")
    return {"days": days, "workflows": rows,
            "totals": {"jobs": total("jobs"), "done": total("done"), "failed": total("failed"), "cancelled": total("cancelled"),
                       "credits": total("credits"), "refunded": total("refunded"), "revenue_inr": revenue, "electricity_inr": electricity,
                       "margin_inr": revenue - electricity, "margin_percent": round(100 * (revenue - electricity) / revenue, 1) if revenue else None,
                       "run_seconds": total("run_seconds"), "output_bytes": total("output_bytes"),
                       "failure_rate": round(100 * total("failed") / runs, 1) if runs else None},
            "electricity_inr_per_kwh": per_kwh, "inr_per_1000_credits": state.credits.inr_per_1000,
            "unmeasured": [s["name"] for s in servers if s["active"] and not s["generation_power_w"]]}


@router.post("/pricing/{table}")
async def add_pricing_row(table: str, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Add a credit package or a server."""
    if table not in TABLES:
        raise HTTPException(404, "No such list.")
    name, fields, what = TABLES[table]
    row = dict(_row(dict({"name": ""}, **body), fields), created=time.time())
    new_id = request.app.state.db.run("INSERT INTO {} ({}) VALUES ({})".format(name, ", ".join(row), ", ".join("?" * len(row))), tuple(row.values()))
    audit.record(request, user, "Added a " + what, row["name"])
    return {"id": new_id}


@router.put("/pricing/{table}/{row_id}")
async def change_pricing_row(table: str, row_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    if table not in TABLES:
        raise HTTPException(404, "No such list.")
    name, fields, what = TABLES[table]
    found = request.app.state.db.one("SELECT name FROM {} WHERE id = ?".format(name), (row_id,))
    if found is None:
        raise HTTPException(404, "No such {}.".format(what))
    row = _row(body, fields)
    if row:
        request.app.state.db.run("UPDATE {} SET {} WHERE id = ?".format(name, ", ".join(key + " = ?" for key in row)), (*row.values(), row_id))
        audit.record(request, user, "Changed a " + what, row.get("name", found["name"]))
    return {"ok": True}


@router.delete("/pricing/{table}/{row_id}")
async def delete_pricing_row(table: str, row_id: int, request: Request, user: dict = Depends(admin_user)):
    if table not in TABLES:
        raise HTTPException(404, "No such list.")
    name, _, what = TABLES[table]
    found = request.app.state.db.one("SELECT name FROM {} WHERE id = ?".format(name), (row_id,))
    if found is None:
        raise HTTPException(404, "No such {}.".format(what))
    request.app.state.db.run("DELETE FROM {} WHERE id = ?".format(name), (row_id,))
    audit.record(request, user, "Deleted a " + what, found["name"])
    return {"ok": True}


# ---------------------------------------------------------------- export

EXPORTS = {
    "users": "SELECT u.id, u.name, u.email, u.role, u.credits, u.disabled, datetime(u.created, 'unixepoch') AS created_utc, "
             "(SELECT COUNT(*) FROM jobs j WHERE j.user_id = u.id) AS jobs, "
             "(SELECT COUNT(*) FROM generations g WHERE g.user_id = u.id) AS items FROM users u ORDER BY u.id",
    "jobs": "SELECT j.id, u.email AS user, j.name, j.workflow, j.summary, j.status, j.cost AS credits, "
            "j.credits_required, j.credits_reserved, j.credits_consumed, j.credits_refunded, j.seconds_requested, j.server, "
            "j.retries, j.output_size, "
            "datetime(j.created, 'unixepoch') AS created_utc, round(j.started - j.created, 1) AS wait_seconds, "
            "round(j.finished - j.started, 1) AS run_seconds, j.error FROM jobs j JOIN users u ON u.id = j.user_id ORDER BY j.created DESC",
    "credits": "SELECT c.id, u.email AS user, c.amount, c.reason, c.job_id, datetime(c.created, 'unixepoch') AS created_utc "
               "FROM credit_events c JOIN users u ON u.id = c.user_id ORDER BY c.id DESC",
    "audit": "SELECT id, actor_email AS actor, action, target, detail, ip, datetime(created, 'unixepoch') AS created_utc "
             "FROM audit_log ORDER BY id DESC",
}


def _cell(value):
    """Text that a spreadsheet would run as a formula is written as plain text instead."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@router.get("/export/{name}.csv")
async def export(name: str, request: Request, user: dict = Depends(admin_user)):
    if name not in EXPORTS:
        raise HTTPException(404, "No such export.")
    rows = request.app.state.db.all(EXPORTS[name])
    out = io.StringIO()
    writer = csv.writer(out)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([_cell(v) for v in row.values()] for row in rows)
    audit.record(request, user, "Exported data", name + ".csv", "{} rows".format(len(rows)))
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="scene_{}_{}.csv"'.format(name, date.today().isoformat())})
