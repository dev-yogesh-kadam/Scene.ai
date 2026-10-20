"""Bringing a picture, clip or sound in from a link on another site, for the library (a link in the chat, a row of a
shot tracker).

The server fetches it, so a link must never reach the studio's own network or the render PC: only http and https, only
public addresses — every address the name resolves to is checked before connecting, again at every redirect, and the
address actually connected to is checked before the body is read — at most MAX_BYTES, read as it streams, and the
content must be an image, a video or a sound by its first bytes, whatever the link or the server says it is.
"""

import asyncio
import ipaddress
import socket
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from .references import KINDS, MAX_BYTES
from .security import sniff

REDIRECTS = 3
TIMEOUT = httpx.Timeout(60, connect=10)
EXTENSION = {"image": ".png", "video": ".mp4", "audio": ".mp3"}   # when the link's name has none of its kind


class FetchError(ValueError):
    pass


def _public(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def _check_host(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Only http and https links can be brought in.")
    if parts.username or parts.password:
        raise FetchError("A link with a name and password in it is not fetched.")
    try:
        found = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                                             type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError("{} could not be found.".format(parts.hostname))
    addresses = {info[4][0] for info in found}
    if not addresses or not all(_public(a) for a in addresses):
        raise FetchError("{} is not a public address: links into a private network are not fetched.".format(parts.hostname))


def _kind(data, url, content_type):
    found = sniff(data)
    if found == "video/audio":   # an MP4-family file: a sound when the link or the server says so
        suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
        return "audio" if suffix in KINDS["audio"] or (content_type or "").startswith("audio/") else "video"
    return found


def filename_for(url, kind):
    """A file name for what a link brought: the link's own name, with an extension of its kind."""
    name = PurePosixPath(urlsplit(url).path).name or kind
    if PurePosixPath(name).suffix.lower() not in KINDS[kind]:
        name = (PurePosixPath(name).stem or kind) + EXTENSION[kind]
    return name


async def fetch(url, client=None):
    """The file at a link: (bytes, kind, the link it finally came from). Raises FetchError with the reason."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "Scene.ai importer"})
    try:
        for _ in range(REDIRECTS + 1):
            await _check_host(url)
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                stream = response.extensions.get("network_stream")
                peer = stream.get_extra_info("server_addr") if stream is not None else None
                if peer and not _public(peer[0]):   # the name pointed somewhere else by the time it was connected to
                    raise FetchError("The link led into a private network: it was not fetched.")
                if response.status_code != 200:
                    raise FetchError("The link answered {}.".format(response.status_code))
                if int(response.headers.get("content-length") or 0) > MAX_BYTES:
                    raise FetchError("The file is larger than 200 MB.")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise FetchError("The file is larger than 200 MB.")
                kind = _kind(bytes(data[:16]), url, response.headers.get("content-type"))
                if kind not in ("image", "video", "audio"):
                    raise FetchError("The link is not an image, a video or a sound (a page, perhaps).")
                return bytes(data), kind, url
        raise FetchError("The link redirected more than {} times.".format(REDIRECTS))
    except httpx.HTTPError as error:
        raise FetchError("The link could not be fetched: {}".format(type(error).__name__))
    finally:
        if own:
            await client.aclose()
