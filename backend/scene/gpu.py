"""One GPU for the agent's model and the renders, when Ollama and ComfyUI run on the same machine.

The two cannot share it: a large model and a video workflow each want all of its memory. So the GPU is held by one
side at a time, "llm" (the agent thinking) or "render" (a ComfyUI job). A side that wants it waits until the other side
has let go; when it takes over, the other side's models are put out of the GPU first (Ollama unloads its model,
ComfyUI frees its memory). Calls of the same side share it. A side waiting for the GPU keeps newer calls of the other
side out, so a long run of renders or a long agent run cannot keep the other waiting forever.

The agent holds the GPU for a whole message (all its calls in a row), not call by call: a render that slipped in
between two calls would make it unload and load its model again for every call."""

import asyncio
import contextvars
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx

SIDES = ("llm", "render")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
UNLOAD_WAIT = 90     # seconds to wait for Ollama to let go of its models
FREE_WAIT = 30       # seconds to wait for ComfyUI to free the GPU's memory
FREE_SHARE = 0.85    # ComfyUI counts as freed when this share of the GPU's memory is free

class Stopped(Exception):
    """The call stopped waiting for the GPU (a job cancelled while it waited)."""


_held = contextvars.ContextVar("gpu_held", default=None)   # the side this task (and the tasks it starts) holds


def same_machine(a, b):
    """Whether two server addresses are the same machine."""
    ha, hb = (urlparse(str(u or "")).hostname or "" for u in (a, b))
    if not ha or not hb:
        return False
    return ha == hb or (ha in LOCAL_HOSTS and hb in LOCAL_HOSTS)


class Gate:
    """shared: function() -> bool, whether the GPU is shared now (the servers can move). free: {side: async function()}
    that puts the other side's models out of the GPU before `side` takes it."""

    def __init__(self, shared, free=None):
        self.shared = shared
        self.free = free or {}
        self.side = None          # the side that holds the GPU, or had it last
        self.users = 0            # calls of that side using it now
        self.waiting = {s: 0 for s in SIDES}
        self.ready = asyncio.Event()
        self.ready.set()
        self.changed = asyncio.Condition()

    def busy(self):
        """What holds the GPU now: {"side", "users", "waiting"}."""
        return {"side": self.side if self.users else None, "users": self.users, "waiting": dict(self.waiting)}

    @asynccontextmanager
    async def use(self, side, waiting=None, stop=None):
        """Hold the GPU for `side` while the block runs. waiting: function(), called once if it has to wait first.
        stop: function() -> bool, checked every second while it waits; Stopped is raised when it says so. Inside a
        block that already holds it for the same side (the agent's calls in one message), it is not taken again."""
        if side not in SIDES:
            raise ValueError(side)
        if _held.get() == side or not self.shared():
            yield
            return
        other = SIDES[1 - SIDES.index(side)]
        async with self.changed:
            self.waiting[side] += 1
            try:
                free = lambda: self.users == 0 or (self.side == side and self.waiting[other] == 0)
                if not free() and waiting:
                    waiting()
                while not free():
                    if stop and stop():
                        raise Stopped()
                    try:
                        await asyncio.wait_for(self.changed.wait(), 1)
                    except asyncio.TimeoutError:
                        pass
            finally:
                self.waiting[side] -= 1
            switching = self.side != side
            self.side, self.users = side, self.users + 1
            if switching:
                self.ready.clear()
        token = _held.set(side)
        try:
            if switching:
                try:
                    if self.free.get(side):
                        await self.free[side]()
                finally:
                    self.ready.set()
            else:
                await self.ready.wait()   # another call of this side is still putting the other side's models out
            yield
        finally:
            try:
                _held.reset(token)
            except ValueError:
                pass   # closed from another task (a stream the user stopped): that task never held it
            async with self.changed:
                self.users -= 1
                self.changed.notify_all()


async def unload_ollama(http, url):
    """Ask Ollama to put every model it has loaded out of memory, and wait until it has."""
    try:
        loaded = (await http.get(url + "/api/ps", timeout=10)).json().get("models") or []
        for model in loaded:
            await http.post(url + "/api/generate", json={"model": model["name"], "keep_alive": 0}, timeout=60)
        ends = time.monotonic() + UNLOAD_WAIT
        while loaded and time.monotonic() < ends:
            loaded = (await http.get(url + "/api/ps", timeout=10)).json().get("models") or []
            if loaded:
                await asyncio.sleep(1)
    except (httpx.HTTPError, ValueError):
        pass   # Ollama is not running: it holds nothing


async def free_comfy(http, url):
    """Ask ComfyUI to unload its models and free the GPU's memory, and wait until most of it is free."""
    try:
        await http.post(url + "/free", json={"unload_models": True, "free_memory": True}, timeout=10)
        ends = time.monotonic() + FREE_WAIT
        while time.monotonic() < ends:
            devices = (await http.get(url + "/system_stats", timeout=5)).json().get("devices") or []
            gpu = next((d for d in devices if d.get("vram_total")), None)
            if gpu is None or gpu.get("vram_free", 0) >= gpu["vram_total"] * FREE_SHARE:
                return
            await asyncio.sleep(1)
    except (httpx.HTTPError, ValueError):
        pass   # ComfyUI is not running: it holds nothing
