"""Whether the studio is well: its two servers (the render server, ComfyUI, and the agent's model server, Ollama), its
disk, its backups and its queue.

`problems` says what is wrong right now; the admin console's Overview lists it. The `Watcher` asks it every minute
while the app runs, so nobody has to have the console open: a problem found twice in a row becomes an alert (the
`alerts` table), which is sent to the admins' phones (phone.py), and is closed, and said so, once it is gone.
"""

import asyncio
import json
import shutil
import time

import httpx

from . import backup, phone, versions

CHECK_EVERY = 60     # seconds between checks
FIRST_CHECK = 30     # after the app starts: it settles first (the render server may take a moment to be reached)
CONFIRM = 2          # checks in a row a problem must be found in before it is sent: a moment's hiccup is not
DAY = 86400

# What is said when a problem is gone, by its key.
RESOLVED = {
    "render": "The render server answers again",
    "model": "The agent's model server answers again",
    "disk": "There is enough disk space again",
    "backup": "The database has been backed up",
    "backup_check": "The newest backup reads back whole",
    "waiting": "No job has been waiting for over an hour",
    "slow": "The slow job is no longer running",
    "failures": "Jobs have stopped failing",
}


def clock(timestamp):
    """A time of day, with the date when it was not today: "14:02", or "9 Oct 14:02"."""
    when = time.localtime(timestamp)
    return time.strftime("%H:%M" if time.strftime("%Y-%m-%d", when) == time.strftime("%Y-%m-%d") else "%d %b %H:%M", when).lstrip("0")


def minutes(seconds):
    return "{} min".format(max(1, round(seconds / 60))) if seconds < 5400 else "{:.1f} h".format(seconds / 3600)


# What each server check last found, so a page of the console does not wait on a server that does not answer (a wait
# of seconds): a check younger than FRESH is used as it is, an older one is shown at once while it is made again behind.
FRESH = 15
_checked = {}    # (app, what) -> (when, found)
_checking = {}   # (app, what) -> the check being made again now


async def remembered(state, what, check, fresh=False):
    """`check()`'s answer, from the last FRESH seconds or made now; `fresh` asks it now whatever was found before."""
    key, now = (id(state), what), time.time()
    hit = _checked.get(key)
    if hit and not fresh:
        if now - hit[0] >= FRESH and key not in _checking:
            _checking[key] = asyncio.ensure_future(_check(key, check))
        return hit[1]
    return await _check(key, check)


async def _check(key, check):
    try:
        found = await check()
        _checked[key] = (time.time(), found)
        return found
    finally:
        _checking.pop(key, None)


def forget(state, what):
    """Drop what a check found, so the next one is made now (after its server was changed)."""
    _checked.pop((id(state), what), None)


def _mark(seen, online):
    """Note whether a server answered, and since when that has been so."""
    if seen["online"] is not online:
        seen.update(online=online, since=time.time())


async def render_server(state, fresh=False):
    """The render server (ComfyUI): whether it answers, since when as far as this app has seen, and what it reports."""
    return dict(await remembered(state, "render:" + state.comfy.url, lambda: _render_server(state), fresh))


async def _render_server(state):
    try:
        stats = await state.comfy.stats()
        state.saw_server(True)
        found = dict(stats, online=True, url=state.comfy.url)
    except (httpx.HTTPError, ValueError):
        state.saw_server(False)
        found = {"online": False, "url": state.comfy.url}
    found["since"] = state.server_seen["since"]   # no earlier than the app's start
    return found


async def model_server(state, fresh=False):
    """The agent's model server (Ollama): whether it answers, its version, and the models it holds in memory now.
    `online` is None when the studio has none (an empty ollama_url)."""
    return dict(await remembered(state, "model:" + state.agent.url, lambda: _model_server(state), fresh))


async def _model_server(state):
    agent = state.agent
    if not agent.url:
        return {"online": None, "url": "", "loaded": []}
    try:
        version = (await agent.http.get(agent.url + "/api/version", timeout=5)).json().get("version", "")
        loaded = (await agent.http.get(agent.url + "/api/ps", timeout=5)).json().get("models") or []
        _mark(state.model_seen, True)
        found = {"online": True, "version": version, "loaded": [
            {"name": m.get("name", ""), "size": m.get("size") or 0, "vram": m.get("size_vram") or 0, "until": m.get("expires_at")}
            for m in loaded]}
    except (httpx.HTTPError, ValueError, AttributeError):
        _mark(state.model_seen, False)
        found = {"online": False, "loaded": []}
    return dict(found, url=agent.url, since=state.model_seen["since"])


def problem(key, level, text, tab):
    """`level`: critical, serious or warning. `tab`: the console's section that deals with it."""
    return {"key": key, "level": level, "text": text, "tab": tab}


async def problems(state, render=None, model=None):
    """What is wrong now with the servers, the disk, the backups and the queue, the worst first. `render` and `model`
    are what render_server and model_server found, when the caller has asked already."""
    db, now = state.db, time.time()
    render = render or await render_server(state)
    model = model or await model_server(state)
    found = []
    if not render["online"]:
        found.append(problem("render", "critical", "The render server has not answered at {} since {}. No renders can run.".format(
            render["url"], clock(render["since"])), "system"))
    if model["online"] is False:
        found.append(problem("model", "serious", "The agent's model server has not answered at {} since {}. The agent can't plan "
                                                 "and image prompts get no captions.".format(model["url"], clock(model["since"])), "system"))
    state.output_dir.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(state.output_dir)   # finished work is what fills a disk
    if disk.free < 10 * 1024 ** 3:
        found.append(problem("disk", "serious", "Only {:.1f} GB of disk space is left for storage.".format(disk.free / 1024 ** 3), "system"))
    saved = backup.newest(state.backup_dir)
    if state.settings.backup_keep > 0 and (saved is None or saved < now - 2 * DAY):
        found.append(problem("backup", "serious", "The database has not been backed up for two days. Check the folder {}.".format(
            state.backup_dir), "system"))
    checked = backup.last_check(db)
    if state.settings.backup_keep > 0 and checked and checked.get("copy") and not checked.get("ok"):
        found.append(problem("backup_check", "serious", "The newest backup, {}, can't be read back: {}".format(
            checked["copy"], checked.get("detail", "")), "system"))
    burst = db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'failed' AND finished > ?", (now - 900,))["n"]
    if burst >= 3:
        found.append(problem("failures", "serious", "{} jobs failed in the last 15 minutes.".format(burst), "jobs"))
    if not state.jobs.paused():   # paused, they wait on purpose
        stuck = db.one("SELECT COUNT(*) n FROM jobs WHERE status = 'queued' AND created < ?", (now - 3600,))["n"]
        if stuck:
            found.append(problem("waiting", "warning", "{} job{} been waiting for over an hour.".format(
                stuck, " has" if stuck == 1 else "s have"), "jobs"))
    for job in db.all("SELECT name, started, est_seconds FROM jobs WHERE status = 'running' AND started IS NOT NULL"):
        if now - job["started"] > max(1800, 3 * (job["est_seconds"] or 0)):
            found.append(problem("slow", "warning", "\"{}\" has been running for {}, far longer than it should.".format(
                job["name"], minutes(now - job["started"])), "jobs"))
            break
    return found


def maintenance(db):
    """Maintenance mode, while it is on: {text, since}. New jobs are refused (jobs.JobManager.add); the waiting ones
    still run, and the studio shows its message."""
    try:
        found = json.loads(db.setting("maintenance", "") or "{}")
    except ValueError:
        return None
    return found if found.get("since") else None


class Watcher:
    """Checks every minute, opens an alert for a problem found CONFIRM checks in a row, closes one no longer found, and
    sends each change to the admins' phones and the console's open pages."""

    def __init__(self, state):
        self.state = state
        self.streak = {}   # problem key -> checks in a row it was found in
        self.http = httpx.AsyncClient(timeout=10)

    async def step(self, found, now=None):
        """One check's problems in; the messages it sent out, as (level, text)."""
        db, now = self.state.db, now or time.time()
        current = {p["key"]: p for p in found}
        self.streak = {key: self.streak.get(key, 0) + 1 for key in current}
        opened = {a["key"]: a for a in db.all("SELECT * FROM alerts WHERE ended IS NULL")}
        messages = []
        for key, p in current.items():
            if key in opened:
                db.run("UPDATE alerts SET text = ? WHERE id = ?", (p["text"], opened[key]["id"]))   # its numbers move on
            elif self.streak[key] >= CONFIRM:
                db.run("INSERT INTO alerts (key, level, text, tab, started) VALUES (?, ?, ?, ?, ?)",
                       (key, p["level"], p["text"], p["tab"], now))
                messages.append((p["level"], p["text"]))
        for key, a in opened.items():
            if key not in current:
                db.run("UPDATE alerts SET ended = ? WHERE id = ?", (now, a["id"]))
                messages.append(("resolved", "{} (after {}).".format(RESOLVED.get(key, "Resolved: " + a["text"]), minutes(now - a["started"]))))
        for level, text in messages:
            await phone.send(self.http, db, level, text)
        if messages:
            self.state.hub.tell({"alerts": len(db.all("SELECT id FROM alerts WHERE ended IS NULL")),
                                 "news": [{"level": level, "text": text} for level, text in messages]})
        return messages

    async def workflows(self, found):
        """Note what the render PC changed in the workflow files, and fetch its node list again when it answers and the
        one in hand is old: the console's Workflows section compares the workflows with it."""
        versions.look(self.state)
        self.state.traces.prune()
        checked = backup.last_check(self.state.db)
        if self.state.settings.backup_keep > 0 and (not checked or checked["when"] < time.time() - DAY):   # once a day
            await asyncio.to_thread(backup.check, self.state.db, self.state.backup_dir)
        catalog = self.state.catalog
        saved = catalog.nodes_saved()
        if not any(p["key"] == "render" for p in found) and (saved is None or time.time() - saved > versions.NODES_STALE):
            try:
                await catalog.refresh_nodes()
            except (httpx.HTTPError, ValueError, OSError):
                pass

    async def run_forever(self):
        await asyncio.sleep(FIRST_CHECK)
        try:
            while True:
                try:
                    found = await problems(self.state, await render_server(self.state, fresh=True),   # asked now: alerts
                                           await model_server(self.state, fresh=True))
                    await self.step(found)
                    await self.workflows(found)
                except Exception as error:   # a check that fails must not stop the next one
                    print("The health check failed: {}".format(error))
                await asyncio.sleep(CHECK_EVERY)
        finally:
            await self.http.aclose()
