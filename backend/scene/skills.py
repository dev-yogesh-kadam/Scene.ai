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
MAX_CHARS = 150_000   # the most of one skill that goes to a hosted model (about 40,000 tokens); a longer one is cut here, and the agent says so


def _pairs(block):
    """The "key: value" lines of a header, keys lower-cased, values without the quotes a YAML header puts round them."""
    meta = {}
    for line in block.splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip() and " " not in key.strip():
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            meta[key.strip().lower()] = value
    return meta


def parse(raw):
    """A skill file as (meta, steps). The header is "key: value" lines, then a line of three dashes. Skills written for
    other tools come as a YAML header between two lines of dashes, sometimes twice in a row; every header is read, the
    first value of a key wins (name, label, description, user_description are understood as id, title and desc)."""
    text = raw.replace("\r\n", "\n").lstrip("\ufeff")
    meta = {}
    if text.startswith("---\n"):
        text = text[4:]
    head, sep, rest = text.partition("\n---\n")
    if sep and all(":" in line or not line.strip() for line in head.splitlines()):
        meta = _pairs(head)
        text = rest
    elif not sep:
        return {}, text.strip()
    # more headers straight after the first (a nested "---" block), or a lone separator
    while True:
        text = text.lstrip("\n")
        if text.startswith("---\n"):
            body = text[4:]
            block, sep, rest = body.partition("\n---\n")
            if sep and all(":" in line or not line.strip() for line in block.splitlines()) and block.strip():
                for key, value in _pairs(block).items():
                    meta.setdefault(key, value)
                text = rest
                continue
            text = body
            continue
        break
    return meta, text.strip()


QUOTED = re.compile(r"[\"“]([^\"”]{4,60})[\"”]")


def triggers_from(description):
    """A pattern for the phrases a description puts in quotes ('when the user says "pocket motion v2"'), or "" when it has none."""
    phrases = []
    for phrase in QUOTED.findall(description or ""):
        phrase = " ".join(phrase.split()).strip(" .")
        if len(phrase.split()) >= 2 and phrase.lower() not in (p.lower() for p in phrases):
            phrases.append(phrase)
    return r"\b(" + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in phrases) + r")\b" if phrases else ""


def _short(text, limit=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"


def load(folder=FOLDER):
    """Every skill in the folder: [{"id", "title", "version", "desc", "words", "text"}], in file-name order."""
    found = []
    for path in sorted(Path(folder).glob("*.md")):
        meta, text = parse(path.read_text(encoding="utf-8"))
        slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("id") or meta.get("name") or path.stem).lower()).strip("-") or path.stem
        title = meta.get("title") or meta.get("label") or path.stem
        if title == slug and meta.get("label"):
            title = meta["label"]
        pattern = meta.get("words") or ""
        if not pattern.strip() or pattern.strip() == "(?!)":
            pattern = triggers_from(meta.get("description") or "")   # a skill that says when it applies, in quotes, is found by those words
        try:
            words = re.compile(pattern or r"(?!)", re.IGNORECASE)
        except re.error:
            continue   # a skill whose words can't be read is left out rather than breaking the agent
        found.append({"id": slug, "title": title, "version": meta.get("version") or "1",
                      "desc": meta.get("desc") or _short(meta.get("user_description") or meta.get("description")), "words": words, "text": text})
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


def guide(picked, limit=MAX_CHARS):
    """The picked skills as one text for the model, or "" when none fits. A skill longer than `limit` characters is cut
    there, with a line saying so."""
    out = []
    for s in picked:
        text = s["text"]
        if len(text) > limit:
            text = text[:limit].rstrip() + "\n[The rest of this skill is cut: it is longer than this model is given.]"
        out.append("{} (skill {} v{}):\n{}".format(s["title"], s["id"], s["version"], text))
    return "\n\n".join(out)
