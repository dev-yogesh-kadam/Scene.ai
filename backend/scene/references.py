"""Reference files (images, videos, audio) that jobs use as inputs."""

import hashlib
import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException

UPLOAD_PREFIX = "scene_"
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
    """The bytes of an uploaded file. One that is too large is refused before it is read into memory."""
    if (upload.size or 0) > MAX_BYTES:
        raise HTTPException(413, "{} is larger than 200 MB.".format(upload.filename or "The file"))
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "{} is larger than 200 MB.".format(upload.filename or "The file"))
    return data


async def upload_reference(comfy, filename, data, mime=None):
    """Put a file into the render server's input folder. The stored name includes a hash of the
    content, so two different files with the same name never overwrite each other."""
    stored = "{}{}_{}".format(UPLOAD_PREFIX, hashlib.sha1(data).hexdigest()[:10], safe_name(filename))
    return await comfy.upload(stored, data, mime or mimetypes.guess_type(stored)[0])
