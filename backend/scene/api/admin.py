"""The admin console: overview, users, every user's jobs and library, credits, workflows, system, audit log, settings."""

import asyncio
import csv
import io
import json
import os
import platform
import re
import shutil
import time
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import __version__, audit, backup, edits, endpoints, errors, health, kit, media, moderation, phone, roles, skills, staff, versions
from ..agent import AgentError
from ..catalog import KINDS
from ..comfy import workflows
from ..comfy.workflows import WorkflowError
from .. import credits as credits_module
from ..credits import MOTION, OVERLAY, PER_JOB, RATES
from .auth import new_hash, password_problem, signup_open
from ..security import new_token, token_hash
from .deps import CONSOLE_COOKIE, admin_user
from .library import poster_response
from .studio import current_announcement, needs_caption

router = APIRouter(prefix="/api/admin", tags=["admin"])
DAY = 86400
RANGES = (7, 30, 90)
SPEND = "reason IN ('generation', 'refund', 'agent')"   # a charge and its refund cancel out; messages to the agent are spending too
COUNT_IF = "SUM(CASE WHEN {} THEN 1 ELSE 0 END)"   # how many rows meet a condition, in SQL both databases speak
DONE_FAILED = COUNT_IF.format("status = 'done'") + " AS done, " + COUNT_IF.format("status = 'failed'") + " AS failed"


def _settings(state):
    return {"comfy_url": state.comfy.url, "allow_signup": signup_open(state),
            "signup_credits": state.credits.signup, "daily_cap": state.credits.daily_cap,
            "admin_mfa": state.db.setting("admin_mfa", "0") == "1"}


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


def _online(state):
    """Who has the studio open now, with the pages of their open tabs and their job, if one is waiting or running."""
    people = state.hub.people()
    if not people:
        return []
    marks = ", ".join("?" * len(people))
    users = {u["id"]: u for u in state.db.all("SELECT id, name, email, role FROM users WHERE id IN ({})".format(marks), list(people))}
    jobs = {}
    for job in state.db.all("SELECT user_id, name, status FROM jobs WHERE status IN ('queued', 'running') AND user_id IN ({}) "
                            "ORDER BY created".format(marks), list(people)):
        if job["user_id"] not in jobs or job["status"] == "running":
            jobs[job["user_id"]] = {"name": job["name"], "status": job["status"]}
    return sorted([dict(users[user_id], **found, job=jobs.get(user_id)) for user_id, found in people.items() if user_id in users],
                  key=lambda p: p["since"])


def _signups(state, now):
    """New accounts lately, and the addresses that made more than one of them in the last day."""
    db = state.db
    made = db.all("SELECT target, ip, created FROM audit_log WHERE action = 'Created account' AND created > ?", (now - DAY,))
    by_address = {}
    for row in made:
        by_address.setdefault(row["ip"], []).append(row["target"])
    recent = db.all("SELECT u.id, u.name, u.email, u.created, u.disabled, u.credits, "
                    "(SELECT COUNT(*) FROM jobs j WHERE j.user_id = u.id) AS jobs FROM users u ORDER BY u.created DESC LIMIT 8")
    address = {row["target"]: row["ip"] for row in db.all(
        "SELECT target, ip FROM audit_log WHERE action = 'Created account' ORDER BY id DESC LIMIT 200")}
    for user in recent:
        user["ip"] = address.get(user["email"], "")
    return {"open": signup_open(state), "today": len(made), "per_day": state.settings.signups_per_day, "recent": recent,
            "crowded": [{"ip": ip, "accounts": len(emails), "emails": emails} for ip, emails in by_address.items() if len(emails) > 1 and ip]}


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
            db.local_day(column), value, table, column, extra), since)

    server, model = await asyncio.gather(health.render_server(state), health.model_server(state))
    running = db.one("SELECT j.id, j.name, j.workflow, j.started, j.est_seconds, u.name AS user_name "
                     "FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.status = 'running'")
    if running:
        live = state.jobs.live.get(running["id"], {})
        running.update(step=live.get("step", 0), steps=live.get("steps", 0), clip=live.get("clip", 0),
                       clips=live.get("clips", 0), node=live.get("node", ""))
    waiting = db.all("SELECT j.id, j.name, j.workflow, j.created, j.est_seconds, j.priority, u.name AS user_name FROM jobs j "
                     "JOIN users u ON u.id = j.user_id WHERE j.status = 'queued' ORDER BY j.priority DESC, j.created LIMIT 8")

    # Things an admin should act on: what the watcher checks for (health.py), then what only matters here.
    attention = [{k: p[k] for k in ("level", "text", "tab")} for p in await health.problems(state, server, model)]
    closed = health.maintenance(db)
    if closed:
        left = db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued', 'running')")["n"]
        attention.append({"level": "warning", "text": "Maintenance has been on since {}: new jobs are refused. {}".format(
            health.clock(closed["since"]), "{} job{} left to finish.".format(left, "" if left == 1 else "s") if left else "The queue is empty."),
            "tab": "system"})
    if state.jobs.paused():
        attention.append({"level": "warning", "text": "Renders are paused. Jobs wait until you resume them.", "tab": "overview"})
    signups = _signups(state, now)
    for crowd in signups["crowded"]:
        attention.append({"level": "warning", "text": "{} accounts were made from one address ({}) in the last 24 hours.".format(
            crowd["accounts"], crowd["ip"]), "tab": "users"})
    money = _economics(state, days, titles={w["id"]: w for w in await state.catalog.listing()})
    for row in money["workflows"]:
        if row["margin_inr"] is not None and row["margin_inr"] < 0 and row["done"]:
            attention.append({"level": "warning", "text": "{} earned ₹{:,.0f} in {} days but its electricity cost ₹{:,.0f}. Its price no longer covers its cost.".format(
                row["title"], row["revenue_inr"], days, row["electricity_inr"]), "tab": "pricing"})
    failed_day = db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'failed' AND created > ?", (now - DAY,))["n"]
    if failed_day:
        attention.append({"level": "serious", "text": "{} job{} failed in the last 24 hours.".format(failed_day, "" if failed_day == 1 else "s"), "tab": "jobs"})
    broke = db.one("SELECT COUNT(*) n FROM users WHERE credits <= 0 AND disabled = 0")["n"]
    if broke:
        attention.append({"level": "warning", "text": "{} user{} out of credits.".format(broke, " is" if broke == 1 else "s are"), "tab": "users"})
    unreadable = [w["title"] for w in await state.catalog.listing() if w.get("error")]
    if unreadable:
        attention.append({"level": "warning", "text": "Workflows that can't be read: {}.".format(", ".join(unreadable)), "tab": "workflows"})

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
            "SELECT workflow, COUNT(*) AS jobs, " + DONE_FAILED + ", "
            "AVG(CASE WHEN status = 'done' THEN finished - started END) AS avg_seconds "
            "FROM jobs WHERE created > ? GROUP BY workflow ORDER BY jobs DESC LIMIT 6", (since,)),
        "failures": db.all(
            "SELECT substr(error, 1, 140) AS error, COUNT(*) AS jobs, MAX(created) AS last_seen FROM jobs "
            "WHERE status = 'failed' AND created > ? GROUP BY substr(error, 1, 140) ORDER BY jobs DESC, last_seen DESC LIMIT 5", (since,)),
        "queue": {"running": running, "waiting": waiting, "paused": state.jobs.paused(),
                  "waiting_total": db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'queued'")["n"]},
        "server": {"online": server["online"], "version": server.get("system", {}).get("comfyui_version"), "since": server["since"]},
        "model_server": {"online": model["online"], "since": model["since"] if model["url"] else None},
        "health": {"render": server["online"], "model": model["online"], "disk_free": shutil.disk_usage(state.output_dir).free,
                   "last_backup": backup.newest(state.backup_dir), "backups_on": state.settings.backup_keep > 0,
                   "alerts": len(db.all("SELECT id FROM alerts WHERE ended IS NULL")), "maintenance": bool(closed),
                   "node_list": state.catalog.nodes_saved()},
        "online": _online(state),
        "signups": signups,
        "economics": {"workflows": money["workflows"][:6], "totals": money["totals"], "unmeasured": money["unmeasured"]},
        "announcement": current_announcement(db),
        "attention": attention,
        "activity": sorted(activity, key=lambda a: a["time"], reverse=True)[:14],
        "totals": {"users": db.one("SELECT COUNT(*) n FROM users")["n"],
                   "online": state.hub.online(),
                   "items": db.one("SELECT COUNT(*) n FROM generations")["n"],
                   "credits_held": db.one("SELECT SUM(credits) n FROM users")["n"] or 0},
    }


# ---------------------------------------------------------------- users

USER_ROWS = (
    "SELECT u.id, u.email, u.name, u.role, u.credits, u.disabled, u.agent, u.mfa_enabled, u.created, "
    "(SELECT COUNT(*) FROM generations g WHERE g.user_id = u.id) AS generations, "
    "(SELECT COUNT(*) FROM jobs j WHERE j.user_id = u.id) AS jobs, "
    "(SELECT MAX(j.created) FROM jobs j WHERE j.user_id = u.id) AS last_job, "
    "(SELECT MAX(s.created) FROM sessions s WHERE s.user_id = u.id) AS last_sign_in, "
    "(SELECT -COALESCE(SUM(c.amount), 0) FROM credit_events c WHERE c.user_id = u.id AND c.{}) AS spent, u.daily_cap "
    "FROM users u ").format(SPEND)


@router.get("/users")
async def list_users(request: Request, q: str = "", show: str = "", user: dict = Depends(admin_user)):
    """`show` narrows the list: "admins", "disabled" or "no_credits"."""
    where, params = [], []
    if q.strip():
        where.append("(u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [_like(q)] * 2
    if show in ("admins", "disabled", "no_credits"):
        where.append({"admins": "u.role != 'user'", "disabled": "u.disabled = 1", "no_credits": "u.credits <= 0"}[show])
    sql = USER_ROWS + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY u.created"
    return {"users": request.app.state.db.all(sql, params)}


@router.get("/users/{user_id}")
async def user_detail(user_id: int, request: Request, user: dict = Depends(admin_user)):
    db = request.app.state.db
    found = db.one(USER_ROWS + "WHERE u.id = ?", (user_id,))
    if found is None:
        raise HTTPException(404, "No such user.")
    stats = db.one(
        "SELECT " + DONE_FAILED + ", " + COUNT_IF.format("status = 'cancelled'") + " AS cancelled, "
        "SUM(CASE WHEN status = 'done' THEN finished - started ELSE 0 END) AS gpu_seconds FROM jobs WHERE user_id = ?", (user_id,))
    state = request.app.state
    limits = {"own": found["daily_cap"], "studio": state.credits.daily_cap, "in_force": state.credits.cap_for(found),
              "spent_today": state.credits.spent_today(user_id), "exempt": found["role"] == "admin"}
    return {
        "user": found,
        "limits": limits,
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
        "sessions": _sessions(db, user_id, token_hash(request.cookies.get(CONSOLE_COOKIE, ""))),
    }


def _sessions(db, user_id, mine):
    """Where a user is signed in: each session's site, start, last use, address and browser. `key` names it (the first
    characters of its hash, never the whole); `here` is this console's own."""
    found = []
    for row in db.all("SELECT token_hash, console, created, expires, seen, ip, agent FROM sessions "
                      "WHERE user_id = ? AND expires > ? ORDER BY COALESCE(seen, created) DESC", (user_id, time.time())):
        hashed = row.pop("token_hash")
        found.append(dict(row, key=hashed[:12], here=hashed == mine))
    return found


@router.post("/users/{user_id}/view")
async def start_view(user_id: int, request: Request, user: dict = Depends(admin_user)):
    """A one-time code to open the studio as this user, read only (api/auth.view_as): to see what they see. An admin's
    alone, and never of another admin's account; it is written in the audit log when it is used."""
    state = request.app.state
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can view the studio as someone.")
    target = state.db.one("SELECT email, role, disabled FROM users WHERE id = ?", (user_id,))
    if target is None:
        raise HTTPException(404, "No such user.")
    if target["role"] == "admin" or user_id == user["id"]:
        raise HTTPException(400, "Not an admin's account.")
    if target["disabled"]:
        raise HTTPException(400, "The account is disabled: there is no studio to see.")
    code = new_token()
    state.view_codes = {k: v for k, v in state.view_codes.items() if v["expires"] > time.time()}   # forget the stale ones
    state.view_codes[token_hash(code)] = {"user_id": user_id, "admin_id": user["id"], "expires": time.time() + 120}
    return {"code": code, "path": "/api/auth/view/" + code, "port": state.settings.port}


@router.post("/users/{user_id}/sign-out")
async def sign_out_user(user_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    """End a user's sessions: one ({key}: the first characters of its hash, as the user's details list it) or all of them,
    in the studio and the console. This console's own session is kept."""
    db = request.app.state.db
    target = db.one("SELECT email, role FROM users WHERE id = ?", (user_id,))
    if target is None:
        raise HTTPException(404, "No such user.")
    if user["role"] != "admin" and target["role"] == "admin" and user_id != user["id"]:
        raise HTTPException(403, "Only an admin can sign an admin out.")
    mine = token_hash(request.cookies.get(CONSOLE_COOKIE, ""))
    key = str(body.get("key") or "")
    if key and not re.match(r"^[0-9a-f]{12}$", key):
        raise HTTPException(400, "No such session.")
    ended = db.change("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?" + (" AND token_hash LIKE ?" if key else ""),
                      (user_id, mine, *([key + "%"] if key else [])))
    audit.record(request, user, "Signed a user out", target["email"], "one session" if key else "everywhere")
    return {"ended": ended}


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Change a user's role, add credits (negative takes them away), disable the account, give or take access to
    the agent, set a new password, or turn off their two-step sign-in (when they have lost their phone)."""
    state = request.app.state
    target = state.db.one("SELECT email, role FROM users WHERE id = ?", (user_id,))
    if target is None:
        raise HTTPException(404, "No such user.")
    problem = staff.user_fields_problem(user["role"], body)
    if problem:
        raise HTTPException(403, problem)
    if user["role"] != "admin" and target["role"] == "admin":
        raise HTTPException(403, "Only an admin can change an admin's account.")
    email = target["email"]
    if ("role" in body or "disabled" in body) and user_id == user["id"]:
        raise HTTPException(400, "You can't change your own role or disable yourself.")
    if "role" in body:
        if body["role"] not in (*staff.roles(), "user"):
            raise HTTPException(400, "The role must be one of: {}.".format(", ".join((*staff.roles(), "user"))))
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
        if password_problem(str(body["password"])):
            raise HTTPException(400, password_problem(str(body["password"])))
        state.db.run("UPDATE users SET password_hash = ? WHERE id = ?", (await new_hash(str(body["password"])), user_id))
        if user_id != user["id"]:
            state.db.run("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        audit.record(request, user, "Set a new password", email)
    if "daily_cap" in body:
        own = None if body["daily_cap"] in (None, "") else int(_number(body, "daily_cap", 10000000))
        state.db.run("UPDATE users SET daily_cap = ? WHERE id = ?", (own, user_id))
        audit.record(request, user, "Set a daily credit limit", email,
                     "follows the studio's limit" if own is None else "no limit" if own == 0 else "{} credits".format(own))
    if body.get("mfa_off"):
        state.db.run("UPDATE users SET mfa_enabled = 0, mfa_secret = '', mfa_step = 0, mfa_recovery = '[]' WHERE id = ?", (user_id,))
        state.db.run("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        audit.record(request, user, "Turned off two-step sign-in", email)
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
                   clips=live.get("clips", 0), node=live.get("node", ""), explained=errors.explain(job["error"]))
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
    job["explained"] = errors.explain(job["error"])
    return job


@router.post("/jobs/{job_id}/front")
async def job_to_front(job_id: str, request: Request, user: dict = Depends(admin_user)):
    """Put a waiting job ahead of the others."""
    state = request.app.state
    job = state.db.one("SELECT j.status, j.name, u.email FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "No such job.")
    if job["status"] != "queued":
        raise HTTPException(400, "Only a waiting job can be moved.")
    state.jobs.to_front(job_id)
    audit.record(request, user, "Moved a job to the front", job["email"], job["name"])
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Run a failed or cancelled job again, for its user, with the same settings. Its first run was refunded, so the
    retry is charged like a new job, unless the admin makes it free ({"free": true}) when the failure was the studio's."""
    state = request.app.state
    job = state.db.one("SELECT j.*, u.email, u.disabled FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "No such job.")
    if job["status"] not in ("failed", "cancelled"):
        raise HTTPException(400, "Only a failed or cancelled job can be run again.")
    if job["disabled"]:
        raise HTTPException(400, "This user's account is disabled.")
    free = body.get("free") is True
    cost = 0 if free else job["cost"]
    if cost and not state.credits.charge(job["user_id"], cost, "generation", note="Run again by an admin"):
        raise HTTPException(402, "This needs {} credits and the user has {}. Give them credits, or run it again for free.".format(
            cost, state.credits.balance(job["user_id"])))
    new_id = state.jobs.add(job["user_id"], job["name"], job["workflow"], json.loads(job["settings"]), job["summary"],
                            job["est_seconds"], cost, job["project_id"], job["seconds_requested"])
    audit.record(request, user, "Ran a job again", job["email"], "{} · {}".format(job["name"], "free" if free else "{} cr".format(cost)))
    return {"id": new_id, "credits": cost}


@router.put("/queue")
async def pause_queue(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Pause or resume the renders. A job already running finishes; edits and motion graphics keep running."""
    paused = body.get("paused") is True
    request.app.state.jobs.pause(paused)
    audit.record(request, user, "Paused the renders" if paused else "Resumed the renders")
    return {"paused": paused}


@router.post("/server/check")
async def check_server(request: Request, user: dict = Depends(admin_user)):
    found = await health.render_server(request.app.state, fresh=True)
    return {"online": found["online"], "since": found["since"], "url": found["url"]}


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
                         "GROUP BY u.id ORDER BY lower(u.name)"),
        "projects": db.all("SELECT p.id, p.name, p.user_id, u.name AS user_name FROM projects p JOIN users u ON u.id = p.user_id "
                           "ORDER BY lower(p.name)"),
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
    media.remove_result(path)
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


@router.post("/credits/everyone")
async def credits_for_everyone(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Give every account that is not disabled the same number of credits, with a reason for the credit log."""
    state = request.app.state
    try:
        amount = int(body.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Credits must be a whole number.")
    if not 1 <= amount <= 1000000:
        raise HTTPException(400, "Enter an amount between 1 and 1,000,000.")
    note = " ".join(str(body.get("note") or "").split())[:200]
    if not note:
        raise HTTPException(400, "Write a reason. It shows in every user's credit history.")
    people = state.db.all("SELECT id FROM users WHERE disabled = 0")
    for person in people:
        state.credits.add(person["id"], amount, "admin grant", note=note)
        state.notify(person["id"])
    audit.record(request, user, "Gave everyone credits", "{} accounts".format(len(people)), "+{} · {}".format(amount, note))
    return {"accounts": len(people), "amount": amount}


# ---------------------------------------------------------------- workflows, system, audit

@router.get("/workflows")
async def workflow_report(request: Request, user: dict = Depends(admin_user)):
    """Each workflow file: whether it can be read, who it is offered to, what it needs that the render server lacked
    when its node list was saved, its versions, and how much it is used. Also what the render PC changed lately."""
    state = request.app.state
    versions.look(state)
    usage = {r["workflow"]: r for r in state.db.all(
        "SELECT workflow, COUNT(*) AS jobs, " + DONE_FAILED + ", "
        "AVG(CASE WHEN status = 'done' THEN finished - started END) AS avg_seconds, MAX(created) AS last_used "
        "FROM jobs GROUP BY workflow")}
    kept = {r["workflow"]: r for r in state.db.all(
        "SELECT workflow, COUNT(*) AS versions, MAX(seen) AS changed FROM workflow_versions GROUP BY workflow")}
    nodes = state.catalog.object_info or state.catalog.saved
    files = state.catalog.files()
    items = await state.catalog.listing()
    for item in items:
        path = files[item["id"]]
        used = usage.get(item["id"], {})
        try:
            needs = versions.missing(await state.catalog.load(item["id"]), nodes)
        except WorkflowError:
            needs = None
        item.update(file=path.name, presets=state.catalog.sidecar_of(path).is_file(),
                    jobs=used.get("jobs", 0), done=used.get("done", 0) or 0, failed=used.get("failed", 0) or 0,
                    avg_seconds=used.get("avg_seconds"), last_used=used.get("last_used"),
                    audience=versions.audience(state.credits.pricing(item["id"])), example=state.credits.cost(item["id"], 5),
                    missing=needs, versions=kept.get(item["id"], {}).get("versions", 0), changed=kept.get(item["id"], {}).get("changed"))
    return {"workflows": items, "folder": str(state.catalog.directory), "nodes_saved": state.catalog.nodes_saved(),
            "new_admins_only": state.db.setting("new_workflows_admins_only", "0") == "1", **state.versions.drops()}


@router.get("/workflows/history")
async def workflow_history(workflow: str, request: Request, user: dict = Depends(admin_user)):
    """Every version of one workflow, newest first, each with what changed from the one before."""
    return {"workflow": workflow, "versions": request.app.state.versions.history(workflow)}


@router.put("/workflows/audience")
async def workflow_audience(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Offer a workflow to everyone, to admins alone (to try it before users see it), or to nobody."""
    state = request.app.state
    workflow, audience = str(body.get("workflow") or ""), body.get("audience")
    if workflow not in state.catalog.files():
        raise HTTPException(404, "There is no workflow named '{}'.".format(workflow))
    if audience not in versions.AUDIENCES:
        raise HTTPException(400, "Offer it to everyone, admins or nobody.")
    versions.set_audience(state.db, workflow, audience)
    audit.record(request, user, "Changed who a workflow is offered to", workflow,
                 {"everyone": "everyone", "admins": "admins only", "off": "switched off"}[audience])
    return {"workflow": workflow, "audience": audience}


@router.put("/workflows/settings")
async def workflow_settings(body: dict, request: Request, user: dict = Depends(admin_user)):
    """{new_admins_only}: whether a workflow the render PC adds is offered to admins alone until one offers it to everyone."""
    hold = body.get("new_admins_only") is True
    request.app.state.db.set_setting("new_workflows_admins_only", "1" if hold else "0")
    audit.record(request, user, "New workflows start for admins only" if hold else "New workflows start for everyone")
    return {"new_admins_only": hold}


@router.post("/workflows/nodes")
async def refresh_nodes(request: Request, user: dict = Depends(admin_user)):
    """Fetch the render server's node list again: which node types and model files it has now."""
    state = request.app.state
    await state.catalog.refresh_nodes()   # an unreachable server is answered as such (main._answer_errors)
    return {"nodes_saved": state.catalog.nodes_saved()}


# A prompt for a test run of a workflow whose own prompt is empty.
SAMPLE = {"video": "A red fox trots through fresh snow at dawn. Soft golden light; the camera follows at its side.",
          "image": "A red fox sitting in fresh snow at dawn, soft golden light, fine detail.",
          "audio": "A calm piano piece with soft strings, slow and warm."}


@router.post("/workflows/test")
async def test_run(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Run a workflow once with its own settings and a sample prompt: free, first in the queue, and allowed under
    maintenance. The result goes to the admin's library."""
    state = request.app.state
    wf = await state.catalog.load(str(body.get("workflow") or ""))
    schema = workflows.describe(wf)
    settings = {"workflow": wf["id"], "values": {}, "options": {}, "refs": {}, "test": True}
    needed = [r["label"] for r in schema["refs"] if r["id"] in workflows.refs_in_use(schema, settings) and r.get("required")]
    if needed:
        raise HTTPException(400, "It needs a file to test with ({}). Try it from Create in the studio.".format(", ".join(needed)))
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    if "prompt" in roles and not roles["prompt"]["default"]:
        settings["values"][roles["prompt"]["id"]] = SAMPLE.get(wf["id"].split("/", 1)[0], SAMPLE["image"])
    _, ctx = workflows.build_prompt(wf, dict(settings, clips=1))   # a setting that is wrong fails here, not in the queue
    ctx = dict(workflows.context(schema, settings), seed=ctx.get("seed"))
    if "prompt" in roles:
        settings["prompt"] = str(settings["values"].get(roles["prompt"]["id"], roles["prompt"]["default"]) or "")
        needs_caption(wf, settings, roles["prompt"]["id"])
    settings["details"] = [[c["label"].split(" (")[0], c["default"]] for c in schema["controls"] if not c["role"]]
    settings["workflow_title"] = schema["title"]
    estimate = workflows.estimate(wf, settings, state.jobs.history())
    job_id = state.jobs.add(user["id"], "Test · " + schema["title"], wf["id"], settings, workflows.summary(schema, ctx),
                            estimate["minutes"] * 60 if estimate["minutes"] else None, 0, during_maintenance=True)
    state.db.run("UPDATE jobs SET priority = 100 WHERE id = ?", (job_id,))
    audit.record(request, user, "Test run of a workflow", wf["id"])
    return {"id": job_id, "name": "Test · " + schema["title"]}


@router.get("/system")
async def system(request: Request, user: dict = Depends(admin_user)):
    state, db = request.app.state, request.app.state.db
    storage = state.storage_dir
    server, model = await asyncio.gather(health.render_server(state), health.model_server(state))
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
    closed = health.maintenance(db)
    return {
        "server": server,
        "model_server": model,
        "maintenance": dict(closed, on=True, left=db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued', 'running')")["n"])
                       if closed else {"on": False},
        "alerts": db.all("SELECT * FROM alerts WHERE ended IS NULL ORDER BY started"),
        "app": {"version": __version__, "python": platform.python_version(), "os": "{} {}".format(platform.system(), platform.release()),
                "uptime_seconds": time.time() - state.started, "ffmpeg": bool(ffmpeg),
                "online_users": state.hub.online(), "open_connections": sum(len(s) for s in state.hub.sockets.values())},
        "storage": {"folder": str(storage), "disk_total": disk.total, "disk_free": disk.free,
                    "database": state.db.size(), "database_kind": state.db.kind,
                    "library": db.one("SELECT SUM(size) n FROM generations")["n"] or 0,
                    "assets": db.one("SELECT SUM(size) n FROM assets")["n"] or 0,
                    "backup_folder": str(state.backup_dir), "last_backup": backup.newest(state.backup_dir)},
        "counts": {name: db.one("SELECT COUNT(*) n FROM " + name)["n"]
                   for name in ("users", "sessions", "jobs", "generations", "assets", "projects", "credit_events", "audit_log")},
    }


@router.get("/backups")
async def list_backups(request: Request, user: dict = Depends(admin_user)):
    """The dated copies in the backup folder, newest first, and how they are made."""
    state = request.app.state
    folder = state.backup_dir
    copies = []
    if folder.is_dir():
        for f in folder.iterdir():
            if f.is_file() and (f.name.startswith("scene_") or f.name.startswith("config_")) and f.suffix in (".db", ".dump", ".json"):
                info = f.stat()
                copies.append({"name": f.name, "what": "settings (config.json)" if f.suffix == ".json" else "database",
                               "bytes": info.st_size, "made": info.st_mtime})
    copies.sort(key=lambda c: c["made"], reverse=True)
    return {"folder": str(folder), "keep": state.settings.backup_keep, "on": state.settings.backup_keep > 0,
            "database_kind": state.db.kind, "storage": str(state.storage_dir), "copies": copies, "check": backup.last_check(state.db)}


@router.post("/backups")
async def back_up_now(request: Request, user: dict = Depends(admin_user)):
    """Make today's copy now, in place of today's earlier one."""
    state = request.app.state
    if state.settings.backup_keep <= 0:
        raise HTTPException(400, "Backups are switched off on this installation (backup_keep is 0 in config.json).")
    try:
        target = await asyncio.to_thread(backup.make, state.db, state.backup_dir, state.settings.config_file, state.settings.backup_keep)
        files = await asyncio.to_thread(backup.copy_files, state.db, state.backup_dir, state.backup_files, state.settings.backup_keep)
    except Exception as error:
        raise HTTPException(400, "The backup failed: {}".format(error))
    audit.record(request, user, "Backed up the database and files", target.name)
    return {"ok": True, "name": target.name, "bytes": target.stat().st_size, "files": files}


def _folder_size(folder):
    """(files, bytes) of everything under a folder; a folder that is not there is (0, 0)."""
    files = total = 0
    for root, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:
                pass
    return files, total


@router.post("/backups/check")
async def check_backup(request: Request, user: dict = Depends(admin_user)):
    """Read the newest copy of the database back, to know it would serve if it were needed."""
    state = request.app.state
    found = await asyncio.to_thread(backup.check, state.db, state.backup_dir)
    audit.record(request, user, "Checked the newest backup", found.get("copy", ""), "whole" if found["ok"] else found.get("detail", ""))
    return found


@router.get("/audit/verify")
async def verify_audit(request: Request, user: dict = Depends(admin_user)):
    """Check the seals of the audit log: whether any entry was changed or taken out."""
    return audit.verify(request.app.state.db)


@router.get("/storage")
async def storage_report(request: Request, user: dict = Depends(admin_user)):
    """Disk space per user (their finished work and saved assets), the largest files, and the reference files the
    studio has put on the render server."""
    state, db = request.app.state, request.app.state.db
    people = []
    for person in db.all("SELECT id, name, email FROM users ORDER BY id"):
        files, used = await asyncio.to_thread(_folder_size, state.outputs.folder(person["id"]))
        asset_files, asset_bytes = await asyncio.to_thread(_folder_size, state.assets_dir / str(person["id"]))
        people.append(dict(person, files=files, bytes=used, asset_files=asset_files, asset_bytes=asset_bytes))
    people.sort(key=lambda p: p["bytes"] + p["asset_bytes"], reverse=True)
    largest = db.all("SELECT g.id, g.name, g.kind, g.size, g.created, g.filename, u.name AS user_name, u.email AS user_email "
                     "FROM generations g JOIN users u ON u.id = g.user_id WHERE g.size IS NOT NULL ORDER BY g.size DESC LIMIT 12")
    uploads = db.all("SELECT u.name AS user_name, u.email AS user_email, COUNT(*) AS files, MAX(x.created) AS newest "
                     "FROM uploads x JOIN users u ON u.id = x.user_id GROUP BY u.id ORDER BY files DESC")
    return {"people": people, "largest": largest,
            "render_server": {"by_user": uploads, "total": sum(u["files"] for u in uploads),
                              "newest": db.all("SELECT name, created FROM uploads ORDER BY created DESC LIMIT 10")}}


@router.get("/audit")
async def audit_log(request: Request, q: str = "", user: dict = Depends(admin_user)):
    sql, params = "SELECT * FROM audit_log", []
    if q.strip():
        sql += " WHERE actor_name LIKE ? ESCAPE '\\' OR actor_email LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\'"
        params = [_like(q)] * 4
    return {"entries": request.app.state.db.all(sql + " ORDER BY id DESC LIMIT 300", params)}


# ---------------------------------------------------------------- servers and APIs

@router.get("/endpoints")
async def list_endpoints(request: Request, fresh: bool = False, user: dict = Depends(admin_user)):
    """The ComfyUI servers, Ollama servers and hosted APIs, each with whether it answers (endpoints.py): as found in the
    last few seconds, or now (`fresh`, the section's Check again)."""
    state = request.app.state
    found = await health.remembered(state, "endpoints", lambda: endpoints.status(state), fresh)
    return {"kinds": endpoints.KINDS, "endpoints": found}


def _endpoints_changed(state, main_before):
    endpoints.apply(state.db, state.agent, state.settings)
    health.forget(state, "endpoints")   # the section shows the change at once
    if state.comfy.url != main_before:   # another main server: its nodes are read again
        state.catalog.forget_nodes()
    state.jobs.wake.set()   # a new free server takes the waiting renders


@router.post("/endpoints")
async def add_endpoint(body: dict, request: Request, user: dict = Depends(admin_user)):
    state, main = request.app.state, request.app.state.comfy.url
    row = endpoints.clean(body)
    state.db.run("INSERT INTO endpoints (kind, name, url, api_key, models, active, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (row["kind"], row["name"], row["url"], row["api_key"], row["models"], row["active"], time.time()))
    _endpoints_changed(state, main)
    audit.record(request, user, "Added a server", row["name"], "{} at {}".format(endpoints.KINDS[row["kind"]], row["url"]))
    return {}


@router.put("/endpoints/{endpoint_id}")
async def change_endpoint(endpoint_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    state, main = request.app.state, request.app.state.comfy.url
    before = state.db.one("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,))
    if before is None:
        raise HTTPException(404, "There is no such server.")
    if not str(body.get("api_key") or "").strip():
        body = {k: v for k, v in body.items() if k != "api_key"}   # left empty: the key it has is kept
    row = endpoints.clean(body, before)
    state.db.run("UPDATE endpoints SET kind = ?, name = ?, url = ?, api_key = ?, models = ?, active = ? WHERE id = ?",
                 (row["kind"], row["name"], row["url"], row["api_key"], row["models"], row["active"], endpoint_id))
    _endpoints_changed(state, main)
    audit.record(request, user, "Changed a server", row["name"], "{} at {}{}".format(
        endpoints.KINDS[row["kind"]], row["url"], "" if row["active"] else ", off"))
    return {}


@router.delete("/endpoints/{endpoint_id}")
async def remove_endpoint(endpoint_id: int, request: Request, user: dict = Depends(admin_user)):
    state, main = request.app.state, request.app.state.comfy.url
    before = state.db.one("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,))
    if before is None:
        raise HTTPException(404, "There is no such server.")
    if before["url"] in state.comfy_pool.busy:
        raise HTTPException(400, "A render is running there. Switch it off, and remove it once the render is done.")
    state.db.run("DELETE FROM endpoints WHERE id = ?", (endpoint_id,))
    _endpoints_changed(state, main)
    audit.record(request, user, "Removed a server", before["name"], before["url"])
    return {}


# ---------------------------------------------------------------- settings

@router.get("/settings")
async def get_settings(request: Request, user: dict = Depends(admin_user)):
    return _settings(request.app.state)


@router.put("/settings")
async def put_settings(body: dict, request: Request, user: dict = Depends(admin_user)):
    state = request.app.state
    before = _settings(state)
    if "allow_signup" in body:
        state.db.set_setting("allow_signup", "1" if body["allow_signup"] else "0")
    if "signup_credits" in body:
        state.db.set_setting("signup_credits", int(_number(body, "signup_credits", 1000000)))
    if "daily_cap" in body:
        state.db.set_setting("daily_cap", int(_number(body, "daily_cap", 10000000)))
    if "admin_mfa" in body:
        # Turning it on locks out every admin without two-step sign-in, so the one who turns it on must have it.
        if body["admin_mfa"] and not user["mfa_enabled"]:
            raise HTTPException(400, "Turn on two-step sign-in for your own account first (Settings, Two-step sign-in), "
                                     "so this does not lock you out.")
        state.db.set_setting("admin_mfa", "1" if body["admin_mfa"] else "0")
    after = _settings(state)
    changed = ["{}: {} to {}".format(k.replace("_", " "), before[k], after[k]) for k in after if after[k] != before[k]]
    if changed:
        audit.record(request, user, "Changed settings", "", "; ".join(changed))
    return after


@router.get("/admins")
async def admins_without_mfa(request: Request, user: dict = Depends(admin_user)):
    """The admins, and whether each has two-step sign-in: who would be locked out if it were required."""
    return {"admins": request.app.state.db.all("SELECT id, name, email, role, mfa_enabled FROM users WHERE role != 'user' AND disabled = 0 ORDER BY id"),
            "roles": [{"id": r, "label": staff.label(r), "about": staff.about(r)} for r in staff.roles()]}


# ---------------------------------------------------------------- projects

# A project's own rows and its modules' (a module is a project inside a project, sharing its kit).
IN_PROJECT = "({0}.project_id = p.id OR {0}.project_id IN (SELECT m.id FROM projects m WHERE m.parent_id = p.id))"


@router.get("/projects")
async def list_projects(request: Request, q: str = "", user: dict = Depends(admin_user)):
    """Every user's projects, the most recently used first: their modules, NeuralCore kit, items, jobs and space."""
    where, params = "p.parent_id IS NULL", []
    if q.strip():
        where += " AND (LOWER(p.name) LIKE ? ESCAPE '\\' OR LOWER(u.name) LIKE ? ESCAPE '\\' OR LOWER(u.email) LIKE ? ESCAPE '\\')"
        params = [_like(q.lower())] * 3   # lower case on both sides: PostgreSQL's LIKE minds case
    # Sorted outside: PostgreSQL takes a column's alias (last_job) in ORDER BY alone, not inside an expression.
    rows = request.app.state.db.all(
        "SELECT * FROM (SELECT p.id, p.name, p.created, u.id AS user_id, u.name AS user_name, u.email AS user_email, "
        "(SELECT COUNT(*) FROM projects m WHERE m.parent_id = p.id) AS modules, "
        "(SELECT COUNT(*) FROM assets a WHERE a.project_id = p.id) AS kit, "
        "(SELECT COUNT(*) FROM generations g WHERE " + IN_PROJECT.format("g") + ") AS items, "
        "(SELECT COALESCE(SUM(g.size), 0) FROM generations g WHERE " + IN_PROJECT.format("g") + ") AS bytes, "
        "(SELECT COUNT(*) FROM jobs j WHERE " + IN_PROJECT.format("j") + ") AS jobs, "
        "(SELECT MAX(j.created) FROM jobs j WHERE " + IN_PROJECT.format("j") + ") AS last_job "
        "FROM projects p JOIN users u ON u.id = p.user_id WHERE " + where + ") AS listed ORDER BY COALESCE(last_job, created) DESC LIMIT 200", params)
    return {"projects": rows}


@router.get("/projects/{project_id}")
async def project_detail(project_id: int, request: Request, user: dict = Depends(admin_user)):
    """One project: its owner, its modules, its NeuralCore kit (the entries the agent and the canvas use by name) and its
    latest items."""
    db = request.app.state.db
    project = db.one("SELECT p.*, u.name AS user_name, u.email AS user_email FROM projects p JOIN users u ON u.id = p.user_id "
                     "WHERE p.id = ?", (project_id,))
    if project is None:
        raise HTTPException(404, "No such project.")
    modules = db.all("SELECT m.id, m.name, m.created, (SELECT COUNT(*) FROM generations g WHERE g.project_id = m.id) AS items, "
                     "(SELECT COUNT(*) FROM jobs j WHERE j.project_id = m.id) AS jobs FROM projects m WHERE m.parent_id = ? ORDER BY m.id",
                     (project["parent_id"] or project_id,))
    root = project["parent_id"] or project_id
    return {"project": project, "modules": modules,
            "kit": [{k: e[k] for k in ("id", "name", "type", "kind", "about", "use_note", "always", "named", "origin", "size", "created")}
                    for e in kit.entries(db, project["user_id"], root)],
            "items": db.all("SELECT g.id, g.kind, g.name, g.filename, g.created FROM generations g, projects p WHERE p.id = ? AND "
                            + IN_PROJECT.format("g") + " ORDER BY g.created DESC LIMIT 12", (root,))}


@router.get("/assets/{asset_id}/file")
async def asset_file(asset_id: int, request: Request, user: dict = Depends(admin_user)):
    """A kit entry's file, for its picture in the console."""
    state = request.app.state
    row = state.db.one("SELECT user_id, filename FROM assets WHERE id = ?", (asset_id,))
    path = row and (state.assets_dir / str(row["user_id"]) / row["filename"]).resolve()
    if not path or not path.is_relative_to(state.assets_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "No such file.")
    return FileResponse(path)


# ---------------------------------------------------------------- moderation

@router.get("/moderation")
async def moderation_queue(request: Request, show: str = "review", user: dict = Depends(admin_user)):
    """What was made in the last 30 days and has no verdict yet, flagged first (its prompt has a listed word); or the
    verdicts (`show` "done") or the refused prompts (`show` "refused"); and the word list."""
    db, found = request.app.state.db, moderation.settings(request.app.state.db)
    if show == "refused":
        rows = db.all("SELECT m.*, u.name AS user_name, u.email AS user_email FROM moderation m LEFT JOIN users u ON u.id = m.user_id "
                      "WHERE m.kind = 'refused' ORDER BY m.id DESC LIMIT 200")
        return {"show": show, "items": rows, **found}
    if show == "done":
        rows = db.all("SELECT m.*, u.name AS user_name, u.email AS user_email FROM moderation m LEFT JOIN users u ON u.id = m.user_id "
                      "WHERE m.kind = 'review' ORDER BY m.id DESC LIMIT 200")
        return {"show": show, "items": rows, **found}
    rows = db.all("SELECT g.id, g.kind, g.name, g.filename, g.settings, g.created, u.id AS user_id, u.name AS user_name, u.email AS user_email "
                  "FROM generations g JOIN users u ON u.id = g.user_id WHERE g.created > ? AND g.run = '' AND NOT EXISTS "
                  "(SELECT 1 FROM moderation m WHERE m.generation_id = g.id) ORDER BY g.created DESC LIMIT 300", (time.time() - 30 * DAY,))
    items = []
    for row in rows:
        prompt = moderation.prompt_of(row.pop("settings"))
        items.append(dict(row, prompt=prompt[:400], words=moderation.matches(prompt + " " + row["name"], found["words"]) if found["mode"] != "off" else []))
    items.sort(key=lambda i: (not i["words"], -i["created"]))
    return {"show": "review", "items": items, "flagged": sum(1 for i in items if i["words"]), **found}


@router.post("/moderation/{item_id}")
async def moderate(item_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    """A verdict on one item: {verdict: "fine"} takes it off the queue; "removed" deletes it from its owner's library."""
    state, verdict = request.app.state, body.get("verdict")
    if verdict not in ("fine", "removed"):
        raise HTTPException(400, "The verdict is fine or removed.")
    row, path = _item(request, item_id)
    prompt = moderation.prompt_of(state.db.one("SELECT settings FROM generations WHERE id = ?", (item_id,))["settings"])
    words = ", ".join(moderation.matches(prompt + " " + row["name"], moderation.settings(state.db)["words"]))
    state.db.run("INSERT INTO moderation (kind, generation_id, user_id, verdict, words, prompt, by_name, created) "
                 "VALUES ('review', ?, ?, ?, ?, ?, ?, ?)", (item_id, row["user_id"], verdict, words, prompt[:1000], user["name"], time.time()))
    if verdict == "removed":
        media.remove_result(path)
        state.db.run("DELETE FROM generations WHERE id = ?", (item_id,))
        state.notify(row["user_id"], library_changed=True)
    audit.record(request, user, "Moderated an item: " + verdict, row["user_email"], row["name"])
    return {"ok": True}


@router.put("/moderation/settings")
async def moderation_settings(body: dict, request: Request, user: dict = Depends(admin_user)):
    """The words (a list, or one per line) and what is done about them: off, flag or refuse."""
    words = body.get("words")
    words = words.splitlines() if isinstance(words, str) else words if isinstance(words, list) else []
    if body.get("mode") not in moderation.MODES:
        raise HTTPException(400, "The mode is off, flag or refuse.")
    found = moderation.save(request.app.state.db, words, body["mode"])
    audit.record(request, user, "Changed the moderation words", "", "{} words, {}".format(len(found["words"]), found["mode"]))
    return found


# ---------------------------------------------------------------- search

@router.get("/search")
async def search(request: Request, q: str = "", user: dict = Depends(admin_user)):
    """People, jobs, projects and workflows whose name (or email, or id) has `q` in it: a few of each, for the console's
    search (Ctrl+K)."""
    state, db = request.app.state, request.app.state.db
    text = q.strip()
    if len(text) < 2:
        return {"users": [], "jobs": [], "projects": [], "workflows": []}
    like = _like(text.lower())   # lower case on both sides: PostgreSQL's LIKE minds case
    low = text.lower()
    return {
        "users": db.all("SELECT id, name, email, role, disabled FROM users WHERE LOWER(name) LIKE ? ESCAPE '\\' OR LOWER(email) LIKE ? ESCAPE '\\' "
                        "ORDER BY name LIMIT 6", (like, like)),
        "jobs": db.all("SELECT j.id, j.name, j.status, j.created, u.name AS user_name FROM jobs j JOIN users u ON u.id = j.user_id "
                       "WHERE LOWER(j.name) LIKE ? ESCAPE '\\' OR j.id = ? ORDER BY j.created DESC LIMIT 6", (like, text)),
        "projects": db.all("SELECT p.id, p.name, p.parent_id, u.name AS user_name FROM projects p JOIN users u ON u.id = p.user_id "
                           "WHERE LOWER(p.name) LIKE ? ESCAPE '\\' ORDER BY p.id DESC LIMIT 6", (like,)),
        "workflows": [{"id": w["id"], "title": w["title"]} for w in await state.catalog.listing()
                      if low in w["id"].lower() or low in w["title"].lower()][:6],
    }


# ---------------------------------------------------------------- the agent's models

CALL_STATS = ("COUNT(*) AS calls, " + COUNT_IF.format("error != ''") + " AS errors, AVG(seconds) AS avg_seconds, "
              "SUM(seconds) AS seconds, SUM(prompt_tokens) AS prompt_tokens, SUM(cached_tokens) AS cached_tokens, "
              "SUM(answer_tokens) AS answer_tokens, SUM(CASE WHEN error = '' THEN seconds ELSE 0 END) AS answered_seconds")


def _speed(row):
    """Answer tokens a second, over the calls that were answered: how fast a model writes."""
    return dict(row, tokens_per_second=round(row["answer_tokens"] / row["answered_seconds"], 1) if row.get("answered_seconds") else None)


@router.get("/agent")
async def agent_report(request: Request, days: int = 7, user: dict = Depends(admin_user)):
    """How the agent's models did in the last `days` days, by model and by what they were asked for; the latest runs (a
    run: the calls made for one turn of the agent); and the models chosen for its roles."""
    state, db = request.app.state, request.app.state.db
    days = days if days in (1, 7, 30) else 7
    since = time.time() - days * DAY
    try:
        models = await state.agent.models()
    except AgentError:
        models = []
    calls = db.all("SELECT c.*, u.name AS user_name, u.email AS user_email FROM agent_calls c LEFT JOIN users u ON u.id = c.user_id "
                   "ORDER BY c.id DESC LIMIT 600")
    runs = {}
    for call in reversed(calls):
        key = call["run"] or "call-{}".format(call["id"])
        run = runs.setdefault(key, {"run": key, "started": call["started"], "calls": 0, "seconds": 0.0, "tokens": 0, "errors": 0,
                                     "purposes": [], "models": [], "tools": [], "user_name": call["user_name"], "user_email": call["user_email"]})
        run["calls"] += 1
        run["seconds"] = max(run["seconds"], call["started"] + call["seconds"] - run["started"])
        run["tokens"] += call["prompt_tokens"] + call["answer_tokens"]
        run["errors"] += bool(call["error"])
        for field, value in (("purposes", call["purpose"]), ("models", call["model"] or call["asked"]), ("tools", call["tool"])):
            if value and value not in run[field]:
                run[field].append(value)
        run["user_name"] = run["user_name"] or call["user_name"]
    return {
        "days": days,
        "roles": roles.chosen(db), "configured": getattr(state.agent, "configured", {}), "models": models,
        "totals": _speed(db.one("SELECT " + CALL_STATS + " FROM agent_calls WHERE started > ?", (since,))),
        "by_model": [_speed(r) for r in db.all("SELECT model, " + CALL_STATS + " FROM agent_calls WHERE started > ? "
                                                "GROUP BY model ORDER BY calls DESC", (since,))],
        "by_purpose": [_speed(r) for r in db.all("SELECT purpose, " + CALL_STATS + " FROM agent_calls WHERE started > ? "
                                                  "GROUP BY purpose ORDER BY calls DESC", (since,))],
        "runs": sorted(runs.values(), key=lambda r: r["started"], reverse=True)[:40],
    }


@router.get("/agent/runs/{run}")
async def agent_run(run: str, request: Request, user: dict = Depends(admin_user)):
    """The calls of one run, in order."""
    db = request.app.state.db
    if run.startswith("call-") and run[5:].isdigit():
        found = db.all("SELECT * FROM agent_calls WHERE id = ?", (int(run[5:]),))
    else:
        found = db.all("SELECT * FROM agent_calls WHERE run = ? ORDER BY id", (run,))
    if not found:
        raise HTTPException(404, "No such run.")
    who = db.one("SELECT name, email FROM users WHERE id = ?", (found[0]["user_id"],)) if found[0]["user_id"] else None
    return {"run": run, "calls": found, "user": who}


@router.get("/agent/calls/{call_id}")
async def agent_call(call_id: int, request: Request, user: dict = Depends(admin_user)):
    """One call and its words: the messages sent and the answer, while they are kept (a week)."""
    state = request.app.state
    row = state.db.one("SELECT * FROM agent_calls WHERE id = ?", (call_id,))
    if row is None:
        raise HTTPException(404, "No such call.")
    return dict(row, exchange=state.traces.exchange(call_id))


@router.post("/agent/calls/{call_id}/replay")
async def replay_call(call_id: int, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Ask a model the same as this call asked, to compare: {model}. Pictures are not kept, so they are not sent again."""
    state = request.app.state
    kept = state.traces.exchange(call_id)
    if not kept:
        raise HTTPException(404, "The words of this call are no longer kept: they are kept for a week.")
    pictures = sum(int(m.get("images") or 0) for m in kept["messages"])
    messages = [{k: v for k, v in m.items() if k != "images"} for m in kept["messages"]]
    model = str(body.get("model") or "").strip() or None
    started = time.time()
    answer = await state.agent.chat(messages, kept["format"], model=model, purpose="replay")
    audit.record(request, user, "Replayed an agent call", str(call_id), answer.get("_model") or "")
    return {"model": answer.get("_model"), "seconds": round(time.time() - started, 2), "usage": answer.get("_usage"),
            "answer": {k: v for k, v in answer.items() if not k.startswith("_")}, "pictures_left_out": pictures}


@router.put("/agent/roles")
async def agent_roles(body: dict, request: Request, user: dict = Depends(admin_user)):
    """The models for the agent's roles: {main, fast, vision}; an empty one follows config.json. Takes effect at once."""
    state = request.app.state
    before = roles.chosen(state.db)
    found = roles.save(state.db, state.agent, body)
    changed = ["{}: {} to {}".format(role, before[role] or "config.json", found[role] or "config.json") for role in found if found[role] != before[role]]
    if changed:
        audit.record(request, user, "Changed the agent's models", "", "; ".join(changed))
    return {"roles": found, "configured": getattr(state.agent, "configured", {})}


# ---------------------------------------------------------------- maintenance and alerts

@router.put("/maintenance")
async def set_maintenance(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Turn maintenance mode on ({on: true, text}) or off. While it is on, new jobs are refused and their credits given
    back; the waiting and running ones still finish, and the studio shows the message."""
    db = request.app.state.db
    if body.get("on") is True:
        text = " ".join(str(body.get("text") or "").split())[:300] or "The studio is under maintenance. New jobs can start again soon."
        db.set_setting("maintenance", json.dumps({"text": text, "since": (health.maintenance(db) or {}).get("since") or time.time()}))
        audit.record(request, user, "Turned on maintenance mode", "", text[:200])
    else:
        db.set_setting("maintenance", "{}")
        audit.record(request, user, "Turned off maintenance mode")
    closed = health.maintenance(db)
    return dict(closed, on=True) if closed else {"on": False}


@router.get("/alerts")
async def alerts(request: Request, user: dict = Depends(admin_user)):
    """What the watcher found: the alerts still open and the latest ones, and where they are sent."""
    db = request.app.state.db
    return {"open": db.all("SELECT * FROM alerts WHERE ended IS NULL ORDER BY started"),
            "recent": db.all("SELECT * FROM alerts ORDER BY started DESC LIMIT 40"),
            "phone": phone.shown(phone.config(db)), "every": health.CHECK_EVERY, "confirm": health.CONFIRM}


@router.put("/alerts/phone")
async def set_phone(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Where alerts go: {telegram_token, telegram_chat, ntfy_url}. A token left empty keeps the saved one; `telegram:
    false` removes Telegram."""
    db = request.app.state.db
    found = phone.config(db)
    if body.get("telegram") is False:
        found.update(telegram_token="", telegram_chat="")
    else:
        token = str(body.get("telegram_token") or "").strip()
        if token:
            if not re.match(r"^\d+:[\w-]{20,}$", token):
                raise HTTPException(400, "That doesn't look like a bot token. @BotFather gives one like 123456789:AAH…")
            found["telegram_token"] = token
        if "telegram_chat" in body:
            chat = str(body.get("telegram_chat") or "").strip()
            if chat and not re.match(r"^-?\d{1,20}$|^@\w{4,}$", chat):
                raise HTTPException(400, "A chat is a number (or @channel name).")
            found["telegram_chat"] = chat
    if "ntfy_url" in body:
        url = str(body.get("ntfy_url") or "").strip()
        if url and not re.match(r"^https?://[^\s/]+/[\w.-]+$", url):
            raise HTTPException(400, "An ntfy address is the server and a topic, for example https://ntfy.sh/scene-alerts-7f3k.")
        found["ntfy_url"] = url
    phone.save(db, found)
    audit.record(request, user, "Changed the phone alerts")
    return phone.shown(found)


@router.post("/alerts/telegram-chat")
async def find_telegram_chat(request: Request, user: dict = Depends(admin_user)):
    """The admin's chat with their bot, from the newest message they sent it, saved as where alerts go."""
    db = request.app.state.db
    found = phone.config(db)
    if not found["telegram_token"]:
        raise HTTPException(400, "Save the bot's token first.")
    async with httpx.AsyncClient(timeout=10) as http:
        chat = await phone.telegram_chat(http, found["telegram_token"])
    if chat is None:
        raise HTTPException(400, "No message found. Open your bot in Telegram, press Start or send it any message, then try again.")
    found["telegram_chat"] = chat
    phone.save(db, found)
    return phone.shown(found)


@router.post("/alerts/test")
async def test_alert(request: Request, user: dict = Depends(admin_user)):
    """Send a test alert everywhere alerts go, and say what happened on each."""
    db = request.app.state.db
    async with httpx.AsyncClient(timeout=10) as http:
        results = await phone.send(http, db, "test", "A test from the admin console, sent by {}. Alerts will arrive like this.".format(user["name"]))
    if not results:
        raise HTTPException(400, "Nowhere to send it yet: set up Telegram or ntfy first.")
    return {"results": results}


@router.get("/announcement")
async def announcement(request: Request, user: dict = Depends(admin_user)):
    return current_announcement(request.app.state.db)


@router.put("/announcement")
async def set_announcement(body: dict, request: Request, user: dict = Depends(admin_user)):
    """A message every user sees at the top of the studio: {text, level: info|warning, hours: 0 for until removed}.
    Empty text removes it."""
    db = request.app.state.db
    text = " ".join(str(body.get("text") or "").split())[:300]
    if not text:
        db.set_setting("announcement", "{}")
        audit.record(request, user, "Removed the announcement")
        return {}
    hours = _number(body, "hours", 24 * 30) if body.get("hours") not in (None, "") else 0
    found = {"text": text, "level": "warning" if body.get("level") == "warning" else "info",
             "until": time.time() + hours * 3600 if hours else None, "set": time.time()}
    db.set_setting("announcement", json.dumps(found))
    audit.record(request, user, "Published an announcement", "", text[:200])
    return current_announcement(db)


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
            "enabled": bool(own.get("enabled", 1)), "admins_only": bool(own.get("admins_only")),
            "own_factors": credits._json(own.get("factors") or "{}"),
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


@router.get("/pricing/llm")
async def get_llm_pricing(request: Request, user: dict = Depends(admin_user)):
    """What a message to the agent costs with each model it can use (and any model that has a price but is not there now)."""
    state = request.app.state
    try:
        models = await state.agent.models()
    except AgentError:
        models = []
    prices = state.credits.llm_prices()
    return {"models": [{"model": m, "credits": prices.get(m, 0), "available": m in models} for m in [*models, *(p for p in prices if p not in models)]],
            "inr_per_1000_credits": state.credits.inr_per_1000}


@router.put("/pricing/llm")
async def put_llm_pricing(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Set what a message to the agent costs with one model: {"model", "credits"}; 0 makes it free."""
    state = request.app.state
    model = str(body.get("model") or "").strip()[:120]
    if not model:
        raise HTTPException(400, "Name the model.")
    value = _amount(body.get("credits"), "Credits per message", maximum=1e5)
    if value is None or value != int(value):
        raise HTTPException(400, "Credits per message is a whole number.")
    before = state.credits.llm_cost(model)
    state.credits.set_llm_price(model, int(value))
    if int(value) != before:
        audit.record(request, user, "Changed agent model pricing", model, "{} cr to {} cr a message".format(before, int(value)))
    return await get_llm_pricing(request, user)


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
    state.db.run("INSERT INTO workflow_pricing (workflow, {}) VALUES (?, {}) ON CONFLICT (workflow) DO UPDATE SET {}".format(
        ", ".join(row), ", ".join("?" * len(row)), ", ".join("{0} = excluded.{0}".format(key) for key in row)),
                 (workflow, *row.values()))
    base, per_second, multiplier = state.credits.rate_for(workflow)
    audit.record(request, user, "Changed workflow pricing", workflow, "{:g} cr + {:g} cr/s × {:g}{}".format(
        base, per_second, multiplier, "" if row["enabled"] else " · switched off"))
    return _pricing(state, await state.catalog.listing())


# ---------------------------------------------------------------- resolution and quality factors

def _tier_times(db, days=90):
    """How long the renders of each resolution and quality took, from the jobs of the last `days` days that finished:
    seconds of render per second of video asked for, and seconds a picture. {"resolution": {tier: (average, jobs)},
    "quality": {...}}."""
    found = {"resolution": {}, "quality": {}}
    for job in db.all("SELECT workflow, settings, started, finished, seconds_requested FROM jobs WHERE status = 'done' "
                      "AND started IS NOT NULL AND finished IS NOT NULL AND created > ?", (time.time() - days * DAY,)):
        try:
            settings = json.loads(job["settings"])
        except ValueError:
            continue
        took = job["finished"] - job["started"]
        per = took / job["seconds_requested"] if job["seconds_requested"] else took
        tier = credits_module.RESOLUTION_TIER.get(settings.get("resolution") if isinstance(settings.get("resolution"), int) else None)
        if tier and not job["workflow"].startswith("image/"):
            found["resolution"].setdefault(tier, []).append(per)
        quality = (settings.get("options") or {}).get("quality")
        if quality:
            found["quality"].setdefault(str(quality), []).append(per)
    return {group: {k: (sum(v) / len(v), len(v)) for k, v in tiers.items()} for group, tiers in found.items()}


def _suggested(times):
    """Factors in proportion to how long each tier took, against 720p and final (or high): what each costs the GPU."""
    suggested = {}
    for group, reference in (("resolution", ("720",)), ("quality", ("final", "high"))):
        base = next((times[group][r][0] for r in reference if r in times[group]), None)
        if base:
            suggested[group] = {tier: round(avg / base, 2) for tier, (avg, _) in times[group].items()}
    return suggested


@router.get("/pricing/factors")
async def get_factors(request: Request, user: dict = Depends(admin_user)):
    """The studio's resolution and quality factors, what they began as, and factors suggested by how long renders of
    each took, with how many jobs each suggestion stands on."""
    state = request.app.state
    times = _tier_times(state.db)
    return {"factors": state.credits.factors(), "defaults": credits_module.FACTORS, "suggested": _suggested(times),
            "samples": {group: {tier: n for tier, (_, n) in tiers.items()} for group, tiers in times.items()},
            "rates": state.credits.rates()}


def _factor_table(body):
    """{"resolution": {...}, "quality": {...}} with each factor a number from 0 to 20; a factor left empty is dropped."""
    found = {}
    for group in ("resolution", "quality"):
        given = body.get(group) if isinstance(body.get(group), dict) else {}
        values = {}
        for key, value in given.items():
            if key not in credits_module.FACTORS[group] or value in (None, ""):
                continue
            number = _amount(value, "The {} factor for {}".format(group, key), 0, 20)
            values[key] = number
        found[group] = values
    return found


@router.put("/pricing/factors")
async def put_factors(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Set the studio's resolution and quality factors; a factor left out goes back to where it began."""
    state = request.app.state
    before = state.credits.factors()
    state.db.set_setting("price_factors", json.dumps(_factor_table(body)))
    after = state.credits.factors()
    changed = ["{} {}: {:g} to {:g}".format(group, key, before[group][key], after[group][key])
               for group in after for key in after[group] if before[group].get(key) != after[group][key]]
    if changed:
        audit.record(request, user, "Changed the price factors", "", "; ".join(changed))
    return await get_factors(request, user)


@router.put("/pricing/workflow/factors")
async def put_workflow_factors(body: dict, request: Request, user: dict = Depends(admin_user)):
    """A workflow's own resolution and quality factors over the studio's: {workflow, resolution: {...}, quality: {...}};
    empty ones follow the studio's."""
    state = request.app.state
    workflow = str(body.get("workflow") or "")
    if workflow not in state.catalog.files():
        raise HTTPException(404, "There is no workflow named '{}'.".format(workflow))
    table = _factor_table(body)
    own = json.dumps(table) if any(table.values()) else ""
    state.db.run("INSERT INTO workflow_pricing (workflow, factors) VALUES (?, ?) ON CONFLICT (workflow) DO UPDATE SET factors = excluded.factors",
                 (workflow, own))
    audit.record(request, user, "Changed a workflow's price factors", workflow, own or "follows the studio's")
    return {"workflow": workflow, "factors": state.credits.factors(workflow), "own": table}


@router.get("/economics")
async def economics(request: Request, days: int = 30, user: dict = Depends(admin_user)):
    """What each workflow earned and what it cost to run, from the jobs of the last `days` days. The cost is
    electricity only: the time a job ran, at the power of the server it ran on. Edits and motion graphics are jobs
    too, made on the machine that hosts the studio."""
    state = request.app.state
    return _economics(state, days if days in RANGES else 30, {w["id"]: w for w in await state.catalog.listing()})


def _economics(state, days, titles):
    db = state.db
    since = time.time() - days * DAY
    servers = db.all("SELECT name, generation_power_w, renders, active FROM servers ORDER BY id")
    watts = {s["name"]: s["generation_power_w"] for s in servers}
    usual = next((s["generation_power_w"] for s in servers if s["renders"] and s["active"]), None)   # for jobs from before servers were recorded
    per_kwh, per_credit = state.credits.electricity_rate, state.credits.inr_per_1000 / 1000

    found = {}
    for row in db.all(
            "SELECT workflow, server, COUNT(*) AS jobs, " + DONE_FAILED + ", "
            + COUNT_IF.format("status = 'cancelled'") + " AS cancelled, SUM(retries) AS retries, SUM(output_size) AS output_bytes, "
            "SUM(CASE WHEN started IS NOT NULL THEN finished - started ELSE 0 END) AS run_seconds, "
            "SUM(CASE WHEN status = 'done' THEN finished - started ELSE 0 END) AS done_seconds, "
            "SUM(CASE WHEN status = 'done' THEN seconds_requested ELSE 0 END) AS seconds_made, "
            "SUM(CASE WHEN status = 'done' THEN cost ELSE 0 END) AS credits, "
            "SUM(CASE WHEN status != 'done' THEN cost ELSE 0 END) AS refunded "
            "FROM jobs WHERE created > ? AND status IN ('done', 'failed', 'cancelled') GROUP BY workflow, server", (since,)):
        item = found.setdefault(row["workflow"], {"id": row["workflow"], "electricity_inr": 0.0, "measured": True})
        for key in ("jobs", "done", "failed", "cancelled", "retries", "output_bytes", "run_seconds", "done_seconds", "seconds_made", "credits", "refunded"):
            item[key] = item.get(key, 0) + (row[key] or 0)
        power = watts[row["server"]] if row["server"] in watts else usual
        if power:
            item["electricity_inr"] += (row["run_seconds"] or 0) / 3600 * power / 1000 * per_kwh
        elif row["run_seconds"]:
            item["measured"] = False   # it ran on a server whose power is not known

    rows = []
    for item in found.values():
        known = titles.get(item["id"], {})
        done, runs = item["done"], item["done"] + item["failed"]
        item.update(
            title=edits.TITLES.get(item["id"]) or known.get("title") or item["id"],
            kind=item["id"].split("/", 1)[0],
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

# Each export is SQL with {created} where the time of the row goes, written as text the way the database knows how.
EXPORTS = {
    "users": "SELECT u.id, u.name, u.email, u.role, u.credits, u.disabled, {created} AS created_utc, "
             "(SELECT COUNT(*) FROM jobs j WHERE j.user_id = u.id) AS jobs, "
             "(SELECT COUNT(*) FROM generations g WHERE g.user_id = u.id) AS items FROM users u ORDER BY u.id",
    "jobs": "SELECT j.id, u.email AS user, j.name, j.workflow, j.summary, j.status, j.cost AS credits, "
            "j.credits_required, j.credits_reserved, j.credits_consumed, j.credits_refunded, j.seconds_requested, j.server, "
            "j.retries, j.output_size, "
            "{created} AS created_utc, round(CAST(j.started - j.created AS NUMERIC), 1) AS wait_seconds, "
            "round(CAST(j.finished - j.started AS NUMERIC), 1) AS run_seconds, j.error FROM jobs j JOIN users u ON u.id = j.user_id ORDER BY j.created DESC",
    "credits": "SELECT c.id, u.email AS user, c.amount, c.reason, c.job_id, {created} AS created_utc "
               "FROM credit_events c JOIN users u ON u.id = c.user_id ORDER BY c.id DESC",
    "audit": "SELECT id, actor_email AS actor, action, target, detail, ip, {created} AS created_utc "
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
    db = request.app.state.db
    table = {"users": "u", "jobs": "j", "credits": "c"}.get(name)
    rows = db.all(EXPORTS[name].format(created=db.utc_text(table + ".created" if table else "created")))
    out = io.StringIO()
    writer = csv.writer(out)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([_cell(v) for v in row.values()] for row in rows)
    audit.record(request, user, "Exported data", name + ".csv", "{} rows".format(len(rows)))
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="scene_{}_{}.csv"'.format(name, date.today().isoformat())})


# ---------------------------------------------------------------- skills: the recipes the agent follows, as files

@router.get("/skills")
async def admin_list_skills(user: dict = Depends(admin_user)):
    """Every skill with its full recipe, for the admin console's Skills section."""
    return {"skills": [{"id": s["id"], "title": s["title"], "desc": s["desc"], "version": s["version"],
                        "words": s["words"].pattern, "text": s["text"]} for s in skills.load()]}


@router.post("/skills")
async def admin_create_skill(body: dict, request: Request, user: dict = Depends(admin_user)):
    """Make a new skill. The id becomes the file name and the /command, and must not already be in use."""
    sid = skills._line(body.get("id")).lower()
    if skills.find(sid):
        raise HTTPException(400, "A skill with the id “{}” already exists.".format(sid))
    try:
        saved = skills.save(body)
    except ValueError as err:
        raise HTTPException(400, str(err))
    audit.record(request, user, "Created skill", saved["id"], saved["title"])
    return {"skill": {"id": saved["id"], "title": saved["title"], "desc": saved["desc"], "version": saved["version"],
                      "words": saved["words"].pattern, "text": saved["text"]}}


@router.put("/skills/{skill_id}")
async def admin_update_skill(skill_id: str, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Change a skill's title, description, trigger words, version or steps. The id (file name) stays the same."""
    if not skills.find(skill_id):
        raise HTTPException(404, "No such skill.")
    try:
        saved = skills.save({**body, "id": skill_id})
    except ValueError as err:
        raise HTTPException(400, str(err))
    audit.record(request, user, "Edited skill", saved["id"], saved["title"])
    return {"skill": {"id": saved["id"], "title": saved["title"], "desc": saved["desc"], "version": saved["version"],
                      "words": saved["words"].pattern, "text": saved["text"]}}


@router.delete("/skills/{skill_id}")
async def admin_delete_skill(skill_id: str, request: Request, user: dict = Depends(admin_user)):
    """Delete a skill file for good."""
    if not skills.remove(skill_id):
        raise HTTPException(404, "No such skill.")
    audit.record(request, user, "Deleted skill", skill_id)
    return {"ok": True}


# ---------------------------------------------------------------- roles of the staff (staff.py)

@router.get("/roles")
async def list_roles(request: Request, user: dict = Depends(admin_user)):
    """The staff roles, what each may see and change, how many people have each, and the areas there are to give."""
    db = request.app.state.db
    counts = {r["role"]: r["n"] for r in db.all("SELECT role, COUNT(*) AS n FROM users GROUP BY role")}
    return {"roles": [dict(r, people=counts.get(r["id"], 0)) for r in staff.described()],
            "areas": [{"id": a, "label": label} for a, label in staff.AREAS.items()]}


@router.put("/roles/{role_id}")
async def save_role(role_id: str, body: dict, request: Request, user: dict = Depends(admin_user)):
    """Make a role (role_id "new") or change one: {"label", "about", "read": [area], "write": [area]}."""
    try:
        saved = staff.save(request.app.state.db, None if role_id == "new" else role_id, body)
    except ValueError as error:
        raise HTTPException(400, str(error))
    audit.record(request, user, "Saved a role", saved, "sees {}; changes {}".format(", ".join(body.get("read") or []) or "nothing",
                                                                                ", ".join(body.get("write") or []) or "nothing"))
    return {"id": saved, "roles": staff.described()}


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, request: Request, user: dict = Depends(admin_user)):
    """Delete a role no one has. A built-in one can be deleted too; it comes back only by making it again."""
    db = request.app.state.db
    if role_id not in staff.roles() or role_id == "admin":
        raise HTTPException(404, "No such role.")
    if db.one("SELECT 1 FROM users WHERE role = ?", (role_id,)):
        raise HTTPException(400, "Some people have this role. Give them another one first.")
    staff.delete(db, role_id)
    audit.record(request, user, "Deleted a role", role_id)
    return {"roles": staff.described()}

