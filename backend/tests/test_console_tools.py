"""More of the admin console: where people are signed in, the projects and their kits, search, the backup read back,
the sealed audit log, the health strip and the queue counts the console is sent."""

import json

from scene import audit, backup
from test_api import ADMIN, console, post_job, register

BOB = {"email": "bob@example.com", "password": "another one"}


def test_where_someone_is_signed_in_and_signing_them_out(client):
    register(client)
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json=BOB, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/141.0"}).json()
    desk = console(client)
    sessions = desk.get("/api/admin/users/{}".format(bob["id"])).json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["console"] == 0 and "Chrome" in sessions[0]["agent"] and len(sessions[0]["key"]) == 12
    assert "token_hash" not in sessions[0] and sessions[0]["here"] is False
    assert client.get("/api/auth/me").status_code == 200
    assert desk.post("/api/admin/users/{}/sign-out".format(bob["id"]), json={"key": "nothex"}).status_code == 400
    assert desk.post("/api/admin/users/{}/sign-out".format(bob["id"]), json={"key": sessions[0]["key"]}).json() == {"ended": 1}
    assert client.get("/api/auth/me").status_code == 401
    # Everywhere, for the admin too: but this console's own session stays.
    me = desk.get("/api/console/me").json()
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    mine = desk.get("/api/admin/users/{}".format(me["id"])).json()["sessions"]
    assert {(s["console"], s["here"]) for s in mine} == {(0, False), (1, True)}
    assert desk.post("/api/admin/users/{}/sign-out".format(me["id"]), json={}).json() == {"ended": 1}
    assert client.get("/api/auth/me").status_code == 401 and desk.get("/api/console/me").status_code == 200
    assert "Signed a user out" in [a["action"] for a in desk.get("/api/admin/audit").json()["entries"]]


def test_projects_and_their_kits_and_search(client):
    me = register(client)
    film = client.post("/api/projects", json={"name": "Pocket Film"}).json()["id"]
    client.post("/api/projects", json={"name": "Episode 1", "parent_id": film})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    entry = client.post("/api/kit", files={"file": ("anna.png", png, "image/png")}, data={"name": "Anna", "type": "character", "project_id": str(film)}).json()
    desk = console(client)
    listed = desk.get("/api/admin/projects").json()["projects"]
    assert [(p["name"], p["modules"], p["kit"], p["user_email"]) for p in listed] == [("Pocket Film", 1, 1, ADMIN["email"])]
    assert desk.get("/api/admin/projects?q=nothing").json()["projects"] == []
    detail = desk.get("/api/admin/projects/{}".format(film)).json()
    assert [m["name"] for m in detail["modules"]] == ["Episode 1"]
    assert [(k["name"], k["type"]) for k in detail["kit"]] == [("Anna", "character")]
    assert desk.get("/api/admin/assets/{}/file".format(entry["id"])).content == png
    assert desk.get("/api/admin/assets/999/file").status_code == 404
    found = desk.get("/api/admin/search", params={"q": "pocket"}).json()
    assert [p["name"] for p in found["projects"]] == ["Pocket Film"] and found["users"] == []
    assert [u["id"] for u in desk.get("/api/admin/search", params={"q": "ada@"}).json()["users"]] == [me["id"]]
    assert desk.get("/api/admin/search", params={"q": "h3"}).json()["workflows"]
    assert desk.get("/api/admin/search", params={"q": "a"}).json() == {"users": [], "jobs": [], "projects": [], "workflows": []}


def test_the_newest_backup_is_read_back(client, tmp_path):
    register(client)
    state = client.app.state
    assert backup.check(state.db, tmp_path)["detail"] == "There is no copy yet."
    backup.make(state.db, tmp_path / "copies")
    found = backup.check(state.db, tmp_path / "copies")
    assert found["ok"] is True and ("1 accounts" in found["detail"] or "pg_restore reads it" in found["detail"])
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ("scene_2026-10-23" + state.db.suffix)).write_bytes(b"not a database at all" * 100)
    bad = backup.check(state.db, broken)
    assert bad["ok"] is False and backup.last_check(state.db)["ok"] is False
    import asyncio
    from scene import health
    assert any(p["key"] == "backup_check" for p in asyncio.run(health.problems(state)))   # it becomes an alert


def test_the_audit_log_is_sealed(client):
    register(client)
    desk = console(client)
    desk.put("/api/admin/queue", json={"paused": True})
    checked = desk.get("/api/admin/audit/verify").json()
    assert checked["ok"] is True and checked["sealed"] >= 3 and checked["missing"] == 0
    db = client.app.state.db
    row = db.one("SELECT id FROM audit_log WHERE action = 'Paused the renders'")
    db.run("UPDATE audit_log SET detail = 'nothing happened' WHERE id = ?", (row["id"],))
    broken = audit.verify(db)
    assert broken["ok"] is False and broken["broken"]["id"] == row["id"]
    db.run("UPDATE audit_log SET detail = '' WHERE id = ?", (row["id"],))
    assert audit.verify(db)["ok"] is True
    last = db.one("SELECT MAX(id) AS id FROM audit_log")["id"]
    db.run("DELETE FROM audit_log WHERE id = ?", (last,))           # an entry cut from the end
    assert audit.verify(db)["missing"] == 1


def test_the_overview_has_a_health_summary_and_the_console_hears_the_queue(client):
    register(client)
    desk = console(client)
    desk.put("/api/admin/queue", json={"paused": True})
    post_job(client)
    health = desk.get("/api/admin/overview").json()["health"]
    assert health["render"] is False and health["model"] is False and health["alerts"] == 0 and health["disk_free"] > 0
    assert health["maintenance"] is False and "node_list" in health
    assert client.app.state.hub.queue() == {"running": 0, "waiting": 1}
    with desk.websocket_connect("/api/console/events") as ws:
        first, second = json.loads(ws.receive_text()), json.loads(ws.receive_text())
        said = {**first, **second}
        assert said["jobs"] == {"running": 0, "waiting": 1} and said["alerts"] == 0 and said["online_users"] == 0
