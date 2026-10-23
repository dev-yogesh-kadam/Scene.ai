"""Dated copies of the database and of config.json: one of each per day, made when the app starts and once a day
after that. A database that is lost or overwritten then costs a day of work at most. The finished pictures, videos and
sounds and the kit's uploads are copied too, into files/ in the same folder: only what is new or changed each time.
Nothing is ever deleted from the copy: a file deleted in the studio (with its project, say) keeps its copy there."""

import asyncio
import json
import shutil
import sqlite3
import subprocess
import time
from datetime import date
from pathlib import Path

EVERY = 24 * 3600   # seconds between copies while the app keeps running


def make(db, folder, config_file="", keep=14):
    """Write today's copies, in place of earlier ones from today, and delete those older than the newest `keep` days."""
    folder = _claim(db, folder)
    day = date.today().isoformat()
    target = folder / "scene_{}{}".format(day, db.suffix)
    partial = folder / "scene.partial"   # a copy that was cut short never stands in for a whole one
    partial.unlink(missing_ok=True)
    db.backup(partial)
    partial.replace(target)
    if config_file and Path(config_file).is_file():
        shutil.copy2(config_file, folder / "config_{}.json".format(day))
    for pattern in ("scene_*" + db.suffix, "config_*.json"):
        for old in sorted(folder.glob(pattern))[:-keep] if keep > 0 else []:
            old.unlink()
    return target


def check(db, folder):
    """Whether the newest copy of the database can be read back. A SQLite copy is opened (read only) and checked whole
    with its own integrity check, and its accounts and jobs are counted; a PostgreSQL copy is read through by pg_restore.
    The finding is kept in the `backup_check` setting: {when, copy, ok, detail}."""
    copies = sorted(Path(folder).glob("scene_*" + db.suffix))
    found = {"when": time.time(), "copy": copies[-1].name if copies else "", "ok": False}
    if not copies:
        found["detail"] = "There is no copy yet."
    elif db.kind == "sqlite":
        try:
            conn = sqlite3.connect(copies[-1].resolve().as_uri() + "?mode=ro", uri=True)
            try:
                verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
                users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            finally:
                conn.close()
            found["ok"] = verdict == "ok"
            found["detail"] = "It opens and is whole: {} accounts, {} jobs.".format(users, jobs) if found["ok"] else "It is damaged: " + str(verdict)[:200]
        except sqlite3.Error as error:
            found["detail"] = "It can't be opened: {}".format(error)
    else:
        from .db import pg_tool
        try:
            listed = subprocess.run([pg_tool("pg_restore"), "--list", str(copies[-1])], capture_output=True, text=True, timeout=120)
            tables = sum(1 for line in listed.stdout.splitlines() if " TABLE DATA " in line)
            found["ok"] = listed.returncode == 0 and tables > 0
            found["detail"] = "pg_restore reads it: {} tables of data.".format(tables) if found["ok"] else "pg_restore can't read it: " + listed.stderr[:200]
        except (OSError, subprocess.SubprocessError) as error:
            found["detail"] = "pg_restore could not be run: {}".format(error)
    db.set_setting("backup_check", json.dumps(found))
    return found


def last_check(db):
    try:
        return json.loads(db.setting("backup_check", "") or "null")
    except ValueError:
        return None


def _claim(db, folder):
    """The folder remembers which database it holds copies of. A second copy of the app (a test run) that was given the
    same folder is refused, so it cannot put its own database or files in place of the real one's copies."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    owner = folder / "database.txt"
    if owner.is_file() and owner.read_text(encoding="utf-8").strip() != str(db.path):
        raise RuntimeError("it holds the copies of another database, {}".format(owner.read_text(encoding="utf-8").strip()))
    owner.write_text(str(db.path), encoding="utf-8")
    return folder


def copy_files(db, folder, sources, keep=14, now=None):
    """Copy each source folder ({"outputs": path, ...}) into files/<name>/ of the backup folder: the files that are not
    there yet or whose size or time has changed. Nothing is deleted from the copy. Posters and keyframes are not copied:
    they are made again from the file. Returns how many files were copied. (`keep` and `now` are not used.)"""
    files = _claim(db, folder) / "files"
    now = now or time.time()
    copied = 0
    seen = set()
    for name, source in sources.items():
        source = Path(source)
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if not path.is_file() or ".posters" in path.parts:
                continue
            seen.add(str(Path(name) / path.relative_to(source)))
            target = files / name / path.relative_to(source)
            info = path.stat()
            if target.is_file():
                there = target.stat()
                if there.st_size == info.st_size and int(there.st_mtime) == int(info.st_mtime):
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")   # a copy cut short never stands in for a whole one
            shutil.copy2(path, partial)
            partial.replace(target)
            copied += 1
    return copied


def newest(folder):
    """When the last copy of the database was made, or None if there is none."""
    return max((f.stat().st_mtime for f in Path(folder).glob("scene_*") if f.suffix in (".db", ".dump")), default=None)


def attempt(db, folder, config_file="", keep=14):
    """A backup that fails (a disk that is full or unplugged) must not stop the app: say so and carry on."""
    try:
        return make(db, folder, config_file, keep)
    except Exception as error:
        print("The backup to {} failed: {}".format(folder, error))
        return None


def attempt_files(db, folder, sources, keep=14):
    try:
        return copy_files(db, folder, sources, keep)
    except Exception as error:
        print("The copy of the files to {} failed: {}".format(folder, error))
        return None


async def run_forever(db, folder, config_file="", keep=14, sources=None):
    """The database was copied as the app started; its files follow here, without holding the start up. Then both
    once a day."""
    while True:
        if sources:
            await asyncio.to_thread(attempt_files, db, folder, sources, keep)
        await asyncio.sleep(EVERY)
        await asyncio.to_thread(attempt, db, folder, config_file, keep)
