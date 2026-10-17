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
                      "version": meta.get("version") or "1", "words": words, "text": text.strip()})
    return found


def pick(instruction, history=(), folder=FOLDER):
    """The skills that fit a message, the one matching most often first, at most MAX_GIVEN.

    A short follow-up ("make it portrait", "now the second scene") is about the same work as the message before it,
    so that message counts too."""
    said = str(instruction or "")
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    if len(said) < 60 and last.get("instruction"):
        said += "\n" + str(last["instruction"])
    scored = [(len(skill["words"].findall(said)), skill) for skill in load(folder)]
    return [skill for count, skill in sorted(scored, key=lambda pair: -pair[0]) if count][:MAX_GIVEN]


def guide(picked):
    """The picked skills as one text for the model, or "" when none fits."""
    return "\n\n".join("{} (skill {} v{}):\n{}".format(s["title"], s["id"], s["version"], s["text"]) for s in picked)
