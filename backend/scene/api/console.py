"""Signing in to the admin console, a site of its own beside the studio (main.create_console), and its live connection.

Only an admin may sign in, with their email and password, and their second step when it is on. A console session is
its own: signing in to the studio does not open the console, and the other way round.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from .. import audit, staff
from ..security import same_origin, token_hash
from .auth import check_sign_in, start_session
from .deps import CONSOLE_COOKIE, admin_problem, admin_user, limited, user_for_token

router = APIRouter(prefix="/api/console", tags=["console"])


def _shown(state, user):
    """The admin as the console's page gets them, with the studio's port for its link back to the studio."""
    return {**{k: user[k] for k in ("id", "email", "name", "role")}, "studio": {"port": state.settings.port},
            "role_label": staff.LABELS.get(user["role"], user["role"]), "sections": staff.sections(user["role"])}


@router.post("/login", dependencies=[limited("console-login", 20, 300, by="address")])
async def login(body: dict, request: Request, response: Response):
    user, answer = await check_sign_in(request, body, failed="Failed sign-in to the admin console")
    if answer:
        return answer
    problem = admin_problem(request.app.state.db, user)
    if problem:
        audit.record(request, user, "Refused the admin console", user["email"], problem)
        raise HTTPException(403, "This account is not an admin." if not staff.is_staff(user) else problem)
    start_session(request, response, user["id"], console=True)
    audit.record(request, user, "Signed in to the admin console", user["email"])
    return _shown(request.app.state, user)


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(CONSOLE_COOKIE)
    if token:
        request.app.state.db.run("DELETE FROM sessions WHERE token_hash = ? AND console = 1", (token_hash(token),))
    response.delete_cookie(CONSOLE_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(request: Request, user: dict = Depends(admin_user)):
    return _shown(request.app.state, user)


@router.websocket("/events")
async def events(ws: WebSocket):
    """The number of people with the studio open, sent at once and again whenever it changes; the number of open
    alerts, likewise; and a word whenever a job changes, for the pages that follow the queue."""
    state = ws.app.state
    user = user_for_token(state.db, ws.cookies.get(CONSOLE_COOKIE), console=True)
    if user is None or admin_problem(state.db, user) or not same_origin(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    state.hub.watch(ws)
    try:
        await ws.send_text(json.dumps({"alerts": len(state.db.all("SELECT id FROM alerts WHERE ended IS NULL")), "jobs": state.hub.queue()}))
        while True:
            await ws.receive_text()   # the console says nothing; this only notices it leave
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.unwatch(ws)
