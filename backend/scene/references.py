"""Reference files (images, videos, audio) that jobs use as inputs."""

import hashlib
import mimetypes
import re
from pathlib import Path

UPLOAD_PREFIX = "scene_"
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


async def upload_reference(comfy, filename, data, mime=None):
    """Put a file into the render server's input folder. The stored name includes a hash of the
    content, so two different files with the same name never overwrite each other."""
    stored = "{}{}_{}".format(UPLOAD_PREFIX, hashlib.sha1(data).hexdigest()[:10], safe_name(filename))
    return await comfy.upload(stored, data, mime or mimetypes.guess_type(stored)[0])
