"""Shared request helpers: who is signed in, and how often they may ask."""

import time

from fastapi import Depends, HTTPException, Request

from .. import staff
from ..db import act_for, act_for_everyone
from ..security import client_address, token_hash

COOKIE = "scene_session"
# The admin console's sign-in. A browser sends both cookies to both sites (a cookie is kept per host, not per port), so
# each session also records which site it is for, and neither opens the other.
CONSOLE_COOKIE = "scene_console"
SEEN_EVERY = 300   # seconds: how often a session's last use is written down


def user_for_token(db, token, console=False):
    if not token:
        return None
    hashed, now = token_hash(token), time.time()
    user = db.one(
        "SELECT u.id, u.email, u.name, u.role, u.credits, u.created, u.agent, u.mfa_enabled, s.seen AS session_seen, "
        "v.name AS viewer FROM sessions s JOIN users u ON u.id = s.user_id LEFT JOIN users v ON v.id = s.view_as "
        "WHERE s.token_hash = ? AND s.expires > ? AND s.console = ? AND u.disabled = 0",
        (hashed, now, int(console)))
    if user:
        if (user.pop("session_seen") or 0) < now - SEEN_EVERY:   # when it was last used, written now and then, not every time
            db.run("UPDATE sessions SET seen = ? WHERE token_hash = ?", (now, hashed))
        viewer = user.pop("viewer")
        if viewer:   # an admin looking at the studio as this user (api/admin.view_as): read only
            user["viewing"] = {"by": viewer}
        user["agent"] = may_use_agent(user)
    return user


def may_use_agent(user):
    """Every account has the agent (17 October: every user sees the same studio). What a message costs is set per
    model in the admin console's Pricing. The `agent` column of users is no longer read."""
    return True


async def current_user(request: Request):
    """The signed-in user. From here on the request's statements see only that user's rows (row-level security).
    Async on purpose: a dependency run in a thread could not pass that on to the request."""
    user = user_for_token(request.app.state.db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Please sign in.")
    if user.get("viewing") and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(403, "This is a read-only view of {}'s studio: nothing can be changed or made.".format(user["name"]))
    act_for(user["id"])
    return user


async def agent_user(user: dict = Depends(current_user)):
    if not user["agent"]:
        raise HTTPException(403, "The agent is coming soon. An admin can give your account access to it.")
    return user


def admin_problem(db, user):
    """Why this user may not use the admin console, or None. The console is for the staff: admins and the roles of
    staff.py, each of which sees part of it."""
    if not staff.is_staff(user):
        return "Only an admin can do this."
    # When the studio asks it of admins, a staff member without two-step sign-in can't use the console until they turn it on.
    if not user["mfa_enabled"] and db.setting("admin_mfa", "0") == "1":
        return ("This studio asks admins to use two-step sign-in. Turn it on in the studio's Settings, "
                "then sign in to the admin console again.")
    return None


async def admin_user(request: Request):
    """An admin signed in to the admin console, whose requests see every user's rows: the console is about all of
    them. A sign-in to the studio is not enough."""
    db = request.app.state.db
    user = user_for_token(db, request.cookies.get(CONSOLE_COOKIE), console=True)
    if user is None:
        raise HTTPException(401, "Please sign in to the admin console.")
    problem = admin_problem(db, user)
    if problem:
        raise HTTPException(403, problem)
    if "/api/admin/" in request.url.path and not staff.may(user["role"], request.url.path, request.method):
        raise HTTPException(403, "Your role ({}) can't do this. Ask an admin.".format(staff.LABELS[user["role"]]))
    act_for_everyone()
    return user


def limited(name, limit, seconds, by="user"):
    """A dependency that refuses a request over `limit` in `seconds`, counted per signed-in user (`by="user"`) or
    per visitor address (`by="address"`, for the routes used before signing in)."""
    async def check(request: Request):
        who = client_address(request) if by == "address" else (await current_user(request))["id"]
        key = "{}|{}".format(name, who)
        limits = request.app.state.limits
        if not limits.allow(key, limit, seconds):
            raise HTTPException(429, "Too many requests. Wait a little and try again.",
                                headers={"Retry-After": str(limits.retry_after(key, seconds))})
    return Depends(check)
