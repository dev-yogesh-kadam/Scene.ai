"""The workflow catalog: every workflow file under workflows/<kind>/, read fresh on each request.

A workflow is <name>.json (the graph that runs: an API export, or ComfyUI's own save), with <name>.studio.json beside it
(its presets) and, when the file that runs is an API export, <name>.ui.json (the save to open in ComfyUI, never run).
A new file shows on the next request. workflows/archive and workflows/reports are never read."""

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
                if not path.name.endswith((".studio.json", ".ui.json")):
                    found["{}/{}".format(kind, path.stem)] = path
        return found

    def sidecar_of(self, path):
        """The presets file of a workflow file: <name>.studio.json beside it."""
        return path.with_name(path.stem + ".studio.json")

    def forget_nodes(self):
        self.object_info, self.tried = None, 0.0

    async def refresh_nodes(self):
        """Ask ComfyUI for its node list now, and keep it: what its nodes are and which model files it has. Raises
        httpx.HTTPError when it can't be reached."""
        async with self.lock:
            self.object_info = self.saved = await self.comfy.object_info()
            self.tried = time.time()
            if self.cache_file:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(self.object_info), encoding="utf-8")
        return self.object_info

    def nodes_saved(self):
        """When the node list in hand was fetched from ComfyUI, or None if there is none."""
        if self.cache_file and self.cache_file.is_file():
            return self.cache_file.stat().st_mtime
        return (self.tried or None) if self.object_info else None

    def replaced(self):
        """Retired workflow id -> the id of the workflow that took its place (its presets file lists it under "replaces").
        Earlier work, a saved default and a job still waiting name the old id; they are served by the new workflow."""
        found = {}
        for workflow_id, path in self.files().items():
            sidecar = self.sidecar_of(path)
            try:
                old = json.loads(sidecar.read_text(encoding="utf-8")).get("replaces") if sidecar.is_file() else None
            except (OSError, ValueError):
                old = None
            found.update({str(name): workflow_id for name in old or []})
        return found

    def current(self, workflow_id):
        """The id a workflow goes by now."""
        return workflow_id if workflow_id in self.files() else self.replaced().get(workflow_id, workflow_id)

    async def load(self, workflow_id):
        workflow_id = self.current(workflow_id)
        path = self.files().get(workflow_id)
        if path is None:
            raise workflows.WorkflowError("There is no workflow named '{}'.".format(workflow_id))
        try:
            wf = workflows.load_workflow(path, self.object_info or self.saved, workflow_id, self.sidecar_of(path))
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
            return workflows.load_workflow(path, self.object_info, workflow_id, self.sidecar_of(path))
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
                # how many reference pictures it takes, as its presets file lists them (0: it makes pictures from words only)
                item["picture_refs"] = len([r for r in [*profile.get("required_refs", []), *profile.get("optional_refs", [])]
                                            if str(r).endswith(":image")])
                listed = profile.get("refs")   # a list of references, none to "max"
                if isinstance(listed, dict) and listed.get("mode") == "dynamic" and str(listed.get("node_class") or "LoadImage") == "LoadImage":
                    item["picture_refs"] += int(listed.get("max", 0))
                if profile.get("replaces"):   # earlier work made with one of these is run again with this workflow
                    item["replaces"] = profile["replaces"]
            except workflows.WorkflowError as e:
                item["error"] = str(e)
            items.append(item)
        return items
