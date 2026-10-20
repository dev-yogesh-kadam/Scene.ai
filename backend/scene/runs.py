"""The state of a long run: what a skill such as Pocket Motion keeps between its steps, as a tree of paths.

A run belongs to one user and one agent conversation (its id is the conversation's). Each path is a leaf holding one
JSON value ("/motion/chunks/c3" = {...}) or a folder of other paths; a path is never both. Every step of a skill reads its
inputs from here and writes its output here, so nothing depends on what the model remembers of the chat, and a run
can be picked up again after the conversation was compacted or the app restarted.
"""

import json
import re
import time

PATH = re.compile(r"^(/[a-z0-9][a-z0-9_.-]{0,63}){1,12}$")   # lower-case segments: /motion/assets/maya/ref_1500
RUN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MAX_VALUE = 64_000      # characters of one value, as JSON
MAX_PATHS = 20_000      # leaves in one run
PAGE = 100              # leaves listed at a time
MANY = 2000             # leaves written by one write_many


BUDGET = "/budget"      # the most credits the run may spend: set by the user only, never by the agent's tools


class RunError(ValueError):
    pass


def clean_run(run):
    run = str(run or "").strip().lower()
    if not RUN.match(run):
        raise RunError("A run is named with lower-case letters, digits and dashes.")
    return run


def clean_path(path):
    path = str(path or "").strip().rstrip("/").lower()
    if not PATH.match(path) or "/../" in path + "/" or "/./" in path + "/":
        raise RunError("A path is like /motion/chunks/c3: lower-case segments of letters, digits, _ . and -.")
    return path


def _under(path):
    """SQL for the paths below `path`, without LIKE (whose _ would be a wildcard) or a collation-dependent range."""
    return "substr(path, 1, ?) = ?", (len(path) + 1, path + "/")


def write(db, user_id, run, path, value, writer="", budget=False):
    """Put a value at a leaf, replacing what was there. Refused when the path is a folder, sits under a leaf, the value
    is too large, or the run is full; and the budget's path unless `budget` (set_budget, for the user)."""
    run, path = clean_run(run), clean_path(path)
    if (path == BUDGET or path.startswith(BUDGET + "/")) and not budget:
        raise RunError("{} is the run's budget: only the user sets it.".format(BUDGET))
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_VALUE:
        raise RunError("{} is too large to keep ({:,} characters; at most {:,}). Split it into several paths.".format(path, len(text), MAX_VALUE))
    where, params = _under(path)
    if db.one("SELECT 1 FROM run_state WHERE user_id = ? AND run = ? AND " + where + " LIMIT 1", (user_id, run, *params)):
        raise RunError("{} is a folder: write to a path inside it.".format(path))
    parents = ["/".join(path.split("/")[:k]) for k in range(2, path.count("/") + 1)]
    if parents and db.one("SELECT path FROM run_state WHERE user_id = ? AND run = ? AND path IN ({})".format(", ".join("?" * len(parents))),
                          (user_id, run, *parents)):
        raise RunError("A path above {} holds a value, so it cannot be a folder.".format(path))
    exists = db.one("SELECT 1 FROM run_state WHERE user_id = ? AND run = ? AND path = ?", (user_id, run, path))
    if not exists and (db.one("SELECT COUNT(*) AS n FROM run_state WHERE user_id = ? AND run = ?", (user_id, run))["n"] >= MAX_PATHS):
        raise RunError("This run holds {:,} paths, the most there may be.".format(MAX_PATHS))
    db.run("INSERT INTO run_state (user_id, run, path, value, writer, updated) VALUES (?, ?, ?, ?, ?, ?) "
           "ON CONFLICT(user_id, run, path) DO UPDATE SET value = excluded.value, writer = excluded.writer, updated = excluded.updated",
           (user_id, run, path, text, str(writer or "")[:40], time.time()))
    return {"path": path, "characters": len(text)}


def write_many(db, user_id, run, folder, values, writer="", replace=False):
    """Put many leaves under one folder at once: {name: value} -> folder/name. replace: the folder's old leaves go
    first (a step done again). Every name and value is checked before anything is written."""
    run, folder = clean_run(run), clean_path(folder)
    if not isinstance(values, dict) or not 1 <= len(values) <= MANY:
        raise RunError("Give 1 to {:,} leaves as an object of name: value.".format(MANY))
    paths = {clean_path("{}/{}".format(folder, name)): value for name, value in values.items()}
    for path, value in paths.items():
        if path.count("/") != folder.count("/") + 1:
            raise RunError("{} is not one level below {}.".format(path, folder))
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > MAX_VALUE:
            raise RunError("{} is too large to keep.".format(path))
    if replace:
        delete(db, user_id, run, folder)
    for path, value in paths.items():
        write(db, user_id, run, path, value, writer)
    return {"path": folder, "written": len(paths)}


def append(db, user_id, run, path, line, writer=""):
    """Add one line to the list at a leaf (a log), making it if it is not there."""
    found = read(db, user_id, run, path)
    lines = found["value"] if found.get("value") is not None and isinstance(found["value"], list) else []
    return write(db, user_id, run, path, [*lines, line], writer)


def read(db, user_id, run, path, offset=0, limit=PAGE):
    """A leaf: {"path", "value", "writer", "updated"}. A folder: {"path", "folder": True, "total", "offset", "leaves":
    [{"path", "value"}]} — every leaf under it, in path order, one page at a time. Nothing there: {"path", "missing": True}."""
    run, path = clean_run(run), clean_path(path)
    row = db.one("SELECT value, writer, updated FROM run_state WHERE user_id = ? AND run = ? AND path = ?", (user_id, run, path))
    if row:
        return {"path": path, "value": json.loads(row["value"]), "writer": row["writer"], "updated": row["updated"]}
    where, params = _under(path)
    total = db.one("SELECT COUNT(*) AS n FROM run_state WHERE user_id = ? AND run = ? AND " + where, (user_id, run, *params))["n"]
    if not total:
        return {"path": path, "missing": True}
    offset, limit = max(0, int(offset or 0)), max(1, min(int(limit or PAGE), PAGE))
    rows = db.all("SELECT path, value FROM run_state WHERE user_id = ? AND run = ? AND " + where + " ORDER BY path LIMIT ? OFFSET ?",
                  (user_id, run, *params, limit, offset))
    return {"path": path, "folder": True, "total": total, "offset": offset,
            "leaves": [{"path": r["path"], "value": json.loads(r["value"])} for r in rows]}


def children(db, user_id, run, path):
    """The names one level below a folder: /motion/clips -> ["c1", "c2", ...], in order."""
    run, path = clean_run(run), clean_path(path)
    where, params = _under(path)
    names = {r["path"][len(path) + 1:].split("/")[0] for r in
             db.all("SELECT path FROM run_state WHERE user_id = ? AND run = ? AND " + where, (user_id, run, *params))}
    return sorted(names, key=_natural)


def _natural(name):
    """c2 before c10."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def coverage(db, user_id, run, path, against):
    """Whether every name under `against` (the chunks) has one under `path` (their clips): {"ok", "missing", "extra"}."""
    have, need = set(children(db, user_id, run, path)), children(db, user_id, run, against)
    missing = [n for n in need if n not in have]
    return {"ok": not missing and bool(need), "missing": missing, "extra": sorted(have - set(need), key=_natural), "count": len(need)}


def delete(db, user_id, run, path, budget=False):
    """Remove a leaf, or a folder and everything in it (never the budget, unless `budget`). Returns how many went."""
    run, path = clean_run(run), clean_path(path)
    if (path == BUDGET or path.startswith(BUDGET + "/")) and not budget:
        raise RunError("{} is the run's budget: only the user sets it.".format(BUDGET))
    where, params = _under(path)
    return db.change("DELETE FROM run_state WHERE user_id = ? AND run = ? AND (path = ? OR " + where + ")", (user_id, run, path, *params))


def listing(db, user_id):
    """The user's runs, newest first: {"run", "paths", "updated", "status"} (status: the leaf "/<x>/status", if any)."""
    rows = db.all("SELECT run, COUNT(*) AS paths, MAX(updated) AS updated FROM run_state WHERE user_id = ? GROUP BY run ORDER BY MAX(updated) DESC",
                  (user_id,))
    for row in rows:
        status = db.one("SELECT value FROM run_state WHERE user_id = ? AND run = ? AND path LIKE '%/status' ORDER BY updated DESC LIMIT 1",
                        (user_id, row["run"]))
        row["status"] = json.loads(status["value"]) if status else None
    return rows


def spent(db, user_id, run):
    """Credits the run's jobs have taken, less what failed jobs gave back."""
    row = db.one("SELECT COALESCE(SUM(cost - credits_refunded), 0) AS n FROM jobs WHERE user_id = ? AND run = ?", (user_id, clean_run(run)))
    return int(row["n"] or 0)


def budget(db, user_id, run):
    """{"credits": the most it may spend, or None for no limit, "spent"}."""
    found = read(db, user_id, run, BUDGET)
    limit = found.get("value") if isinstance(found.get("value"), int) else None
    return {"credits": limit, "spent": spent(db, user_id, run)}


def set_budget(db, user_id, run, credits):
    """Set the run's budget (a whole number of credits), or take it away (None)."""
    if credits is None:
        delete(db, user_id, run, BUDGET, budget=True)
    elif isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
        raise RunError("A budget is a whole number of credits.")
    else:
        write(db, user_id, run, BUDGET, credits, "user", budget=True)
    return budget(db, user_id, run)


def budget_problem(db, user_id, run, credits):
    """Why a job of `credits` may not start in this run (its budget would be passed), or None."""
    if not run:
        return None
    found = budget(db, user_id, run)
    if found["credits"] is not None and found["spent"] + credits > found["credits"]:
        return "This run's budget is {:,} credits and it has spent {:,}: this step needs {:,} more. Raise the budget to go on.".format(
            found["credits"], found["spent"], credits)
    return None


STATE_REF = re.compile(r"^\$state:(/[a-z0-9_./-]+?)(/\*)?$")


def leaves(db, user_id, run, folder):
    """Every leaf one level below a folder, in natural order (2 before 10): [(name, value)]."""
    run, folder = clean_run(run), clean_path(folder)
    where, params = _under(folder)
    rows = db.all("SELECT path, value FROM run_state WHERE user_id = ? AND run = ? AND " + where, (user_id, run, *params))
    found = [(r["path"][len(folder) + 1:], json.loads(r["value"])) for r in rows if "/" not in r["path"][len(folder) + 1:]]
    return sorted(found, key=lambda pair: _natural(pair[0]))


def resolve(db, user_id, run, reference):
    """What a "$state:/motion/assets/maya/ref_1500" reference stands for: the value at that leaf. A value that is
    {"item": id} or a bare library id gives the id. "$state:/folder/*" stands for every leaf of the folder, as a list:
    each value with "n" (its name, a number when it is one) added. Raises RunError, naming the path, when nothing is
    written there: a step may only point at state that already exists."""
    match = STATE_REF.match(str(reference or ""))
    if not match:
        raise RunError("A state reference is written $state:/path/to/leaf, or $state:/folder/* for all of a folder.")
    if match.group(2):
        found = leaves(db, user_id, run, match.group(1))
        if not found:
            raise RunError("state_reference_unresolved: nothing is written under {} yet.".format(match.group(1)))
        name = lambda n: int(n) if n.isdigit() else n
        return [dict(value, n=name(n)) if isinstance(value, dict) else {"n": name(n), "value": value} for n, value in found]
    found = read(db, user_id, run, match.group(1))
    if found.get("missing") or found.get("folder"):
        raise RunError("state_reference_unresolved: nothing is written at {} yet.".format(match.group(1)))
    value = found["value"]
    return value.get("item", value) if isinstance(value, dict) else value
