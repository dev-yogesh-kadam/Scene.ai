"""The generation queue, shared by all users, with live progress: one render at a time on each ComfyUI server, each
waiting render going to the first server that is free (endpoints.py). Edits and motion
graphics, which are made on this machine, are jobs too and have a lane of their own (see edits.py).

A job is either one render, or a chain: several clips where each one starts on the last frame of the
clip before it, joined into one video at the end.
"""

import asyncio
import copy
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import websockets
from fastapi import HTTPException

from . import edits, errors, gpu, health, media, memory, moderation, motion, sequence, sharing
from .comfy import workflows
from .agent import AgentError
from .comfy.client import ComfyError
from .db import as_everyone

VIDEO_TYPES = {".mp4", ".webm", ".mov", ".mkv", ".gif"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_TYPES = {".mp3", ".flac", ".wav", ".opus", ".ogg", ".m4a"}
TEXT_TYPES = {".json", ".srt", ".txt"}   # a transcript, a list of times: filed as "text"
CLIP_BREAK = re.compile(r"^\s*-{3,}\s*$", re.M)  # a line of dashes separates per-clip prompts
RESUMES = 3          # times a render cut off by the render server going away goes back in the queue before it fails
JUST_FINISHED = 300  # seconds a finished job stays in its owner's list whatever came after it (the canvas waits for its result)
OFFLINE_CHECK = 10  # seconds between asking whether the render server answers again, while renders wait for it


class Cancelled(Exception):
    pass


class Closed(HTTPException):
    """A new job refused while the studio is under maintenance (health.maintenance). It is an HTTP answer (503), so a
    route that adds a job says it as it says any refusal, and so does the agent, which reads its steps' refusals."""

    def __init__(self, text):
        super().__init__(503, text)


class JobManager:
    def __init__(self, db, comfy, catalog, credits, outputs, notify, tmp_dir, node_path="", assets_dir=None):
        self.db = db
        self.assets_dir = Path(assets_dir) if assets_dir else None   # where a result kept for reuse is copied as an asset
        self.node_path = node_path      # the Node.js program that renders motion graphics
        self.comfy = comfy        # the main ComfyUI server, where uploaded files are put
        self.pool = None          # every ComfyUI server a render may go to (endpoints.ComfyPool; main.py sets it)
        self.working = set()      # the renders running now, each on its own server
        self.catalog = catalog
        self.credits = credits
        self.outputs = outputs          # where each user's finished work goes
        self.tmp_dir = Path(tmp_dir)    # working files of chained videos
        self.notify = notify      # notify(user_id, library_changed=False)
        self.live = {}            # job id -> progress of the running job (not stored)
        self.gpu = gpu.Gate(lambda: False)   # the GPU it may share with the agent's model (main.py sets the real one)
        self.agent = None         # the agent's model, which writes the captions some image models need (main.py sets it)
        self.wake = asyncio.Event()
        self.hold_offline = True    # renders wait for the render server instead of failing (settings.hold_queue_offline)
        self.server_down = False    # the render server did not answer the last time a render was about to start
        # A job that was running when the app stopped can't be picked up again. Waiting jobs stay queued.
        for job in db.all("SELECT id, user_id, cost FROM jobs WHERE status = 'running'"):
            db.run("UPDATE jobs SET status = 'failed', error = ?, finished = ? WHERE id = ?",
                   ("The app was restarted before this job finished.", time.time(), job["id"]))
            self._refund(job)

    # ------------------------------------------------------------ public

    def snapshot(self, user_id):
        now = time.time()
        # A job waits only behind the jobs of its own lane: renders behind renders, edits behind edits.
        waiting, busy = {True: [], False: []}, {True: 0, False: 0}
        servers = max(1, len(self.pool.servers())) if self.pool else 1
        with as_everyone():   # where the user's jobs stand in the queue depends on everyone's
            queue = self.db.all("SELECT id, workflow, status FROM jobs WHERE status IN ('queued', 'running') ORDER BY priority DESC, created")
        for r in queue:
            if r["status"] == "running":
                busy[edits.is_edit(r["workflow"])] += 1
            else:
                waiting[edits.is_edit(r["workflow"])].append(r["id"])
        jobs = []
        # The latest 40, and however many more are waiting, running or just finished: the canvas holds each one's place
        # until what it made comes in, so a job left off this list would see its result land at the bottom instead.
        for row in self.db.all(
                "SELECT * FROM jobs WHERE user_id = ? AND hidden = 0 AND (status IN ('queued', 'running') OR finished > ? "
                "OR id IN (SELECT id FROM jobs WHERE user_id = ? AND hidden = 0 ORDER BY created DESC LIMIT 40)) "
                "ORDER BY created DESC", (user_id, now - JUST_FINISHED, user_id)):
            live = self.live.get(row["id"], {})
            row["settings"] = json.loads(row["settings"])
            lane = edits.is_edit(row["workflow"])
            row.update(step=live.get("step", 0), steps=live.get("steps", 0), node=live.get("node", ""),
                       clip=live.get("clip", 0), clips=live.get("clips", 0), eta_seconds=self._eta(row, live, now),
                       position=(waiting[lane].index(row["id"]) + busy[lane]) // (1 if lane else servers) + 1
                       if row["id"] in waiting[lane] else None)
            if row["status"] == "queued" and self.server_down and not edits.is_edit(row["workflow"]):
                row["waiting_for_server"] = True   # the render server is off: it waits for it, and says so
            if row["status"] == "failed":   # why, in words its owner reads (the canvas shows a failed job)
                row["reason"] = errors.for_user(row["error"])
            del row["hidden"], row["user_id"]
            jobs.append(row)
        return jobs

    def add(self, user_id, name, workflow_id, settings, summary, est_seconds, cost=0, project_id=None, seconds=None,
            during_maintenance=False):
        """`cost` has already been taken from the user: it is held for the job until it finishes or is refunded.
        `seconds` is the length of the result that was asked for, which is what the price is based on.
        Under maintenance it is refused, and what was taken for it is given back, unless it is `during_maintenance`
        (an admin's test run, which is what maintenance is for)."""
        closed = health.maintenance(self.db)
        if closed and not during_maintenance:
            if cost:
                self.credits.add(user_id, cost, "refund", note="Maintenance")
            raise Closed(closed["text"])
        if moderation.refusal(self.db, user_id, settings):   # a prompt with words the studio does not make
            if cost:
                self.credits.add(user_id, cost, "refund", note="Prompt refused")
            raise HTTPException(400, "This prompt can't be made here. Change its words and try again.")
        job_id = uuid.uuid4().hex[:12]
        self.db.run(
            "INSERT INTO jobs (id, user_id, name, workflow, kind, settings, summary, status, est_seconds, cost, "
            "credits_required, credits_reserved, seconds_requested, project_id, run, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, user_id, name, workflow_id, workflow_id.split("/", 1)[0], json.dumps(settings), summary,
             est_seconds, cost, cost, cost, seconds, project_id, str(settings.get("run_of") or settings.get("run") or "")[:32], time.time()))
        self.wake.set()
        self.notify(user_id)
        return job_id

    def remove(self, user_id, job_id):
        """Cancel a waiting or running job, or take a finished one off the list."""
        job = self.db.one("SELECT id, user_id, status, cost FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
        if job is None:
            return False
        if job["status"] == "queued":
            self.db.run("UPDATE jobs SET status = 'cancelled', finished = ? WHERE id = ?", (time.time(), job_id))
            self._refund(job)
        elif job["status"] == "running":
            self.live.setdefault(job_id, {})["cancel"] = True  # the worker interrupts ComfyUI on its next check
        else:
            self.db.run("UPDATE jobs SET hidden = 1 WHERE id = ?", (job_id,))
        self.notify(user_id)
        return True

    async def run_forever(self, local=False):
        """Take the waiting jobs of one lane, oldest first. There are two lanes, each with its own worker: renders,
        one at a time on each ComfyUI server, and edits (`local`), one at a time, which are made on this machine and
        so never wait behind a render."""
        mine = "workflow LIKE 'edit/%'" if local else "workflow NOT LIKE 'edit/%'"
        while True:
            # An admin can pause the renders (while the render server is being restarted, say). Edits keep running.
            if not local and self.paused():
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), 5)
                except asyncio.TimeoutError:
                    pass
                continue
            job = self.db.one("SELECT * FROM jobs WHERE status = 'queued' AND {} ORDER BY priority DESC, created LIMIT 1".format(mine))
            if job is None:
                self.wake.clear()
                await self.wake.wait()
                continue
            # Each render goes to a ComfyUI server that is free. When none is (all are busy), it waits for one to finish.
            # When none answers (turned off, restarting, its network gone), the renders wait for one, and their owners
            # are told so, instead of each one failing in turn. They are asked again every few seconds.
            server = None
            if not local:
                server, alive = await self._free_server()
                down = server is None and not alive
                if down != self.server_down:
                    self.server_down = down
                    self._notify_all_waiting(None)
                if server is None:
                    self.wake.clear()
                    try:
                        await asyncio.wait_for(self.wake.wait(), OFFLINE_CHECK)
                    except asyncio.TimeoutError:
                        pass
                    continue
            job["settings"] = json.loads(job["settings"])
            job["started"] = time.time()
            self.live[job["id"]] = {"step": 0, "steps": 0, "titles": {}}
            # The machine it runs on, as the Pricing section names it (what it draws is costed by that name): the main
            # render server is the machine that renders, another server is named as its row in Servers & APIs.
            main = server is None or server["url"] == self.comfy.url
            if main:
                found = self.db.one("SELECT name FROM servers WHERE renders = ? AND active = 1 ORDER BY id LIMIT 1", (0 if local else 1,))
                name = found["name"] if found else ""
            else:
                name = server["name"]
            if server is not None:
                self.live[job["id"]]["comfy"] = self.pool.client(server["url"]) if self.pool else self.comfy
            self.db.run("UPDATE jobs SET status = 'running', started = ?, server = ? WHERE id = ?",
                        (job["started"], name, job["id"]))
            self._notify_all_waiting(job["user_id"])
            if local:
                await self._work(job, local)
                continue
            # The render runs on its own while the next waiting one looks for another free server.
            if self.pool:
                self.pool.busy[server["url"]] = job["id"]
            task = asyncio.ensure_future(self._work(job, local, server["url"]))
            self.working.add(task)
            task.add_done_callback(self.working.discard)

    async def _free_server(self):
        """(a free ComfyUI server {"name", "url"} or None, whether any answers or runs a render)."""
        if self.pool is None:   # one server: free when nothing of the studio runs on it
            if self.working:
                return None, True
            up = not self.hold_offline or await self._render_server_up()
            return ({"name": "", "url": self.comfy.url} if up else None), up
        async def answers(url):   # the main server is asked as it always was
            return await (self._render_server_up() if url == self.comfy.url else self.pool.answers(url))
        return await self.pool.free(answers if self.hold_offline else None)

    async def _work(self, job, local, url=None):
        """Run one job that was taken from the queue, and record how it ended."""
        try:
            await self._finish(job, local)
        finally:
            if url is not None and self.pool:
                self.pool.busy.pop(url, None)
            self.wake.set()   # its server is free again

    async def _finish(self, job, local):
        status, error = "done", None
        try:
            if not local and isinstance(job["settings"].get("caption"), dict):
                await self._captions(job)
            await self._run(job)
        except Cancelled:
            status = "cancelled"
        except (ComfyError, workflows.WorkflowError, media.MediaError, motion.MotionError, sequence.SequenceError) as e:
            status, error = "failed", str(e)
        except httpx.HTTPError as e:
            status, error = "failed", "Lost the connection to ComfyUI ({}).".format(e or type(e).__name__)
            # The render server went away while it ran: back to the front of the queue, its credits still held, to
            # run again when a server answers. After RESUMES times it fails, as anything else would.
            if not local and self.hold_offline and (job.get("resumes") or 0) < RESUMES:
                status = "resumed"
        except Exception as e:  # keep the queue alive whatever one job does
            status, error = "failed", "{}: {}".format(type(e).__name__, e)
        self.live.pop(job["id"], None)
        if status == "resumed":
            self.db.run("UPDATE jobs SET status = 'queued', started = NULL, error = '', resumes = resumes + 1, "
                        "priority = CASE WHEN priority < 50 THEN 50 ELSE priority END WHERE id = ?", (job["id"],))
            self.notify(job["user_id"])
            self._notify_all_waiting(None)
            return
        self.db.run("UPDATE jobs SET status = ?, error = ?, finished = ? WHERE id = ?",
                    (status, error, time.time(), job["id"]))
        if status == "done":
            self.db.run("UPDATE jobs SET credits_reserved = 0, credits_consumed = cost, output_size = "
                        "(SELECT SUM(size) FROM generations WHERE job_id = jobs.id) WHERE id = ?", (job["id"],))
        else:
            self._refund(job)
        self.notify(job["user_id"], library_changed=status == "done")
        if status == "done" and job.get("project_id"):   # the others in a shared project see it on their canvas too
            for person in sharing.people_of(self.db, job["project_id"]):
                if person != job["user_id"]:
                    self.notify(person, library_changed=True)
        self._notify_all_waiting(None)

    async def _render_server_up(self):
        try:
            await self.comfy.stats()
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def paused(self):
        return self.db.setting("queue_paused", "0") == "1"

    def pause(self, paused):
        self.db.set_setting("queue_paused", "1" if paused else "0")
        self.wake.set()
        self._notify_all_waiting(None)

    def to_front(self, job_id):
        """Put a waiting job ahead of every other waiting job."""
        with as_everyone():
            top = self.db.one("SELECT MAX(priority) n FROM jobs WHERE status = 'queued'")["n"] or 0
            self.db.run("UPDATE jobs SET priority = ? WHERE id = ? AND status = 'queued'", (top + 1, job_id))
        self._notify_all_waiting(None)

    def _refund(self, job):
        """Give back what was held for a job that did not finish."""
        self.credits.add(job["user_id"], job["cost"], "refund", job["id"])
        self.db.run("UPDATE jobs SET credits_reserved = 0, credits_refunded = cost WHERE id = ?", (job["id"],))

    # ------------------------------------------------------------ one job

    async def _run_edit(self, job):
        """An edit or a motion graphic, made on this machine. It reports no steps; a cancel stops it within a second."""
        live = self.live[job["id"]]
        work = asyncio.ensure_future(edits.run(job, self.outputs.folder(job["user_id"]), self.db, self.node_path, self.tmp_dir))
        while not work.done():
            await asyncio.wait([work], timeout=1)
            if live.get("cancel") and not work.done():
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                raise Cancelled()
        made = work.result()
        if made[0][2]["duration"]:
            job["summary"] = "{} · {:.0f} s".format(job["summary"], made[0][2]["duration"])
            self.db.run("UPDATE jobs SET summary = ? WHERE id = ?", (job["summary"], job["id"]))
        for target, kind, ctx in made:
            self._record(job, kind, target, ctx)

    async def _captions(self, job):
        """Write the structured caption this job needs (an image model such as Ideogram is trained on them), and those of
        every render waiting with one, in one go: the agent's model is loaded once for them all, and the renders after
        it run one after another with the image model loaded. A caption that cannot be written fails its own job only."""
        live = self.live[job["id"]]
        with as_everyone():
            rows = self.db.all("SELECT id, user_id, settings FROM jobs WHERE status = 'queued' AND settings LIKE ?", ('%"caption": {%',))
        todo = [(job["id"], job["settings"])] + [(r["id"], json.loads(r["settings"])) for r in rows if r["id"] != job["id"]]

        def waiting():
            live["node"] = "Waiting for the GPU…"
            self.notify(job["user_id"])
        live["node"] = "Writing the caption…"
        self.notify(job["user_id"])
        if self.agent is None:
            raise ComfyError("This model needs a structured caption, which the agent writes, and there is no agent here.")
        async with self.gpu.use("llm", waiting, stop=lambda: live.get("cancel")):
            for job_id, settings in todo:
                rule = settings.get("caption")
                if not isinstance(rule, dict):
                    continue
                try:
                    caption = await self.agent.caption(rule["template"], str(settings.get("prompt") or ""), str(rule.get("ratio") or "auto"))
                except AgentError as error:
                    if job_id == job["id"]:
                        raise ComfyError("This model needs a structured caption, which the agent writes from your prompt. {}".format(error))
                    continue   # that job tries again when its turn comes
                settings.setdefault("values", {})[rule["prompt"]] = caption
                settings.pop("caption", None)
                with as_everyone():
                    self.db.run("UPDATE jobs SET settings = ? WHERE id = ?", (json.dumps(settings), job_id))
        live["node"] = ""

    async def _run(self, job):
        if edits.is_edit(job["workflow"]):
            return await self._run_edit(job)
        live = self.live[job["id"]]
        # On a GPU shared with the agent's model, a render waits while the agent thinks, and the model is put out of
        # the GPU before the render starts.
        def waiting():
            live["node"] = "Waiting for the GPU: the agent is thinking"
            self.notify(job["user_id"])
        live.setdefault("comfy", self.comfy)
        if live["comfy"] is not self.comfy:   # another server: no GPU shared with the agent there, but the files to send
            live["node"] = "Sending the files it needs"
            self.notify(job["user_id"])
            await self._send_inputs(job["settings"], live["comfy"])
            live["node"] = ""
            return await self._render_job(job, live)
        try:
            async with self.gpu.use("render", waiting, stop=lambda: live.get("cancel")):
                live["node"] = ""
                await self._render_job(job, live)
        except gpu.Stopped:
            raise Cancelled()

    async def _send_inputs(self, settings, comfy):
        """Copy the uploaded files a render uses from the main server to the one it runs on, under the same names."""
        names = set()
        def walk(value):
            if isinstance(value, dict):
                if isinstance(value.get("comfy_name"), str):
                    names.add(value["comfy_name"])
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
        walk(settings)
        for name in sorted(names):
            folder, _, base = name.rpartition("/")
            response = await self.comfy.view(base, folder, "input")
            try:
                if response.status_code >= 400:
                    raise ComfyError("The file {} is not on the main render server any more.".format(name))
                data = await response.aread()
            finally:
                await response.aclose()
            await comfy.upload(base, data, response.headers.get("content-type"), subfolder=folder)

    async def _render_job(self, job, live):
        wf = await self.catalog.load(job["workflow"])
        schema = workflows.describe(wf)
        clips = workflows.clip_count(schema, job["settings"])
        client_id = uuid.uuid4().hex
        listener = asyncio.create_task(self._listen(job, live, client_id))
        try:
            if clips > 1:
                await self._run_chain(job, live, wf, schema, clips, client_id)
                return
            entry, ctx = await self._render(job, live, wf, job["settings"], client_id)
        finally:
            listener.cancel()

        folder, stem = self._target(job)
        saved = 0
        outputs = list(_outputs(entry))
        labels = _output_labels(wf, outputs)
        for (item, kind, suffix), label in zip(outputs, labels):
            target = folder / "{}{}{}".format(stem, "_{}".format(saved + 1) if saved else "", suffix)
            await self._fetch(item, target, comfy=live["comfy"])
            # What the form did not say about the result is read from the file: the frame of a picture
            # (the canvas draws it at its true proportions) and the length of a sound.
            found = await media.probe(target)
            if kind == "audio":
                ctx = dict(ctx, duration=round(found["seconds"], 1))
            elif kind == "text":
                pass   # nothing to read from a transcript's file
            elif found["width"] and not ctx.get("width"):
                ctx = dict(ctx, width=found["width"], height=found["height"])
            self._record(job, kind, target, dict(ctx, output=label) if label else ctx,
                         name="{} · {}".format(job["name"], label)[:120] if label else None)
            saved += 1
        if not saved:
            raise ComfyError("ComfyUI finished but saved no image, video or sound. Does the workflow have a Save node?")

    async def _run_chain(self, job, live, wf, schema, clips, client_id):
        settings, slots = job["settings"], schema["slots"]
        roles = {c["role"]: c for c in schema["controls"] if c["role"]}
        full_ctx = workflows.context(schema, settings)
        prompt = str((settings.get("values") or {}).get(roles["prompt"]["id"], roles["prompt"]["default"]) or "")
        prompts = [p.strip() for p in CLIP_BREAK.split(prompt) if p.strip()] or [prompt]
        refs = dict(settings.get("refs") or {})
        seed = None
        if schema["seeded"]:  # one seed for the whole video, stepped per clip so the clips differ
            seed = full_ctx["seed"] = workflows.job_seed(wf, settings, schema)

        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.tmp_dir) as tmp:
            tmp = Path(tmp)
            voice, voice_start = None, 0.0
            if slots.get("voice_track") in refs:
                voice = tmp / "voice{}".format(Path(refs[slots["voice_track"]]["comfy_name"]).suffix or ".wav")
                await self._fetch({"filename": refs[slots["voice_track"]]["comfy_name"]}, voice, kind="input")
                voice_seconds = (await media.probe(voice))["seconds"]

            parts, previous = [], None
            for i in range(clips):
                live.update(clip=i + 1, clips=clips, step=0, steps=0, node="")
                live.pop("first_step", None)
                self.notify(job["user_id"])
                clip_settings = copy.deepcopy(settings)
                clip_settings["values"] = dict(settings.get("values") or {})
                clip_settings["values"][roles["prompt"]["id"]] = prompts[min(i, len(prompts) - 1)]
                if seed is not None:
                    clip_settings.update(seed_mode="fixed", seed=seed + i)
                clip_refs = dict(refs)
                if previous:
                    clip_refs[slots["first_frame"]] = {"comfy_name": previous, "name": "end of clip {}".format(i)}
                if i < clips - 1:
                    clip_refs.pop(slots.get("last_frame"), None)  # only the final clip ends on the last-frame image
                if voice:
                    clip_refs.pop(slots["voice_track"], None)
                    if voice_start < voice_seconds - 0.2:
                        piece = await media.cut_audio(voice, voice_start, full_ctx["duration"] + 0.5, tmp / "voice_{}.wav".format(i))
                        name = await live["comfy"].upload("scene_chain_{}_{}.wav".format(job["id"], i), piece.read_bytes(), "audio/wav")
                        clip_refs[slots["voice_track"]] = {"comfy_name": name, "name": "voice part {}".format(i + 1)}
                clip_settings["refs"] = clip_refs

                entry, _ = await self._render(job, live, wf, clip_settings, client_id)
                video = next((item for item, kind, _ in _outputs(entry) if kind == "video"), None)
                if video is None:
                    raise ComfyError("ComfyUI finished clip {} but saved no video.".format(i + 1))
                part = tmp / "clip_{}{}".format(i, Path(video["filename"]).suffix)
                await self._fetch(video, part, comfy=live["comfy"])
                parts.append(part)
                # Where the next clip's sound starts: this clip's length, minus the one frame the two clips share.
                voice_start += (await media.probe(part))["seconds"] - (1 / media.FPS if i else 0)
                if i < clips - 1:
                    frame = await media.last_frame(part, tmp / "frame_{}.png".format(i))
                    previous = await live["comfy"].upload("scene_chain_{}_{}.png".format(job["id"], i), frame.read_bytes(), "image/png")

            live.update(node="Joining the clips", step=0, steps=0)
            self.notify(job["user_id"])
            folder, stem = self._target(job)
            target = folder / (stem + ".mp4")
            await media.join(parts, target)
        self._record(job, "video", target, full_ctx)

    async def _render(self, job, live, wf, settings, client_id):
        """Run one graph on ComfyUI and wait for it. Returns (history entry, context)."""
        prompt, ctx = workflows.build_prompt(wf, dict(settings, clips=1))
        live["titles"] = {nid: n.get("_meta", {}).get("title") or n["class_type"] for nid, n in prompt.items()}
        live["prompt_id"] = await live["comfy"].queue(prompt, client_id)
        failures = 0
        while True:
            await asyncio.sleep(2)
            if live.get("cancel"):
                await live["comfy"].cancel(live["prompt_id"])
                raise Cancelled()
            try:
                found = await live["comfy"].history(live["prompt_id"])
                failures = 0
            except httpx.HTTPError:
                failures += 1
                if failures > 30:
                    raise
                continue
            status = (found or {}).get("status", {})
            if status.get("status_str") == "error":
                raise ComfyError(_execution_error(status))
            if status.get("completed"):
                return found, ctx
            self.notify(job["user_id"])

    async def _listen(self, job, live, client_id):
        """Follow ComfyUI's websocket for step progress. Best effort: the job works without it."""
        while True:
            try:
                async with websockets.connect(live.get("comfy", self.comfy).ws_url(client_id), max_size=None) as ws:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue  # preview images
                        message = json.loads(raw)
                        data = message.get("data") or {}
                        if data.get("prompt_id") not in (None, live.get("prompt_id")):
                            continue
                        if message.get("type") == "progress":
                            now = time.time()
                            if data.get("max") != live["steps"] or data.get("value", 0) < live["step"]:
                                live["first_step"] = (now, data.get("value", 0))  # a new progress bar started
                            live.update(step=data.get("value", 0), steps=data.get("max", 0), step_time=now)
                        elif message.get("type") == "executing" and data.get("node"):
                            live["node"] = live["titles"].get(str(data["node"]), "")
                        else:
                            continue
                        self.notify(job["user_id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(3)

    # ------------------------------------------------------------ files

    def _target(self, job):
        folder = self.outputs.folder(job["user_id"]) / self.outputs.relative(job.get("project_id"))   # its project's folder
        folder.mkdir(parents=True, exist_ok=True)
        stem = "{}_{}".format(re.sub(r"[^\w.-]+", "_", job["name"]).strip("._") or "scene",
                              time.strftime("%Y%m%d_%H%M%S"))
        return folder, stem

    async def _fetch(self, item, target, kind="output", comfy=None):
        response = await (comfy or self.comfy).view(item["filename"], item.get("subfolder", ""), kind)
        try:
            response.raise_for_status()
            with open(target, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
        finally:
            await response.aclose()

    def _record(self, job, kind, target, ctx, name=None):
        if job.get("project_id") and not self.db.one("SELECT 1 FROM projects WHERE id = ?", (job["project_id"],)):
            media.remove_result(target)   # its project was deleted while it ran: nothing to file it in, nothing kept
            return
        # Its path inside the user's folder, in its project's folder (an edit writes at the top: it is moved there).
        filename = self.outputs.settle(job["user_id"], job.get("project_id"), target)
        target = self.outputs.folder(job["user_id"]) / filename
        item_id = self.db.run(
            "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
            "context, seconds, size, run, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job["user_id"], job["id"], job.get("project_id"), job["workflow"], kind, name or job["name"], filename,
             job["summary"], json.dumps(job["settings"]), json.dumps(ctx), round(time.time() - job["started"], 1),
             target.stat().st_size, str((job.get("settings") or {}).get("run") or ""), time.time()))
        if kind in ("image", "video"):   # its thumbnail, made now rather than when the canvas first asks for it
            try:
                asyncio.get_running_loop().create_task(media.make_poster_soon(target))
            except RuntimeError:
                pass
        # A step the agent planned as something to reuse ("keep": a character called Maya) goes into shared memory.
        keep = (job.get("settings") or {}).get("keep")
        if keep and item_id and self.assets_dir:
            try:
                memory.keep_made(self.db, self.assets_dir / str(job["user_id"]), job["user_id"], item_id, target, kind, keep)
            except OSError:
                pass   # the result is in the library either way; only its copy for reuse is missing

    # ------------------------------------------------------------ helpers

    def history(self):
        """Earlier runs, for time estimates."""
        with as_everyone():   # every user's runs: how long a workflow takes does not depend on who ran it
            rows = self.db.all("SELECT workflow, context, seconds FROM generations ORDER BY created DESC LIMIT 500")
        return [dict(r, context=json.loads(r["context"])) for r in rows]

    def _notify_all_waiting(self, also):
        users = {r["user_id"] for r in self.db.all("SELECT DISTINCT user_id FROM jobs WHERE status = 'queued'")}
        for user_id in users | ({also} if also else set()):
            self.notify(user_id)

    @staticmethod
    def _eta(job, live, now):
        if job["status"] != "running":
            return None
        clips, clip = live.get("clips") or 1, live.get("clip") or 1
        per_clip = (job.get("est_seconds") or 0) / clips
        first = live.get("first_step")
        if first and live.get("steps") and live["step"] > first[1]:
            per_step = (live["step_time"] - first[0]) / (live["step"] - first[1])
            current = max(0, per_step * (live["steps"] - live["step"]) - (now - live["step_time"]))
            return current + per_clip * (clips - clip)
        if job.get("est_seconds"):
            return max(0, job["est_seconds"] - (now - job["started"]))
        return None


def _outputs(entry):
    """The images, videos, sounds and texts a finished ComfyUI run saved: (item, kind, file suffix). Each item also
    says which node saved it ("node"), so a workflow with several outputs can tell them apart."""
    for node_id, node_output in (entry.get("outputs") or {}).items():
        for items in node_output.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "output" or not item.get("filename"):
                    continue
                suffix = Path(item["filename"]).suffix.lower()
                kind = "video" if suffix in VIDEO_TYPES else "image" if suffix in IMAGE_TYPES else \
                    "audio" if suffix in AUDIO_TYPES else "text" if suffix in TEXT_TYPES else None
                if kind:
                    yield dict(item, node=str(node_id)), kind, suffix


def _output_labels(wf, outputs):
    """What tells the outputs of one run apart, when it saved more than one: the title of the node that saved each
    ("VOICE STEM", "MUSIC AND EFFECTS STEM"), or its file type alone when one node saved several (a transcript's JSON
    and SRT). A run with one output needs none: [None]."""
    if len(outputs) < 2:
        return [None] * len(outputs)
    nodes = wf.get("nodes") or {}
    titles = [str(((nodes.get(item["node"]) or {}).get("_meta") or {}).get("title") or "").strip()[:60] for item, _, _ in outputs]
    labels = []
    for (item, kind, suffix), title in zip(outputs, titles):
        alone = title and titles.count(title) == 1
        labels.append(title if alone else suffix.lstrip(".").upper())
    return labels


def _execution_error(status):
    for kind, info in status.get("messages", []):
        if kind == "execution_error":
            return "ComfyUI error in node '{}': {}".format(info.get("node_type"), info.get("exception_message"))
        if kind == "execution_interrupted":
            return "The job was interrupted in ComfyUI."
    return "ComfyUI reported an error."
