"""The audit log: who did what, to what, when and from where.

Each entry is sealed: its `seal` is a hash of its own fields and the seal of the entry before it, so an entry changed
or taken out of the middle breaks every seal after it. The newest seal and the count are also kept in the settings
(`audit_head`), so entries cut from the end show too. `verify` checks the whole chain. It is not proof against someone
who rewrites the whole database, but nothing can be quietly edited or removed.
"""

import hashlib
import json
import time

from .security import client_address

FIELDS = ("actor_id", "actor_name", "actor_email", "action", "target", "detail", "ip", "created")


def _seal(before, row):
    text = json.dumps([before] + [row[k] for k in FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(request, actor, action, target="", detail=""):
    """`actor` is the signed-in user (or None for a failed sign-in)."""
    db = request.app.state.db
    row = {"actor_id": actor and actor["id"], "actor_name": actor["name"] if actor else "", "actor_email": actor["email"] if actor else "",
           "action": action, "target": str(target)[:200], "detail": str(detail)[:500], "ip": client_address(request),
           "created": time.time()}
    last = db.one("SELECT seal FROM audit_log ORDER BY id DESC LIMIT 1")
    seal = _seal(last["seal"] if last else "", row)
    db.run("INSERT INTO audit_log ({}, seal) VALUES ({}, ?)".format(", ".join(FIELDS), ", ".join("?" * len(FIELDS))),
           (*row.values(), seal))
    head = json.loads(db.setting("audit_head", "") or "{}")
    db.set_setting("audit_head", json.dumps({"seal": seal, "count": int(head.get("count") or 0) + 1}))


def verify(db):
    """Check every seal. Returns {ok, entries, sealed, since, broken: the first entry whose seal does not hold, or None,
    missing: entries cut from the end}."""
    rows = db.all("SELECT id, seal, " + ", ".join(FIELDS) + " FROM audit_log ORDER BY id")
    before, sealed, since, broken = "", 0, None, None
    for row in rows:
        if not row["seal"]:   # written before entries were sealed
            continue
        if since is None:
            since, before = row["created"], ""   # the chain starts at the first sealed entry
        if _seal(before, row) != row["seal"] and broken is None:
            broken = {"id": row["id"], "action": row["action"], "created": row["created"]}
        before = row["seal"]
        sealed += 1
    head = json.loads(db.setting("audit_head", "") or "{}")
    missing = max(0, int(head.get("count") or 0) - sealed)
    if head.get("seal") and head["seal"] != before and not missing and broken is None:
        broken = {"id": None, "action": "the newest entries", "created": None}
    return {"ok": broken is None and not missing, "entries": len(rows), "sealed": sealed, "since": since, "broken": broken, "missing": missing}
