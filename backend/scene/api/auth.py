"""Sign up, sign in (with an optional second step), sign out, password and two-step sign-in settings."""

import asyncio
import json
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import audit
from ..security import (DUMMY_HASH, MAX_PASSWORD, check_totp, client_address, hash_password, is_https, needs_rehash,
                        new_recovery_codes, new_token, new_totp_secret, recovery_hash, token_hash, totp_uri, verify_password)
from .deps import COOKIE, current_user, limited, may_use_agent

router = APIRouter(prefix="/api/auth", tags=["auth"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
# Each hash takes 128 MB for a moment; a few at a time is plenty for signing in and keeps a burst from using it all.
HASHING = threading.BoundedSemaphore(4)


def _guarded(work, *args):
    with HASHING:
        return work(*args)


async def check_password(password, stored):
    """verify_password, off the event loop: a strong hash takes a noticeable moment and must not stall other requests."""
    return await asyncio.to_thread(_guarded, verify_password, password, stored)


async def new_hash(password):
    return await asyncio.to_thread(_guarded, hash_password, password)


def password_problem(password):
    if len(password) < MIN_PASSWORD:
        return "The password needs at least {} characters.".format(MIN_PASSWORD)
    if len(password) > MAX_PASSWORD:
        return "The password can have at most {} characters.".format(MAX_PASSWORD)
    return None


def signup_open(state):
    return state.db.setting("allow_signup", "1" if state.settings.allow_signup else "0") == "1"


def on_this_machine(request):
    """A request from a browser on the computer the studio runs on, not one that came in through the tunnel."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") and "cf-connecting-ip" not in request.headers


def start_session(request, response, user_id):
    state = request.app.state
    token = new_token()
    lifetime = state.settings.session_days * 86400
    state.db.run("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    state.db.run("INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?, ?, ?, ?)",
                 (token_hash(token), user_id, time.time(), time.time() + lifetime))
    # Over https the cookie is marked Secure, so the browser never sends it over plain http.
    response.set_cookie(COOKIE, token, max_age=lifetime, httponly=True, samesite="lax",
                        secure=state.settings.secure_cookies or is_https(request))


@router.get("/state")
async def auth_state(request: Request):
    """What the sign-in page needs to know before anyone is signed in."""
    state = request.app.state
    first_run = state.db.one("SELECT 1 FROM users LIMIT 1") is None
    return {"first_run": first_run, "signup_open": first_run or signup_open(state)}


@router.post("/register", dependencies=[limited("register", 10, 3600, by="address")])
async def register(body: dict, request: Request, response: Response):
    state = request.app.state
    email = str(body.get("email", "")).strip().lower()[:254]
    name = str(body.get("name", "")).strip()[:80] or email.split("@")[0]
    password = str(body.get("password", ""))
    first_run = state.db.one("SELECT 1 FROM users LIMIT 1") is None
    if not first_run and not signup_open(state):
        raise HTTPException(403, "New accounts are closed. Ask an admin for access.")
    # The first account is the admin. On an installation that is already on the internet, a stranger must not be the
    # one to make it.
    if first_run and state.settings.first_account_local and not on_this_machine(request):
        raise HTTPException(403, "The first account can only be made on the computer the studio runs on. "
                                 "Open http://localhost:{} there.".format(state.settings.port))
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if password_problem(password):
        raise HTTPException(400, password_problem(password))
    if state.db.one("SELECT 1 FROM users WHERE email = ?", (email,)):
        raise HTTPException(409, "There is already an account with this email.")
    # Every new account is given credits, so one visitor may not make account after account.
    limit = state.settings.signups_per_day
    made = state.db.one("SELECT COUNT(*) n FROM audit_log WHERE action = 'Created account' AND ip = ? AND created > ?",
                        (client_address(request), time.time() - 86400))["n"]
    if not first_run and limit and made >= limit:
        audit.record(request, None, "Refused a new account", email, "too many from this address today")
        raise HTTPException(429, "Too many new accounts were made from here today. Try again tomorrow, or ask an admin.")
    # The first account owns the installation.
    user_id = state.db.run("INSERT INTO users (email, name, password_hash, role, created) VALUES (?, ?, ?, ?, ?)",
                           (email, name, await new_hash(password), "admin" if first_run else "user", time.time()))
    state.credits.add(user_id, state.credits.signup, "welcome")
    start_session(request, response, user_id)
    user = state.db.one("SELECT id, email, name, role, credits, agent FROM users WHERE id = ?", (user_id,))
    user["agent"] = may_use_agent(user)
    audit.record(request, user, "Created account", email)
    return user


def _second_step(db, user, code):
    """Whether `code` is the user's current authenticator code or one of their unused recovery codes. A code is
    used up either way: an authenticator code by its time step, a recovery code by being struck off the list."""
    step = check_totp(user["mfa_secret"], code, user["mfa_step"])
    if step is not None:
        db.run("UPDATE users SET mfa_step = ? WHERE id = ?", (step, user["id"]))
        return True
    left = json.loads(user["mfa_recovery"] or "[]")
    hashed = recovery_hash(code)
    if code and hashed in left:
        left.remove(hashed)
        db.run("UPDATE users SET mfa_recovery = ? WHERE id = ?", (json.dumps(left), user["id"]))
        return True
    return False


@router.post("/login", dependencies=[limited("login", 20, 300, by="address")])
async def login(body: dict, request: Request, response: Response):
    state = request.app.state
    email = str(body.get("email", "")).strip().lower()[:254]
    key = "{}|{}".format(email, client_address(request))
    if state.throttle.blocked(key):
        raise HTTPException(429, "Too many wrong passwords. Wait a minute and try again.")
    user = state.db.one("SELECT * FROM users WHERE email = ?", (email,))
    password = str(body.get("password", ""))
    # An email with no account is checked against a made-up hash, so it takes as long as a wrong password.
    right = await check_password(password, user["password_hash"] if user else DUMMY_HASH)
    if user is None or not right:
        state.throttle.fail(key)
        audit.record(request, None, "Failed sign-in", email)
        raise HTTPException(401, "Wrong email or password.")
    state.throttle.clear(key)
    if user["disabled"]:
        raise HTTPException(403, "This account is disabled. Ask an admin for access.")
    if user["mfa_enabled"]:
        code = str(body.get("code") or "").strip()
        if not code:
            return JSONResponse({"detail": "Enter the 6-digit code from your authenticator app.", "mfa_required": True}, status_code=401)
        # Five wrong codes lock the account's second step for a minute, from wherever they come.
        second = "mfa|{}".format(user["id"])
        if state.throttle.blocked(second):
            raise HTTPException(429, "Too many wrong codes. Wait a minute and try again.")
        if not _second_step(state.db, user, code):
            state.throttle.fail(second)
            audit.record(request, None, "Failed sign-in", email, "wrong code")
            return JSONResponse({"detail": "That code is not right. Try the newest one.", "mfa_required": True}, status_code=401)
        state.throttle.clear(second)
    if needs_rehash(user["password_hash"]):   # hashed with the older, weaker settings
        state.db.run("UPDATE users SET password_hash = ? WHERE id = ?", (await new_hash(password), user["id"]))
    start_session(request, response, user["id"])
    audit.record(request, user, "Signed in", email)
    return {**{k: user[k] for k in ("id", "email", "name", "role", "credits")}, "agent": may_use_agent(user)}


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


async def _confirm_password(request, user, password):
    """Check the signed-in user's password before a change to how they sign in. Wrong ones count like sign-ins."""
    state = request.app.state
    key = "confirm|{}".format(user["id"])
    if state.throttle.blocked(key):
        raise HTTPException(429, "Too many wrong passwords. Wait a minute and try again.")
    stored = state.db.one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))["password_hash"]
    if not await check_password(str(password or ""), stored):
        state.throttle.fail(key)
        raise HTTPException(400, "The current password is wrong.")
    state.throttle.clear(key)


def _sign_out_others(request, user):
    request.app.state.db.run("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                             (user["id"], token_hash(request.cookies.get(COOKIE, ""))))


@router.put("/password", dependencies=[limited("password", 10, 600)])
async def change_password(body: dict, request: Request, user: dict = Depends(current_user)):
    await _confirm_password(request, user, body.get("current"))
    new = str(body.get("new", ""))
    if password_problem(new):
        raise HTTPException(400, password_problem(new))
    request.app.state.db.run("UPDATE users SET password_hash = ? WHERE id = ?", (await new_hash(new), user["id"]))
    _sign_out_others(request, user)
    audit.record(request, user, "Changed password", user["email"])
    return {"ok": True}


# ---------------------------------------------------------------- two-step sign-in

def _mfa(db, user):
    return db.one("SELECT mfa_secret, mfa_enabled, mfa_step, mfa_recovery FROM users WHERE id = ?", (user["id"],))


@router.get("/mfa")
async def mfa_status(request: Request, user: dict = Depends(current_user)):
    row = _mfa(request.app.state.db, user)
    return {"enabled": bool(row["mfa_enabled"]), "recovery_left": len(json.loads(row["mfa_recovery"] or "[]"))}


@router.post("/mfa/setup", dependencies=[limited("mfa", 10, 300)])
async def mfa_setup(body: dict, request: Request, user: dict = Depends(current_user)):
    """Start turning two-step sign-in on: a new secret for the authenticator app. It is not used until a code from
    the app confirms it was added (POST /api/auth/mfa/enable)."""
    db = request.app.state.db
    if _mfa(db, user)["mfa_enabled"]:
        raise HTTPException(400, "Two-step sign-in is already on.")
    await _confirm_password(request, user, body.get("password"))
    secret = new_totp_secret()
    db.run("UPDATE users SET mfa_secret = ?, mfa_step = 0 WHERE id = ?", (secret, user["id"]))
    return {"secret": secret, "uri": totp_uri(secret, user["email"])}


@router.post("/mfa/enable", dependencies=[limited("mfa", 10, 300)])
async def mfa_enable(body: dict, request: Request, user: dict = Depends(current_user)):
    db = request.app.state.db
    row = _mfa(db, user)
    if row["mfa_enabled"]:
        raise HTTPException(400, "Two-step sign-in is already on.")
    if not row["mfa_secret"]:
        raise HTTPException(400, "Start again: set up the authenticator app first.")
    step = check_totp(row["mfa_secret"], body.get("code"))
    if step is None:
        raise HTTPException(400, "That code is not right. Check the app shows Scene.ai and try the newest code.")
    codes = new_recovery_codes()
    db.run("UPDATE users SET mfa_enabled = 1, mfa_step = ?, mfa_recovery = ? WHERE id = ?",
           (step, json.dumps([recovery_hash(c) for c in codes]), user["id"]))
    _sign_out_others(request, user)
    audit.record(request, user, "Turned on two-step sign-in", user["email"])
    return {"recovery_codes": codes}


@router.post("/mfa/disable", dependencies=[limited("mfa", 10, 300)])
async def mfa_disable(body: dict, request: Request, user: dict = Depends(current_user)):
    db = request.app.state.db
    row = _mfa(db, user)
    if not row["mfa_enabled"]:
        return {"ok": True}
    await _confirm_password(request, user, body.get("password"))
    if not _second_step(db, dict(row, id=user["id"]), str(body.get("code") or "").strip()):
        raise HTTPException(400, "That code is not right. Use the newest code from the app, or a recovery code.")
    db.run("UPDATE users SET mfa_enabled = 0, mfa_secret = '', mfa_step = 0, mfa_recovery = '[]' WHERE id = ?", (user["id"],))
    audit.record(request, user, "Turned off two-step sign-in", user["email"])
    return {"ok": True}
