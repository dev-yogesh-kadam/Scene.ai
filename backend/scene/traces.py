"""What the agent's models were asked and how they did: one row per call (agent.Agent.chat) in `agent_calls`, for the
admin console's Agent section, and the whole exchange (the messages sent and the answer) kept for a week in
storage/agent_calls/<id>.json.gz, to read it again or replay it with another model.

The calls of one turn of the agent (its rounds of tool calls) share a run: `RUN` is set for the turn and every call
in it carries the same one. Who asked is the user the request acts for (db.ACTING).
"""

import contextvars
import gzip
import json
import time
import uuid
from pathlib import Path

from .db import ACTING, EVERYONE

RUN = contextvars.ContextVar("agent_run", default="")
KEEP_CALLS = 30 * 86400       # the rows: what was asked of which model, how long it took, what it cost
KEEP_EXCHANGES = 7 * 86400    # the words themselves, which can be long (a skill) and are the users' own


def new_run():
    """Start a run for the calls that follow in this task (one turn of the agent). Returns the token to end it."""
    return RUN.set(uuid.uuid4().hex[:12])


class Recorder:
    def __init__(self, db, folder):
        self.db, self.folder = db, Path(folder)

    def record(self, purpose, model, asked, started, messages, answer_format, content=None, usage=None, error=None, tool=None):
        acting = ACTING.get()
        usage = usage or {}
        call_id = self.db.run(
            "INSERT INTO agent_calls (run, user_id, purpose, model, asked, started, seconds, prompt_tokens, cached_tokens, "
            "answer_tokens, tool, error, chars) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (RUN.get(), int(acting) if acting not in (EVERYONE, None) and str(acting).isdigit() else None, purpose, model or "",
             asked or "", started, round(time.time() - started, 3), int(usage.get("prompt") or 0), int(usage.get("cached") or 0),
             int(usage.get("answer") or 0), str(tool or "")[:60], str(error or "")[:500],
             sum(len(str(m.get("content") or "")) for m in messages)))
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            kept = {"messages": [{k: (len(v) if k == "images" else v) for k, v in m.items()} for m in messages],
                    "format": answer_format, "answer": content}
            (self.folder / "{}.json.gz".format(call_id)).write_bytes(gzip.compress(json.dumps(kept, ensure_ascii=False).encode("utf-8")))
        except (OSError, TypeError, ValueError):
            pass   # the row is what counts; the words are a help
        return call_id

    def exchange(self, call_id):
        try:
            return json.loads(gzip.decompress((self.folder / "{}.json.gz".format(int(call_id))).read_bytes()))
        except (OSError, ValueError, EOFError):
            return None

    def prune(self, now=None):
        """Forget rows older than a month and words older than a week."""
        now = now or time.time()
        self.db.run("DELETE FROM agent_calls WHERE started < ?", (now - KEEP_CALLS,))
        if self.folder.is_dir():
            for path in self.folder.glob("*.json.gz"):
                try:
                    if path.stat().st_mtime < now - KEEP_EXCHANGES:
                        path.unlink()
                except OSError:
                    pass
