"""A project's analytics (what it spent and made, by day, kind and module) and duplicating a project."""

import time

from test_api import console, post_job, register


def test_a_projects_spend_by_kind_and_module(client):
    me = register(client)
    console(client).put("/api/admin/queue", json={"paused": True})   # jobs stay charged while they wait
    film = client.post("/api/projects", json={"name": "Pocket"}).json()["id"]
    one = client.post("/api/projects", json={"name": "Episode 1", "parent_id": film}).json()["id"]
    assert post_job(client, project_id=one).status_code == 200
    assert post_job(client, project_id=film).status_code == 200
    client.app.state.credits.charge(me["id"], 3, "agent", note="local:9b", project_id=one)    # a message to the agent
    client.app.state.db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, project_id) "
                            "VALUES (?, 'video/h3_master', 'video', 'Shot', 'shot.mp4', '{}', '{}', ?, ?)", (me["id"], time.time(), one))
    found = client.get("/api/projects/{}/analytics?period=today".format(one)).json()   # a module's address shows its project
    assert found["project"] == {"id": film, "name": "Pocket"} and found["period"] == "today"
    assert found["spend"] == 203 and found["generations"] == 1 and found["contributors"] == 1 and found["change"] is None
    kinds = {t["id"]: (t["credits"], t["generations"]) for t in found["types"]}
    assert kinds["video"] == (200, 1) and kinds["llm"] == (3, 0)
    assert len(found["days"]) == 1 and found["daily"][0]["video"] == 200
    rows = {r["name"]: r for r in found["modules"]}
    assert rows["Episode 1"]["credits"] == 103 and rows["Episode 1"]["asset_types"] == 2 and rows["Episode 1"]["first"]
    assert rows["Module 1"]["credits"] == 100 and found["modules"][0]["name"] == "Episode 1"   # the most spent first
    assert len(client.get("/api/projects/{}/analytics?period=30".format(film)).json()["days"]) == 30
    csv = client.get("/api/projects/{}/analytics.csv?period=today".format(film))
    assert csv.headers["content-type"].startswith("text/csv") and "Episode 1" in csv.text
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    assert client.get("/api/projects/{}/analytics".format(film)).status_code == 404               # not another's


def test_duplicating_a_project_copies_its_modules_and_kit(client):
    register(client)
    film = client.post("/api/projects", json={"name": "Pocket"}).json()["id"]
    client.post("/api/projects", json={"name": "Episode 1", "parent_id": film})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    client.post("/api/kit", files={"file": ("anna.png", png, "image/png")}, data={"name": "Anna", "type": "character", "project_id": str(film)})
    copy = client.post("/api/projects/{}/duplicate".format(film)).json()
    assert copy["name"] == "Pocket copy"
    page = client.get("/api/projects/{}".format(copy["id"])).json()
    assert [m["name"] for m in page["modules"] if not m.get("main")] == ["Episode 1"]
    entries = client.get("/api/kit?project={}".format(copy["id"])).json()["entries"]
    assert [e["name"] for e in entries] == ["Anna"] and client.get("/api/assets/{}/file".format(entries[0]["id"])).content == png


def test_deleting_a_module_or_project_deletes_everything_in_it(client):
    from test_api import console
    me = register(client)
    db, state = client.app.state.db, client.app.state
    console(client).put("/api/admin/queue", json={"paused": True})
    folder = state.outputs.folder(me["id"])
    (folder / ".posters").mkdir(parents=True, exist_ok=True)
    film = client.post("/api/projects", json={"name": "Pocket"}).json()["id"]
    one = client.post("/api/projects", json={"name": "Episode 1", "parent_id": film}).json()["id"]
    other = client.post("/api/projects", json={"name": "Another"}).json()["id"]

    def item(name, project):
        (folder / name).write_bytes(b"x" * 100)
        (folder / ".posters" / (name + ".jpg")).write_bytes(b"p")
        (folder / ".posters" / (name + ".15.jpg")).write_bytes(b"f")   # a keyframe of a video
        return db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, project_id) "
                      "VALUES (?, 'video/x', 'video', ?, ?, '{}', '{}', 1, ?)", (me["id"], name, name, project))
    in_module, in_project, elsewhere = item("a.mp4", one), item("b.mp4", film), item("c.mp4", other)
    for project in (film, one):
        db.run("INSERT INTO boards (user_id, project_id, kind, data, updated) VALUES (?, ?, 'canvas', '{}', 1)", (me["id"], project))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    client.post("/api/kit", files={"file": ("anna.png", png, "image/png")}, data={"name": "Anna", "type": "character", "project_id": str(film)})
    before = client.get("/api/auth/me").json()["credits"]
    waiting = post_job(client, project_id=one).json()

    gone = client.delete("/api/projects/{}".format(one)).json()                           # a module
    assert gone["items_deleted"] == 1 and not (folder / "a.mp4").exists()
    assert not list((folder / ".posters").glob("a.mp4*"))                                  # its poster and keyframes too
    assert db.one("SELECT 1 FROM generations WHERE id = ?", (in_module,)) is None
    assert db.one("SELECT status FROM jobs WHERE id = ?", (waiting["id"],))["status"] == "cancelled"
    assert client.get("/api/auth/me").json()["credits"] == before                          # its credits came back
    assert client.get("/api/kit?project={}".format(film)).json()["entries"]               # the project's NeuralCore stays

    assert client.delete("/api/projects/{}".format(film)).json()["items_deleted"] == 1    # the project
    assert not (folder / "b.mp4").exists() and db.one("SELECT 1 FROM generations WHERE id = ?", (in_project,)) is None
    assert db.all("SELECT 1 FROM assets WHERE user_id = ?", (me["id"],)) == []             # its NeuralCore went with it
    assert db.all("SELECT 1 FROM boards WHERE user_id = ?", (me["id"],)) == []
    assert (folder / "c.mp4").exists() and db.one("SELECT 1 FROM generations WHERE id = ?", (elsewhere,))   # not another's


def test_a_render_that_finishes_after_its_project_was_deleted_is_not_kept(client, tmp_path):
    me = register(client)
    manager = client.app.state.jobs
    target = tmp_path / "late.png"
    target.write_bytes(b"x")
    manager._record({"id": "j1", "user_id": me["id"], "project_id": 999, "workflow": "image/x", "name": "Late", "summary": "",
                     "settings": {}, "started": 1}, "image", target, {})
    assert not target.exists() and client.app.state.db.one("SELECT 1 FROM generations WHERE job_id = 'j1'") is None
