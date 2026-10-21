"""The kit of a project: every character, location, prop, outfit, voice, style and script it is made from, by name.

One store for what the cast and the shared memory were. Each entry is a row of `assets` with the project's id: a copy
of its file, a name, a type (the tag), what it shows (written by the agent's model looking at it, or by the user), a
note on how to use it, its place in the kit, and whether it is always on.

- An always-on entry goes into every shot of the project that has a slot meant for it (what the cast did): the
  characters in their order into the character slots, the location into the background slot, and so on.
- Every entry is known to the agent by name and id, which uses it where a shot needs it, and to the user's pickers.
- An entry attached without a name (named = 0) is one the agent asks the user about.

Entries come in from everywhere work is done: named in an agent message ("Maya - @3"), kept from what a step made
(keep_made), saved by the agent (its kit_save tool), dropped into a job's reference slot (keep_upload), and added by
the user in the panel or from a result on the canvas.

The assets saved before kits existed (no project) are kept, but no longer used on their own: a project can import them.
"""

import hashlib
import json
import re
import shutil
import time

from .references import safe_name

# The types of entry, as tags (as stored) and as the user and the agent read them.
TYPES = {"character": "character", "background": "location", "outfit": "outfit", "prop": "prop", "voice": "voice",
         "style": "style", "script": "script", "other": "other"}
TAG_OF = {said: tag for tag, said in TYPES.items()}   # "location" -> "background"
NOTE_CHARS = 600
NAME_CHARS = 60

# What a slot of each type is called in a workflow's labels; the kind of file it takes; and what each kind of slot can be
# filled with (a video gives a picture slot its last frame, and a voice slot its sound).
SLOT_WORDS = (("character", r"character|main character|second person|\bperson\b"),
              ("background", r"background|location"),
              ("outfit", r"outfit|costume|clothing"),
              ("prop", r"\bprop\b|product"),
              ("voice", r"voice sample"),
              ("style", r"\bstyle\b"))
OTHER_ANGLE = re.compile(r"same person|another angle|other angle", re.IGNORECASE)   # a second picture of the first character
SLOT_KIND = {"voice": "audio"}
FITS = {"image": ("image", "video"), "video": ("video",), "audio": ("audio", "video")}
# How a prompt names each always-on entry, so the model ties the words to the reference instead of inventing a look.
PEOPLE = ("the main character", "the second person", "the third person", "the fourth person")
SAID_AS = {"background": "the background", "outfit": "the outfit", "prop": "the prop", "voice": "the voice", "style": "the style"}


def tag_of(said):
    """The stored tag of a type as anyone says it ("location", "Character", "background"), or "other"."""
    said = str(said or "").strip().lower()
    return said if said in TYPES else TAG_OF.get(said, "other")


def clean_name(name):
    return " ".join(str(name or "").split())[:NAME_CHARS]


def clean_note(text):
    return " ".join(str(text or "").split())[:NOTE_CHARS]


def _where(project):
    return ("project_id = ?", (project,)) if project else ("project_id IS NULL AND origin <> 'saved'", ())


def entries(db, user_id, project):
    """The kit of a project, in order: the always-on entries first, then the rest. Each a row of assets with "type"."""
    where, params = _where(project)
    rows = db.all("SELECT id, name, tag, kind, filename, size, about, use_note, origin, made_from, always, position, named, created "
                  "FROM assets WHERE user_id = ? AND " + where + " ORDER BY always DESC, position, created", (user_id, *params))
    return [dict(row, type=TYPES.get(row["tag"], "other")) for row in rows]


def entry(db, user_id, asset_id):
    row = db.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (asset_id, user_id))
    return dict(row, type=TYPES.get(row["tag"], "other")) if row else None


def _next_position(db, user_id, project):
    where, params = _where(project)
    found = db.one("SELECT MAX(position) AS last FROM assets WHERE user_id = ? AND " + where, (user_id, *params))
    return (found["last"] or 0) + 1 if found else 1


def add(db, folder, user_id, project, data, filename, kind, name, tag="other", always=False, named=True, about="",
        use_note="", made_from=None, origin="kit"):
    """Add a file to a project's kit and return its id. The same file added again to the same project is the entry it
    already is: a name, a type and always-on given now fill in what it lacked (an entry without a name gets one)."""
    digest = hashlib.sha1(data).hexdigest()[:10]
    stored = "{}_{}".format(digest, safe_name(filename))
    where, params = _where(project)
    # the same content, whatever the file was called (its stored name starts with the content's digest)
    before = next((r for r in db.all("SELECT id, named, tag, always, filename FROM assets WHERE user_id = ? AND " + where, (user_id, *params))
                   if r["filename"].startswith(digest + "_")), None)
    name, tag = clean_name(name) or "Untitled", tag_of(tag)
    if before:
        changes = {}
        if named and not before["named"]:
            changes.update(name=name, named=1)
        if tag != "other" and before["tag"] == "other":
            changes["tag"] = tag
        if always and not before["always"]:
            changes["always"] = 1
        if changes:
            db.run("UPDATE assets SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in changes)), (*changes.values(), before["id"]))
        return before["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored).write_bytes(data)
    return db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin, project_id, about, use_note, "
                  "made_from, always, position, named) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (user_id, name, tag, kind, stored, len(data), time.time(), origin, project or None, clean_note(about),
                   clean_note(use_note), made_from, 1 if always else 0, _next_position(db, user_id, project), 1 if named else 0))


def add_item(db, folder, outputs, user_id, project, item_id, name="", tag="other", always=False, named=True, about=""):
    """Add a library item (a result on the canvas, an attached file) to a project's kit. None if there is no such item."""
    row = db.one("SELECT id, name, kind, filename, about FROM generations WHERE id = ? AND user_id = ?", (item_id, user_id))
    source = outputs / row["filename"] if row else None
    if not source or not source.is_file():
        return None
    return add(db, folder, user_id, project, source.read_bytes(), row["filename"], row["kind"], name or row["name"], tag, always,
               named, about or row["about"] or "", made_from=row["id"])


def update(db, user_id, asset_id, changes):
    """Change an entry: name, type, about, use_note, always, position. Returns the entry, or None if it is not the user's."""
    row = entry(db, user_id, asset_id)
    if row is None:
        return None
    fields = {}
    if "name" in changes and clean_name(changes["name"]):
        fields.update(name=clean_name(changes["name"]), named=1)
    if "type" in changes or "tag" in changes:
        fields["tag"] = tag_of(changes.get("type", changes.get("tag")))
    for key in ("about", "use_note"):
        if key in changes:
            fields[key] = clean_note(changes[key])
    if "always" in changes:
        fields["always"] = 1 if changes["always"] else 0
    if isinstance(changes.get("position"), (int, float)) and not isinstance(changes.get("position"), bool):
        fields["position"] = float(changes["position"])
    if fields:
        db.run("UPDATE assets SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in fields)), (*fields.values(), asset_id))
    return entry(db, user_id, asset_id)


def reorder(db, user_id, project, ids):
    """Put a project's entries in the order given (ids); the ones not named keep their place after them."""
    mine = {row["id"] for row in entries(db, user_id, project)}
    for position, asset_id in enumerate([i for i in ids if i in mine], start=1):
        db.run("UPDATE assets SET position = ? WHERE id = ?", (position, asset_id))


def remove(db, folder, user_id, asset_id):
    row = entry(db, user_id, asset_id)
    if row is None:
        return False
    db.run("DELETE FROM assets WHERE id = ?", (asset_id,))
    if not db.one("SELECT 1 FROM assets WHERE user_id = ? AND filename = ?", (user_id, row["filename"])):
        (folder / row["filename"]).unlink(missing_ok=True)   # another project may have the same file: then it stays
    return True


def earlier(db, user_id):
    """The assets saved before kits existed (no project), which a project can import."""
    return db.all("SELECT id, name, tag, kind, about FROM assets WHERE user_id = ? AND project_id IS NULL AND origin = 'saved' "
                  "ORDER BY tag, lower(name)", (user_id,))


def import_earlier(db, folder, user_id, project, ids):
    """Copy assets saved before kits existed into a project's kit. Returns the new entries' ids."""
    made = []
    for asset_id in ids:
        row = db.one("SELECT * FROM assets WHERE id = ? AND user_id = ? AND project_id IS NULL AND origin = 'saved'", (asset_id, user_id))
        if row and (folder / row["filename"]).is_file():
            made.append(add(db, folder, user_id, project, (folder / row["filename"]).read_bytes(), row["filename"].split("_", 1)[-1],
                            row["kind"], row["name"], row["tag"], about=row["about"], use_note=row["use_note"]))
    return made


# ---------------------------------------------------------------- always on: what goes into every shot

def always(db, user_id, project):
    """The always-on entries of a project, in order."""
    return [e for e in entries(db, user_id, project) if e["always"]]


def fills(schema, on, taken=(), used=(), left_out=(), used_items=()):
    """The reference slots of a workflow that the always-on entries fill:
    [{"id": 0, "asset", "name", "slot", "label", "kind", "role", "item_kind", "said_as"}].

    on: always(), in order. taken: slot ids that have a file already; used: asset ids already in the job; left_out:
    asset ids a shot leaves out (a close-up on white has no location); used_items: library ids already in the job (an
    entry kept from one of them is in it already). The characters go into the character slots in
    their order (a slot for the same person from another angle takes a second picture under the first one's name), the
    rest into the slot for their type. First frame, last frame and voice track are never filled from the kit."""
    special = set((schema.get("slots") or {}).values())
    taken, used, left_out, used_items = set(taken), set(used), set(left_out), set(used_items)
    slots = [r for r in schema["refs"] if r["id"] not in special and r["id"] not in taken]
    out = []

    def put(slot, e, said_as):
        taken.add(slot["id"])
        used.add(e["id"])
        out.append({"id": 0, "asset": e["id"], "name": e["name"], "slot": slot["id"], "label": slot["label"].split(" (")[0],
                    "kind": slot["kind"], "role": e["tag"], "item_kind": e["kind"], "said_as": said_as})

    def fit(e, slot):
        return (e["kind"] in FITS.get(slot["kind"], ()) and e["id"] not in used and e["id"] not in left_out
                and not (e.get("made_from") and e["made_from"] in used_items))

    people = [e for e in on if e["tag"] == "character"]
    first_name = people[0]["name"].lower() if people else None
    names_seen, distinct = set(), []
    for e in people:   # the characters, one picture each, in order; more pictures of the same one are its other angles
        if e["name"].lower() not in names_seen:
            names_seen.add(e["name"].lower())
            distinct.append(e)
    angles = [e for e in people if e["name"].lower() == first_name and e not in distinct[:1]]
    order = 0
    for slot in slots:
        if slot["id"] in taken:
            continue
        label = slot["label"]
        if OTHER_ANGLE.search(label):
            e = next((a for a in angles if fit(a, slot)), None)
            if e:
                put(slot, e, PEOPLE[0])
            continue
        tag = next((t for t, words in SLOT_WORDS if SLOT_KIND.get(t, "image") == slot["kind"] and re.search(words, label, re.IGNORECASE)), None)
        if tag == "character":
            while order < len(distinct) and not fit(distinct[order], slot):
                order += 1
            if order < len(distinct):
                put(slot, distinct[order], PEOPLE[min(order, len(PEOPLE) - 1)])
                order += 1
        elif tag:
            e = next((e for e in on if e["tag"] == tag and fit(e, slot)), None)
            if e:
                put(slot, e, SAID_AS.get(tag, "the " + TYPES[tag]))
    return out


def described(on):
    """The always-on entries in words for the agent's model, or "" when there are none."""
    if not on:
        return ""
    people = []
    lines = []
    for e in on:
        if e["tag"] == "character":
            if e["name"].lower() in people:
                continue   # another angle of a character already said
            people.append(e["name"].lower())
            said = PEOPLE[min(len(people) - 1, len(PEOPLE) - 1)]
        else:
            said = SAID_AS.get(e["tag"], "the " + TYPES.get(e["tag"], "reference"))
        lines.append('- {} "{}" (asset {}): in prompts call it "{}".'.format(TYPES.get(e["tag"], "other"), e["name"], e["id"], said))
    return ("Always on: these entries of the kit are attached to every shot automatically, in the slots meant for them "
            "(the characters in this order). Do not describe how they look and do not list them in \"uses\"; name them in "
            "the prompt with the words given. A shot they do not belong in leaves them out: list their asset ids in "
            "\"leave_out\".\n" + "\n".join(lines))


IN_WORDS = ("character", "background", "outfit", "prop")   # the entries a prompt describes when a model takes no pictures
IN_WORDS_CHARS = 220


def in_words(on, left_out=()):
    """The always-on entries in words, for a workflow that takes no reference pictures (text to image, text to video):
    what each shows, so the model keeps them the same from the words alone. "" when there is nothing to say."""
    left_out, seen, people, parts = set(left_out), set(), 0, []
    for e in on:
        if e["tag"] not in IN_WORDS or e["id"] in left_out or not e.get("about"):
            continue
        if e["tag"] == "character":
            if e["name"].lower() in seen or people >= 2:
                continue   # one description a person, and no more than two people: a prompt is not a cast list
            seen.add(e["name"].lower())
            said = PEOPLE[people]
            people += 1
        else:
            said = SAID_AS[e["tag"]]
        parts.append("{}: {}".format(said[0].upper() + said[1:], e["about"][:IN_WORDS_CHARS].rstrip(".")))
    return ". ".join(parts) + "." if parts else ""


def mentions(schema, text, all_entries, taken=(), usable=None):
    """@names in a prompt the user wrote ("@Violet walks into @Bonfire Clearing"): each entry of the kit named so goes
    into a free reference slot that fits it, and its name in the prompt becomes the words the model ties to that slot
    ("the main character", "the background"). An entry with no slot for it (a model that takes no pictures) is said by
    what it shows. Returns (the prompt, {slot id: asset id}). taken: slots that have a file; usable: the slots the
    chosen mode reads (all when None)."""
    named = sorted((e for e in all_entries if e["name"]), key=lambda e: -len(e["name"]))
    if "@" not in str(text or "") or not named:
        return text, {}
    special = set((schema.get("slots") or {}).values())
    taken = set(taken)
    slots = [r for r in schema["refs"] if r["id"] not in special and (usable is None or r["id"] in usable)]
    people = [r for r in slots if r["kind"] == "image" and re.search(SLOT_WORDS[0][1], r["label"], re.IGNORECASE) and not OTHER_ANGLE.search(r["label"])]
    placed, words = {}, {}

    def slot_for(e):
        fits = [r for r in slots if r["id"] not in taken and e["kind"] in FITS.get(r["kind"], ())]
        if e["tag"] == "character":
            return next((r for r in people if r in fits), None)
        words_for_type = dict(SLOT_WORDS).get(e["tag"])
        return next((r for r in fits if words_for_type and re.search(words_for_type, r["label"], re.IGNORECASE)), None)

    def said(e):
        if e["id"] in words:
            return words[e["id"]]
        slot = slot_for(e)
        if slot is None:   # nowhere to put it: the model is told what it shows instead
            words[e["id"]] = (e.get("about") or e["name"])[:IN_WORDS_CHARS].rstrip(".")
            return words[e["id"]]
        taken.add(slot["id"])
        placed[slot["id"]] = e["id"]
        if e["tag"] == "character":
            words[e["id"]] = PEOPLE[min(people.index(slot), len(PEOPLE) - 1)]
        else:
            words[e["id"]] = SAID_AS.get(e["tag"], "the " + TYPES.get(e["tag"], "reference"))
        return words[e["id"]]

    pattern = re.compile(r"@(" + "|".join(re.escape(e["name"]) for e in named) + r")(?![\w])", re.IGNORECASE)
    by_name = {e["name"].lower(): e for e in named}
    out = pattern.sub(lambda m: said(by_name[m.group(1).lower()]), str(text))
    return out, placed


# ---------------------------------------------------------------- the cast boards of before

CAST_ROLES = (("character_1", "character"), ("character_2", "character"), ("character_3", "character"), ("outfit", "outfit"),
              ("background", "background"), ("prop", "prop"), ("voice", "voice"))


def migrate_cast(db, assets_root, outputs):
    """Once: every project's cast (a board of pins: {role: library item id}) becomes always-on entries of its kit, in the
    cast's order. "Main character, another angle" keeps the main character's name, so it fills the other-angle slot."""
    if db.setting("kit_migrated", "0") == "1":
        return 0
    moved = 0
    for board in db.all("SELECT user_id, project_id, data FROM boards WHERE kind = 'cast'"):
        try:
            pins = json.loads(board["data"] or "{}")
        except ValueError:
            continue
        main = None
        for role, tag in CAST_ROLES:
            item_id = pins.get(role)
            if not isinstance(item_id, int):
                continue
            row = db.one("SELECT id, name FROM generations WHERE id = ? AND user_id = ?", (item_id, board["user_id"]))
            if not row:
                continue
            name = main if role == "character_2" and main else row["name"]
            made = add_item(db, assets_root / str(board["user_id"]), outputs.folder(board["user_id"]), board["user_id"],
                            board["project_id"] or None, item_id, name, tag, always=True)
            if made:
                moved += 1
                if role == "character_1":
                    main = name
    db.set_setting("kit_migrated", "1")
    return moved
