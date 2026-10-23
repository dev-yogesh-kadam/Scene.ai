"""Where finished images, videos and sounds are kept: one folder per user, named after the user's email, and in it one
folder per project, with one per module inside it:

    <outputs>/ada@example.com/Pocket Film (6)/Main canvas/      the project's own canvas
    <outputs>/ada@example.com/Pocket Film (6)/Episode 1 (9)/    a module of it
    <outputs>/ada@example.com/No project/                       work in no project

A folder is named after its project and its number, so two projects of the same name stay apart; it follows the project
when it is renamed, and goes with it when it is deleted. An item's `filename` is its path inside the user's folder.
"""

import glob
import re
import shutil
from pathlib import Path

NO_PROJECT = "No project"
MAIN_CANVAS = "Main canvas"   # the folder of a project's own canvas, beside its modules' folders


def folder_name(email):
    """An email as a folder name every system accepts: ada@example.com stays as it is."""
    return re.sub(r"[^\w.@+-]+", "_", email).strip("._ ") or "user"


def safe(name):
    """A name made safe as a folder name on any system (at most 60 characters); empty when nothing is left."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "")).strip(" .")[:60].strip(" .")


def canvas_folder(name):
    """The folder of a project's own canvas, by the name it was given ("Main canvas" when it has none)."""
    return safe(name) or MAIN_CANVAS


def label(row):
    """A project's folder name: its name, made safe for any system, and its number."""
    name = safe(row["name"]) or "Untitled"
    return "{} ({})".format(name, row["id"])


class Outputs:
    def __init__(self, root, db):
        self.root = Path(root)
        self.db = db
        self.names = {}   # user id -> folder name; an email never changes, so this is filled once per user

    def folder(self, user_id):
        """The folder of one user's finished work. It is not created here."""
        if user_id not in self.names:
            user = self.db.one("SELECT email FROM users WHERE id = ?", (user_id,))
            if user is None:
                return self.root / str(user_id)
            name = folder_name(user["email"])
            # Folders used to be named by user id. One that is still around is renamed the first time it is needed.
            old = self.root / str(user_id)
            if old.is_dir() and not (self.root / name).exists():
                old.rename(self.root / name)
            self.names[user_id] = name
        return self.root / self.names[user_id]

    def relative(self, project_id):
        """Where the work of a project goes inside its user's folder: "<project> (n)/Main canvas" for its own canvas,
        "<project> (n)/<module> (m)" for a module, "No project" for none."""
        row = self.db.one("SELECT id, parent_id, canvas_name FROM projects WHERE id = ?", (project_id,)) if project_id else None
        if row is None:
            return Path(NO_PROJECT)
        return self.folder_of(project_id) if row["parent_id"] else self.folder_of(project_id) / canvas_folder(row["canvas_name"])

    def folder_of(self, project_id):
        """The folder of a project (holding its Main canvas and its modules' folders), or of a module (inside its
        project's): what is renamed with it and deleted with it."""
        row = self.db.one("SELECT id, name, parent_id FROM projects WHERE id = ?", (project_id,)) if project_id else None
        if row is None:
            return Path(NO_PROJECT)
        if row["parent_id"]:
            parent = self.db.one("SELECT id, name FROM projects WHERE id = ?", (row["parent_id"],))
            return Path(label(parent)) / label(row) if parent else Path(label(row))
        return Path(label(row))

    def settle(self, user_id, project_id, path):
        """Put a file of a user's work into the folder of its project, if it is not there, and return its path inside
        the user's folder ("Pocket Film (6)/shot.png"), which is what an item records as its filename."""
        home = self.folder(user_id)
        target_dir = home / self.relative(project_id)
        path = Path(path)
        if path.parent.resolve() != target_dir.resolve():
            target_dir.mkdir(parents=True, exist_ok=True)
            target = _free(target_dir / path.name)
            path.replace(target)
            _move_posters(path, target)
            path = target
        return path.relative_to(home).as_posix()

    def refile(self, user_id, item_id, project_id):
        """Move an item's file into the folder of `project_id` (an item moved to another project) and record it."""
        row = self.db.one("SELECT filename FROM generations WHERE id = ?", (item_id,))
        if row is None:
            return
        path = self.folder(user_id) / row["filename"]
        if path.is_file():
            self.db.run("UPDATE generations SET filename = ? WHERE id = ?", (self.settle(user_id, project_id, path), item_id))

    def rename(self, user_id, before, after):
        """A project or module was renamed: its folder (`before`, a path inside the user's folder) becomes `after`, and
        its items' recorded paths with it."""
        if before == after:
            return
        home = self.folder(user_id)
        if (home / before).is_dir():
            (home / after).parent.mkdir(parents=True, exist_ok=True)
            if (home / after).exists():   # a folder of that name is there already: what is in the old one joins it
                for path in (home / before).rglob("*"):
                    if path.is_file():
                        dest = home / after / path.relative_to(home / before)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        path.replace(dest)
                shutil.rmtree(home / before, ignore_errors=True)
            else:
                (home / before).rename(home / after)
        old, new = before.as_posix() + "/", after.as_posix() + "/"
        for row in self.db.all("SELECT id, filename FROM generations WHERE user_id = ?", (user_id,)):
            if row["filename"].startswith(old):
                self.db.run("UPDATE generations SET filename = ? WHERE id = ?", (new + row["filename"][len(old):], row["id"]))

    def remove_folder(self, user_id, relative):
        """Delete what is left of a project's or module's folder (it goes with the project or module)."""
        target = self.folder(user_id) / relative
        if relative.parts and relative.parts[0] != NO_PROJECT and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    def file_all(self):
        """Put every item that is not in its project's folder (saved before projects had folders, by an older copy of
        the app, or before the Main canvas folder) into it. Done at every start; an item in its place is not touched,
        and one whose file is missing keeps its name."""
        moved, places, emptied = 0, {}, set()
        for row in self.db.all("SELECT id, user_id, project_id, filename FROM generations"):
            if row["project_id"] not in places:
                places[row["project_id"]] = self.relative(row["project_id"]).as_posix()
            if row["filename"].rpartition("/")[0] == places[row["project_id"]]:
                continue
            path = self.folder(row["user_id"]) / row["filename"]
            if path.is_file():
                self.db.run("UPDATE generations SET filename = ? WHERE id = ?", (self.settle(row["user_id"], row["project_id"], path), row["id"]))
                emptied.add(path.parent / ".posters")
                moved += 1
        for posters in emptied:   # a .posters folder its files' posters all left
            try:
                posters.rmdir()
            except OSError:
                pass
        return moved


def _free(path):
    """`path`, or the same name with a number when a file is there already."""
    if not path.exists():
        return path
    for n in range(2, 10000):
        candidate = path.with_name("{}_{}{}".format(path.stem, n, path.suffix))
        if not candidate.exists():
            return candidate
    return path


def _move_posters(old, new):
    """A file's poster and keyframes (.posters/<name>.jpg, .posters/<name>.<tenth>.jpg) follow it."""
    posters = old.parent / ".posters"
    if not posters.is_dir():
        return
    for made in list(posters.glob(glob.escape(old.name) + "*.jpg")):
        dest = new.parent / ".posters" / (new.name + made.name[len(old.name):])
        dest.parent.mkdir(exist_ok=True)
        made.replace(dest)
