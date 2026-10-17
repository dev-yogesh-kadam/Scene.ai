"""Storage: users, sessions, jobs, finished generations, projects, boards, assets, credits, pricing and settings.

Two databases with the same interface (run, change, all, one, setting, backup): PostgreSQL when `database_url` is set,
otherwise SQLite in one file. The app's SQL is written once, with ? for each value; the PostgreSQL side translates it.
The tables are described once, below, in SQLite's words; PostgreSQL gets the same tables in its own types."""

import contextlib
import contextvars
import functools
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    workflow TEXT NOT NULL,
    kind TEXT NOT NULL,
    settings TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT,
    est_seconds REAL,
    hidden INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    started REAL,
    finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id, created);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id TEXT,
    workflow TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL,
    context TEXT NOT NULL,
    seconds REAL,
    size INTEGER,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS generations_user ON generations(user_id, created);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS boards (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    updated REAL NOT NULL,
    PRIMARY KEY (user_id, project_id, kind)
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    tag TEXT NOT NULL DEFAULT 'character',
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_events (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    job_id TEXT,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (user_id, name)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER,
    actor_name TEXT NOT NULL DEFAULT '',
    actor_email TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_pricing (
    workflow TEXT PRIMARY KEY,
    credits_per_second REAL,
    base_credits REAL,
    resolution_multiplier REAL NOT NULL DEFAULT 1,
    quality_multiplier REAL NOT NULL DEFAULT 1,
    preferred_server TEXT NOT NULL DEFAULT '',
    fallback_servers TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS credit_packages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    price_inr REAL NOT NULL DEFAULT 0,
    credits INTEGER NOT NULL DEFAULT 0,
    bonus_credits INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cpu TEXT NOT NULL DEFAULT '',
    gpu TEXT NOT NULL DEFAULT '',
    vram_gb REAL,
    role TEXT NOT NULL DEFAULT '',
    renders INTEGER NOT NULL DEFAULT 0,
    idle_power_w REAL,
    generation_power_w REAL,
    max_power_w REAL,
    preferred_workflows TEXT NOT NULL DEFAULT '',
    supported_workflows TEXT NOT NULL DEFAULT '',
    purchase_price_inr REAL,
    purchase_date TEXT NOT NULL DEFAULT '',
    life_months REAL,
    salvage_value_inr REAL,
    productive_hours REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created REAL NOT NULL
);
"""

# Columns added after the first release: (table, column, definition). Added to older databases on start.
COLUMNS = [
    ("users", "credits", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "disabled", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "agent", "INTEGER NOT NULL DEFAULT 0"),   # may use the agent; an admin always may
    ("jobs", "project_id", "INTEGER"),
    ("jobs", "cost", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "project_id", "INTEGER"),
    ("credit_events", "note", "TEXT NOT NULL DEFAULT ''"),
    # What a job was asked for and what became of its credits. `cost` stays the price of the job.
    ("jobs", "seconds_requested", "REAL"),
    ("jobs", "credits_required", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "credits_reserved", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "credits_consumed", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "credits_refunded", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "server", "TEXT NOT NULL DEFAULT ''"),
    ("jobs", "retries", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "output_size", "INTEGER"),
    # Two-step sign-in: the authenticator secret, whether it is on, the last code's time step (a code is used once)
    # and the hashes of the unused recovery codes, as a JSON list.
    ("users", "mfa_secret", "TEXT NOT NULL DEFAULT ''"),
    ("users", "mfa_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "mfa_step", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "mfa_recovery", "TEXT NOT NULL DEFAULT '[]'"),
    # The most credits a user may spend in 24 hours: NULL follows the studio's limit, 0 means no limit for them.
    ("users", "daily_cap", "INTEGER"),
    # A job an admin moved to the front of the queue is taken before older ones: higher first, then oldest first.
    ("jobs", "priority", "INTEGER NOT NULL DEFAULT 0"),
    # The asset book of the agent: what a saved asset or a library item shows, written by the agent's model looking at
    # it, and the user's own note on when and how to use a saved asset.
    ("assets", "about", "TEXT NOT NULL DEFAULT ''"),
    ("assets", "use_note", "TEXT NOT NULL DEFAULT ''"),
    ("generations", "about", "TEXT NOT NULL DEFAULT ''"),
    # Shared memory: a reference file dropped into a job is kept as an asset of the project it was used in
    # (origin "upload"), beside the ones saved on purpose (origin "saved", which belong to no one project).
    ("assets", "origin", "TEXT NOT NULL DEFAULT 'saved'"),
    ("assets", "project_id", "INTEGER"),
    # An asset the agent made for reuse (a character, a place, a voice): the library item it was kept from. A retake of
    # the same name replaces it, where an asset the user saved is never replaced.
    ("assets", "made_from", "INTEGER"),
    # Review: the agent's verdict on a library item it looked at after it was made (JSON, see review.py).
    ("generations", "review", "TEXT NOT NULL DEFAULT ''"),
    # The user's thumbs on a result: 1 up, -1 down, 0 not rated. The agent reuses what was liked and avoids the rest.
    ("generations", "rating", "INTEGER NOT NULL DEFAULT 0"),
]

# The studio's two machines, added to an installation that has no servers yet. Every value can be changed in the
# admin console; the power of Zoro is a first assumption until it is measured at the wall.
SERVERS = [
    ("Lufi", "Ryzen 9 7900X", "RTX 4060 Ti", 8, "Hosting, the agent's local models, light workflows", 0, None),
    ("Zoro", "Ryzen 9 9950X", "RTX 5090", 32, "Heavy image, video and audio generation", 1, 950),
]



# Whose rows a statement may see: a user's id, or EVERYONE. Each request that signs a user in narrows it to that user
# (api/deps.py), the admin console widens it again, and work that is no one request's (the queue, backups, signing in)
# keeps the default. PostgreSQL enforces it with row-level security; SQLite has none, and relies on the queries alone.
EVERYONE = "all"
ACTING = contextvars.ContextVar("acting", default=EVERYONE)


def act_for(user_id):
    """From here to the end of this request, statements see only this user's rows."""
    ACTING.set(str(user_id))


def act_for_everyone():
    ACTING.set(EVERYONE)


@contextlib.contextmanager
def as_everyone():
    """For a read inside a user's request that is meant to span all users (queue positions, time estimates)."""
    token = ACTING.set(EVERYONE)
    try:
        yield
    finally:
        ACTING.reset(token)


def open_database(settings, storage):
    """PostgreSQL when config.json names one (database_url), else SQLite in the storage folder."""
    if settings.database_url:
        return PostgresDatabase(settings.database_url, settings.signup_credits, settings.database_owner_url)
    return Database(Path(storage) / "scene.db", settings.signup_credits)


def _seed(db, starting_credits):
    """What both databases do once their tables exist: add the columns of later releases, and the two servers."""
    for table, column, definition in COLUMNS:
        if column not in db.columns(table):
            db.add_column(table, column, definition)
            if (table, column) == ("users", "credits"):  # accounts from before credits existed
                db.run("UPDATE users SET credits = ?", (starting_credits,))
    if not db.one("SELECT 1 FROM servers"):
        for server in SERVERS:
            db.run("INSERT INTO servers (name, cpu, gpu, vram_gb, role, renders, generation_power_w, created) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*server, time.time()))


class Database:
    """SQLite: one file, one connection, one statement at a time."""

    kind = "sqlite"
    suffix = ".db"   # of its backup copies

    def __init__(self, path, starting_credits=0):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        _seed(self, starting_credits)

    def columns(self, table):
        return [row["name"] for row in self.all("PRAGMA table_info({})".format(table))]

    def add_column(self, table, column, definition):
        self.run("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition))

    def size(self):
        return self.path.stat().st_size if self.path.is_file() else 0

    def close(self):
        with self.lock:
            self.conn.close()

    @staticmethod
    def local_day(column):
        """SQL for the local calendar day (YYYY-MM-DD) of a time in seconds."""
        return "date({}, 'unixepoch', 'localtime')".format(column)

    @staticmethod
    def utc_text(column):
        """SQL for a time in seconds as "YYYY-MM-DD HH:MM:SS" in UTC."""
        return "datetime({}, 'unixepoch')".format(column)

    def backup(self, target):
        """Write a whole copy of the database to `target`. Safe while the app is running."""
        copy = sqlite3.connect(str(target))
        try:
            with self.lock:
                self.conn.backup(copy)
        finally:
            copy.close()

    def run(self, sql, params=()):
        """Run a statement and return the new row id (for INSERT)."""
        with self.lock:
            return self.conn.execute(sql, params).lastrowid

    def change(self, sql, params=()):
        """Run a statement and return how many rows it changed."""
        with self.lock:
            return self.conn.execute(sql, params).rowcount

    def all(self, sql, params=()):
        with self.lock:
            return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))


# ---------------------------------------------------------------- PostgreSQL

# The tables whose rows get a number of their own; an INSERT into one of them returns it.
ID_TABLES = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(\s*id INTEGER PRIMARY KEY", SCHEMA))

# Row-level security: each row of these tables belongs to the user in this column. A statement made for one user sees
# and writes only that user's rows, even if its SQL forgot to say so. Tables of the whole installation (settings,
# pricing, servers, the audit log) have no owner.
OWNED = {"users": "id", "sessions": "user_id", "jobs": "user_id", "generations": "user_id", "projects": "user_id",
         "boards": "user_id", "assets": "user_id", "credit_events": "user_id", "uploads": "user_id"}
ACTING_SQL = "current_setting('app.user_id', true)"
OWN_ROWS = ("{acting} = 'all' OR {column} = (CASE WHEN {acting} ~ '^[0-9]+$' THEN {acting}::bigint END)")


def postgres_types(sql):
    """SQLite's column types in PostgreSQL's words: a numbered row, 64-bit whole numbers, double-precision decimals."""
    sql = re.sub(r"\bid INTEGER PRIMARY KEY\b", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", sql)
    sql = re.sub(r"\bINTEGER\b", "BIGINT", sql)
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)


@functools.lru_cache(maxsize=1024)
def postgres_sql(sql):
    """A statement written with ? for each value, as psycopg takes it: %s for each value outside quotes, and every
    % of the text doubled. An INSERT into a numbered table also returns the new number."""
    out, quote = [], None
    for ch in sql:
        if ch == "%":
            out.append("%%")
        elif quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            out.append(ch)
            quote = ch
        else:
            out.append("%s" if ch == "?" else ch)
    sql = "".join(out)
    table = re.match(r"\s*INSERT INTO (\w+)", sql, re.I)
    if table and table.group(1) in ID_TABLES and not re.search(r"\bRETURNING\b", sql, re.I):
        sql += " RETURNING id"   # how PostgreSQL tells the new row's number, which SQLite keeps as lastrowid
    return sql


def _plain(value):
    """A sum or a rounded number comes back from PostgreSQL as a Decimal, which does not mix with float. The app
    expects what SQLite gives: an int or a float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class PostgresDatabase:
    """PostgreSQL. One connection and one statement at a time, as with SQLite; the connection is opened again if the
    server restarted. `owner_url`, when given, is the account that owns the tables: it makes and changes them when
    the app starts, and the app itself works as an account that may only read and write rows."""

    kind = "postgres"
    suffix = ".dump"   # of its backup copies: pg_dump's own format, put back with pg_restore

    def __init__(self, url, starting_credits=0, owner_url=""):
        import psycopg   # only an installation that uses PostgreSQL needs it
        from psycopg.rows import dict_row
        self.psycopg, self.dict_row = psycopg, dict_row
        self.url = url
        parts = urlsplit(url)
        # What the backup folder records as the database it holds copies of: the address without the password.
        self.path = urlunsplit((parts.scheme, "{}:{}".format(parts.hostname, parts.port or 5432), parts.path, "", ""))
        self.lock = threading.Lock()
        self.conn = None
        self.acting = None   # whose rows the open connection was last told to show
        if owner_url:
            with psycopg.connect(owner_url, autocommit=True) as owner:
                self._make_tables(owner, app_account=parts.username)
        else:
            with self.lock:
                self._make_tables(self._connection(), app_account=None)
        _seed(self, starting_credits)

    @staticmethod
    def _make_tables(conn, app_account):
        for statement in postgres_types(SCHEMA).split(";"):
            if statement.strip():
                conn.execute(statement)
        for table, column, definition in COLUMNS:
            conn.execute("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}".format(table, column, postgres_types(definition)))
        for table, column in OWNED.items():
            rule = OWN_ROWS.format(acting=ACTING_SQL, column=column)
            conn.execute("ALTER TABLE {} ENABLE ROW LEVEL SECURITY".format(table))
            conn.execute("ALTER TABLE {} FORCE ROW LEVEL SECURITY".format(table))   # for the tables' owner as well
            conn.execute("DROP POLICY IF EXISTS own_rows ON {}".format(table))
            conn.execute("CREATE POLICY own_rows ON {} USING ({}) WITH CHECK ({})".format(table, rule, rule))
        if app_account:   # the app's own account may use the rows, not change the tables
            conn.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{}"'.format(app_account))
            conn.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{}"'.format(app_account))

    def _lost(self):
        return self.conn is None or self.conn.closed or self.conn.broken

    def _connection(self):
        if self._lost():
            self.conn = self.psycopg.connect(self.url, autocommit=True, row_factory=self.dict_row)
            self.acting = None
        return self.conn

    def _execute(self, sql, params):
        """Run one statement; if the connection was lost (the server restarted), open it again and try once more."""
        with self.lock:
            for attempt in (1, 2):
                try:
                    conn, acting = self._connection(), ACTING.get()
                    if acting != self.acting:   # tell the database whose rows this statement is for
                        conn.execute("SELECT set_config('app.user_id', %s, false)", (acting,))
                        self.acting = acting
                    cursor = conn.execute(postgres_sql(sql), tuple(params))
                    rows = [{k: _plain(v) for k, v in row.items()} for row in cursor.fetchall()] if cursor.description else []
                    return rows, cursor.rowcount
                except self.psycopg.OperationalError:
                    if attempt == 2 or not self._lost():
                        raise

    def columns(self, table):
        return [r["column_name"] for r in self.all(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?", (table,))]

    def add_column(self, table, column, definition):
        self.run("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}".format(table, column, postgres_types(definition)))

    def size(self):
        return self.one("SELECT pg_database_size(current_database()) AS n")["n"]

    def close(self):
        with self.lock:
            if self.conn is not None:
                self.conn.close()

    @staticmethod
    def local_day(column):
        return "to_char(to_timestamp({}), 'YYYY-MM-DD')".format(column)   # in the server's time zone: this machine's

    @staticmethod
    def utc_text(column):
        return "to_char(to_timestamp({}) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')".format(column)

    def backup(self, target):
        """A whole copy of the database in pg_dump's format. The password goes in the environment, not the command.
        It reads as EVERYONE, so row-level security lets it see every row; without that, pg_dump refuses to run."""
        parts = urlsplit(self.url)
        env = dict(os.environ, PGPASSWORD=unquote(parts.password or ""), PGOPTIONS="-c app.user_id=" + EVERYONE)
        address = urlunsplit((parts.scheme, "{}@{}:{}".format(parts.username, parts.hostname, parts.port or 5432),
                              parts.path, parts.query, ""))
        subprocess.run([pg_tool("pg_dump"), "--format=custom", "--enable-row-security", "--file", str(target), "--dbname", address],
                       env=env, check=True, capture_output=True, timeout=600)

    def run(self, sql, params=()):
        """Run a statement and return the new row id (for INSERT into a numbered table)."""
        rows, _ = self._execute(sql, params)
        return rows[0]["id"] if rows and "id" in rows[0] else None

    def change(self, sql, params=()):
        return self._execute(sql, params)[1]

    def all(self, sql, params=()):
        return self._execute(sql, params)[0]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    setting = Database.setting
    set_setting = Database.set_setting


def pg_tool(name):
    """A PostgreSQL program (pg_dump, pg_restore): on the PATH, or where the Windows installer puts it."""
    found = shutil.which(name)
    if found:
        return found
    for folder in sorted(Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "PostgreSQL").glob("*/bin"), reverse=True):
        if (folder / (name + ".exe")).is_file():
            return str(folder / (name + ".exe"))
    raise RuntimeError("{} was not found. Install PostgreSQL's command-line tools.".format(name))
