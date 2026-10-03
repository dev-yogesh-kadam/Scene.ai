"""Shared request helpers: who is signed in."""

import time

from fastapi import Depends, HTTPException, Request

from ..security import token_hash

COOKIE = "scene_session"


def user_for_token(db, token):
    if not token:
        return None
    return db.one(
        "SELECT u.id, u.email, u.name, u.role, u.credits, u.created FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires > ? AND u.disabled = 0", (token_hash(token), time.time()))


def current_user(request: Request):
    user = user_for_token(request.app.state.db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def admin_user(user: dict = Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do this.")
    return user
