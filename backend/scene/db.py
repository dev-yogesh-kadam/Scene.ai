"""SQLite storage: users, sessions, jobs, finished generations, projects, boards, assets, credits, pricing and settings."""

import sqlite3
import threading
import time
from pathlib import Path

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
]

# The studio's two machines, added to an installation that has no servers yet. Every value can be changed in the
# admin console; the power of Zoro is a first assumption until it is measured at the wall.
SERVERS = [
    ("Lufi", "Ryzen 9 7900X", "RTX 4060 Ti", 8, "Hosting, the agent's local models, light workflows", 0, None),
    ("Zoro", "Ryzen 9 9950X", "RTX 5090", 32, "Heavy image, video and audio generation", 1, 950),
]


class Database:
    def __init__(self, path, starting_credits=0):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        for table, column, definition in COLUMNS:
            existing = [row["name"] for row in self.conn.execute("PRAGMA table_info({})".format(table))]
            if column not in existing:
                self.conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition))
                if (table, column) == ("users", "credits"):  # accounts from before credits existed
                    self.conn.execute("UPDATE users SET credits = ?", (starting_credits,))
        if not self.conn.execute("SELECT 1 FROM servers").fetchone():
            self.conn.executemany("INSERT INTO servers (name, cpu, gpu, vram_gb, role, renders, generation_power_w, created) "
                                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(*server, time.time()) for server in SERVERS])

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
