"""While the render server is off, renders wait in the queue instead of failing one after another, and a render cut off
by it going away goes back in the queue, its credits still held, and runs again when the server answers."""

import time

import httpx

from scene import jobs as jobs_module
from test_api import post_job, register


def until(check, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        found = check()
        if found:
            return found
        time.sleep(0.2)
    return check()


def test_renders_wait_while_the_render_server_is_off(client):
    register(client)
    manager = client.app.state.jobs
    manager.hold_offline = True                     # as on a real studio; the tests' render server never answers
    before = client.get("/api/auth/me").json()["credits"]
    job = post_job(client).json()
    seen = until(lambda: next((j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job["id"] and j.get("waiting_for_server")), None))
    assert seen and seen["status"] == "queued"
    time.sleep(1)
    assert client.app.state.db.one("SELECT status FROM jobs WHERE id = ?", (job["id"],))["status"] == "queued"   # not failed
    assert client.get("/api/auth/me").json()["credits"] == before - job["credits"]                                  # still held
    manager.hold_offline = False


def test_a_render_cut_off_goes_back_in_the_queue_and_runs_again(client, monkeypatch):
    register(client)
    manager = client.app.state.jobs
    tries = []

    async def up():
        return True

    async def run(job):
        tries.append(job["id"])
        if len(tries) == 1:
            raise httpx.ConnectError("the render server went away")
    monkeypatch.setattr(manager, "_render_server_up", up)
    monkeypatch.setattr(manager, "_run", run)
    manager.hold_offline = True
    before = client.get("/api/auth/me").json()["credits"]
    job = post_job(client).json()
    row = until(lambda: (lambda r: r if r["status"] == "done" else None)(client.app.state.db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))), 30)
    assert row and row["resumes"] == 1 and len(tries) == 2
    assert client.get("/api/auth/me").json()["credits"] == before - job["credits"]   # charged once, never refunded
    manager.hold_offline = False


def test_it_gives_up_after_a_few_tries(client, monkeypatch):
    register(client)
    manager = client.app.state.jobs

    async def up():
        return True

    async def run(job):
        raise httpx.ConnectError("gone again")
    monkeypatch.setattr(manager, "_render_server_up", up)
    monkeypatch.setattr(manager, "_run", run)
    manager.hold_offline = True
    job = post_job(client).json()
    row = until(lambda: (lambda r: r if r["status"] == "failed" else None)(client.app.state.db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))), 30)
    assert row and row["resumes"] == jobs_module.RESUMES and "Lost the connection" in row["error"]
    manager.hold_offline = False
