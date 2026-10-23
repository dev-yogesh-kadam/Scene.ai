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


# What the user brings that is words, filed as "text": a script (.docx, .txt, .md) or a transcript (.srt, .json).
# A Word document is kept as the plain text of it.
TEXT_SUFFIXES = {".srt", ".json", ".txt", ".md", ".docx"}
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_DOCX_BYTES = 25 * 1024 * 1024          # a Word file with pictures in it is larger than its words
MAX_DOCX_XML = 30 * 1024 * 1024            # the document part, unpacked: a file that unpacks larger is refused
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def text_kind(filename):
    return "text" if Path(filename or "").suffix.lower() in TEXT_SUFFIXES else None


def docx_text(data):
    """The words of a Word document (.docx), paragraph by paragraph, tabs and line breaks kept. Raises ValueError when
    it is not one."""
    import io
    import zipfile
    from xml.etree import ElementTree
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            part = package.getinfo("word/document.xml")
            if part.file_size > MAX_DOCX_XML:
                raise ValueError("its text is too large")
            root = ElementTree.fromstring(package.read(part))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise ValueError("it is not a Word document")
    lines = []
    for paragraph in root.iter(WORD + "p"):
        words = []
        for node in paragraph.iter():
            if node.tag == WORD + "t":
                words.append(node.text or "")
            elif node.tag == WORD + "tab":
                words.append("\t")
            elif node.tag in (WORD + "br", WORD + "cr"):
                words.append("\n")
        lines.append("".join(words))
    return "\n".join(lines).strip() + "\n"


async def read_text_upload(upload):
    """The words of an uploaded script or transcript, as (UTF-8 bytes, the file name to keep them under). A Word file
    becomes its plain text (.txt); anything else must be text — UTF-8, with no NUL bytes — whatever its name says.
    At most 5 MB of text."""
    label = upload.filename or "The file"
    docx = Path(upload.filename or "").suffix.lower() == ".docx"
    most = MAX_DOCX_BYTES if docx else MAX_TEXT_BYTES
    if (upload.size or 0) > most:
        raise HTTPException(413, "{} is larger than {} MB.".format(label, most // (1024 * 1024)))
    data = await upload.read()
    if len(data) > most:
        raise HTTPException(413, "{} is larger than {} MB.".format(label, most // (1024 * 1024)))
    name = upload.filename or "text.txt"
    if docx:
        try:
            data = docx_text(data).encode("utf-8")
        except ValueError as error:
            raise HTTPException(400, "{} could not be read: {}.".format(label, error))
        name = Path(name).stem + ".txt"
        if len(data) > MAX_TEXT_BYTES:
            raise HTTPException(413, "The text of {} is larger than 5 MB.".format(label))
    try:
        if b"\x00" in data:
            raise UnicodeError
        data.decode("utf-8-sig")
    except UnicodeError:
        raise HTTPException(400, "{} is not a text file.".format(label))
    return data, name


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
        db.run("INSERT INTO uploads (user_id, name, created) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (user_id, name, time.time()))
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
