"""Small async client for the ComfyUI HTTP API."""

import httpx


class ComfyError(Exception):
    pass


class Comfy:
    def __init__(self, get_url):
        self.get_url = get_url  # called on every request, so the address can change while the app runs
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=8))

    @property
    def url(self):
        return self.get_url().rstrip("/")

    def ws_url(self, client_id):
        return "ws" + self.url[4:] + "/ws?clientId=" + client_id

    async def stats(self):
        r = await self.http.get(self.url + "/system_stats", timeout=5)
        r.raise_for_status()
        return r.json()

    async def queue_state(self):
        """How many prompts ComfyUI itself is running and holding (from any client)."""
        r = await self.http.get(self.url + "/queue", timeout=5)
        r.raise_for_status()
        body = r.json()
        return {"running": len(body.get("queue_running", [])), "pending": len(body.get("queue_pending", []))}

    async def object_info(self):
        r = await self.http.get(self.url + "/object_info", timeout=httpx.Timeout(60, connect=5))
        r.raise_for_status()
        return r.json()

    async def upload(self, filename, data, mime):
        """Put a file into ComfyUI's input folder and return the name ComfyUI stored it under."""
        r = await self.http.post(self.url + "/upload/image", data={"overwrite": "true"},
                                 files={"image": (filename, data, mime or "application/octet-stream")})
        if r.status_code >= 400:
            raise ComfyError("ComfyUI refused the upload of {}: {}".format(filename, r.text[:300]))
        info = r.json()
        return (info["subfolder"] + "/" if info.get("subfolder") else "") + info["name"]

    async def queue(self, prompt, client_id):
        r = await self.http.post(self.url + "/prompt", json={"prompt": prompt, "client_id": client_id})
        try:
            body = r.json()
        except ValueError:
            body = {}
        # A 200 with node_errors means ComfyUI skipped a side branch (say, an unconnected preview) and runs the rest.
        if r.status_code >= 400 or "prompt_id" not in body:
            raise ComfyError(_explain(body) or "ComfyUI rejected the workflow: " + r.text[:500])
        return body["prompt_id"]

    async def history(self, prompt_id):
        r = await self.http.get("{}/history/{}".format(self.url, prompt_id), timeout=30)
        r.raise_for_status()
        return r.json().get(prompt_id)

    async def view(self, filename, subfolder="", kind="output"):
        """Open a streamed download of a file in ComfyUI. The caller must close the response."""
        request = self.http.build_request(
            "GET", self.url + "/view", params={"filename": filename, "subfolder": subfolder, "type": kind})
        return await self.http.send(request, stream=True)

    async def cancel(self, prompt_id):
        await self.http.post(self.url + "/queue", json={"delete": [prompt_id]}, timeout=15)
        await self.http.post(self.url + "/interrupt", json={"prompt_id": prompt_id}, timeout=15)


def _explain(body):
    lines = []
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        lines.append(error["message"])
    for node_id, node in (body.get("node_errors") or {}).items():
        for e in node.get("errors", []):
            lines.append("{} (node {}): {} {}".format(
                node.get("class_type", "?"), node_id, e.get("message", ""), e.get("details", "")).strip())
    return "ComfyUI rejected the workflow. " + " | ".join(lines[:6]) if lines else ""
