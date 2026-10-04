"""Scene.ai: the web app. Builds the FastAPI application and wires its parts together."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import media
from .agent import Agent, AgentError
from .api import admin, assets, auth, library, studio, workspace
from .catalog import Catalog
from .comfy import workflows
from .comfy.client import Comfy, ComfyError
from .config import load_settings
from .credits import Credits
from .db import Database
from .jobs import JobManager
from .security import LoginThrottle


class Hub:
    """The open browser connections of each user, for live queue updates."""

    def __init__(self):
        self.sockets = {}

    def add(self, user_id, ws):
        self.sockets.setdefault(user_id, set()).add(ws)

    def discard(self, user_id, ws):
        self.sockets.get(user_id, set()).discard(ws)

    def send(self, user_id, message):
        for ws in list(self.sockets.get(user_id, ())):
            asyncio.ensure_future(self._send(user_id, ws, message))

    async def _send(self, user_id, ws, message):
        try:
            await ws.send_text(message)
        except Exception:
            self.discard(user_id, ws)


def create_app(settings=None):
    settings = settings or load_settings()
    storage = settings.path("storage_dir")
    db = Database(storage / "scene.db", settings.signup_credits)
    comfy = Comfy(lambda: db.setting("comfy_url", settings.comfy_url))
    catalog = Catalog(settings.path("workflows_dir"), comfy, storage / "cache" / "node_definitions.json")
    credits = Credits(db, settings)
    agent = Agent(settings.ollama_url, settings.agent_model)
    hub = Hub()

    def live_message(user_id, library_changed=False):
        """What a user's open pages are sent whenever something of theirs changes."""
        return json.dumps({"jobs": app.state.jobs.snapshot(user_id), "credits": credits.balance(user_id),
                           "library_changed": library_changed})

    def notify(user_id, library_changed=False):
        hub.send(user_id, live_message(user_id, library_changed))

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = JobManager(db, comfy, catalog, credits, app.state.output_dir, notify)
        worker = asyncio.create_task(app.state.jobs.run_forever())
        yield
        worker.cancel()
        await comfy.http.aclose()
        await agent.http.aclose()

    app = FastAPI(title="Scene.ai", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.comfy = comfy
    app.state.catalog = catalog
    app.state.hub = hub
    app.state.credits = credits
    app.state.agent = agent
    app.state.notify = notify
    app.state.live_message = live_message
    app.state.assets_dir = storage / "assets"
    app.state.throttle = LoginThrottle()
    app.state.started = time.time()
    app.state.output_dir = storage / "outputs"

    @app.exception_handler(workflows.WorkflowError)
    @app.exception_handler(media.MediaError)
    @app.exception_handler(AgentError)
    @app.exception_handler(ComfyError)
    async def known_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(httpx.HTTPError)
    async def comfy_unreachable(request, exc):
        return JSONResponse({"detail": "The render server (ComfyUI) can't be reached right now."}, status_code=502)

    @app.middleware("http")
    async def always_current_pages(request, call_next):
        """Make the browser check for a newer page file every time, so an update shows without clearing its cache.

        Unchanged files are still answered with "not modified", so this costs almost nothing.
        """
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    for module in (auth, studio, library, workspace, assets, admin):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=settings.path("frontend_dir"), html=True), name="frontend")
    return app
