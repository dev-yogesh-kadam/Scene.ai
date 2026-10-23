"""What is made in the studio, looked at by its moderators.

A list of words the studio does not want in prompts (setting `moderation_words`) and what is done about them (setting
`moderation_mode`): "off"; "flag", which marks an item made from such a prompt for review; or "refuse", which also
refuses the job before it is made (jobs.JobManager.add), gives its credits back, and writes the refusal down. The
console's Moderation section shows what was made lately, flagged first, and each item gets a verdict: fine, or
removed from its owner's library. Verdicts and refusals are kept in the `moderation` table.
"""

import json
import re
import time

MODES = ("off", "flag", "refuse")


def settings(db):
    try:
        words = json.loads(db.setting("moderation_words", "") or "[]")
    except ValueError:
        words = []
    mode = db.setting("moderation_mode", "off")
    return {"words": [str(w) for w in words if str(w).strip()], "mode": mode if mode in MODES else "off"}


def save(db, words, mode):
    clean = sorted({" ".join(str(w).lower().split())[:60] for w in words if str(w).strip()})[:500]
    db.set_setting("moderation_words", json.dumps(clean))
    db.set_setting("moderation_mode", mode if mode in MODES else "off")
    return settings(db)


def matches(text, words):
    """The listed words (or phrases) in `text`, as whole words, any case."""
    low = str(text or "").lower()
    return [w for w in words if re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", low)]


def prompt_of(settings_json):
    """The words a job or an item was made from: its prompt and the text values typed into it."""
    try:
        found = json.loads(settings_json) if isinstance(settings_json, str) else (settings_json or {})
    except ValueError:
        return ""
    values = found.get("values") if isinstance(found.get("values"), dict) else {}
    parts = [found.get("prompt")] + [v for v in values.values() if isinstance(v, str)]
    return " · ".join(dict.fromkeys(str(p).strip() for p in parts if p and str(p).strip()))


def refusal(db, user_id, job_settings):
    """The words that refuse this job, when the studio refuses such prompts; written down. None when it may run."""
    found = settings(db)
    if found["mode"] != "refuse" or not found["words"]:
        return None
    prompt = prompt_of(job_settings)
    hit = matches(prompt, found["words"])
    if not hit:
        return None
    db.run("INSERT INTO moderation (kind, generation_id, user_id, verdict, words, prompt, by_name, created) "
           "VALUES ('refused', NULL, ?, 'refused', ?, ?, '', ?)", (user_id, ", ".join(hit), prompt[:1000], time.time()))
    return hit
