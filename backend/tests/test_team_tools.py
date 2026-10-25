"""The console's roles an admin makes for the team (staff.py), and Bulk generation on the canvas (api/bulk.py): one prompt
sent to many workflows at once, free, for admins only."""

import json

from test_api import ADMIN, console, register

BOB = {"name": "Bob", "email": "bob@example.com", "password": "correct horse 2"}


def test_an_admin_makes_a_role_and_gives_it_to_someone(client):
    register(client)   # the first account is the admin
    bob = register(client, **BOB)
    desk = console(client)
    roles = {r["id"]: r for r in desk.get("/api/admin/roles").json()["roles"]}
    assert {"admin", "support", "finance", "moderator"} <= set(roles) and roles["admin"]["fixed"]
    made = desk.put("/api/admin/roles/new", json={"label": "QA testers", "about": "Tries the workflows",
                                                   "read": ["overview", "workflows", "roles", "settings"], "write": ["workflows", "users"]}).json()
    qa = next(r for r in made["roles"] if r["id"] == made["id"])
    assert made["id"] == "qa_testers" and qa["read"] == ["overview", "workflows"] and qa["write"] == ["workflows"]   # never Roles or Settings
    assert desk.put("/api/admin/users/{}".format(bob["id"]), json={"role": "qa_testers"}).status_code == 200
    assert desk.delete("/api/admin/roles/qa_testers").status_code == 400                                  # Bob has it

    bobs = console(client, BOB)
    me = bobs.get("/api/console/me").json()
    assert me["role_label"] == "QA testers" and me["sections"] == ["overview", "workflows"]
    assert bobs.get("/api/admin/workflows").status_code == 200
    assert bobs.get("/api/admin/users").status_code == 403
    assert bobs.get("/api/admin/roles").status_code == 403
    assert bobs.put("/api/admin/roles/qa_testers", json={"label": "QA", "read": ["users"]}).status_code == 403

    desk = console(client)
    desk.put("/api/admin/roles/support", json={"label": "Helpers", "read": ["overview", "users"], "write": []})
    assert next(r for r in desk.get("/api/admin/roles").json()["roles"] if r["id"] == "support")["label"] == "Helpers"
    desk.put("/api/admin/users/{}".format(bob["id"]), json={"role": "user"})
    assert desk.delete("/api/admin/roles/qa_testers").status_code == 200
    assert "qa_testers" not in [r["id"] for r in desk.get("/api/admin/roles").json()["roles"]]


def test_bulk_generation_queues_one_free_job_per_workflow_on_the_canvas(client):
    register(client)   # the admin
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    listed = {w["id"]: w for w in client.get("/api/bulk/workflows?kind=image").json()["workflows"]}
    assert "image/image_t2i_hunyuan_image_21" in listed and listed["image/image_t2i_flux2_klein_9b"]["needs_pictures"] == 0
    before = client.get("/api/auth/me").json()["credits"]
    done = client.post("/api/bulk", data={"kind": "image", "prompt": "a red fox in snow", "quality": "draft", "project_id": str(film),
                                          "workflows": json.dumps(["image/image_t2i_hunyuan_image_21", "image/image_t2i_flux2_klein_9b"])})
    assert done.status_code == 200, done.text
    assert done.json()["queued"] == 2
    jobs = client.app.state.db.all("SELECT cost, project_id, settings FROM jobs")
    assert len(jobs) == 2 and all(j["cost"] == 0 and j["project_id"] == film for j in jobs)        # free, on this canvas
    assert json.loads(jobs[0]["settings"])["options"]["quality"] == "draft"
    assert client.get("/api/auth/me").json()["credits"] == before
    assert client.post("/api/bulk", data={"kind": "image", "prompt": "x", "workflows": "[]"}).status_code == 400


def test_a_bulk_run_is_a_grid_of_prompts_by_workflows_on_one_seed(client):
    register(client)
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    wfs = ["image/image_t2i_hunyuan_image_21", "image/image_t2i_flux2_klein_9b"]
    client.app.state.jobs.pause(True)   # nothing renders: the grid is looked at as it was queued
    done = client.post("/api/bulk", data={"kind": "image", "prompts": json.dumps(["a red fox", "a blue whale"]), "workflows": json.dumps(wfs),
                                          "takes": "2", "same_seed": "1", "project_id": str(film)}).json()
    assert done["queued"] == 8 and done["run"].startswith("bulk-")
    grid = client.get("/api/bulk/runs/" + done["run"]).json()
    assert grid["prompts"] == ["a red fox", "a blue whale"] and [w["id"] for w in grid["workflows"]] == wfs and grid["takes"] == 2
    seeds = {(c["take"], c["seed"]) for c in grid["cells"]}
    assert len(seeds) == 2 and all(seed for _, seed in seeds)   # one seed per take, shared by every cell of it
    assert client.get("/api/bulk/runs").json()["runs"][0]["cells"] == 8
    assert client.delete("/api/bulk/runs/" + done["run"]).json()["stopped"] == 8
    cell = client.get("/api/bulk/runs/" + done["run"]).json()["cells"][0]
    again = client.post("/api/bulk/runs/{}/again".format(done["run"]), json={"job": cell["job"]}).json()["job"]
    cells = client.get("/api/bulk/runs/" + done["run"]).json()["cells"]
    assert len(cells) == 8 and any(c["job"] == again and c["status"] == "queued" and c["seed"] == cell["seed"] for c in cells)
    assert client.get("/api/bulk/runs/bulk-0000000000").status_code == 404
    client.app.state.jobs.pause(False)


def test_bulk_generation_is_for_admins_only(client):
    register(client)
    register(client, **BOB)   # signed in as Bob now, who is not an admin
    assert client.get("/api/bulk/workflows?kind=image").status_code == 403
    assert client.post("/api/bulk", data={"kind": "image", "prompt": "x", "workflows": json.dumps(["image/image_t2i_hunyuan_image_21"])}).status_code == 403
