"""The cast of a project: the pictures (and voice) that stay the same in every shot.

A user pins library items to roles once: the main character, an outfit, the location, a prop, a voice. Every
generation in that project then gets them as reference files, in whichever slots of its workflow are meant for them,
which is what keeps a face, a costume and a place the same from one shot to the next.
The pins are saved per project as a board of kind "cast": {role id: library item id}.
"""

import json
import re

# id, what the user sees, the kind of slot it fills, and the words that mark such a slot in a workflow's labels
ROLES = (
    ("character_1", "Main character", "image", r"character 1|main character"),
    ("character_2", "Main character, another angle", "image", r"character 2"),
    ("character_3", "Second person", "image", r"character 3|second person"),
    ("outfit", "Outfit", "image", r"outfit|costume|clothing"),
    ("background", "Location", "image", r"background|location"),
    ("prop", "Prop or product", "image", r"\bprop\b|product"),
    ("voice", "Voice to imitate", "audio", r"voice sample"),
)
# How the prompt should name each role, so the model ties the words to the reference instead of inventing a new look.
SAID_AS = {"character_1": "the main character", "character_2": "the main character", "character_3": "the second person",
           "outfit": "the outfit", "background": "the background", "prop": "the prop", "voice": "the voice"}
# What a slot of each kind can be filled with from the library. A video gives an image slot its last frame.
FITS = {"image": ("image", "video"), "video": ("video",), "audio": ("audio", "video")}


def roles():
    return [{"id": rid, "label": label, "takes": kind} for rid, label, kind, _ in ROLES]


def load(db, user_id, project):
    """The cast of a project, keeping only pins whose item still exists and fits: {role id: {"id", "name", "kind"}}."""
    row = db.one("SELECT data FROM boards WHERE user_id = ? AND project_id = ? AND kind = 'cast'", (user_id, project))
    try:
        pins = json.loads(row["data"]) if row else {}
    except ValueError:
        pins = {}
    cast = {}
    for rid, _, takes, _ in ROLES:
        item = db.one("SELECT id, name, kind FROM generations WHERE id = ? AND user_id = ?", (pins.get(rid), user_id)) \
            if isinstance(pins.get(rid), int) else None
        if item and item["kind"] in FITS[takes]:
            cast[rid] = {"id": item["id"], "name": item["name"], "kind": item["kind"]}
    return cast


def fills(schema, cast, taken=(), used=()):
    """The reference slots of a workflow that the cast fills: [{"id", "name", "slot", "label", "kind", "role", "item_kind"}].

    kind is what the slot takes. taken: slot ids that already have a file; used: item ids already in the job."""
    special = set((schema.get("slots") or {}).values())   # first frame, last frame, voice track: never the cast's
    out, taken, used = [], set(taken), set(used)
    for rid, _, takes, words in ROLES:
        pin = cast.get(rid)
        if not pin or pin["id"] in used:
            continue
        slot = next((r for r in schema["refs"] if r["id"] not in taken and r["id"] not in special and r["kind"] == takes
                     and re.search(words, r["label"], re.IGNORECASE)), None)
        if slot is None:
            continue
        taken.add(slot["id"])
        used.add(pin["id"])
        out.append({"id": pin["id"], "name": pin["name"], "slot": slot["id"], "label": slot["label"].split(" (")[0],
                    "kind": slot["kind"], "role": rid, "item_kind": pin["kind"]})
    return out


def described(cast):
    """The cast in a sentence for a language model, or "" when there is none."""
    if not cast:
        return ""
    names = {rid: label for rid, label, _, _ in ROLES}
    lines = ['- {}: "{}". In prompts call it "{}".'.format(names[rid], pin["name"], SAID_AS[rid]) for rid, pin in cast.items()]
    return ("These reference files are attached to every shot automatically. Do not describe how they look and do not "
            "list them in \"uses\"; name them in the prompt with the words given.\n" + "\n".join(lines))
