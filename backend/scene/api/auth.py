"""Sign up, sign in, sign out."""

import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit
from ..security import hash_password, new_token, token_hash, verify_password
from .deps import COOKIE, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


def signup_open(state):
    return state.db.setting("allow_signup", "1" if state.settings.allow_signup else "0") == "1"


def start_session(request, response, user_id):
    state = request.app.state
    token = new_token()
    lifetime = state.settings.session_days * 86400
    state.db.run("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    state.db.run("INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?, ?, ?, ?)",
                 (token_hash(token), user_id, time.time(), time.time() + lifetime))
    response.set_cookie(COOKIE, token, max_age=lifetime, httponly=True, samesite="lax",
                        secure=state.settings.secure_cookies)


@router.get("/state")
async def auth_state(request: Request):
    """What the sign-in page needs to know before anyone is signed in."""
    state = request.app.state
    first_run = state.db.one("SELECT 1 FROM users LIMIT 1") is None
    return {"first_run": first_run, "signup_open": first_run or signup_open(state)}


@router.post("/register")
async def register(body: dict, request: Request, response: Response):
    state = request.app.state
    email = str(body.get("email", "")).strip().lower()
    name = str(body.get("name", "")).strip()[:80] or email.split("@")[0]
    password = str(body.get("password", ""))
    first_run = state.db.one("SELECT 1 FROM users LIMIT 1") is None
    if not first_run and not signup_open(state):
        raise HTTPException(403, "New accounts are closed. Ask an admin for access.")
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, "The password needs at least {} characters.".format(MIN_PASSWORD))
    if state.db.one("SELECT 1 FROM users WHERE email = ?", (email,)):
        raise HTTPException(409, "There is already an account with this email.")
    # The first account owns the installation.
    user_id = state.db.run("INSERT INTO users (email, name, password_hash, role, created) VALUES (?, ?, ?, ?, ?)",
                           (email, name, hash_password(password), "admin" if first_run else "user", time.time()))
    state.credits.add(user_id, state.credits.signup, "welcome")
    start_session(request, response, user_id)
    user = state.db.one("SELECT id, email, name, role, credits FROM users WHERE id = ?", (user_id,))
    audit.record(request, user, "Created account", email)
    return user


@router.post("/login")
async def login(body: dict, request: Request, response: Response):
    state = request.app.state
    email = str(body.get("email", "")).strip().lower()
    key = "{}|{}".format(email, request.client.host if request.client else "")
    if state.throttle.blocked(key):
        raise HTTPException(429, "Too many wrong passwords. Wait a minute and try again.")
    user = state.db.one("SELECT * FROM users WHERE email = ?", (email,))
    if user is None or not verify_password(str(body.get("password", "")), user["password_hash"]):
        state.throttle.fail(key)
        audit.record(request, None, "Failed sign-in", email)
        raise HTTPException(401, "Wrong email or password.")
    state.throttle.clear(key)
    if user["disabled"]:
        raise HTTPException(403, "This account is disabled. Ask an admin for access.")
    start_session(request, response, user["id"])
    audit.record(request, user, "Signed in", email)
    return {k: user[k] for k in ("id", "email", "name", "role", "credits")}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        request.app.state.db.run("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.put("/password")
async def change_password(body: dict, request: Request, user: dict = Depends(current_user)):
    db = request.app.state.db
    stored = db.one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))["password_hash"]
    if not verify_password(str(body.get("current", "")), stored):
        raise HTTPException(400, "The current password is wrong.")
    if len(str(body.get("new", ""))) < MIN_PASSWORD:
        raise HTTPException(400, "The password needs at least {} characters.".format(MIN_PASSWORD))
    db.run("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(str(body["new"])), user["id"]))
    # Sign out every other device.
    db.run("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
           (user["id"], token_hash(request.cookies.get(COOKIE, ""))))
    return {"ok": True}
