"""Scene.ai: the web app. Builds the FastAPI application and wires its parts together."""

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import backup, media, motion, sequence
from .agent import Agent, AgentError, service
from .api import admin, assets, auth, film, library, runs, studio, workspace
from .catalog import Catalog
from .comfy import workflows
from .comfy.client import Comfy, ComfyError
from .config import load_settings
from .credits import Credits
from .db import open_database
from .jobs import JobManager
from .outputs import Outputs
from .security import LoginThrottle, RateLimit, is_https, same_origin


class Hub:
    """The open browser connections of each user, for live queue updates, and the page each one has open."""

    def __init__(self):
        self.sockets = {}
        self.pages = {}   # connection -> {"page": "#/canvas", "since": when it connected}
        self.admins = set()   # the connections of admins, who are told the number of people online as it changes

    def add(self, user_id, ws, admin=False):
        arrived = user_id not in self.sockets
        self.sockets.setdefault(user_id, set()).add(ws)
        self.pages[ws] = {"page": "", "since": time.time()}
        if admin:
            self.admins.add(ws)
        if arrived:
            self.tell_admins()
        elif admin:   # an admin's new tab is told the number at once
            asyncio.ensure_future(self._send(user_id, ws, self.headcount()))

    def discard(self, user_id, ws):
        self.sockets.get(user_id, set()).discard(ws)
        self.pages.pop(ws, None)
        self.admins.discard(ws)
        if user_id in self.sockets and not self.sockets[user_id]:
            self.sockets.pop(user_id, None)   # nobody with no connection left counts as online
            self.tell_admins()

    def headcount(self):
        return json.dumps({"online_users": self.online()})

    def tell_admins(self):
        message = self.headcount()
        for user_id, sockets in list(self.sockets.items()):
            for ws in sockets & self.admins:
                asyncio.ensure_future(self._send(user_id, ws, message))

    def set_page(self, ws, page):
        if ws in self.pages:
            self.pages[ws]["page"] = page

    def online(self):
        """How many users have the app open: someone with three tabs is one user."""
        return len(self.sockets)

    def people(self):
        """Who has the app open: user id -> the pages of their open tabs and when the first one opened."""
        found = {}
        for user_id, sockets in self.sockets.items():
            tabs = [self.pages[ws] for ws in sockets if ws in self.pages]
            found[user_id] = {"pages": sorted({t["page"] for t in tabs if t["page"]}),
                              "since": min((t["since"] for t in tabs), default=time.time()), "tabs": len(tabs)}
        return found

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
    db = open_database(settings, storage)
    comfy = Comfy(lambda: db.setting("comfy_url", settings.comfy_url))
    catalog = Catalog(settings.path("workflows_dir"), comfy, storage / "cache" / "node_definitions.json")
    credits = Credits(db, settings)
    agent = Agent(settings.ollama_url, settings.agent_model, local=settings.ollama_models, options={
        "context": settings.ollama_context, "timeout": settings.ollama_timeout, "keep_alive": settings.ollama_keep_alive,
        "vision": settings.ollama_vision_model, "fast": settings.ollama_fast_model, "think": settings.ollama_think,
        "tools": settings.local_tools}, services=[
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
        app.state.jobs = JobManager(db, comfy, catalog, credits, app.state.outputs, notify, storage / "tmp", settings.node_path,
                                    storage / "assets")
        workers = [asyncio.create_task(app.state.jobs.run_forever()), asyncio.create_task(app.state.jobs.run_forever(local=True))]
        if settings.backup_keep > 0:
            copies = (db, app.state.backup_dir, settings.config_file, settings.backup_keep)
            backup.attempt(*copies)   # one at every start, before anything is changed
            workers.append(asyncio.create_task(backup.run_forever(*copies)))
        yield
        for worker in workers:
            worker.cancel()
        await comfy.http.aclose()
        await agent.http.aclose()
        db.close()

    # No /docs, /redoc or /openapi.json: a map of every route is of no use to the studio's users, only to an attacker.
    app = FastAPI(title="Scene.ai", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
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
    app.state.limits = RateLimit()
    app.state.started = time.time()
    app.state.storage_dir = storage
    app.state.output_dir = settings.path("output_dir") if settings.output_dir else storage / "outputs"
    app.state.outputs = Outputs(app.state.output_dir, db)
    app.state.backup_dir = settings.path("backup_dir") if settings.backup_dir else storage / "backups"
    # Whether the render server answered the last time anyone asked, and since when that has been so.
    app.state.server_seen = {"online": None, "since": time.time()}

    def saw_server(online):
        seen = app.state.server_seen
        if seen["online"] is not online:
            seen.update(online=online, since=time.time())
    app.state.saw_server = saw_server

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

    @app.middleware("http")
    async def guarded(request, call_next):
        """Refuse a change sent from another site's page (cross-site request forgery), and send every answer with the
        headers that tell the browser what the page may do."""
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
            return JSONResponse({"detail": "This request came from another site and was refused."}, status_code=403)
        response = await call_next(request)
        host = re.sub(r"[^\w.:\[\]-]", "", request.headers.get("host", ""))[:255]   # nothing that could end the policy early
        headers = response.headers
        # Scripts, styles, pictures, sounds and connections only from this site; nothing may frame the studio.
        # Styles allow inline, because the page sets sizes and colours in style attributes (charts, progress bars).
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; font-src 'self'; connect-src 'self' ws://{0} wss://{0}; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'".format(host))
        headers["X-Content-Type-Options"] = "nosniff"   # a file is only ever read as the type it is served as
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "same-origin"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if is_https(request):
            headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    for module in (auth, studio, library, workspace, film, runs, assets, admin):
        app.include_router(module.router)

    frontend = settings.path("frontend_dir").resolve()

    def page_version():
        """The time of the last change to a script or the stylesheet of the page. A tab opened before it runs old code:
        /api/status says this, and the tab offers to reload."""
        return int(max((f.stat().st_mtime for f in (frontend / "assets").rglob("*") if f.suffix in (".js", ".css")), default=0))
    app.state.page_version = page_version

    # The studio's pages have addresses of their own (/library, /canvas), all answered by the one page, which routes them.
    PAGE_PATHS = ("/", "/index.html", "/signin", "/signup", "/home", "/projects", "/library", "/skills", "/create", "/canvas",
                  "/timeline", "/assets", "/settings", "/admin")

    async def page():
        """The page, with its stylesheet and script fetched from under /v/<time of the last change>/.

        The scripts import each other by relative address, so every one of them is fetched from under that same
        address, and a change to any file gives all of them a new one. A browser or a network in between that keeps
        files for hours (Cloudflare tells browsers to, by default) then cannot run old code against new, or the
        other way round."""
        changed = page_version()
        html = (frontend / "index.html").read_text(encoding="utf-8")
        for name in ("/assets/css/app.css", "/assets/js/theme.js", "/assets/js/main.js"):
            html = html.replace(name, "/v/{}{}".format(changed, name))
        return HTMLResponse(html)

    for page_path in PAGE_PATHS:
        app.get(page_path, include_in_schema=False)(page)

    @app.get("/v/{version}/assets/{path:path}", include_in_schema=False)
    async def versioned(version: str, path: str):
        """A file of the page under its versioned address. The version only makes the address new; any value serves the file."""
        target = (frontend / "assets" / path).resolve()
        if not target.is_relative_to(frontend / "assets") or not target.is_file():
            raise HTTPException(404, "No such file.")
        return FileResponse(target)
    app.mount("/", StaticFiles(directory=settings.path("frontend_dir"), html=True), name="frontend")
    return app
