"""The studio's servers and APIs, as the admin console's Servers section lists them: the ComfyUI servers the renders run
on, the Ollama servers the agent's local models run on, and hosted APIs that speak the OpenAI chat API (Kimi, Gemini, a
notebook's tunnel...). Each one is added, switched off or removed in the console while the app runs.

A render goes to a ComfyUI server that is free: one that answers and runs none of the studio's renders now (jobs.py).
A call to a local model goes to the Ollama server that has the model and the fewest calls in hand (agent.py).

The first ComfyUI server is the main one: the files people upload are put there and the node definitions are read from
it. A render on another server is given the files it needs first (jobs.py).
"""

import asyncio
import re
import time

import httpx

from .agent import service
from .comfy.client import Comfy

KINDS = {"comfy": "ComfyUI", "ollama": "Ollama", "openai": "OpenAI-style API"}
FIELDS = ("kind", "name", "url", "api_key", "models", "active")


def seed(db, settings):
    """An installation without any: the ComfyUI and Ollama servers config.json names (and the console's old address)."""
    if db.one("SELECT 1 FROM endpoints"):
        return
    first = [("comfy", "Render server", db.setting("comfy_url", settings.comfy_url)), ("ollama", "Agent's models", settings.ollama_url)]
    for kind, name, url in first:
        if str(url or "").strip():
            db.run("INSERT INTO endpoints (kind, name, url, api_key, models, active, created) VALUES (?, ?, ?, '', '', 1, ?)",
                   (kind, name, str(url).strip().rstrip("/"), time.time()))


def listed(db, kind=None, active_only=False):
    sql, params = "SELECT * FROM endpoints WHERE 1 = 1", []
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if active_only:
        sql += " AND active = 1"
    return db.all(sql + " ORDER BY id", tuple(params))


def clean(body, before=None):
    """What an admin typed for one, tidied: {"kind", "name", "url", "api_key", "models", "active"}. Nothing is refused:
    a missing name gets one, an address without http:// gets it, and one that does not answer is shown as not answering."""
    row = dict(before or {"kind": "comfy", "name": "", "url": "", "api_key": "", "models": "", "active": 1})
    for key in FIELDS:
        if key in body:
            row[key] = body[key]
    row["kind"] = str(row["kind"])
    if row["kind"] not in KINDS:
        row["kind"] = "comfy"
    row["name"] = " ".join(str(row["name"] or "").split())[:60] or KINDS[row["kind"]]
    row["url"] = "".join(str(row["url"] or "").split()).rstrip("/")[:300]
    if row["url"] and not re.match(r"^[a-z][a-z0-9+.-]*://", row["url"], re.I):
        row["url"] = "http://" + row["url"]
    row["api_key"] = str(row["api_key"] or "").strip()[:500]
    row["models"] = ", ".join(m.strip() for m in str(row["models"] or "").split(",") if m.strip())[:500]
    row["active"] = 1 if row["active"] else 0
    return row


def shown(row):
    """A row as the console sees it: the key is never sent back, only whether there is one."""
    return {k: row[k] for k in ("id", "kind", "name", "url", "models", "active", "created")} | {"has_key": bool(row.get("api_key"))}


def apply(db, agent, settings):
    """Give the agent the Ollama servers and the hosted APIs as they are now. At start and after each change in the console."""
    ollama = [r["url"] for r in listed(db, "ollama", active_only=True)]
    if not listed(db, "ollama"):   # none was ever added: config.json's
        ollama = [settings.ollama_url.rstrip("/")] if settings.ollama_url else []
    agent.set_servers(ollama)
    extra = [service(re.sub(r"[^a-z0-9]+", "-", r["name"].lower()).strip("-") or "api{}".format(r["id"]), r["name"], r["url"],
                     r["api_key"] or "none", r["models"]) for r in listed(db, "openai", active_only=True)]
    agent.set_services(extra)


class ComfyPool:
    """The ComfyUI servers the renders may go to, with the one each is running now."""

    def __init__(self, db, fallback):
        self.db = db
        self.fallback = fallback.rstrip("/") if fallback else ""   # config.json's, while none is in the table
        self.main = Comfy(self.main_url)   # the main server (app.state.comfy)
        self.clients = {}
        self.busy = {}   # url -> the id of the studio's job running there

    def servers(self):
        """[{"name", "url"}] of the servers a render may go to now, the main one first."""
        rows = listed(self.db, "comfy")
        if not rows:
            return [{"name": "", "url": self.fallback}] if self.fallback else []
        return [{"name": r["name"], "url": r["url"]} for r in rows if r["active"] and r["url"]]

    def main_url(self):
        every = self.servers() or [{"url": r["url"]} for r in listed(self.db, "comfy")[:1]]
        return every[0]["url"] if every else self.fallback

    def client(self, url):
        """The client of one server: the main one is app.state.comfy itself."""
        if url == self.main.url:
            return self.main
        if url not in self.clients:
            self.clients[url] = Comfy(lambda: url)
        return self.clients[url]

    async def free(self, answers=None):
        """(the first free server that answers or None, whether any server answers or runs a render). `answers`:
        async function(url) -> bool, whether a server answers; without it a free one is taken without asking it."""
        alive = False
        for s in self.servers():
            if s["url"] in self.busy:
                alive = True
                continue
            if answers is None or await answers(s["url"]):
                return s, True
        return None, alive

    async def answers(self, url):
        try:
            await self.client(url).stats()
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def close(self):
        for c in [self.main, *self.clients.values()]:
            await c.http.aclose()


async def status(state):
    """Every row with whether it answers now, what it runs and the models it has. All are asked at once, briefly."""
    agent, pool = state.agent, state.comfy_pool

    async def one(http, row):
        item = shown(row)
        if not row["url"]:
            return dict(item, online=False)
        try:
            if row["kind"] == "comfy":
                r = await http.get(row["url"] + "/system_stats")
                r.raise_for_status()
                devices = r.json().get("devices") or [{}]
                item.update(online=True, detail=devices[0].get("name", ""), running=pool.busy.get(row["url"]))
            elif row["kind"] == "ollama":
                r = await http.get(row["url"] + "/api/tags")
                r.raise_for_status()
                item.update(online=True, found=[m["name"] for m in r.json().get("models") or []], calls=agent.calls.get(row["url"], 0))
            else:
                r = await http.get(row["url"] + "/models", headers={"Authorization": "Bearer " + (row["api_key"] or "none")})
                item.update(online=r.status_code < 400,
                            found=[str(m.get("id")) for m in (r.json().get("data") or [])][:40] if r.status_code < 400 else [])
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            item["online"] = False
        return item

    async with httpx.AsyncClient(timeout=httpx.Timeout(4, connect=2)) as http:
        return list(await asyncio.gather(*(one(http, row) for row in listed(state.db))))
