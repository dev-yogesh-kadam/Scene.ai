"""Who may do what in the admin console. An admin may do everything; every other staff role sees the parts of the console
its work needs, and may change less than it sees. Everyone else (role "user") can't sign in to the console at all.

The console's routes are /api/admin/<area>/...; a role may read an area (GET) or change it (anything else). The check
is made for every request (api/deps.admin_user), so a page the console hides is refused on the server too. Which fields
of a user a role may change is said here as well (api/admin.update_user).

The roles are the built-in ones below, changed or added to in the console's Roles section (the "staff_roles" setting):
an admin gives each role a name and the areas it may see and change. "admin" itself can't be changed, and only an admin
ever gets the Roles and Settings areas, so no one can give themselves more.
"""

import json
import re

# The areas of the console, as /api/admin/<area> names them, with what the Roles section calls them.
AREAS = {
    "overview": "Overview", "search": "Search", "jobs": "Jobs", "system": "System", "server": "Servers", "alerts": "Alerts",
    "users": "Users", "credits": "Credits", "library": "Library", "projects": "Projects", "assets": "Project files",
    "moderation": "Moderation", "pricing": "Pricing", "economics": "Economics", "export": "CSV exports",
    "workflows": "Workflows", "agent": "Agent", "skills": "Skills",
    "audit": "Audit log", "backups": "Backups", "storage": "Storage", "announcement": "Announcement",
}
ADMIN_ONLY = {"roles", "settings", "maintenance", "endpoints"}   # never given to another role

BASE = {"overview", "search", "projects", "assets"}
BUILT_IN = {
    "support": {"label": "Support", "about": "Helps people: sees users, jobs, the library, projects, the system and the audit log; gives "
                "credits, runs jobs again, resets passwords and two-step sign-in, signs people out.",
                "read": BASE | {"users", "jobs", "library", "credits", "audit", "system", "backups", "storage", "workflows", "agent",
                                "announcement", "alerts", "export"},
                "write": {"users", "jobs", "server"},
                "fields": {"add_credits", "note", "password", "mfa_off", "disabled", "daily_cap", "sign-out"}},
    "finance": {"label": "Finance", "about": "Money: credits, pricing and economics, and the CSV exports; may give credits and set spending limits.",
                "read": BASE | {"users", "jobs", "credits", "pricing", "economics", "export"},
                "write": {"users", "credits", "pricing"},
                "fields": {"add_credits", "note", "daily_cap"}},
    "moderator": {"label": "Moderator", "about": "What is made: reviews the library and the moderation queue, removes items, disables accounts.",
                  "read": BASE | {"users", "jobs", "library", "moderation"},
                  "write": {"users", "library", "moderation"},
                  "fields": {"disabled", "sign-out"}},
}
# The fields of a user a role that may change Users may change, by what else it may change.
FIELDS_FOR = {"users": {"note", "disabled", "sign-out"}, "credits": {"add_credits", "daily_cap"}}

# The console's sections and the area each one reads.
SECTIONS = {"overview": "overview", "jobs": "jobs", "system": "system", "users": "users", "credits": "credits",
            "library": "library", "projects": "projects", "moderation": "moderation", "pricing": "pricing",
            "economics": "economics", "workflows": "workflows", "agent": "agent", "skills": "skills",
            "audit": "audit", "roles": "roles", "endpoints": "endpoints", "settings": "settings"}

_roles = {}   # role id -> {"label", "about", "read", "write", "fields", "built_in"}, without "admin"


def configure(db):
    """Read the roles as the console last saved them over the built-in ones. Done when the app starts and after a save."""
    try:
        saved = json.loads(db.setting("staff_roles", "") or "{}")
    except ValueError:
        saved = {}
    roles = {rid: dict(r, built_in=True) for rid, r in BUILT_IN.items()}
    for rid, r in saved.items():
        if rid == "admin" or not isinstance(r, dict):
            continue
        if r.get("deleted"):
            roles.pop(rid, None)
            continue
        base = roles.get(rid, {"label": rid.title(), "about": "", "read": set(), "write": set(), "fields": set(), "built_in": False})
        read = {a for a in r.get("read", base["read"]) if a in AREAS}
        write = {a for a in r.get("write", base["write"]) if a in AREAS} & read
        fields = base["fields"] if base["built_in"] and "write" not in r else set().union(*(FIELDS_FOR.get(a, set()) for a in write))
        roles[rid] = {"label": str(r.get("label") or base["label"])[:40], "about": str(r.get("about", base["about"]))[:300],
                      "read": read, "write": write, "fields": fields, "built_in": base["built_in"]}
    _roles.clear()
    _roles.update(roles)


def _built_in_only():
    _roles.clear()
    _roles.update({rid: dict(r, built_in=True) for rid, r in BUILT_IN.items()})


_built_in_only()   # until configure() reads the saved ones


def roles():
    """Every staff role, "admin" first. "user" is everyone else."""
    return ("admin", *_roles)


def label(role):
    return "Admin" if role == "admin" else "User" if role == "user" else _roles.get(role, {}).get("label", role)


def about(role):
    return "Everything, including settings, roles, pricing and maintenance." if role == "admin" else _roles.get(role, {}).get("about", "")


def described():
    """The roles as the Roles section shows them."""
    return [{"id": "admin", "label": "Admin", "about": about("admin"), "read": sorted(AREAS), "write": sorted(AREAS), "built_in": True, "fixed": True}] + [
        {"id": rid, "label": r["label"], "about": r["about"], "read": sorted(r["read"]), "write": sorted(r["write"]),
         "built_in": r["built_in"], "fixed": False} for rid, r in _roles.items()]


def save(db, role_id, body):
    """Make or change a role: {"label", "about", "read": [area], "write": [area]}. Returns its id."""
    role_id = re.sub(r"[^a-z0-9_]+", "_", str(role_id or body.get("label") or "").strip().lower()).strip("_")[:24]
    if not role_id or role_id in ("admin", "user"):
        raise ValueError("Give the role a name other than Admin or User.")
    label_ = " ".join(str(body.get("label") or "").split())[:40]
    if not label_:
        raise ValueError("Give the role a name.")
    read = sorted({a for a in body.get("read") or [] if a in AREAS})
    write = sorted({a for a in body.get("write") or [] if a in AREAS} & set(read))
    saved = json.loads(db.setting("staff_roles", "") or "{}")
    saved[role_id] = {"label": label_, "about": str(body.get("about") or "")[:300], "read": read, "write": write}
    db.set_setting("staff_roles", json.dumps(saved))
    configure(db)
    return role_id


def delete(db, role_id):
    saved = json.loads(db.setting("staff_roles", "") or "{}")
    saved[role_id] = {"deleted": True}
    db.set_setting("staff_roles", json.dumps(saved))
    configure(db)


def is_staff(user):
    return bool(user) and user.get("role") in roles()


def area_of(path):
    """/api/admin/users/3 -> "users"; /api/admin/export/users.csv -> "export"."""
    rest = path.split("/api/admin/", 1)[1] if "/api/admin/" in path else ""
    return rest.split("/", 1)[0]


def may(role, path, method):
    """Whether `role` may make this request of the console."""
    if role == "admin":
        return True
    found = _roles.get(role)
    if found is None:
        return False
    area = area_of(path)
    if area in ADMIN_ONLY:
        return False
    if method in ("GET", "HEAD"):
        return area in found["read"]
    if area == "users" and path.rstrip("/").endswith("/sign-out"):
        return "sign-out" in found["fields"]
    return area in found["write"]


def sections(role):
    """The console's sections a role sees, in the console's order."""
    if role == "admin":
        return list(SECTIONS)
    found = _roles.get(role, {"read": set()})
    return [s for s, area in SECTIONS.items() if area in found["read"]]


def user_fields_problem(role, body):
    """Why `role` may not make this change to a user, or None."""
    if role == "admin":
        return None
    refused = [k for k in body if k not in _roles.get(role, {}).get("fields", set())]
    if refused:
        return "As {} you can't change that ({}). Ask an admin.".format(label(role).lower(), ", ".join(sorted(refused)))
    return None
