"""Dated copies of the database and of config.json: one of each per day, made when the app starts and once a day
after that. A database that is lost or overwritten then costs a day of work at most."""

import asyncio
import shutil
from datetime import date
from pathlib import Path

EVERY = 24 * 3600   # seconds between copies while the app keeps running


def make(db, folder, config_file="", keep=14):
    """Write today's copies, in place of earlier ones from today, and delete those older than the newest `keep` days."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # The folder remembers which database it holds copies of. A second copy of the app (a test run) that was given the
    # same folder is refused, so it cannot put its own database in place of the real one's copies.
    owner = folder / "database.txt"
    if owner.is_file() and owner.read_text(encoding="utf-8").strip() != str(db.path):
        raise RuntimeError("it holds the copies of another database, {}".format(owner.read_text(encoding="utf-8").strip()))
    owner.write_text(str(db.path), encoding="utf-8")
    day = date.today().isoformat()
    target = folder / "scene_{}.db".format(day)
    partial = folder / "scene.partial"   # a copy that was cut short never stands in for a whole one
    partial.unlink(missing_ok=True)
    db.backup(partial)
    partial.replace(target)
    if config_file and Path(config_file).is_file():
        shutil.copy2(config_file, folder / "config_{}.json".format(day))
    for pattern in ("scene_*.db", "config_*.json"):
        for old in sorted(folder.glob(pattern))[:-keep] if keep > 0 else []:
            old.unlink()
    return target


def newest(folder):
    """When the last copy of the database was made, or None if there is none."""
    return max((f.stat().st_mtime for f in Path(folder).glob("scene_*.db")), default=None)


def attempt(db, folder, config_file="", keep=14):
    """A backup that fails (a disk that is full or unplugged) must not stop the app: say so and carry on."""
    try:
        return make(db, folder, config_file, keep)
    except Exception as error:
        print("The backup to {} failed: {}".format(folder, error))
        return None


async def run_forever(db, folder, config_file="", keep=14):
    while True:
        await asyncio.sleep(EVERY)
        await asyncio.to_thread(attempt, db, folder, config_file, keep)
