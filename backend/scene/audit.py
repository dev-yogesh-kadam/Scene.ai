"""The audit log: who did what, to what, when and from where."""

import time

from .security import client_address


def record(request, actor, action, target="", detail=""):
    """`actor` is the signed-in user (or None for a failed sign-in)."""
    request.app.state.db.run(
        "INSERT INTO audit_log (actor_id, actor_name, actor_email, action, target, detail, ip, created) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (actor and actor["id"], actor["name"] if actor else "", actor["email"] if actor else "", action,
         str(target)[:200], str(detail)[:500], client_address(request), time.time()))
