"""The admin console's Workflows: the versions the render PC hands over and what changed, what a workflow needs that the
render server lacks, who a workflow is offered to, and test runs."""

import json

from scene import versions
from test_api import ADMIN, console, post_job, register

BOB = {"email": "bob@example.com", "password": "another one"}


class Folder:
    """A stand-in for the catalog: workflow files in one folder, each with its presets file beside it."""

    def __init__(self, path):
        self.path = path

    def files(self):
        return {"image/" + p.stem: p for p in sorted(self.path.glob("*.json")) if not p.name.endswith(".studio.json")}

    def sidecar_of(self, path):
        return path.with_name(path.stem + ".studio.json")


def graph(steps=20, sampler="KSampler"):
    return json.dumps({"3": {"class_type": sampler, "inputs": {"steps": steps, "model": ["4", 0]}, "_meta": {"title": "Sampler"}},
                       "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}}})


def test_versions_record_what_arrived_and_say_what_changed(tmp_path):
    from scene.db import Database
    folder = tmp_path / "wf"
    folder.mkdir()
    (folder / "one.json").write_text(graph(), encoding="utf-8")
    (folder / "one.studio.json").write_text(json.dumps({"title": "One"}), encoding="utf-8")
    db = Database(tmp_path / "scene.db")
    shelf = versions.Shelf(db, Folder(folder), tmp_path / "kept")
    held = []
    assert shelf.scan(now=100) == [("image/one", "first")]          # what was there when the record began
    assert shelf.scan(now=110) == []                                 # nothing changed: nothing is read again
    (folder / "one.json").write_text(graph(steps=30), encoding="utf-8")
    (folder / "one.studio.json").write_text(json.dumps({"title": "One, faster"}), encoding="utf-8")
    (folder / "two.json").write_text(graph(sampler="KSamplerAdvanced"), encoding="utf-8")
    assert sorted(shelf.scan(now=200, new_admins_only=held.append)) == [("image/one", "updated"), ("image/two", "new")]
    assert held == ["image/two"]                                     # only a new one is held back, when asked
    (folder / "two.json").unlink()
    assert shelf.scan(now=300) == [("image/two", "removed")]
    drops = shelf.drops()
    assert drops["since"] == 100 and [(d["seen"], d["new"], d["updated"], d["removed"]) for d in drops["drops"]] == [
        (300, [], [], ["image/two"]), (200, ["image/two"], ["image/one"], [])]
    newest, first = shelf.history("image/one")
    assert (newest["change"], first["change"], first["changes"]) == ("updated", "first", [])
    assert newest["changes"] == ["Node 3 (Sampler): steps: 20 → 30", 'Presets: title "One" → "One, faster"']
    assert [v["change"] for v in shelf.history("image/two")] == ["removed", "new"]


def test_a_changed_graph_reads_node_by_node():
    old = {"file": "a.json", "presets": "", "graph": json.dumps({"nodes": [
        {"id": 1, "type": "KSampler", "widgets_values": [20, "euler"], "mode": 0},
        {"id": 2, "type": "LoraLoader", "widgets_values": ["x.safetensors"], "mode": 0}]})}
    new = {"file": "a.json", "presets": "", "graph": json.dumps({"nodes": [
        {"id": 1, "type": "KSampler", "widgets_values": [24, "euler"], "mode": 4},
        {"id": 3, "type": "VAEDecode", "widgets_values": [], "mode": 0}]})}
    assert versions.diff(old, new) == ["Added Node 3 (VAEDecode)", "Removed Node 2 (LoraLoader)",
                                       "Node 1 (KSampler): on → bypassed", 'Node 1 (KSampler): [20, "euler"] → [24, "euler"]']


def test_what_the_render_server_lacks_is_named():
    info = {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["base.safetensors", "sdxl\\turbo.safetensors"]]}}},
            "UNETLoader": {"input": {"required": {"unet_name": ["COMBO", {"options": ["flux.safetensors"]}]}}}}
    wf = {"nodes": {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl/turbo.safetensors"}},
                    "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "gone.safetensors"}},
                    "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "other.safetensors"}},
                    "4": {"class_type": "SceneCustomNode", "inputs": {}},
                    "5": {"class_type": "MissingButBypassed", "inputs": {}},
                    "6": {"class_type": "Note", "inputs": {}}},
          "info": {"5": {"mode": 4}}}
    assert versions.missing(wf, info) == {"nodes": ["SceneCustomNode"], "files": [
        {"node": "2", "type": "CheckpointLoaderSimple", "input": "ckpt_name", "file": "gone.safetensors"},
        {"node": "3", "type": "UNETLoader", "input": "unet_name", "file": "other.safetensors"}]}
    assert versions.missing(wf, None) is None                       # no node list: nothing can be said


def test_a_workflow_can_be_tried_by_admins_before_users_see_it(client):
    register(client)
    desk = console(client)
    report = desk.get("/api/admin/workflows").json()
    assert report["since"] and report["drops"] == []
    h3 = next(w for w in report["workflows"] if w["id"] == "video/h3_master")
    assert h3["audience"] == "everyone" and h3["versions"] == 1 and h3["example"] > 0 and isinstance(h3["missing"], dict)
    assert desk.put("/api/admin/workflows/audience", json={"workflow": "video/h3_master", "audience": "nobody"}).status_code == 400
    assert desk.put("/api/admin/workflows/audience", json={"workflow": "video/h3_master", "audience": "admins"}).json()["audience"] == "admins"
    ids = lambda: [w["id"] for w in client.get("/api/workflows").json()["workflows"]]
    assert "video/h3_master" in ids()                                # the admin sees it
    assert post_job(client).status_code == 200
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json=BOB)
    assert "video/h3_master" not in ids()                            # a user does not, and can't use it
    assert post_job(client).status_code == 400
    desk.put("/api/admin/workflows/audience", json={"workflow": "video/h3_master", "audience": "everyone"})
    assert "video/h3_master" in ids()
    desk.put("/api/admin/workflows/audience", json={"workflow": "video/h3_master", "audience": "off"})
    assert "video/h3_master" not in ids()
    pricing = next(w for w in desk.get("/api/admin/pricing").json()["workflows"] if w["id"] == "video/h3_master")
    assert pricing["enabled"] is False and pricing["admins_only"] is False
    assert desk.put("/api/admin/workflows/settings", json={"new_admins_only": True}).json() == {"new_admins_only": True}
    assert desk.get("/api/admin/workflows").json()["new_admins_only"] is True
    assert [v["change"] for v in desk.get("/api/admin/workflows/history", params={"workflow": "video/h3_master"}).json()["versions"]] == ["first"]


def test_a_test_run_is_free_first_in_the_queue_and_runs_under_maintenance(client):
    me = register(client)
    desk = console(client)
    desk.put("/api/admin/queue", json={"paused": True})
    post_job(client)
    credits = client.get("/api/auth/me").json()["credits"]
    desk.put("/api/admin/maintenance", json={"on": True})
    test = desk.post("/api/admin/workflows/test", json={"workflow": "video/h3_master"})
    assert test.status_code == 200 and test.json()["name"].startswith("Test · ")
    job = client.app.state.db.one("SELECT * FROM jobs WHERE id = ?", (test.json()["id"],))
    assert job["user_id"] == me["id"] and job["cost"] == 0 and job["priority"] == 100 and job["status"] == "queued"
    assert json.loads(job["settings"])["test"] is True and json.loads(job["settings"])["prompt"]
    assert client.get("/api/auth/me").json()["credits"] == credits
    waiting = desk.get("/api/admin/overview").json()["queue"]["waiting"]
    assert waiting[0]["id"] == test.json()["id"]                     # ahead of the job that was there first
    assert desk.post("/api/admin/workflows/test", json={"workflow": "video/nothing"}).status_code == 400
    assert "Test run of a workflow" in [a["action"] for a in desk.get("/api/admin/audit").json()["entries"]]
