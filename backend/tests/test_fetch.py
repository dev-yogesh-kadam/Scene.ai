"""Bringing a file in from a link (fetch.py, POST /api/library/import): what is fetched, and what is refused."""

import asyncio

import httpx
import pytest

from scene import fetch
from test_api import register

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.png", "http://10.0.0.5/a.png", "http://192.168.1.4/a.png", "http://169.254.169.254/latest",
                                 "http://[::1]/a.png", "http://[::ffff:127.0.0.1]/a.png", "http://100.123.221.34:8188/view"])
def test_private_addresses_are_never_fetched(url):
    with pytest.raises(fetch.FetchError, match="not a public address"):
        run(fetch._check_host(url))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a.png", "http://user:pw@example.com/a.png", "nothing"])
def test_only_plain_web_links(url):
    with pytest.raises(fetch.FetchError):
        run(fetch._check_host(url))


def served(pages, monkeypatch):
    """A client whose web is `pages` (url -> response); every host counts as public except "internal"."""
    async def check(url):
        if "internal" in url:
            raise fetch.FetchError("internal is not a public address: links into a private network are not fetched.")
    monkeypatch.setattr(fetch, "_check_host", check)
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pages[str(request.url)]), follow_redirects=False)


def test_a_picture_is_fetched_and_a_page_is_not(monkeypatch):
    client = served({"https://cdn.example.com/maya.png": httpx.Response(200, content=PNG),
                     "https://example.com/page": httpx.Response(200, content=b"<html>hi</html>", headers={"content-type": "image/png"})}, monkeypatch)
    data, kind, final = run(fetch.fetch("https://cdn.example.com/maya.png", client))
    assert (data, kind, final) == (PNG, "image", "https://cdn.example.com/maya.png")
    with pytest.raises(fetch.FetchError, match="not an image"):   # what the server says it is does not count
        run(fetch.fetch("https://example.com/page", client))
    assert fetch.filename_for("https://cdn.example.com/x/Maya%20sheet", "image") == "Maya%20sheet.png"
    assert fetch.filename_for("https://cdn.example.com/x/clip.mov", "video") == "clip.mov"


def test_a_redirect_into_the_private_network_is_refused(monkeypatch):
    client = served({"https://example.com/a.png": httpx.Response(302, headers={"location": "http://internal/secret.png"}),
                     "http://internal/secret.png": httpx.Response(200, content=PNG)}, monkeypatch)
    with pytest.raises(fetch.FetchError, match="not a public address"):
        run(fetch.fetch("https://example.com/a.png", client))
    loop = {"https://example.com/loop": httpx.Response(302, headers={"location": "/loop"})}
    with pytest.raises(fetch.FetchError, match="redirected"):
        run(fetch.fetch("https://example.com/loop", served(loop, monkeypatch)))


def test_too_large_is_refused_as_it_streams(monkeypatch):
    monkeypatch.setattr(fetch, "MAX_BYTES", 100)
    client = served({"https://example.com/big.png": httpx.Response(200, content=PNG + b"\x00" * 200)}, monkeypatch)
    with pytest.raises(fetch.FetchError, match="larger"):
        run(fetch.fetch("https://example.com/big.png", client))


def test_the_import_endpoint_files_the_link_in_the_library(client, monkeypatch):
    register(client)

    async def fake_fetch(url, client=None):
        if "bad" in url:
            raise fetch.FetchError("The link answered 404.")
        return PNG, "image", url
    monkeypatch.setattr(fetch, "fetch", fake_fetch)
    made = client.post("/api/library/import", json={"url": "https://cdn.example.com/kabir_sheet.png", "name": "Kabir sheet"}).json()
    assert (made["kind"], made["name"], made["workflow"]) == ("image", "Kabir sheet", "upload/link")
    assert made["settings"]["source"] == "https://cdn.example.com/kabir_sheet.png"
    assert client.get(f"/api/library/{made['id']}/file").content == PNG
    assert client.post("/api/library/import", json={"url": "https://cdn.example.com/bad.png"}).status_code == 400
    assert client.post("/api/library/import", json={}).status_code == 400


def test_the_agent_brings_in_a_link_from_the_chat(client, monkeypatch):
    from test_agent_shots import hosted
    register(client)

    async def fake_fetch(url, client=None):
        return PNG, "image", url
    monkeypatch.setattr(fetch, "fetch", fake_fetch)
    seen = hosted(monkeypatch, client, {"tool": "import_url", "text": "https://cdn.example.com/emma.png", "query": "emma (base)"},
                  {"tool": "finish", "reply": "ok", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "here is emma: https://cdn.example.com/emma.png"}).json()
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any('"name": "emma (base)"' in t and '"item": ' in t for t in told)
    assert any(e.get("text") == "Brought in “emma (base)” from a link" for e in plan["activity"])
