"""Shared request helpers: who is signed in, and how often they may ask."""

import time

from fastapi import Depends, HTTPException, Request

from ..db import act_for, act_for_everyone
from ..security import client_address, token_hash

COOKIE = "scene_session"


def user_for_token(db, token):
    if not token:
        return None
    user = db.one(
        "SELECT u.id, u.email, u.name, u.role, u.credits, u.created, u.agent FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires > ? AND u.disabled = 0", (token_hash(token), time.time()))
    if user:
        user["agent"] = may_use_agent(user)
    return user


def may_use_agent(user):
    """The agent is open to admins and to the users an admin has given it to. For everyone else it is "coming soon"."""
    return user["role"] == "admin" or bool(user.get("agent"))


async def current_user(request: Request):
    """The signed-in user. From here on the request's statements see only that user's rows (row-level security).
    Async on purpose: a dependency run in a thread could not pass that on to the request."""
    user = user_for_token(request.app.state.db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Please sign in.")
    act_for(user["id"])
    return user


async def agent_user(user: dict = Depends(current_user)):
    if not user["agent"]:
        raise HTTPException(403, "The agent is coming soon. An admin can give your account access to it.")
    return user


async def admin_user(user: dict = Depends(current_user)):
    """An admin, whose requests see every user's rows: the admin console is about all of them."""
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do this.")
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
