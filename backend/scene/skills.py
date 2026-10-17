"""Skills: how the agent does one kind of work (a short film, an ad, a character sheet), written as text, not code.

Each skill is a Markdown file in skills/ that starts with a few "key: value" lines and a line of three dashes:

    id: short-film
    title: A short film or a story
    version: 1
    words: \\b(film|story|scene)\\b
    ---
    The steps, in plain words.

"words" is a regular expression; a skill is given to the agent when the user's new message (or, for a short follow-up,
the message before it) matches it. The files are read on every message, so a change to one counts at once.
"""

import re
from pathlib import Path

FOLDER = Path(__file__).parent / "skills"
MAX_GIVEN = 2   # skills given with one message, the best matches first


def load(folder=FOLDER):
    """Every skill in the folder: [{"id", "title", "version", "words", "text"}], in file-name order."""
    found = []
    for path in sorted(Path(folder).glob("*.md")):
        head, _, text = path.read_text(encoding="utf-8").partition("\n---\n")
        meta = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
        meta = {key.strip(): value.strip() for key, value in meta.items()}
        try:
            words = re.compile(meta.get("words") or r"(?!)", re.IGNORECASE)
        except re.error:
            continue   # a skill whose words can't be read is left out rather than breaking the agent
        found.append({"id": meta.get("id") or path.stem, "title": meta.get("title") or path.stem,
                      "version": meta.get("version") or "1", "desc": meta.get("desc") or "", "words": words, "text": text.strip()})
    return found


def find(skill_id, folder=FOLDER):
    """The one skill with this id, or None. Used when the user asks for a skill by name with /<id>."""
    for skill in load(folder):
        if skill["id"] == skill_id:
            return skill
    return None


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _line(value):
    """A header value kept to one line: newlines would break the "key: value" format."""
    return " ".join(str(value or "").split())


def save(meta, folder=FOLDER):
    """Write a skill file from fields (id, title, desc, version, words, text) and return the saved skill. Admin only
    (the caller checks). Raises ValueError on a bad id or a words pattern that is not a valid regular expression."""
    sid = _line(meta.get("id")).lower()
    if not SLUG.match(sid):
        raise ValueError("The id must be lower-case letters, numbers and hyphens, and start with a letter or number.")
    words = _line(meta.get("words"))
    try:
        re.compile(words or r"(?!)", re.IGNORECASE)
    except re.error as err:
        raise ValueError("The trigger words are not a valid regular expression: {}".format(err))
    head = "id: {}\ntitle: {}\n".format(sid, _line(meta.get("title")) or sid)
    desc = _line(meta.get("desc"))
    if desc:
        head += "desc: {}\n".format(desc)
    head += "version: {}\nwords: {}\n".format(_line(meta.get("version")) or "1", words)
    path = Path(folder) / (sid + ".md")
    path.write_text(head + "---\n" + str(meta.get("text") or "").strip() + "\n", encoding="utf-8")
    return find(sid, folder)


def remove(skill_id, folder=FOLDER):
    """Delete a skill file. Returns True when one was there to delete."""
    if not SLUG.match(_line(skill_id)):
        return False
    path = Path(folder) / (_line(skill_id) + ".md")
    if path.is_file():
        path.unlink()
        return True
    return False


def pick(instruction, history=(), folder=FOLDER, force=()):
    """The skills that fit a message, with any the user named by /<id> first; the rest fill up to MAX_GIVEN.

    `force` is a list of skill ids the user chose explicitly (from a /command). They are always included.

    A short follow-up ("make it portrait", "now the second scene") is about the same work as the message before it,
    so that message counts too.
    """
    said = str(instruction or "")
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    if len(said) < 60 and last.get("instruction"):
        said += "\n" + str(last["instruction"])
    all_skills = load(folder)
    chosen = [s for s in all_skills if s["id"] in (force or [])]   # the ones the user named, first and always kept
    scored = [(len(s["words"].findall(said)), s) for s in all_skills if s["id"] not in (force or [])]
    matched = [s for count, s in sorted(scored, key=lambda pair: -pair[0]) if count]
    return (chosen + matched)[:max(MAX_GIVEN, len(chosen))]


def guide(picked):
    """The picked skills as one text for the model, or "" when none fits."""
    return "\n\n".join("{} (skill {} v{}):\n{}".format(s["title"], s["id"], s["version"], s["text"]) for s in picked)
