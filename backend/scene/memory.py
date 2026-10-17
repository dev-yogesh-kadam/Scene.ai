"""Shared memory: everything the studio keeps for a project, which the user browses on the canvas and the agent plans with.

The Shared memory tab shows two parts:
- assets: what the user saved for reuse on purpose (the Assets page), in every project;
- uploads: every reference file dropped into a job, kept as an asset of the project it was used in.
The agent also knows what was made in the project (the library, on the canvas).

What a picture shows is written once by the agent's model looking at it, and kept with it (assets.about,
generations.about), so the agent knows what is in a picture and not only its name. The agent gets all of it as its
"asset book": the saved assets and uploads in full, the latest items in full, older items by name.
"""

import asyncio
import base64
import hashlib
import json
import re
import shutil
import time

from . import cast, media, review
from .references import safe_name

BOOK_ASSETS = 40        # saved assets in the agent's book
BOOK_UPLOADS = 20       # uploads of the project in the book
BOOK_FULL_ITEMS = 12    # the project's latest items, in full
BOOK_ITEMS = 60         # the project's items in the book, the older ones by name only
PANEL_ITEMS = 200       # what the Shared memory tab lists of each part
DESCRIBE_AT_ONCE = 4    # pictures described at once, while the user waits
DESCRIBE_SECONDS = 25   # how long a plan waits for descriptions before it goes on without the rest

# What each tag of an asset is called in the book.
TYPES = {"character": "character", "outfit": "outfit", "background": "location", "prop": "prop", "voice": "voice",
         "style": "style", "other": "other"}
# The tag an uploaded file gets from the reference slot it was dropped into.
ROLE_TAGS = {"character_1": "character", "character_2": "character", "character_3": "character", "outfit": "outfit",
             "background": "background", "prop": "prop", "voice": "voice"}


def _prompt(settings):
    try:
        return str(json.loads(settings or "{}").get("prompt") or "")
    except ValueError:
        return ""



# ---------------------------------------------------------------- uploads

def tag_for_slot(label):
    """The tag of an asset made from a file dropped into a reference slot with this label."""
    for rid, _, _, words in cast.ROLES:
        if re.search(words, label or "", re.IGNORECASE):
            return ROLE_TAGS.get(rid, "other")
    return "other"


def keep_upload(db, folder, user_id, project, filename, data, kind, label):
    """Keep a reference file the user dropped into a job as an upload of the project, once per file.
    folder: the user's assets folder. Returns the asset id, or None when the file is kept already."""
    stored = "{}_{}".format(hashlib.sha1(data).hexdigest()[:10], safe_name(filename))
    if db.one("SELECT 1 FROM assets WHERE user_id = ? AND filename = ?", (user_id, stored)):
        return None   # this very file is kept already: saved on purpose, or dropped in before
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored).write_bytes(data)
    name = re.sub(r"[_\-]+", " ", filename.rsplit(".", 1)[0]).strip()[:60] or "Upload"
    return db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin, project_id) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, 'upload', ?)",
                  (user_id, name, tag_for_slot(label), kind, stored, len(data), time.time(), project or None))


# ---------------------------------------------------------------- what the agent makes for reuse

# What the agent may say a step's result is kept as, and the tag that gets. Only a voice is a sound; the rest are pictures.
KEEP_AS = {"character": "character", "outfit": "outfit", "location": "background", "prop": "prop", "voice": "voice", "style": "style"}


def clean_keep(keep, kind=None):
    """{"tag", "name"} of a step's result to keep in shared memory, or None. kind: what the step makes, when known."""
    if not isinstance(keep, dict):
        return None
    tag = KEEP_AS.get(str(keep.get("as") or "").strip().lower()) or (keep.get("tag") if keep.get("tag") in KEEP_AS.values() else None)
    name = " ".join(str(keep.get("name") or "").split())[:60]
    if not tag or not name or (kind and kind != ("audio" if tag == "voice" else "image")):
        return None
    return {"tag": tag, "name": name}


def keep_made(db, folder, user_id, item_id, source, kind, keep):
    """Keep what a step made as a saved asset under the name it was planned with ("Maya", a character), so every agent
    tab, every project and the Shared memory tab know it. The file is copied, so deleting either leaves the other.
    A retake under the same name and type replaces the asset the agent made before. Returns the asset id."""
    keep = clean_keep(keep, kind)
    if not keep:
        return None
    stored = "made_{}_{}".format(item_id, safe_name(source.name))
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, folder / stored)
    size = (folder / stored).stat().st_size
    before = db.one("SELECT id, filename FROM assets WHERE user_id = ? AND tag = ? AND lower(name) = lower(?) AND made_from IS NOT NULL",
                    (user_id, keep["tag"], keep["name"]))
    if before:
        db.run("UPDATE assets SET kind = ?, filename = ?, size = ?, made_from = ?, about = '', created = ? WHERE id = ?",
               (kind, stored, size, item_id, time.time(), before["id"]))
        if before["filename"] != stored:
            (folder / before["filename"]).unlink(missing_ok=True)
        return before["id"]
    return db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin, made_from) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, 'saved', ?)", (user_id, keep["name"], keep["tag"], kind, stored, size, time.time(), item_id))


# ---------------------------------------------------------------- the book and the panel

def _asset_entry(row):
    entry = {"asset": row["id"], "name": row["name"], "type": TYPES.get(row["tag"], "other"), "kind": row["kind"],
             "shows": row["about"] or "", "_file": ("asset", row["filename"]), "_table": "assets"}
    if row["origin"] == "upload":
        entry["uploaded"] = True
    if row["use_note"]:
        entry["use"] = row["use_note"]
    return entry


def _item_entry(row, in_cast):
    entry = {"item": row["id"], "name": row["name"], "type": "made in this project", "kind": row["kind"],
             "shows": row["about"] or "", "_file": ("item", row["filename"]), "_table": "generations"}
    made = _prompt(row["settings"])
    if not entry["shows"] and made:
        entry["made_from"] = made[:240]
    if row["id"] in in_cast:
        entry["in_cast"] = True
    checked = review.summary(review.load(row))
    if checked:   # what the agent found when it looked at it: a later plan does not repeat a failed shot
        entry["review"] = checked
    if row.get("rating"):   # the user's thumbs: reuse what they liked, never what they did not
        entry["liked" if row["rating"] > 0 else "disliked"] = True
    return entry


def _project_items(db, user_id, project, limit, kinds=("image", "video")):
    where, params = ("project_id = ?", (user_id, project)) if project else ("project_id IS NULL", (user_id,))
    marks = ", ".join("?" for _ in kinds)
    return db.all("SELECT id, name, kind, filename, about, settings, workflow, created, review, rating FROM generations WHERE user_id = ? AND "
                  + where + " AND kind IN (" + marks + ") ORDER BY created DESC LIMIT ?", (*params, *kinds, limit))


def _uploads(db, user_id, project, limit):
    where, params = ("project_id = ?", (user_id, project)) if project else ("project_id IS NULL", (user_id,))
    return db.all("SELECT id, name, tag, kind, filename, about, use_note, origin, created FROM assets WHERE user_id = ? "
                  "AND origin = 'upload' AND " + where + " ORDER BY created DESC LIMIT ?", (*params, limit))


def book(db, user_id, project, pinned=None):
    """The agent's asset book for a project: [entry], saved assets first, then the project's uploads, then its items.

    pinned: the project's cast, from cast.load(); its items are marked "in_cast" (they go into every shot already).
    Each entry: {"asset" or "item": id, "name", "type", "kind", "shows", "use"?, "uploaded"?, "in_cast"?}. Items past the
    latest few have only their id, name and kind, and "brief": True. The private keys "_file" and "_table" say where
    the file is and where its description is kept; book_for_model() drops them."""
    pinned = pinned or {}
    in_cast = {pin["id"] for pin in pinned.values()}
    entries = [_asset_entry(row) for row in db.all(
        "SELECT id, name, tag, kind, filename, about, use_note, origin FROM assets WHERE user_id = ? AND origin = 'saved' "
        "ORDER BY tag, lower(name) LIMIT ?", (user_id, BOOK_ASSETS))]
    entries += [_asset_entry(row) for row in _uploads(db, user_id, project, BOOK_UPLOADS)]
    rows = _project_items(db, user_id, project, BOOK_ITEMS)
    listed = {row["id"] for row in rows}
    for item_id in in_cast - listed:   # a cast picture from another project is in the book too
        row = db.one("SELECT id, name, kind, filename, about, settings, workflow, created, review, rating FROM generations "
                     "WHERE id = ? AND user_id = ?", (item_id, user_id))
        if row:
            rows.insert(0, row)
    for number, row in enumerate(rows):
        entry = _item_entry(row, in_cast)
        if number >= BOOK_FULL_ITEMS and not entry.get("in_cast"):
            entry = {"item": entry["item"], "name": entry["name"], "kind": entry["kind"], "brief": True,
                     "shows": entry["shows"][:90], "_file": entry["_file"], "_table": entry["_table"]}
        entries.append(entry)
    return entries


def book_for_model(entries):
    """The book as the model is shown it: without the private keys, and without empty fields."""
    return [{k: v for k, v in entry.items() if not k.startswith("_") and k != "brief" and v not in ("", None)} for entry in entries]


def lookup(entries):
    """({item id: {"name", "kind"}}, {asset id: {"name", "kind"}}) of the book, for agent.uses_for."""
    items = {e["item"]: {"name": e["name"], "kind": e["kind"]} for e in entries if "item" in e}
    assets = {e["asset"]: {"name": e["name"], "kind": e["kind"]} for e in entries if "asset" in e}
    return items, assets


def panel(db, user_id, project, pinned=None):
    """Everything the Shared memory tab shows for a project: {"assets", "uploads"}."""
    def asset(row):
        return {"id": row["id"], "name": row["name"], "tag": row["tag"], "type": TYPES.get(row["tag"], "other"), "kind": row["kind"],
                "about": row["about"], "use_note": row["use_note"], "origin": row["origin"], "created": row["created"],
                "url": "/api/assets/{}/file".format(row["id"])}
    saved = db.all("SELECT id, name, tag, kind, about, use_note, origin, created FROM assets WHERE user_id = ? AND origin = 'saved' "
                   "ORDER BY tag, lower(name) LIMIT ?", (user_id, PANEL_ITEMS))
    return {"assets": [asset(r) for r in saved], "uploads": [asset(r) for r in _uploads(db, user_id, project, PANEL_ITEMS)]}


# ---------------------------------------------------------------- looking at pictures

def _path(state, user_id, where):
    table, filename = where
    return (state.assets_dir / str(user_id) if table == "asset" else state.outputs.folder(user_id)) / filename


async def _picture(path):
    """A small JPEG of a picture or of a video's first moments, base64, for the model to look at."""
    still = await media.poster(path)   # reads an image as well as a video, and keeps the result next to the file
    return base64.b64encode(still.read_bytes()).decode("ascii")


async def describe_missing(state, user_id, entries, limit=DESCRIBE_AT_ONCE, seconds=DESCRIBE_SECONDS):
    """Have the agent's model look at the pictures and videos of the book that have no description yet, up to
    `limit` of them, the ones given in full first, and keep what it writes. The entries are updated in place. A model
    that cannot see, a missing file or a slow answer leaves an entry as it is; it is not tried again until a restart."""
    tried = getattr(state, "described_tried", None)
    if tried is None:
        tried = state.described_tried = set()
    waiting = sorted((e for e in entries if not e["shows"] and e["kind"] in ("image", "video")
                      and (e["_table"], e.get("asset") or e.get("item")) not in tried), key=lambda e: bool(e.get("brief")))[:limit]
    if not waiting:
        return 0

    async def one(entry):
        key = (entry["_table"], entry.get("asset") or entry.get("item"))
        tried.add(key)
        try:
            path = _path(state, user_id, entry["_file"])
            if not path.is_file():
                return False
            shows = await state.agent.describe(await _picture(path), entry["name"], entry["kind"])
        except Exception:   # noqa: BLE001 - a description is a help, never a reason for the plan to fail
            return False
        entry["shows"] = shows if not entry.get("brief") else shows[:90]
        entry.pop("made_from", None)
        state.db.run("UPDATE {} SET about = ? WHERE id = ? AND user_id = ?".format(entry["_table"]), (shows, key[1], user_id))
        return True

    tasks = [asyncio.ensure_future(one(entry)) for entry in waiting]
    done, pending = await asyncio.wait(tasks, timeout=seconds)
    for task in pending:   # it goes on in the background and keeps its description for the next message
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return sum(1 for task in done if not task.exception() and task.result())
