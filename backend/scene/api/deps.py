"""Shared request helpers: who is signed in."""

import time

from fastapi import Depends, HTTPException, Request

from ..security import token_hash

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


def current_user(request: Request):
    user = user_for_token(request.app.state.db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def agent_user(user: dict = Depends(current_user)):
    if not user["agent"]:
        raise HTTPException(403, "The agent is coming soon. An admin can give your account access to it.")
    return user


def admin_user(user: dict = Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do this.")
    return user
