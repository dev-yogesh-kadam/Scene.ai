ADMIN = {"name": "Ada", "email": "ada@example.com", "password": "correct horse"}


def test_everything_needs_a_sign_in(client):
    for path in ("/api/workflows", "/api/jobs", "/api/library", "/api/status", "/api/admin/users"):
        assert client.get(path).status_code == 401


def test_first_account_is_admin_and_later_ones_are_users(client):
    assert client.get("/api/auth/state").json() == {"first_run": True, "signup_open": True}
    assert client.post("/api/auth/register", json=ADMIN).json()["role"] == "admin"
    client.post("/api/auth/logout")
    second = client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    assert second.json()["role"] == "user"
    assert client.get("/api/admin/users").status_code == 403


def test_login_logout_and_wrong_password(client):
    client.post("/api/auth/register", json=ADMIN)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ADA@example.com", "password": ADMIN["password"]}).status_code == 200
    assert client.get("/api/auth/me").json()["email"] == ADMIN["email"]


def test_weak_or_duplicate_registration_is_refused(client):
    assert client.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "long enough"}).status_code == 400
    client.post("/api/auth/register", json=ADMIN)
    assert client.post("/api/auth/register", json=ADMIN).status_code == 409


def test_admin_can_close_signups(client):
    client.post("/api/auth/register", json=ADMIN)
    assert client.put("/api/admin/settings", json={"allow_signup": False}).json()["allow_signup"] is False
    client.post("/api/auth/logout")
    assert client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"}).status_code == 403


def test_workflow_catalog_and_form(client):
    client.post("/api/auth/register", json=ADMIN)
    catalog = client.get("/api/workflows").json()
    assert "video/h3_director" in [w["id"] for w in catalog["workflows"]]
    form = client.get("/api/workflows/video/h3_director").json()
    assert form["title"] == "H3 Director" and len(form["refs"]) == 11
    estimate = client.post("/api/estimate", json={"workflow": "video/h3_director"}).json()
    assert estimate["text"] == "about 2.3 min"


def test_a_job_with_an_empty_prompt_is_refused(client):
    client.post("/api/auth/register", json=ADMIN)
    response = client.post("/api/jobs", data={"settings": '{"workflow": "video/h3_director"}'})
    assert response.status_code == 400 and response.json()["detail"] == "The prompt is empty."


def test_users_only_see_their_own_jobs(client):
    client.post("/api/auth/register", json=ADMIN)
    settings = '{"workflow": "video/h3_director", "values": {"100:value": "She waves."}}'
    job_id = client.post("/api/jobs", data={"settings": settings}).json()["id"]
    assert [j["id"] for j in client.get("/api/jobs").json()["jobs"]] == [job_id]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    assert client.get("/api/jobs").json()["jobs"] == []
    assert client.delete("/api/jobs/" + job_id).status_code == 404


def register(client, **extra):
    return client.post("/api/auth/register", json={**ADMIN, **extra}).json()


JOB = {"workflow": "video/h3_director", "values": {"100:value": "She waves."}, "options": {"mode": "fast", "quality": "low"}}


def post_job(client, **extra):
    import json
    return client.post("/api/jobs", data={"settings": json.dumps({**JOB, **extra})})


def test_new_accounts_get_credits_and_jobs_cost_them(client):
    assert register(client)["credits"] == 500
    quote = client.post("/api/estimate", json=JOB).json()
    assert quote["credits"] == 9 and quote["balance"] == 500   # 0.9 min at 10 credits per minute
    assert post_job(client).json()["credits"] == 9
    assert client.get("/api/auth/me").json()["credits"] in (491, 500)  # charged; refunded once the job fails offline


def test_a_job_is_refused_without_enough_credits_and_admin_can_add_more(client):
    me = register(client)
    client.put("/api/admin/users/%d" % me["id"], json={"add_credits": -495})
    response = post_job(client)
    assert response.status_code == 402 and "9 credits and you have 5" in response.json()["detail"]
    assert client.put("/api/admin/users/%d" % me["id"], json={"add_credits": 100}).json()["credits"] == 105
    assert post_job(client).status_code == 200


def test_cancelling_a_waiting_job_refunds_it(client):
    register(client)
    first, second = post_job(client).json()["id"], post_job(client).json()["id"]
    client.delete("/api/jobs/" + second)
    client.delete("/api/jobs/" + first)
    import time
    for _ in range(50):
        if client.get("/api/auth/me").json()["credits"] == 500:
            break
        time.sleep(0.1)
    assert client.get("/api/auth/me").json()["credits"] == 500


def test_a_long_video_costs_per_clip_and_needs_a_chain_workflow(client):
    register(client)
    single = client.post("/api/estimate", json=JOB).json()
    chained = client.post("/api/estimate", json={**JOB, "clips": 3}).json()
    assert chained["minutes"] == single["minutes"] * 3 and chained["credits"] == 27
    assert client.get("/api/workflows/video/h3_director").json()["chain"] is True
    assert client.post("/api/estimate", json={**JOB, "clips": 99}).status_code == 400


def test_projects_and_search(client):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Skincare ad"}).json()
    db = client.app.state.db
    for name, prompt, project_id in (("street", "She waves on a sunny street", project["id"]), ("cafe", "He drinks coffee", None)):
        db.run("INSERT INTO generations (user_id, project_id, workflow, kind, name, filename, settings, context, created) "
               "VALUES (?, ?, 'video/h3_director', 'video', ?, 'x.mp4', ?, '{}', 1)",
               (me["id"], project_id, name, '{"values": {"100:value": "%s"}}' % prompt))
    names = lambda query: [i["name"] for i in client.get("/api/library" + query).json()["items"]]
    assert sorted(names("")) == ["cafe", "street"]
    assert names("?q=sunny+waves") == ["street"] and names("?q=coffee") == ["cafe"] and names("?q=nothing") == []
    assert names("?project=%d" % project["id"]) == ["street"] and names("?project=none") == ["cafe"]
    cafe = client.get("/api/library?q=coffee").json()["items"][0]["id"]
    client.put("/api/library/%d" % cafe, json={"project_id": project["id"]})
    assert client.get("/api/projects").json()["projects"][0]["items"] == 2
    client.delete("/api/projects/%d" % project["id"])
    assert sorted(names("?project=none")) == ["cafe", "street"]


def test_assets_are_saved_listed_and_private(client):
    register(client)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    asset = client.post("/api/assets", files={"file": ("anna.png", png, "image/png")}, data={"name": "Anna", "tag": "character"}).json()
    listed = client.get("/api/assets?kind=image").json()["assets"]
    assert [(a["name"], a["tag"], a["kind"]) for a in listed] == [("Anna", "character", "image")]
    assert client.get("/api/assets/%d/file" % asset["id"]).content == png
    assert client.post("/api/assets", files={"file": ("notes.txt", b"hi", "text/plain")}).status_code == 400
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    assert client.get("/api/assets").json()["assets"] == []
    assert client.get("/api/assets/%d/file" % asset["id"]).status_code == 404


def test_admin_console_is_admin_only(client):
    register(client)
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    for path in ("overview", "users", "users/1", "jobs", "library", "credits", "workflows", "system", "audit", "settings", "export/users.csv"):
        assert client.get("/api/admin/" + path).status_code == 403


def test_admin_overview_jobs_credit_log_and_workflows(client):
    register(client)
    post_job(client)
    overview = client.get("/api/admin/overview?days=7").json()
    assert overview["days"] == 7 and len(overview["calendar"]) == 7 and len(overview["series"]["done"]) == 7
    assert overview["current"]["jobs"] == 1 and overview["previous"]["jobs"] == 0 and overview["totals"]["users"] == 1
    assert overview["server"]["online"] is False and overview["attention"][0]["level"] == "critical"
    listing = client.get("/api/admin/jobs?q=ada").json()
    jobs = listing["jobs"]
    assert listing["total"] == 1 and jobs[0]["user_email"] == ADMIN["email"] and jobs[0]["cost"] == 9
    assert client.get("/api/admin/jobs?q=nobody").json()["total"] == 0
    detail = client.get("/api/admin/jobs/" + jobs[0]["id"]).json()
    assert detail["settings"]["options"]["quality"] == "low" and detail["user_name"] == "Ada"
    person = client.get("/api/admin/users/1").json()
    assert person["user"]["email"] == ADMIN["email"] and len(person["jobs"]) == 1 and person["credits"]
    assert client.get("/api/admin/credits").json()["summary"]["welcome"] == 500
    system = client.get("/api/admin/system").json()
    assert system["server"]["online"] is False and system["counts"]["users"] == 1 and system["storage"]["disk_total"] > 0
    reasons = [e["reason"] for e in client.get("/api/admin/credits").json()["events"]]
    assert "welcome" in reasons and "generation" in reasons
    report = {w["id"]: w for w in client.get("/api/admin/workflows").json()["workflows"]}
    assert report["video/h3_director"]["presets"] is True and report["video/h3_director"]["jobs"] == 1


def test_admin_can_disable_a_user_reset_a_password_and_cancel_their_job(client):
    register(client)
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"}).json()
    client.app.state.db.run("UPDATE jobs SET status = 'done'")           # nothing else in the queue
    job = post_job(client).json()["id"]
    client.app.state.db.run("UPDATE jobs SET status = 'queued' WHERE id = ?", (job,))
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})

    assert client.delete("/api/admin/jobs/" + job).status_code in (200, 400)   # 400 if the worker already failed it
    assert client.put("/api/admin/users/%d" % bob["id"], json={"password": "brand new pass"}).status_code == 200
    assert client.put("/api/admin/users/%d" % bob["id"], json={"disabled": True}).status_code == 200
    assert client.put("/api/admin/users/1", json={"disabled": True}).status_code == 400   # not yourself
    client.post("/api/auth/logout")
    login = lambda: client.post("/api/auth/login", json={"email": "bob@example.com", "password": "brand new pass"})
    assert login().status_code == 403
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    client.put("/api/admin/users/%d" % bob["id"], json={"disabled": False})
    client.post("/api/auth/logout")
    assert login().status_code == 200


def test_audit_log_records_sign_ins_and_admin_actions(client):
    me = register(client)
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong password"})
    client.put("/api/admin/users/%d" % me["id"], json={"add_credits": 25})
    client.put("/api/admin/settings", json={"signup_credits": 100})
    actions = [(e["action"], e["detail"]) for e in client.get("/api/admin/audit").json()["entries"]]
    assert ("Gave credits", "+25") in actions and ("Failed sign-in", "") in actions and ("Created account", "") in actions
    assert any(a == "Changed settings" and "signup credits: 500 to 100" in d for a, d in actions)
    assert client.get("/api/admin/audit?q=credits").json()["entries"][0]["action"] == "Gave credits"


def test_admin_library_and_csv_export(client):
    me = register(client)
    folder = client.app.state.output_dir / str(me["id"])
    folder.mkdir(parents=True)
    (folder / "x.mp4").write_bytes(b"video")
    item = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, size, created) "
        "VALUES (?, 'video/h3_director', 'video', '=street', 'x.mp4', '{}', '{}', 5, 1)", (me["id"],))
    listing = client.get("/api/admin/library?q=ada").json()
    assert listing["total"] == 1 and listing["items"][0]["user_email"] == ADMIN["email"]
    assert client.get("/api/admin/library/%d/file" % item).content == b"video"
    assert client.delete("/api/admin/library/%d" % item).status_code == 200
    assert not (folder / "x.mp4").exists() and client.get("/api/admin/library").json()["total"] == 0
    export = client.get("/api/admin/export/users.csv")
    assert export.headers["content-type"].startswith("text/csv") and "ada@example.com" in export.text
    assert client.get("/api/admin/export/secrets.csv").status_code == 404


def test_admin_gives_and_takes_credits_with_a_note(client):
    me = register(client)
    put = lambda **body: client.put("/api/admin/users/%d" % me["id"], json=body)
    assert put(add_credits=250, note="Launch bonus").json()["credits"] == 750
    assert put(add_credits=-100, note="Correction").json()["credits"] == 650
    assert put(add_credits=-5000).json()["credits"] == 0          # a balance never goes below zero
    assert put(add_credits=0).status_code == 400 and put(add_credits="lots").status_code == 400
    events = client.get("/api/admin/credits?reason=admin+grant").json()["events"]
    assert [(e["amount"], e["note"]) for e in events] == [(-650, ""), (-100, "Correction"), (250, "Launch bonus")]
    audit = [(e["action"], e["detail"]) for e in client.get("/api/admin/audit?q=credits").json()["entries"]]
    assert ("Took credits", "-650") in audit and ("Gave credits", "+250 · Launch bonus") in audit


def test_canvas_and_timeline_boards_are_saved_per_project_and_private(client):
    register(client)
    project = client.post("/api/projects", json={"name": "Skincare ad"}).json()
    assert client.get("/api/boards/canvas").json() == {"data": {}}
    client.put("/api/boards/canvas", json={"data": {"items": {"7": {"x": 40, "y": 80}}}})
    client.put("/api/boards/canvas", json={"project": project["id"], "data": {"items": {}}})
    client.put("/api/boards/timeline", json={"data": {"clips": [{"id": 7, "start": 0, "end": 2}]}})
    assert client.get("/api/boards/canvas").json()["data"]["items"]["7"] == {"x": 40, "y": 80}
    assert client.get("/api/boards/canvas?project=%d" % project["id"]).json() == {"data": {"items": {}}}
    assert client.get("/api/boards/timeline").json()["data"]["clips"][0]["end"] == 2
    assert client.get("/api/boards/notes").status_code == 404
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"})
    assert client.get("/api/boards/canvas").json() == {"data": {}}
    assert client.get("/api/boards/canvas?project=%d" % project["id"]).status_code == 404


def test_timeline_export_joins_clips_into_a_new_library_video(client):
    import asyncio
    from scene import media

    me = register(client)
    folder = client.app.state.output_dir / str(me["id"])
    folder.mkdir(parents=True)
    for i, (colour, size) in enumerate((("red", "64x64"), ("blue", "96x64"))):   # different sizes, the second one silent
        sound = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"] if i == 0 else []
        asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color={}:s={}:r=24:d=1".format(colour, size),
                                  *sound, "-pix_fmt", "yuv420p", folder / "clip{}.mp4".format(i)))
        client.app.state.db.run(
            "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
            "VALUES (?, 'video/h3_director', 'video', ?, ?, '{}', '{}', 1)", (me["id"], "clip%d" % i, "clip%d.mp4" % i))
    first, second = sorted(i["id"] for i in client.get("/api/library").json()["items"])
    assert client.post("/api/timeline/export", json={"clips": []}).status_code == 400
    assert client.post("/api/timeline/export", json={"clips": [{"id": 999}]}).status_code == 404
    made = client.post("/api/timeline/export", json={"name": "Cut 1", "clips": [{"id": first}, {"id": second, "start": 0.25, "end": 0.75}]}).json()
    assert 1.45 < made["seconds"] < 1.55
    item = next(i for i in client.get("/api/library").json()["items"] if i["id"] == made["id"])
    assert (item["name"], item["workflow"], item["context"]["width"]) == ("Cut 1", "edit/timeline", 64)
    joined = asyncio.run(media.probe(folder / item["filename"]))
    assert joined["audio"] and 1.4 < joined["seconds"] < 1.6


def test_agent_plans_are_checked_and_priced_and_nothing_is_queued(client, monkeypatch):
    register(client)
    client.put("/api/boards/brief", json={"data": {"text": "Warm evening light. The main character wears a red coat."}})
    asked = {}

    async def fake_ask(system, message, workflow_ids):
        asked.update(message=message, ids=workflow_ids)
        return {"reply": "Two shots.", "steps": [
            {"workflow": "video/h3_director", "name": "Street walk", "prompt": "She walks down a wet street.", "duration": 99, "resolution": 123},
            {"workflow": "video/does_not_exist", "name": "Bad", "prompt": "x"},
            {"workflow": "video/h3_director", "name": "No prompt", "prompt": "  "}]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    assert client.post("/api/agent/plan", json={"instruction": " "}).status_code == 400
    plan = client.post("/api/agent/plan", json={"instruction": "Make a street shot"}).json()
    assert "red coat" in asked["message"] and "video/h3_director" in asked["ids"]
    assert [s["name"] for s in plan["steps"]] == ["Street walk"]      # the unknown workflow and the empty prompt are dropped
    step = plan["steps"][0]
    assert step["credits"] > 0 and plan["total"] == step["credits"] and plan["balance"] == 500
    assert 15 in step["settings"]["values"].values() and step["settings"]["resolution"] != 123   # clamped, and a made-up size is ignored
    assert client.get("/api/jobs").json()["jobs"] == [] and client.get("/api/auth/me").json()["credits"] == 500


def test_agent_says_so_when_its_model_server_is_down(client):
    register(client)
    assert client.get("/api/agent/status").json()["online"] is False
    refused = client.post("/api/agent/plan", json={"instruction": "Make a street shot"})
    assert refused.status_code == 400 and "Ollama" in refused.json()["detail"]
