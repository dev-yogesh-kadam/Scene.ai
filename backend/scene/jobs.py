"""The generation queue: one job at a time on the GPU, shared by all users, with live progress.

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

from . import media
from .comfy import workflows
from .comfy.client import ComfyError

VIDEO_TYPES = {".mp4", ".webm", ".mov", ".mkv", ".gif"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_TYPES = {".mp3", ".flac", ".wav", ".opus", ".ogg", ".m4a"}
CLIP_BREAK = re.compile(r"^\s*-{3,}\s*$", re.M)  # a line of dashes separates per-clip prompts


class Cancelled(Exception):
    pass


class JobManager:
    def __init__(self, db, comfy, catalog, credits, outputs, notify, tmp_dir):
        self.db = db
        self.comfy = comfy
        self.catalog = catalog
        self.credits = credits
        self.outputs = outputs          # where each user's finished work goes
        self.tmp_dir = Path(tmp_dir)    # working files of chained videos
        self.notify = notify      # notify(user_id, library_changed=False)
        self.live = {}            # job id -> progress of the running job (not stored)
        self.wake = asyncio.Event()
        # A job that was running when the app stopped can't be picked up again. Waiting jobs stay queued.
        for job in db.all("SELECT id, user_id, cost FROM jobs WHERE status = 'running'"):
            db.run("UPDATE jobs SET status = 'failed', error = ?, finished = ? WHERE id = ?",
                   ("The app was restarted before this job finished.", time.time(), job["id"]))
            self._refund(job)

    # ------------------------------------------------------------ public

    def snapshot(self, user_id):
        now = time.time()
        waiting = [r["id"] for r in self.db.all("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created")]
        busy = 1 if self.db.one("SELECT 1 FROM jobs WHERE status = 'running'") else 0
        jobs = []
        for row in self.db.all(
                "SELECT * FROM jobs WHERE user_id = ? AND hidden = 0 ORDER BY created DESC LIMIT 40", (user_id,)):
            live = self.live.get(row["id"], {})
            row["settings"] = json.loads(row["settings"])
            row.update(step=live.get("step", 0), steps=live.get("steps", 0), node=live.get("node", ""),
                       clip=live.get("clip", 0), clips=live.get("clips", 0), eta_seconds=self._eta(row, live, now),
                       position=waiting.index(row["id"]) + 1 + busy if row["id"] in waiting else None)
            del row["hidden"], row["user_id"]
            jobs.append(row)
        return jobs

    def add(self, user_id, name, workflow_id, settings, summary, est_seconds, cost=0, project_id=None, seconds=None):
        """`cost` has already been taken from the user: it is held for the job until it finishes or is refunded.
        `seconds` is the length of the result that was asked for, which is what the price is based on."""
        job_id = uuid.uuid4().hex[:12]
        self.db.run(
            "INSERT INTO jobs (id, user_id, name, workflow, kind, settings, summary, status, est_seconds, cost, "
            "credits_required, credits_reserved, seconds_requested, project_id, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
            (job_id, user_id, name, workflow_id, workflow_id.split("/", 1)[0], json.dumps(settings), summary,
             est_seconds, cost, cost, cost, seconds, project_id, time.time()))
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

    async def run_forever(self):
        while True:
            job = self.db.one("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created LIMIT 1")
            if job is None:
                self.wake.clear()
                await self.wake.wait()
                continue
            job["settings"] = json.loads(job["settings"])
            job["started"] = time.time()
            self.live[job["id"]] = {"step": 0, "steps": 0, "titles": {}}
            server = self.db.one("SELECT name FROM servers WHERE renders = 1 AND active = 1 ORDER BY id LIMIT 1")
            self.db.run("UPDATE jobs SET status = 'running', started = ?, server = ? WHERE id = ?",
                        (job["started"], server["name"] if server else "", job["id"]))
            self._notify_all_waiting(job["user_id"])
            status, error = "done", None
            try:
                await self._run(job)
            except Cancelled:
                status = "cancelled"
            except (ComfyError, workflows.WorkflowError, media.MediaError) as e:
                status, error = "failed", str(e)
            except httpx.HTTPError as e:
                status, error = "failed", "Lost the connection to ComfyUI ({}).".format(e or type(e).__name__)
            except Exception as e:  # keep the queue alive whatever one job does
                status, error = "failed", "{}: {}".format(type(e).__name__, e)
            self.live.pop(job["id"], None)
            self.db.run("UPDATE jobs SET status = ?, error = ?, finished = ? WHERE id = ?",
                        (status, error, time.time(), job["id"]))
            if status == "done":
                self.db.run("UPDATE jobs SET credits_reserved = 0, credits_consumed = cost, output_size = "
                            "(SELECT SUM(size) FROM generations WHERE job_id = jobs.id) WHERE id = ?", (job["id"],))
            else:
                self._refund(job)
            self.notify(job["user_id"], library_changed=status == "done")
            self._notify_all_waiting(None)

    def _refund(self, job):
        """Give back what was held for a job that did not finish."""
        self.credits.add(job["user_id"], job["cost"], "refund", job["id"])
        self.db.run("UPDATE jobs SET credits_reserved = 0, credits_refunded = cost WHERE id = ?", (job["id"],))

    # ------------------------------------------------------------ one job

    async def _run(self, job):
        live = self.live[job["id"]]
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
        for item, kind, suffix in _outputs(entry):
            target = folder / "{}{}{}".format(stem, "_{}".format(saved + 1) if saved else "", suffix)
            await self._fetch(item, target)
            # What the form did not say about the result is read from the file: the frame of a picture
            # (the canvas draws it at its true proportions) and the length of a sound.
            found = await media.probe(target)
            if kind == "audio":
                ctx = dict(ctx, duration=round(found["seconds"], 1))
            elif found["width"] and not ctx.get("width"):
                ctx = dict(ctx, width=found["width"], height=found["height"])
            self._record(job, kind, target, ctx)
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
        if "seed" in roles:  # one seed for the whole video, stepped per clip so the clips differ
            seed = int.from_bytes(os.urandom(6), "big") if settings.get("seed_mode") == "random" else int(float(
                (settings.get("values") or {}).get(roles["seed"]["id"], roles["seed"]["default"])))
            full_ctx["seed"] = seed

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
                    clip_settings["seed_mode"] = "fixed"
                    clip_settings["values"][roles["seed"]["id"]] = seed + i
                clip_refs = dict(refs)
                if previous:
                    clip_refs[slots["first_frame"]] = {"comfy_name": previous, "name": "end of clip {}".format(i)}
                if i < clips - 1:
                    clip_refs.pop(slots.get("last_frame"), None)  # only the final clip ends on the last-frame image
                if voice:
                    clip_refs.pop(slots["voice_track"], None)
                    if voice_start < voice_seconds - 0.2:
                        piece = await media.cut_audio(voice, voice_start, full_ctx["duration"] + 0.5, tmp / "voice_{}.wav".format(i))
                        name = await self.comfy.upload("scene_chain_{}_{}.wav".format(job["id"], i), piece.read_bytes(), "audio/wav")
                        clip_refs[slots["voice_track"]] = {"comfy_name": name, "name": "voice part {}".format(i + 1)}
                clip_settings["refs"] = clip_refs

                entry, _ = await self._render(job, live, wf, clip_settings, client_id)
                video = next((item for item, kind, _ in _outputs(entry) if kind == "video"), None)
                if video is None:
                    raise ComfyError("ComfyUI finished clip {} but saved no video.".format(i + 1))
                part = tmp / "clip_{}{}".format(i, Path(video["filename"]).suffix)
                await self._fetch(video, part)
                parts.append(part)
                # Where the next clip's sound starts: this clip's length, minus the one frame the two clips share.
                voice_start += (await media.probe(part))["seconds"] - (1 / media.FPS if i else 0)
                if i < clips - 1:
                    frame = await media.last_frame(part, tmp / "frame_{}.png".format(i))
                    previous = await self.comfy.upload("scene_chain_{}_{}.png".format(job["id"], i), frame.read_bytes(), "image/png")

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
        live["prompt_id"] = await self.comfy.queue(prompt, client_id)
        failures = 0
        while True:
            await asyncio.sleep(2)
            if live.get("cancel"):
                await self.comfy.cancel(live["prompt_id"])
                raise Cancelled()
            try:
                found = await self.comfy.history(live["prompt_id"])
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
                async with websockets.connect(self.comfy.ws_url(client_id), max_size=None) as ws:
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
        folder = self.outputs.folder(job["user_id"])
        folder.mkdir(parents=True, exist_ok=True)
        stem = "{}_{}".format(re.sub(r"[^\w.-]+", "_", job["name"]).strip("._") or "scene",
                              time.strftime("%Y%m%d_%H%M%S"))
        return folder, stem

    async def _fetch(self, item, target, kind="output"):
        response = await self.comfy.view(item["filename"], item.get("subfolder", ""), kind)
        try:
            response.raise_for_status()
            with open(target, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
        finally:
            await response.aclose()

    def _record(self, job, kind, target, ctx):
        self.db.run(
            "INSERT INTO generations (user_id, job_id, project_id, workflow, kind, name, filename, summary, settings, "
            "context, seconds, size, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job["user_id"], job["id"], job.get("project_id"), job["workflow"], kind, job["name"], target.name,
             job["summary"], json.dumps(job["settings"]), json.dumps(ctx), round(time.time() - job["started"], 1),
             target.stat().st_size, time.time()))

    # ------------------------------------------------------------ helpers

    def history(self):
        """Earlier runs, for time estimates."""
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
    """The images, videos and sounds a finished ComfyUI run saved: (item, kind, file suffix)."""
    for node_output in (entry.get("outputs") or {}).values():
        for items in node_output.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "output" or not item.get("filename"):
                    continue
                suffix = Path(item["filename"]).suffix.lower()
                kind = "video" if suffix in VIDEO_TYPES else "image" if suffix in IMAGE_TYPES else "audio" if suffix in AUDIO_TYPES else None
                if kind:
                    yield item, kind, suffix


def _execution_error(status):
    for kind, info in status.get("messages", []):
        if kind == "execution_error":
            return "ComfyUI error in node '{}': {}".format(info.get("node_type"), info.get("exception_message"))
        if kind == "execution_interrupted":
            return "The job was interrupted in ComfyUI."
    return "ComfyUI reported an error."
