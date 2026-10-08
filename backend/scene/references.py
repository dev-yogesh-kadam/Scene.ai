"""Reference files (images, videos, audio) that jobs use as inputs."""

import hashlib
import mimetypes
import re
import time
from pathlib import Path

from fastapi import HTTPException

from .security import content_matches

UPLOAD_PREFIX = "scene_"
# The names upload_reference gives, and nothing else: no folder, no way out of ComfyUI's input folder.
UPLOAD_NAME = re.compile(r"^scene_[0-9a-f]{10}_[\w.-]{1,200}$")
MAX_BYTES = 200 * 1024 * 1024
KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".webm", ".mov", ".mkv"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"},
}


def media_kind(filename):
    suffix = Path(filename or "").suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), None)


def safe_name(filename):
    return re.sub(r"[^\w.-]+", "_", Path(filename or "file").name) or "file"


async def read_upload(upload):
    """The bytes of an uploaded image, video or sound. A file that is too large is refused before it is read into
    memory, and one whose content is not what its name says (a page or a program named .png) is refused too."""
    label = upload.filename or "The file"
    kind = media_kind(upload.filename)
    if kind is None:
        raise HTTPException(400, "{} is not an image, video or audio file.".format(label))
    if (upload.size or 0) > MAX_BYTES:
        raise HTTPException(413, "{} is larger than 200 MB.".format(label))
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "{} is larger than 200 MB.".format(label))
    if not content_matches(kind, data):
        raise HTTPException(400, "{} is not the {} file its name says it is.".format(label, kind))
    return data


async def upload_reference(comfy, filename, data, mime=None, db=None, user_id=None):
    """Put a file into the render server's input folder. The stored name includes a hash of the
    content, so two different files with the same name never overwrite each other. With `db` and `user_id`,
    the name is remembered as that user's, so they and nobody else can use it again (see owns_upload)."""
    stored = "{}{}_{}".format(UPLOAD_PREFIX, hashlib.sha1(data).hexdigest()[:10], safe_name(filename)[:200])
    name = await comfy.upload(stored, data, mime or mimetypes.guess_type(stored)[0])
    if db is not None and user_id is not None:
        db.run("INSERT OR IGNORE INTO uploads (user_id, name, created) VALUES (?, ?, ?)", (user_id, name, time.time()))
    return name


def owns_upload(db, user_id, name):
    """Whether a file in the render server's input folder is one this user put there. A file sent before uploads
    were recorded counts when one of the user's own jobs used it."""
    name = str(name or "")
    if not UPLOAD_NAME.match(name):
        return False
    if db.one("SELECT 1 FROM uploads WHERE user_id = ? AND name = ?", (user_id, name)):
        return True
    like = '%"{}"%'.format(name.replace("_", r"\_"))   # the name has no other character LIKE reads specially
    return db.one("SELECT 1 FROM jobs WHERE user_id = ? AND settings LIKE ? ESCAPE '\\' LIMIT 1", (user_id, like)) is not None
