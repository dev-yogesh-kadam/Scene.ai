"""Scene.ai: the web app. Builds the FastAPI application and wires its parts together."""

import asyncio
import json
import posixpath
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import backup, endpoints, gpu, health, kit, media, motion, roles, sequence, staff, traces, versions
from .agent import Agent, AgentError, service
from .api import admin, assets, auth, bulk, console as console_api, film, kit as kit_api, library, runs, studio, workspace
from .catalog import Catalog
from .comfy import workflows
from .comfy.client import ComfyError
from .config import load_settings
from .credits import Credits
from .db import as_everyone, open_database
from .jobs import JobManager
from .outputs import Outputs
from .security import LoginThrottle, RateLimit, is_https, same_origin


class Hub:
    """The open browser connections of each user, for live queue updates, and the page each one has open."""

    def __init__(self):
        self.sockets = {}
        self.pages = {}   # connection -> {"page": "#/canvas", "since": when it connected}
        self.watchers = set()   # the admin console's open pages, told the number of people online as it changes
        self.jobs_told = False   # a "jobs changed" for the console is on its way
        self.queue = lambda: {}  # how many jobs run and wait now, sent with it (main.create_app sets it)

    def add(self, user_id, ws):
        arrived = user_id not in self.sockets
        self.sockets.setdefault(user_id, set()).add(ws)
        self.pages[ws] = {"page": "", "since": time.time()}
        if arrived:
            self.tell_watchers()

    def discard(self, user_id, ws):
        self.sockets.get(user_id, set()).discard(ws)
        self.pages.pop(ws, None)
        if user_id in self.sockets and not self.sockets[user_id]:
            self.sockets.pop(user_id, None)   # nobody with no connection left counts as online
            self.tell_watchers()

    def watch(self, ws):
        """A page of the admin console, told the number at once and again as it changes. It is not someone online."""
        self.watchers.add(ws)
        asyncio.ensure_future(self._send(None, ws, self.headcount()))

    def unwatch(self, ws):
        self.watchers.discard(ws)

    def headcount(self):
        return json.dumps({"online_users": self.online()})

    def tell_watchers(self):
        self.tell({"online_users": self.online()})

    def tell(self, message):
        """Send something to every open page of the admin console: {"online_users": n}, {"jobs": true}, {"alerts": n}."""
        text = json.dumps(message)
        for ws in list(self.watchers):
            asyncio.ensure_future(self._send(None, ws, text))

    def jobs_changed(self):
        """Tell the console's pages that a job changed, at most once a second: a busy queue changes many times a second."""
        if not self.watchers or self.jobs_told:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:   # not from the app's own loop (a test calling straight in): nothing is listening
            return
        self.jobs_told = True

        def tell():
            self.jobs_told = False
            self.tell({"jobs": self.queue() or True})
        loop.call_later(1, tell)

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
        """Send to one connection: a user's (`user_id`), or a console page's (None). One that is gone is forgotten."""
        try:
            await ws.send_text(message)
        except Exception:
            if user_id is None:
                self.unwatch(ws)
            else:
                self.discard(user_id, ws)


def create_app(settings=None):
    settings = settings or load_settings()
    storage = settings.path("storage_dir")
    db = open_database(settings, storage)
    endpoints.seed(db, settings)   # the servers and APIs of the console's Servers section
    comfy_pool = endpoints.ComfyPool(db, settings.comfy_url)
    comfy = comfy_pool.main
    staff.configure(db)   # the console's roles as an admin last saved them
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
    endpoints.apply(db, agent, settings)
    def renders_waiting():
        """Whether renders wait to start, anyone's (the queue not paused): a polite call (a review) waits for them."""
        if db.setting("queue_paused", "0") == "1":
            return False
        with as_everyone():
            return bool(db.one("SELECT 1 FROM jobs WHERE status = 'queued' AND workflow NOT LIKE 'edit/%' LIMIT 1"))

    # The agent's model and the renders take turns on the GPU when they are on one machine (gpu_shared "auto").
    mode = str(settings.gpu_shared or "auto").strip().lower()
    turns = gpu.Gate(lambda: mode == "on" or (mode == "auto" and gpu.same_machine(agent.url, comfy.url)), free={
        "llm": lambda: gpu.free_comfy(comfy.http, comfy.url), "render": lambda: gpu.unload_ollama(agent.http, agent.url)},
        pending={"render": renders_waiting})
    agent.gpu = turns
    hub = Hub()

    def queue_counts():
        with as_everyone():
            rows = db.all("SELECT status, COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'running') GROUP BY status")
        found = {r["status"]: r["n"] for r in rows}
        return {"running": found.get("running", 0), "waiting": found.get("queued", 0)}
    hub.queue = queue_counts

    def live_message(user_id, library_changed=False):
        """What a user's open pages are sent whenever something of theirs changes."""
        return json.dumps({"jobs": app.state.jobs.snapshot(user_id), "credits": credits.balance(user_id),
                           "library_changed": library_changed})

    def notify(user_id, library_changed=False):
        hub.send(user_id, live_message(user_id, library_changed))
        hub.jobs_changed()   # the console's Jobs and Overview follow every job

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = JobManager(db, comfy, catalog, credits, app.state.outputs, notify, storage / "tmp", settings.node_path,
                                    storage / "assets")
        app.state.jobs.gpu = turns
        app.state.jobs.pool = comfy_pool
        app.state.jobs.hold_offline = settings.hold_queue_offline
        app.state.jobs.agent = agent   # writes the captions some image models need, just before they render
        workers = [asyncio.create_task(app.state.jobs.run_forever()), asyncio.create_task(app.state.jobs.run_forever(local=True)),
                   asyncio.create_task(health.Watcher(app.state).run_forever())]   # alerts, sent while nobody watches
        if settings.backup_keep > 0:
            copies = (db, app.state.backup_dir, settings.config_file, settings.backup_keep)
            backup.attempt(*copies)   # one at every start, before anything is changed
            workers.append(asyncio.create_task(backup.run_forever(*copies, app.state.backup_files)))
        yield
        for worker in workers:
            worker.cancel()
        await comfy_pool.close()
        await agent.http.aclose()
        db.close()

    # No /docs, /redoc or /openapi.json: a map of every route is of no use to the studio's users, only to an attacker.
    app = FastAPI(title="Scene.ai", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.comfy = comfy
    app.state.comfy_pool = comfy_pool
    app.state.gpu = turns
    app.state.catalog = catalog
    app.state.hub = hub
    app.state.credits = credits
    app.state.agent = agent
    app.state.notify = notify
    app.state.live_message = live_message
    app.state.assets_dir = storage / "assets"
    app.state.throttle = LoginThrottle()
    app.state.limits = RateLimit()
    app.state.view_codes = {}   # one-time codes to view the studio as a user (api/admin.start_view), by their hash
    app.state.started = time.time()
    app.state.storage_dir = storage
    app.state.output_dir = settings.path("output_dir") if settings.output_dir else storage / "outputs"
    app.state.outputs = Outputs(app.state.output_dir, db)
    with as_everyone():   # work saved at the top of a user's folder (before projects had folders) goes into its project's
        app.state.outputs.file_all()
    with as_everyone():   # once: every project's cast becomes the always-on entries of its kit
        kit.migrate_cast(db, storage / "assets", app.state.outputs)
        kit.remove_global(db, storage / "assets")   # a NeuralCore belongs to a project: assets of no project are deleted
    app.state.versions = versions.Shelf(db, catalog, storage / "workflow_versions")
    agent.recorder = app.state.traces = traces.Recorder(db, storage / "agent_calls")   # every call to its models
    roles.apply(db, agent)   # the models an admin chose in the console for the agent's roles, over config.json
    with as_everyone():
        versions.look(app.state)   # what arrived while the app was stopped
    app.state.backup_dir = settings.path("backup_dir") if settings.backup_dir else storage / "backups"
    # The files a lost disk would take with it: the finished work and the kit's uploads. Copied into files/ beside the backups.
    app.state.backup_files = {"outputs": app.state.output_dir, "assets": app.state.assets_dir}
    # Whether the render server answered the last time anyone asked, and since when that has been so.
    app.state.server_seen = {"online": None, "since": time.time()}
    app.state.model_seen = {"online": None, "since": time.time()}   # the same for the agent's model server (health.py)

    def saw_server(online):
        seen = app.state.server_seen
        if seen["online"] is not online:
            seen.update(online=online, since=time.time())
    app.state.saw_server = saw_server

    @app.middleware("http")
    async def no_console_here(request, call_next):
        """The studio does not serve the admin console's page or scripts; the console's own port does."""
        path = posixpath.normpath(request.url.path).lower()   # as the files are found: "//" and ".." resolved, any case
        if path == "/console.html" or CONSOLE_FILES.match(path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await call_next(request)

    _answer_errors(app)
    _guard(app)   # after the one above, so its answers get the headers too
    # The admin routes are not here: they are the admin console's, a site of its own (create_console).
    for module in (auth, studio, library, workspace, film, runs, kit_api, assets, bulk):
        app.include_router(module.router)

    frontend = settings.path("frontend_dir").resolve()

    def page_version():
        """The time of the last change to a script or the stylesheet of the page. A tab opened before it runs old code:
        /api/status says this, and the tab offers to reload."""
        return int(max((f.stat().st_mtime for f in (frontend / "assets").rglob("*") if f.suffix in (".js", ".css")), default=0))
    app.state.page_version = page_version

    # The studio's pages have addresses of their own (/library, /canvas), all answered by the one page, which routes them.
    # /admin, where the console used to be, sends an admin on to it.
    PAGE_PATHS = ("/", "/index.html", "/signin", "/signup", "/home", "/projects", "/library", "/skills", "/create", "/canvas",
                  "/timeline", "/settings", "/admin", "/project", "/analytics", "/guide")
    _pages(app, frontend, "index.html", "main.js", PAGE_PATHS)
    app.mount("/", StaticFiles(directory=settings.path("frontend_dir"), html=True), name="frontend")
    app.state.console = create_console(app) if settings.console_port else None
    return app


def _answer_errors(app):
    """The errors of the studio's parts, answered with what went wrong instead of as a crash."""
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


def _guard(app):
    """What both sites do with every request: refuse a change from another site's page, and tell the browser what
    the page may do and to check for newer files."""
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
        traces.new_run()   # the agent's calls made for this request are one run (traces.py)
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


def _pages(app, frontend, html_file, script, paths):
    """`paths` answered by the page `html_file`, with its stylesheet and scripts fetched from under /v/<time of the
    last change>/.

    The scripts import each other by relative address, so every one of them is fetched from under that same
    address, and a change to any file gives all of them a new one. A browser or a network in between that keeps
    files for hours (Cloudflare tells browsers to, by default) then cannot run old code against new, or the
    other way round."""
    async def page():
        changed = app.state.page_version()
        html = (frontend / html_file).read_text(encoding="utf-8")
        for name in ("/assets/css/app.css", "/assets/js/theme.js", "/assets/js/" + script):
            html = html.replace(name, "/v/{}{}".format(changed, name))
        return HTMLResponse(html)

    for page_path in paths:
        app.get(page_path, include_in_schema=False)(page)

    @app.get("/v/{version}/assets/{path:path}", include_in_schema=False)
    async def versioned(version: str, path: str):
        """A file of the page under its versioned address. The version only makes the address new; any value serves the file."""
        target = (frontend / "assets" / path).resolve()
        if not target.is_relative_to(frontend / "assets") or not target.is_file():
            raise HTTPException(404, "No such file.")
        return FileResponse(target)
    return page


# The admin console's scripts, under the page files: /assets/js/console/, or the same under a /v/<version>/ address.
CONSOLE_FILES = re.compile(r"^(/v/[^/]+)?/assets/js/console(/|$)")
SECTION = re.compile(r"^[a-z]{1,30}$")


def create_console(studio):
    """The admin console: a site of its own, on its own port and address (settings console_host and console_port),
    with its own sign-in. It shares the studio's state (the database, the queue, who is online), and the admin routes
    are only here: the studio's port, the one on the internet, has none of them."""
    settings = studio.state.settings
    if settings.console_port == settings.port:
        raise ValueError("The admin console needs a port of its own: console_port is {}, the same as port.".format(settings.port))
    console = FastAPI(title="Scene.ai admin console", docs_url=None, redoc_url=None, openapi_url=None)
    console.state = studio.state   # request.app.state is the studio's, whichever site the request came to
    _answer_errors(console)
    _guard(console)
    for module in (console_api, admin):
        console.include_router(module.router)
    frontend = settings.path("frontend_dir").resolve()
    page = _pages(console, frontend, "console.html", "console/main.js", ("/", "/signin"))

    @console.get("/{section}", include_in_schema=False)
    async def section_page(section: str):
        """Each section of the console has an address of its own (/users, /jobs), all answered by the one page."""
        if not SECTION.match(section):
            raise HTTPException(404, "No such page.")
        return await page()
    console.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
    return console


class Doors:
    """The studio and the admin console, served by one server on two ports: a request goes to the site of the port it
    came in on. Both share one process, so the console sees the live queue and who is online."""

    def __init__(self, studio):
        self.studio = studio
        self.console = studio.state.console
        self.console_port = studio.state.settings.console_port

    async def __call__(self, scope, receive, send):
        port = (scope.get("server") or (None, None))[1]
        if self.console is not None and scope["type"] != "lifespan" and port == self.console_port:
            return await self.console(scope, receive, send)
        return await self.studio(scope, receive, send)   # the start and stop of the app (lifespan) are the studio's
