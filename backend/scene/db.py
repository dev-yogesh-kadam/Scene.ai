"""SQLite storage: users, sessions, jobs, finished generations, projects, assets, credits and settings."""

import sqlite3
import threading
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
"""

# Columns added after the first release: (table, column, definition). Added to older databases on start.
COLUMNS = [
    ("users", "credits", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "disabled", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "project_id", "INTEGER"),
    ("jobs", "cost", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "project_id", "INTEGER"),
    ("credit_events", "note", "TEXT NOT NULL DEFAULT ''"),
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
