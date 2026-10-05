"""The workflow catalog: every workflow file under workflows/<kind>/, read fresh on each request."""

import asyncio
import json
import time

import httpx

from .comfy import workflows

KINDS = ("video", "image", "audio")
# The folders of workflows/. An upscaler makes nothing from a prompt: it takes a video the user has and returns it
# larger, so it is its own action in the studio and is left out of the Create page and the agent's workflows.
FOLDERS = (*KINDS, "upscaler")


class Catalog:
    def __init__(self, directory, comfy, cache_file=None):
        self.directory = directory
        self.comfy = comfy
        self.object_info = None
        self.tried = 0.0
        # The node definitions from the last time ComfyUI answered, so workflows stay readable while it is off.
        self.cache_file = cache_file
        self.saved = None
        if cache_file and cache_file.is_file():
            try:
                self.saved = json.loads(cache_file.read_text(encoding="utf-8"))
            except ValueError:
                pass
        self.lock = asyncio.Lock()  # several requests may need the node definitions at once: fetch them once

    def files(self):
        """Workflow id ("video/h3_director") -> path."""
        found = {}
        for kind in FOLDERS:
            folder = self.directory / kind
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json"), key=lambda p: p.name.lower()):
                if not path.name.endswith(".studio.json"):
                    found["{}/{}".format(kind, path.stem)] = path
        return found

    def forget_nodes(self):
        self.object_info, self.tried = None, 0.0

    async def load(self, workflow_id):
        path = self.files().get(workflow_id)
        if path is None:
            raise workflows.WorkflowError("There is no workflow named '{}'.".format(workflow_id))
        try:
            wf = workflows.load_workflow(path, self.object_info or self.saved, workflow_id)
            if not wf["approximate"]:
                return wf
            error = None
        except workflows.WorkflowError as e:
            if not e.needs_info:
                raise
            wf, error = None, e
        # The file alone wasn't enough. Ask ComfyUI how its nodes are defined (at most once a minute).
        async with self.lock:
            if self.object_info is None and time.time() - self.tried > 60:
                self.tried = time.time()
                try:
                    self.object_info = self.saved = await self.comfy.object_info()
                    if self.cache_file:
                        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                        self.cache_file.write_text(json.dumps(self.object_info), encoding="utf-8")
                except (httpx.HTTPError, ValueError, OSError):
                    pass
        if self.object_info is not None:
            return workflows.load_workflow(path, self.object_info, workflow_id)
        if wf is None:
            raise error
        return wf

    async def listing(self):
        items = []
        for workflow_id in self.files():
            kind, name = workflow_id.split("/", 1)
            item = {"id": workflow_id, "kind": kind, "title": name.replace("_", " "), "description": ""}
            try:
                profile = (await self.load(workflow_id))["profile"]
                item["title"] = profile.get("title") or item["title"]
                item["description"] = profile.get("description", "")
            except workflows.WorkflowError as e:
                item["error"] = str(e)
            items.append(item)
        return items
