"""Projects shared with other people: who is in a project and what each one may do there.

A project's owner adds people by email, each with a role. A member works in the whole project: its own canvas and every
module. What a member makes stays theirs (their credits, their folder of results), filed in the project for everyone in
it to see. The canvas layout, the timeline and the NeuralCore kit of a project are the owner's, which members open and,
by their role, change.

Every route that touches a project asks `require` first. Rows of other people are then read for the project only, on
the owner's behalf (db.as_everyone); the database's own guard of each user's rows stays as it is.
"""

import time

from fastapi import HTTPException

from .db import as_everyone

# A member's role, from least to most. The owner is above them all and is not a member.
ROLES = ("viewer", "creator", "manager")
RANK = {"viewer": 1, "creator": 2, "manager": 3, "owner": 4}
LABELS = {"viewer": "Viewer", "creator": "Creator", "manager": "Manager", "owner": "Owner"}
ABOUT = {
    "viewer": "Sees the project, its canvases and what is made there, and downloads it.",
    "creator": "Also makes things there, adds modules, arranges the canvas and the timeline and edits the NeuralCore.",
    "manager": "Also adds and removes people, renames the project and its modules, and deletes modules.",
}
# What each action needs, so the routes and the studio say the same thing.
NEEDS = {"see": "viewer", "make": "creator", "manage": "manager", "own": "owner"}


def top_of(db, project_id):
    """The project a project id is in (itself, or the project of a module), or None."""
    with as_everyone():
        row = db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row and row["parent_id"]:
            return db.one("SELECT * FROM projects WHERE id = ?", (row["parent_id"],)), row
    return row, row


def role_in(db, user_id, project_id):
    """(role, the project or module asked for, its project) for this user, role None when they are not in it."""
    top, here = top_of(db, project_id)
    if top is None:
        return None, None, None
    if top["user_id"] == user_id:
        return "owner", here, top
    with as_everyone():
        member = db.one("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?", (top["id"], user_id))
    return (member["role"] if member else None), here, top


def require(db, user, project_id, need="viewer"):
    """The project or module, with "role" and "owner_id" added, when `user` may do what `need` asks there. Someone not
    in the project is told there is no such project; a member whose role is too low is told what they would need."""
    role, here, top = role_in(db, user["id"], project_id)
    if role is None:
        raise HTTPException(404, "No such project.")
    if RANK[role] < RANK[need]:
        raise HTTPException(403, "As {} in this project you can't do that. Ask its owner{}.".format(
            LABELS[role].lower(), "" if need == "owner" else " or a manager for the {} role".format(LABELS[need].lower())))
    return dict(here, role=role, owner_id=top["user_id"], top_id=top["id"])


def shared_ids(db, user_id):
    """The ids of the projects shared with this user, and of their modules."""
    with as_everyone():
        rows = db.all("SELECT p.id FROM projects p JOIN project_members m ON m.project_id = COALESCE(p.parent_id, p.id) "
                      "WHERE m.user_id = ?", (user_id,))
    return [r["id"] for r in rows]


def members(db, project_id):
    """Everyone in a project: its owner first, then its members in the order they were added."""
    with as_everyone():
        top = db.one("SELECT p.user_id, u.name, u.email FROM projects p JOIN users u ON u.id = p.user_id WHERE p.id = ?", (project_id,))
        rows = db.all("SELECT m.user_id, m.role, m.created, u.name, u.email FROM project_members m JOIN users u ON u.id = m.user_id "
                      "WHERE m.project_id = ? ORDER BY m.created", (project_id,))
    owner = [{"user_id": top["user_id"], "name": top["name"], "email": top["email"], "role": "owner"}] if top else []
    return owner + [{"user_id": r["user_id"], "name": r["name"], "email": r["email"], "role": r["role"], "added": r["created"]} for r in rows]


def add(db, project, adder, people):
    """Add [{"email", "role"}] to a project. Returns (added, problems): a problem is an email with no account here, the
    owner, or a role the adder may not give (only the owner makes managers)."""
    added, problems = [], []
    for person in people:
        email, role = str(person.get("email") or "").strip().lower(), str(person.get("role") or "creator")
        if role not in ROLES:
            problems.append({"email": email, "problem": "Pick a role: viewer, creator or manager."})
            continue
        if role == "manager" and project["role"] != "owner":
            problems.append({"email": email, "problem": "Only the project's owner can make someone a manager."})
            continue
        with as_everyone():
            found = db.one("SELECT id FROM users WHERE LOWER(email) = ?", (email,))
        if found is None:
            problems.append({"email": email, "problem": "No one has an account with this email yet. Ask them to sign up first."})
            continue
        if found["id"] == project["owner_id"]:
            problems.append({"email": email, "problem": "This is the project's owner."})
            continue
        with as_everyone():
            if db.one("SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?", (project["top_id"], found["id"])):
                db.run("UPDATE project_members SET role = ? WHERE project_id = ? AND user_id = ?", (role, project["top_id"], found["id"]))
            else:
                db.run("INSERT INTO project_members (project_id, user_id, role, added_by, created) VALUES (?, ?, ?, ?, ?)",
                       (project["top_id"], found["id"], role, adder["id"], time.time()))
        added.append({"email": email, "role": role, "user_id": found["id"]})
    return added, problems


def change(db, project, user_id, role):
    """Give a member another role, or take them out of the project (role None)."""
    with as_everyone():
        member = db.one("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?", (project["top_id"], user_id))
        if member is None:
            raise HTTPException(404, "They are not in this project.")
        if project["role"] != "owner" and "manager" in (member["role"], role):
            raise HTTPException(403, "Only the project's owner can make or change a manager.")
        if role is None:
            db.run("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project["top_id"], user_id))
        elif role in ROLES:
            db.run("UPDATE project_members SET role = ? WHERE project_id = ? AND user_id = ?", (role, project["top_id"], user_id))
        else:
            raise HTTPException(400, "Pick a role: viewer, creator or manager.")


def people_of(db, project_id):
    """The user ids of everyone in the project a project id is in, to tell them something changed there."""
    top, _ = top_of(db, project_id)
    if top is None:
        return []
    with as_everyone():
        rows = db.all("SELECT user_id FROM project_members WHERE project_id = ?", (top["id"],))
    return [top["user_id"]] + [r["user_id"] for r in rows]
