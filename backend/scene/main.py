"""Scene.ai: the web app. Builds the FastAPI application and wires its parts together."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import media, motion, sequence
from .agent import Agent, AgentError, service
from .api import admin, assets, auth, library, studio, workspace
from .catalog import Catalog
from .comfy import workflows
from .comfy.client import Comfy, ComfyError
from .config import load_settings
from .credits import Credits
from .db import Database
from .jobs import JobManager
from .outputs import Outputs
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
    agent = Agent(settings.ollama_url, settings.agent_model, [
        service(settings.api_name.strip().lower().replace(" ", "-") or "api", settings.api_name, settings.api_url, settings.api_key, settings.api_models),
        service("gemini", "Gemini", settings.gemini_url, settings.gemini_key, settings.gemini_models,
                only=r"^gemini-[\d.]+-(pro|flash)(-lite)?(-preview)?$"),
    ])
    hub = Hub()

    def live_message(user_id, library_changed=False):
        """What a user's open pages are sent whenever something of theirs changes."""
        return json.dumps({"jobs": app.state.jobs.snapshot(user_id), "credits": credits.balance(user_id),
                           "library_changed": library_changed})

    def notify(user_id, library_changed=False):
        hub.send(user_id, live_message(user_id, library_changed))

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = JobManager(db, comfy, catalog, credits, app.state.outputs, notify, storage / "tmp", settings.node_path)
        workers = [asyncio.create_task(app.state.jobs.run_forever()), asyncio.create_task(app.state.jobs.run_forever(local=True))]
        yield
        for worker in workers:
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
    app.state.storage_dir = storage
    app.state.output_dir = settings.path("output_dir") if settings.output_dir else storage / "outputs"
    app.state.outputs = Outputs(app.state.output_dir, db)

    @app.exception_handler(workflows.WorkflowError)
    @app.exception_handler(media.MediaError)
    @app.exception_handler(motion.MotionError)
    @app.exception_handler(sequence.SequenceError)
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

    frontend = settings.path("frontend_dir").resolve()

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def page():
        """The page, with its stylesheet and script fetched from under /v/<time of the last change>/.

        The scripts import each other by relative address, so every one of them is fetched from under that same
        address, and a change to any file gives all of them a new one. A browser or a network in between that keeps
        files for hours (Cloudflare tells browsers to, by default) then cannot run old code against new, or the
        other way round."""
        changed = max((f.stat().st_mtime for f in (frontend / "assets").rglob("*") if f.suffix in (".js", ".css")), default=0)
        html = (frontend / "index.html").read_text(encoding="utf-8")
        for name in ("/assets/css/app.css", "/assets/js/main.js"):
            html = html.replace(name, "/v/{}{}".format(int(changed), name))
        return HTMLResponse(html)

    @app.get("/v/{version}/assets/{path:path}", include_in_schema=False)
    async def versioned(version: str, path: str):
        """A file of the page under its versioned address. The version only makes the address new; any value serves the file."""
        target = (frontend / "assets" / path).resolve()
        if not target.is_relative_to(frontend / "assets") or not target.is_file():
            raise HTTPException(404, "No such file.")
        return FileResponse(target)
    app.mount("/", StaticFiles(directory=settings.path("frontend_dir"), html=True), name="frontend")
    return app
