"""Who may do what in the admin console. An admin may do everything; the other staff roles each see the parts their work
needs, and may change less than they see. Everyone else (role "user") can't sign in to the console at all.

The console's routes are /api/admin/<area>/...; a role may read an area (GET) or change it (anything else). The check
is made for every request (api/deps.admin_user), so a page the console hides is refused on the server too. Which fields
of a user a role may change is said here as well (api/admin.update_user).
"""

ROLES = ("admin", "support", "finance", "moderator")   # the staff; "user" is everyone else
LABELS = {"admin": "Admin", "support": "Support", "finance": "Finance", "moderator": "Moderator", "user": "User"}
ABOUT = {
    "admin": "Everything, including settings, roles, pricing and maintenance.",
    "support": "Helps people: sees users, jobs, the library, projects, the system and the audit log; gives credits, runs jobs again, "
               "resets passwords and two-step sign-in, signs people out.",
    "finance": "Money: credits, pricing and economics, and the CSV exports; may give credits and set spending limits.",
    "moderator": "What is made: reviews the library and the moderation queue, removes items, disables accounts.",
}

BASE = {"overview", "search", "projects", "assets"}
READ = {
    "support": BASE | {"users", "jobs", "library", "credits", "audit", "system", "backups", "storage", "workflows", "agent",
                       "announcement", "alerts", "export"},
    "finance": BASE | {"users", "jobs", "credits", "pricing", "economics", "export"},
    "moderator": BASE | {"users", "jobs", "library", "moderation"},
}
WRITE = {
    "support": {"users", "jobs", "server"},
    "finance": {"users", "credits", "pricing"},
    "moderator": {"users", "library", "moderation"},
}
# The fields of a user (PUT /api/admin/users/<id>) each role may change; "sign-out" is POST .../sign-out.
USER_FIELDS = {
    "support": {"add_credits", "note", "password", "mfa_off", "disabled", "daily_cap", "sign-out"},
    "finance": {"add_credits", "note", "daily_cap"},
    "moderator": {"disabled", "sign-out"},
}
# The console's sections and the area each one reads.
SECTIONS = {"overview": "overview", "jobs": "jobs", "system": "system", "users": "users", "credits": "credits",
            "library": "library", "projects": "projects", "moderation": "moderation", "pricing": "pricing",
            "economics": "economics", "workflows": "workflows", "agent": "agent", "skills": "skills", "audit": "audit",
            "settings": "settings"}


def is_staff(user):
    return bool(user) and user.get("role") in ROLES


def area_of(path):
    """/api/admin/users/3 -> "users"; /api/admin/export/users.csv -> "export"."""
    rest = path.split("/api/admin/", 1)[1] if "/api/admin/" in path else ""
    return rest.split("/", 1)[0]


def may(role, path, method):
    """Whether `role` may make this request of the console."""
    if role == "admin":
        return True
    if role not in ROLES:
        return False
    area = area_of(path)
    if method in ("GET", "HEAD"):
        return area in READ.get(role, set())
    if area == "users" and path.rstrip("/").endswith("/sign-out"):
        return "sign-out" in USER_FIELDS.get(role, set())
    return area in WRITE.get(role, set())


def sections(role):
    """The console's sections a role sees, in the console's order."""
    return [s for s, area in SECTIONS.items() if role == "admin" or area in READ.get(role, set())]


def user_fields_problem(role, body):
    """Why `role` may not make this change to a user, or None."""
    if role == "admin":
        return None
    refused = [k for k in body if k not in USER_FIELDS.get(role, set())]
    if refused:
        return "As {} you can't change that ({}). Ask an admin.".format(LABELS.get(role, role).lower(), ", ".join(sorted(refused)))
    return None
