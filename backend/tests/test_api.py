ADMIN = {"name": "Ada", "email": "ada@example.com", "password": "correct horse"}


def test_everything_needs_a_sign_in(client):
    for path in ("/api/workflows", "/api/jobs", "/api/library", "/api/status", "/api/admin/users"):
        assert client.get(path).status_code == 401


def test_page_files_are_never_served_stale(client):
    assert client.get("/assets/js/main.js").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/auth/state").headers
    # the page fetches its files from under an address that changes with every change to them
    import re
    page = client.get("/")
    script = re.search(r'src="(/v/\d+/assets/js/main\.js)"', page.text).group(1)
    assert page.headers["cache-control"] == "no-cache" and re.search(r'href="/v/\d+/assets/css/app\.css"', page.text)
    assert client.get(script).text == client.get("/assets/js/main.js").text
    assert client.get(script.replace("main.js", "pages/admin/sections.js")).status_code == 200      # what main.js imports, relatively
    assert client.get(script.replace("assets/js/main.js", "assets/../index.html")).status_code == 404


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


def after(client, job_id):
    """A job, once it is no longer waiting or running."""
    import time
    for _ in range(300):
        job = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job_id)
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    return job


def made_by(client, response):
    """The library item a queued edit or motion graphic made."""
    job = after(client, response.json()["job"])
    assert job["status"] == "done", job["error"]
    return next(i for i in client.get("/api/library").json()["items"] if i["job_id"] == job["id"])


JOB = {"workflow": "video/h3_director", "values": {"100:value": "She waves."}, "options": {"mode": "fast", "quality": "low"}}


def post_job(client, **extra):
    import json
    return client.post("/api/jobs", data={"settings": json.dumps({**JOB, **extra})})


def test_new_accounts_get_credits_and_jobs_cost_them(client):
    assert register(client)["credits"] == 500
    quote = client.post("/api/estimate", json=JOB).json()
    assert quote["credits"] == 100 and quote["seconds"] == 5 and quote["balance"] == 500   # 5 s at 20 credits a second
    assert post_job(client).json()["credits"] == 100
    assert client.get("/api/auth/me").json()["credits"] in (400, 500)  # charged; refunded once the job fails offline


def test_a_job_is_refused_without_enough_credits_and_admin_can_add_more(client):
    me = register(client)
    client.put("/api/admin/users/%d" % me["id"], json={"add_credits": -495})
    response = post_job(client)
    assert response.status_code == 402 and "100 credits and you have 5" in response.json()["detail"]
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
    assert chained["minutes"] == single["minutes"] * 3 and chained["seconds"] == 15 and chained["credits"] == 300
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
    listed = client.get("/api/projects").json()["projects"][0]   # its newest item is the cover
    assert (listed["cover_kind"], listed["updated"]) == ("video", 1) and listed["cover_id"] == client.get("/api/library?q=sunny").json()["items"][0]["id"]
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
    for path in ("overview", "users", "users/1", "jobs", "library", "credits", "pricing", "economics", "workflows", "system", "audit", "settings", "export/users.csv"):
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
    assert listing["total"] == 1 and jobs[0]["user_email"] == ADMIN["email"] and jobs[0]["cost"] == 100
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
    folder = client.app.state.outputs.folder(me["id"])
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
    folder = client.app.state.outputs.folder(me["id"])
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
    item = made_by(client, client.post("/api/timeline/export", json={"name": "Cut 1", "clips": [{"id": first}, {"id": second, "start": 0.25, "end": 0.75}]}))
    assert (item["name"], item["workflow"], item["context"]["width"], item["context"]["duration"]) == ("Cut 1", "edit/timeline", 64, 1.5)
    assert item["summary"] == "2 clips joined · 2 s" and client.get("/api/jobs").json()["jobs"][0]["status"] == "done"
    joined = asyncio.run(media.probe(folder / item["filename"]))
    assert joined["audio"] and 1.4 < joined["seconds"] < 1.6


def test_video_thumbnails_are_small_posters_the_browser_keeps(client):
    import asyncio
    from scene import media

    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=64x64:r=24:d=1",
                              "-pix_fmt", "yuv420p", folder / "clip.mp4"))
    (folder / "broken.mp4").write_bytes(b"video")
    ids = [client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
        "VALUES (?, 'video/h3_director', 'video', ?, ?, '{}', '{}', 1)", (me["id"], name, name + ".mp4")) for name in ("clip", "broken")]
    poster = client.get("/api/library/%d/poster" % ids[0])
    assert poster.headers["content-type"] == "image/jpeg" and poster.content[:2] == b"\xff\xd8"
    again = client.get("/api/library/%d/poster" % ids[0], headers={"If-None-Match": poster.headers["etag"]})
    assert again.status_code == 304 and not again.content
    assert client.get("/api/admin/library/%d/poster" % ids[0]).content == poster.content
    assert client.get("/api/library/%d/poster" % ids[1]).status_code == 404
    assert client.delete("/api/library/%d" % ids[0]).status_code == 200
    assert not media.poster_path(folder / "clip.mp4").exists()


def test_agent_plans_are_checked_and_priced_and_nothing_is_queued(client, monkeypatch):
    register(client)
    client.put("/api/boards/brief", json={"data": {"text": "Warm evening light. The main character wears a red coat."}})
    asked = {}

    async def fake_ask(system, message, workflow_ids, history=()):
        asked.update(message=message, ids=workflow_ids, history=history)
        return {"reply": "Two shots.", "steps": [
            {"workflow": "video/h3_director", "name": "Street walk", "prompt": "She walks down a wet street.", "duration": 99, "resolution": 123},
            {"workflow": "video/does_not_exist", "name": "Bad", "prompt": "x"},
            {"workflow": "video/h3_director", "name": "No prompt", "prompt": "  "}]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    assert client.post("/api/agent/plan", json={"instruction": " "}).status_code == 400
    earlier = [{"instruction": "hi", "reply": "Hello. What are we making?", "steps": []}, "junk", {"instruction": "", "reply": "x"}]
    plan = client.post("/api/agent/plan", json={"instruction": "Make a street shot", "history": earlier}).json()
    assert "oldest first:\nUser: hi\nYou: Hello. What are we making?\n\n" in asked["message"]      # junk and empty turns are left out
    assert "red coat" in asked["message"] and "video/h3_director" in asked["ids"]
    assert [s["name"] for s in plan["steps"]] == ["Street walk"]      # the unknown workflow and the empty prompt are dropped
    step = plan["steps"][0]
    assert step["credits"] > 0 and plan["total"] == step["credits"] and plan["balance"] == 500
    assert 15 in step["settings"]["values"].values() and step["settings"]["resolution"] != 123   # clamped, and a made-up size is ignored
    assert client.get("/api/jobs").json()["jobs"] == [] and client.get("/api/auth/me").json()["credits"] == 500


def test_a_plain_prompt_becomes_a_caption_for_a_model_that_needs_one(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from scene.config import Settings
    from scene.main import create_app
    folder = tmp_path / "workflows" / "image"
    folder.mkdir(parents=True)
    (folder / "captioned.json").write_text(json.dumps({
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "5": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "How to write a caption.\n[USER]\nRATIO: {{ratio}}.\nUser idea: {{original_prompt}}"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "t"}}}))
    (folder / "captioned.studio.json").write_text(json.dumps({"caption": {"template": "5:value", "ratio": "3:shape"}, "hide": ["5:value"]}))
    app = create_app(Settings(comfy_url="http://127.0.0.1:9", ollama_url="http://127.0.0.1:9", storage_dir=str(tmp_path / "storage"),
                              workflows_dir=str(tmp_path / "workflows")))
    asked = {}

    async def fake_chat(messages, answer_format, context=None):
        asked.update(system=messages[0]["content"], user=messages[1]["content"], context=context)
        return {"aspect_ratio": "3:4", "high_level_description": "A fox."}

    with TestClient(app) as client:
        register(client)
        monkeypatch.setattr(app.state.agent, "chat", fake_chat)
        job = {"workflow": "image/captioned", "values": {"1:text": "a fox", "3:shape": "3:4 (Portrait Standard)"}}
        assert client.post("/api/jobs", data={"settings": json.dumps(job)}).status_code == 200
        queued = client.get("/api/jobs").json()["jobs"][0]["settings"]
        assert json.loads(queued["values"]["1:text"])["high_level_description"] == "A fox." and queued["prompt"] == "a fox"
        assert asked == {"system": "How to write a caption.", "user": "RATIO: 3:4.\nUser idea: a fox", "context": 16384}
        asked.clear()
        job["values"]["1:text"] = '{"aspect_ratio": "1:1", "high_level_description": "Ready."}'     # already a caption: used as it is
        assert client.post("/api/jobs", data={"settings": json.dumps(job)}).status_code == 200 and not asked
        monkeypatch.undo()                                                                            # the model server is down
        job["values"]["1:text"] = "a fox"
        waiting = len(client.get("/api/jobs").json()["jobs"])
        refused = client.post("/api/jobs", data={"settings": json.dumps(job)})
        assert refused.status_code == 400 and "Nothing was charged" in refused.json()["detail"]
        assert len(client.get("/api/jobs").json()["jobs"]) == waiting


def test_agent_edits_selected_videos_instead_of_generating(client, monkeypatch):
    from scene import media
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    ids = []
    for name, colour in (("first", "red"), ("second", "blue")):
        asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c={}:s=64x48:d=2:r=24".format(colour),
                                  "-pix_fmt", "yuv420p", folder / (name + ".mp4")))
        ids.append(client.app.state.db.run(
            "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
            "VALUES (?, 'video/h3_director', 'video', ?, ?, '', '{}', '{}', 1, 1, 1)", (me["id"], name, name + ".mp4")))
    asked = {}
    answers = [
        {"reply": "A dog.", "steps": []},
        {"reply": "The first half.", "steps": [{"tool": "trim", "source": ids[0], "start": 0, "end": 1, "parts": 1},     # a small model's
                                               {"tool": "trim", "source": ids[0], "start": 1, "end": 2, "parts": 1}]},  # idea of a split
        {"reply": "Two halves.", "steps": [{"tool": "split", "workflow": "video/h3_director", "source": ids[0], "parts": 2, "prompt": ""}]},
        {"reply": "Trimmed and joined.", "steps": [
            {"tool": "trim", "source": ids[1], "start": 0.5, "end": 99, "name": "Tail"},
            {"tool": "trim", "source": 999, "start": 0, "end": 1},        # not a selected video
            {"tool": "join", "name": "Both"}]},
    ]

    async def fake_ask(system, message, workflow_ids, history=()):
        asked["message"] = message
        return answers.pop(0)

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    client.post("/api/agent/plan", json={"instruction": "a dog running on a beach", "selection": ids})
    assert "new message:\n(none; " in asked["message"]      # the instruction is not about the selection, so it is left out
    thirds = client.post("/api/agent/plan", json={"instruction": "split this video into three parts", "selection": ids[:1]}).json()
    assert [s["name"] for s in thirds["steps"]] == ["first part 1 of 3", "first part 2 of 3", "first part 3 of 3"]   # asked for pieces, got pieces
    plan = client.post("/api/agent/plan", json={"instruction": "cut it in half", "selection": ids}).json()
    assert '"seconds": 2.0' in asked["message"] and '"tag": "@1"' in asked["message"]
    assert [s["edit"]["clips"] for s in plan["steps"]] == [[{"id": ids[0], "start": 0.0, "end": 1.0}], [{"id": ids[0], "start": 1.0, "end": 2.0}]]
    assert plan["total"] == 0 and plan["steps"][0]["name"] == "first part 1 of 2"
    plan = client.post("/api/agent/plan", json={"instruction": "trim and join", "selection": ids}).json()
    assert [s["name"] for s in plan["steps"]] == ["Tail", "Both"]
    assert plan["steps"][0]["edit"]["clips"] == [{"id": ids[1], "start": 0.5, "end": 2.0}]      # the end is held to the video's length
    made = made_by(client, client.post("/api/timeline/export", json={"name": "Tail", "clips": plan["steps"][0]["edit"]["clips"]}))
    assert 1.3 < made["context"]["duration"] < 1.7 and client.get("/api/auth/me").json()["credits"] == 500


def asyncio_run(coroutine):
    import asyncio
    return asyncio.run(coroutine)


def test_agent_puts_attached_items_into_the_slots_named_for_them(client, monkeypatch):
    me = register(client)
    ids = {}
    for name, kind in (("Mira", "image"), ("Library", "image"), ("Walk", "video"), ("Voice", "audio")):
        ids[name] = client.app.state.db.run(
            "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
            "VALUES (?, 'x/y', ?, ?, 'missing', '', '{}', '{}', 1, 1, 1)", (me["id"], kind, name))

    async def fake_ask(system, message, workflow_ids, history=()):
        return {"reply": "One shot.", "steps": [{
            "tool": "generate", "workflow": "video/h3_director", "name": "Reading", "prompt": "She opens a book.", "start_from": ids["Library"],
            "uses": [{"item": ids["Mira"], "slot": "201:image"}, {"item": ids["Library"], "slot": "205"},      # a shortened slot id
                     {"item": ids["Walk"], "slot": "207:video"}, {"item": ids["Voice"], "slot": "206:image"},   # a sound is not an image
                     {"item": ids["Mira"], "slot": "201:image"}, {"item": 999, "slot": "204:image"}, "junk"]}]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    step = client.post("/api/agent/plan", json={"instruction": "use @1 as the character and @2 as the place", "selection": list(ids.values())}).json()["steps"][0]
    assert [(use["name"], use["slot"], use["kind"]) for use in step["uses"]] == [
        ("Mira", "201:image", "image"), ("Library", "205:image", "image"), ("Walk", "207:video", "video")]
    assert step["start"] is None       # the library picture was given a purpose, so the shot does not also start on it
    refused = client.post("/api/library/%d/reference?kind=image" % ids["Voice"])
    assert refused.status_code in (400, 404)


def test_agent_improves_a_prompt_with_the_brief_and_charges_nothing(client, monkeypatch):
    register(client)
    client.put("/api/boards/brief", json={"data": {"text": "Warm evening light."}})
    asked = {}

    async def fake_chat(messages, answer_format):
        asked.update(system=messages[0]["content"], message=messages[1]["content"])
        return {"prompt": ' "A fox sits on a mossy rock in warm evening light." '}

    monkeypatch.setattr(client.app.state.agent, "chat", fake_chat)
    assert client.post("/api/agent/improve", json={"prompt": " "}).status_code == 400
    better = client.post("/api/agent/improve", json={"prompt": "a fox", "kind": "image"}).json()
    assert better == {"prompt": "A fox sits on a mossy rock in warm evening light."}
    assert "image model" in asked["system"] and "Warm evening light." in asked["message"] and "a fox" in asked["message"]
    assert client.get("/api/auth/me").json()["credits"] == 500


def test_a_step_can_start_on_what_an_earlier_step_makes(client, monkeypatch):
    register(client)
    shot = {"tool": "generate", "workflow": "video/h3_director", "prompt": "She waits.", "start_from": 0, "uses": []}

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        return {"reply": "Three shots.", "steps": [
            dict(shot, name="Arrives", after=0),
            dict(shot, name="Empty", prompt=" ", after=1),        # dropped: the numbers after it still mean what the model meant
            dict(shot, name="Waits", after=1),
            dict(shot, name="Leaves", after=3),
            dict(shot, name="Lost", after=2),                     # the step it names was dropped: it stands on its own
            dict(shot, name="Ahead", after=9)]}                   # no such step

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    steps = client.post("/api/agent/plan", json={"instruction": "she arrives, then waits, then leaves"}).json()["steps"]
    assert [(s["name"], s["after"] and s["after"]["step"]) for s in steps] == [
        ("Arrives", None), ("Waits", 0), ("Leaves", 1), ("Lost", None), ("Ahead", None)]
    assert steps[1]["after"]["slot"] == "209:image" and steps[1]["start"] is None


def test_a_shot_takes_the_shape_of_the_picture_it_starts_on(client, monkeypatch):
    from scene import agent
    me = register(client)
    tall = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
        "VALUES (?, 'x/y', 'image', 'Tall', 'missing', '', '{}', '{\"width\": 768, \"height\": 1344}', 1, 1, 1)", (me["id"],))
    shot = {"tool": "generate", "workflow": "video/h3_director", "uses": []}

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        return {"reply": "Two.", "steps": [dict(shot, name="From it", prompt="It moves.", start_from=tall, orientation="landscape", after=0),
                                           dict(shot, name="Then", prompt="It goes on.", start_from=0, orientation="square", after=1)]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    steps = client.post("/api/agent/plan", json={"instruction": "animate this", "selection": [tall]}).json()["steps"]
    assert [s["settings"]["orientation"] for s in steps] == ["portrait", "portrait"]       # the picture's shape wins, down the chain
    assert steps[0]["shape"][0] < steps[0]["shape"][1]
    # a workflow that takes an aspect ratio gets the nearest one
    schema = {"size": None, "controls": [{"id": "9:aspect_ratio", "input": "aspect_ratio", "choices": ["16:9 (Widescreen)", "9:16 (Portrait Widescreen)", "1:1 (Square)"]}]}
    settings = {"values": {"9:aspect_ratio": "16:9 (Widescreen)"}}
    agent.shape_like(schema, settings, [768, 1344])
    assert settings["values"]["9:aspect_ratio"] == "9:16 (Portrait Widescreen)" and agent.shape_of(schema, settings, {})[0] < 1000


def test_a_projects_cast_goes_into_every_shot_that_has_slots_for_it(client, monkeypatch):
    me = register(client)
    ids = {}
    for name, kind in (("Mira", "image"), ("Harbour", "image"), ("Narration", "audio"), ("Clip", "video")):
        ids[name] = client.app.state.db.run(
            "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
            "VALUES (?, 'x/y', ?, ?, 'missing', '', '{}', '{}', 1, 1, 1)", (me["id"], kind, name))
    assert client.get("/api/cast").json()["cast"] == {}
    client.put("/api/boards/cast", json={"data": {"character_1": ids["Mira"], "background": ids["Harbour"], "voice": ids["Narration"],
                                                  "outfit": ids["Narration"], "prop": 999}})      # a sound is no outfit; 999 is nobody's
    found = client.get("/api/cast?workflow=video/h3_director").json()
    assert sorted(found["cast"]) == ["background", "character_1", "voice"]
    assert [(f["name"], f["slot"]) for f in found["fills"]] == [("Mira", "201:image"), ("Harbour", "205:image"), ("Narration", "208:audio")]
    asked = {}

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        asked["message"] = message
        return {"reply": "One shot.", "steps": [{"tool": "generate", "workflow": "video/h3_director", "name": "Walk",
                                                 "prompt": "The main character walks along the quay.",
                                                 "uses": [{"item": ids["Clip"], "slot": "205:image"}]}]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    step = client.post("/api/agent/plan", json={"instruction": "use this as the place: she walks along the quay", "selection": [ids["Clip"]]}).json()["steps"][0]
    assert 'Main character: "Mira". In prompts call it "the main character".' in asked["message"]
    # what the user attached keeps its slot; the cast fills the others
    assert [(u["name"], u["slot"], bool(u.get("cast"))) for u in step["uses"]] == [
        ("Clip", "205:image", False), ("Mira", "201:image", True), ("Narration", "208:audio", True)]


def test_the_agent_uses_the_model_the_user_picked_when_the_server_has_it(client, monkeypatch):
    register(client)
    brain = client.app.state.agent
    used = []

    async def fake_models():
        return ["small:9b", "large:27b"]

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        used.append(await brain.pick_model(model))
        return {"reply": "Hello.", "steps": []}

    monkeypatch.setattr(brain, "models", fake_models)
    monkeypatch.setattr(brain, "ask", fake_ask)
    monkeypatch.setattr(brain, "model", "small:9b")
    assert client.get("/api/agent/status").json() == {"online": True, "model": "small:9b", "models": ["small:9b", "large:27b"], "hosted": []}
    for picked in ("large:27b", "not-installed", "", None):
        client.post("/api/agent/plan", json={"instruction": "hi", "model": picked})
    assert used == ["large:27b", "small:9b", "small:9b", "small:9b"]


def test_a_hosted_model_is_listed_beside_the_local_ones_and_asked_over_its_api(monkeypatch):
    import asyncio
    from scene.agent import Agent, AgentError, service
    brain = Agent("http://127.0.0.1:9", "", [service("kimi", "Kimi", "https://api.example.com/v1/", "secret-key", "kimi-k3, kimi-k2.6"),
                                             service("gemini", "Gemini", "https://g.example.com/openai", "g-key", "gemini-flash"),
                                             service("other", "Other", "https://o.example.com", "", "x"),      # no key: not offered
                                             service("idle", "Idle", "https://i.example.com", "i-key", "off")])  # switched off, key kept
    sent = []

    class Reply:
        def __init__(self, status, body):
            self.status_code, self.body = status, body

        def json(self):
            return self.body

    async def fake_post(url, json=None, headers=None):
        sent.append({"url": url, "body": dict(json), "auth": headers.get("Authorization")})
        if "temperature" in json:
            return Reply(400, {"error": {"message": "invalid temperature: only 1 is allowed for this model"}})
        return Reply(200, {"choices": [{"message": {"content": '```json\n{"reply": "Hello.", "steps": []}\n```'}}]})

    monkeypatch.setattr(brain.http, "post", fake_post)
    # Ollama is down, and the hosted models are still there to pick from
    assert asyncio.run(brain.models()) == ["kimi/kimi-k3", "kimi/kimi-k2.6", "gemini/gemini-flash"]
    assert brain.hosted() == [{"id": "kimi", "name": "Kimi"}, {"id": "gemini", "name": "Gemini"}]
    asyncio.run(brain.ask("You plan.", "hi", [], model="gemini/gemini-flash"))
    assert sent.pop()["url"] == "https://g.example.com/openai/chat/completions" and sent.pop()["auth"] == "Bearer g-key"
    answer = asyncio.run(brain.ask("You plan.", "hi", ["video/h3_director"], model="kimi/kimi-k2.6"))
    assert answer == {"reply": "Hello.", "steps": []}
    assert [s["url"] for s in sent] == ["https://api.example.com/v1/chat/completions"] * 2 and sent[0]["auth"] == "Bearer secret-key"
    assert sent[1]["body"]["model"] == "kimi-k2.6" and "temperature" not in sent[1]["body"]            # asked again without it
    assert sent[1]["body"]["response_format"] == {"type": "json_object"} and '"required": ["reply", "steps"]' in sent[1]["body"]["messages"][0]["content"]

    # a busy service is tried again, and when it stays busy the smallest local model answers and the reply says so
    calls = []

    async def busy(url, json=None, headers=None):
        calls.append(url)
        if "chat/completions" in url:
            return Reply(503, {"error": {"message": "This model is currently experiencing high demand."}})
        return Reply(200, {"message": {"content": '{"reply": "From here.", "steps": []}'}})

    async def local_models(url, headers=None):
        return Reply(200, {"models": [{"name": "big:27b", "size": 17}, {"name": "small:9b", "size": 6}]})

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(brain.http, "post", busy)
    monkeypatch.setattr(brain.http, "get", local_models)
    monkeypatch.setattr("scene.agent.asyncio.sleep", no_wait)
    answer = asyncio.run(brain.ask("You plan.", "hi", [], model="kimi/kimi-k3"))
    assert answer["reply"] == "From here. (Kimi was busy, so small:9b answered.)"
    assert [c.rsplit("/", 2)[-2:] for c in calls] == [["chat", "completions"]] * 2 + [["api", "chat"]]

    async def refused(url, json=None, headers=None):
        return Reply(401, {"error": {"message": "Invalid Authentication"}})

    monkeypatch.setattr(brain.http, "post", refused)
    try:
        asyncio.run(brain.ask("You plan.", "hi", [], model="kimi/kimi-k3"))
        raise AssertionError("a refused key must be reported")
    except AgentError as error:
        assert "Kimi refused the API key" in str(error) and "secret-key" not in str(error)
    assert asyncio.run(Agent("http://127.0.0.1:9")._hosted_models()) == []                                    # no services, no hosted models


def test_the_agent_is_for_admins_and_for_users_an_admin_gives_it_to(client):
    admin = register(client)
    assert admin["agent"] is True and client.get("/api/agent/status").status_code == 200
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one"}).json()
    assert bob["agent"] is False and client.get("/api/auth/me").json()["agent"] is False
    for refused in (client.get("/api/agent/status"), client.post("/api/agent/plan", json={"instruction": "hi"})):
        assert refused.status_code == 403 and "coming soon" in refused.json()["detail"]
    assert client.get("/api/motion/templates").status_code == 200           # the rest of the panel stays open
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json=ADMIN)
    assert client.put("/api/admin/users/%d" % bob["id"], json={"agent": True}).status_code == 200
    assert [u["agent"] for u in client.get("/api/admin/users").json()["users"]] == [0, 1]
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "bob@example.com", "password": "another one"}).json()["agent"] is True
    assert client.get("/api/agent/status").status_code == 200


def test_agent_says_so_when_its_model_server_is_down(client):
    register(client)
    assert client.get("/api/agent/status").json()["online"] is False
    refused = client.post("/api/agent/plan", json={"instruction": "Make a street shot"})
    assert refused.status_code == 400 and "Ollama" in refused.json()["detail"]


def test_an_upload_over_the_size_limit_is_refused(client, monkeypatch):
    from scene import references
    monkeypatch.setattr(references, "MAX_BYTES", 16)
    register(client)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    assert client.post("/api/assets", files={"file": ("anna.png", png, "image/png")}).status_code == 413
    refused = client.post("/api/jobs", data={"settings": __import__("json").dumps(JOB)},
                          files={"ref:201:image": ("anna.png", png, "image/png")})
    assert refused.status_code == 413 and "200 MB" in refused.json()["detail"]


def test_timeline_export_refuses_clips_that_are_not_in_the_expected_form(client):
    register(client)
    assert client.post("/api/timeline/export", json={"clips": ["first"]}).status_code == 400
    assert client.post("/api/timeline/export", json={"clips": "first"}).status_code == 400


def test_the_login_throttle_blocks_and_then_forgets(monkeypatch):
    from scene import security
    throttle = security.LoginThrottle()
    for _ in range(security.MAX_FAILURES):
        throttle.fail("ada|1.2.3.4")
    assert throttle.blocked("ada|1.2.3.4") and not throttle.blocked("bob|1.2.3.4")
    now = security.time.time()
    monkeypatch.setattr(security.time, "time", lambda: now + security.LOCK_SECONDS + 1)
    throttle.fail("bob|1.2.3.4")
    assert list(throttle.failures) == ["bob|1.2.3.4"]


def test_finished_work_can_be_kept_in_a_folder_outside_storage(tmp_path):
    from fastapi.testclient import TestClient
    from scene.config import Settings
    from scene.main import create_app
    app = create_app(Settings(comfy_url="http://127.0.0.1:9", storage_dir=str(tmp_path / "storage"), output_dir=str(tmp_path / "Outputs")))
    with TestClient(app):
        assert app.state.output_dir == tmp_path / "Outputs"
        assert app.state.jobs.tmp_dir == tmp_path / "storage" / "tmp"


def test_each_users_work_is_kept_in_a_folder_named_after_their_email(client):
    me = register(client)
    old = client.app.state.output_dir / str(me["id"])     # how folders were named before
    old.mkdir(parents=True)
    (old / "clip.mp4").write_bytes(b"x")
    folder = client.app.state.outputs.folder(me["id"])
    assert folder == client.app.state.output_dir / ADMIN["email"]
    assert (folder / "clip.mp4").is_file() and not old.exists()


def test_a_job_and_an_edit_remember_the_item_they_were_made_from(client):
    from scene import media
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=1:r=24", "-pix_fmt", "yuv420p", folder / "a.mp4"))
    source = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
        "VALUES (?, 'video/h3_director', 'video', 'a', 'a.mp4', '', '{}', '{}', 1, 1, 1)", (me["id"],))
    post_job(client, parent=source)
    post_job(client, parent=source + 50)        # not an item of this user
    post_job(client)
    assert [j["settings"]["parent"] for j in client.get("/api/jobs").json()["jobs"]][::-1] == [source, None, None]
    clip = {"id": source, "start": 0, "end": 0.5}
    cut = made_by(client, client.post("/api/timeline/export", json={"clips": [clip], "parent": source}))
    plain = made_by(client, client.post("/api/timeline/export", json={"clips": [clip], "parent": 999}))
    made = {i["id"]: i["settings"]["parent"] for i in client.get("/api/library").json()["items"] if i["workflow"] == "edit/timeline"}
    assert made == {cut["id"]: source, plain["id"]: None}


def test_the_agent_puts_a_sound_on_a_video_with_ffmpeg(client, monkeypatch):
    from scene import media
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=3:r=24", "-pix_fmt", "yuv420p", folder / "clip.mp4"))
    asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=1", folder / "tune.mp3"))
    ids = {}
    for name, kind, filename, at in (("Clip", "video", "clip.mp4", 1), ("Tune", "audio", "tune.mp3", 2)):
        ids[name] = client.app.state.db.run(
            "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
            "VALUES (?, 'x/y', ?, ?, ?, '', '{}', '{}', 1, 1, ?)", (me["id"], kind, name, filename, at))
    asked = {}

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        asked["message"] = message
        return {"reply": "Adding it.", "steps": [{"tool": "sound", "source": 0, "audio": 999, "replace": False}]}   # ids left out or wrong

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    # nothing is attached: "the audio" and "the video" are the newest of each kind among the recent items
    step = client.post("/api/agent/plan", json={"instruction": "attach the generated audio to the video"}).json()["steps"][0]
    assert '"name": "Tune"' in asked["message"].split("Recent items")[1]
    assert step["sound"] == {"video": ids["Clip"], "audio": ids["Tune"], "replace": False, "name": "Clip with sound"} and step["credits"] == 0
    # a model that only answers in words: the step that was asked for is made anyway
    async def only_talks(system, message, workflow_ids, history=(), model=None):
        return {"reply": "I cannot use ffmpeg.", "steps": []}

    monkeypatch.setattr(client.app.state.agent, "ask", only_talks)
    talked = client.post("/api/agent/plan", json={"instruction": "use ffmpeg and do this", "history": [
        {"instruction": "attach this generated audio to the vido", "reply": "I cannot attach audio.", "steps": []}]}).json()
    assert talked["steps"][0]["sound"]["audio"] == ids["Tune"] and talked["reply"] == "I'll put Tune under Clip. Approve to make it."
    assert client.post("/api/agent/plan", json={"instruction": "what can you do?"}).json()["steps"] == []
    item = made_by(client, client.post("/api/edit/sound", json=step["sound"]))
    result = asyncio_run(media.probe(folder / item["filename"]))
    assert result["audio"] and 2.8 < result["seconds"] < 3.2          # the 1 s tune is looped to the length of the 3 s video
    assert item["workflow"] == "edit/sound" and item["settings"]["parent"] == ids["Clip"]
    assert client.post("/api/edit/sound", json={"video": ids["Tune"], "audio": ids["Clip"]}).status_code == 400   # the wrong way round
    assert client.get("/api/auth/me").json()["credits"] == 500


def test_agent_plans_a_motion_graphics_video_as_scenes_of_words(client, monkeypatch):
    from scene import sequence
    register(client)

    async def fake_ask(system, message, workflow_ids, history=()):
        return {"reply": "A short intro.", "steps": [{
            "tool": "motion", "workflow": "video/h3_director", "name": "Intro", "prompt": "", "orientation": "portrait", "look": "warm",
            "scenes": [{"kind": "title", "heading": "Scene.ai", "text": "A studio", "items": [], "seconds": 0},
                       {"kind": "list", "heading": "What it makes", "text": "", "items": ["Images", "<b>Video</b>", "", 7], "seconds": 99},
                       {"kind": "nonsense", "heading": "", "text": "One sentence here", "items": [], "seconds": 0.1},
                       {"kind": "end", "heading": "", "text": "", "items": [], "seconds": 3}, "junk"]}]}

    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    step = client.post("/api/agent/plan", json={"instruction": "make a motion graphics intro"}).json()["steps"][0]
    scenes = step["motion"]["scenes"]
    assert step["credits"] == 390 and (step["motion"]["look"], step["motion"]["shape"]) == ("warm", "portrait")   # 13 s at 30 a second
    assert [(s["kind"], s["seconds"]) for s in scenes] == [("title", 3.0), ("list", 8.0), ("statement", 2.0)]     # the empty scene is dropped
    assert scenes[1]["items"] == ["Images", "<b>Video</b>", "7"]
    page, seconds = sequence.page(scenes, "warm", 1080, 1920)
    assert seconds == 13.0 and "&lt;b&gt;Video&lt;/b&gt;" in page and "<b>Video" not in page                       # typed words are never markup
    assert 'data-start="3.0" data-duration="8.0"' in page and 'data-duration="13.0" data-width="1080"' in page
    assert client.post("/api/motion/render", json={"scenes": [{"kind": "title", "heading": "", "text": ""}]}).status_code == 400


def test_a_whole_motion_video_is_written_as_scenes_from_what_it_is_about(client, monkeypatch):
    register(client)
    client.put("/api/boards/brief", json={"data": {"text": "Friendly and plain."}})
    asked = {}

    async def fake_chat(messages, answer_format):
        asked.update(system=messages[0]["content"], message=messages[1]["content"])
        return {"name": " Scene.ai  intro ", "look": "pink", "orientation": "portrait", "scenes": [
            {"kind": "title", "heading": "Scene.ai", "text": "A studio", "items": ["dropped"]},
            {"kind": "list", "heading": "It makes", "text": "", "items": ["Images", "Video"]},
            {"kind": "stat", "heading": "100%", "text": "made up", "items": []},          # a figure the user never gave
            {"kind": "quote", "heading": "Sarah", "text": "Love it", "items": []},        # and a quotation nobody said
            {"kind": "end", "heading": "", "text": "", "items": []}]}

    monkeypatch.setattr(client.app.state.agent, "chat", fake_chat)
    assert client.post("/api/motion/scenes", json={"about": " "}).status_code == 400
    written = client.post("/api/motion/scenes", json={"about": "an intro to Scene.ai"}).json()
    assert (written["name"], written["look"], written["shape"]) == ("Scene.ai intro", "dark", "portrait")
    assert [(s["kind"], s["items"]) for s in written["scenes"]] == [("title", []), ("list", ["Images", "Video"])]
    assert "Friendly and plain." in asked["message"] and "an intro to Scene.ai" in asked["message"]

    async def nothing(messages, answer_format):
        return {"name": "", "look": "dark", "orientation": "landscape", "scenes": []}

    monkeypatch.setattr(client.app.state.agent, "chat", nothing)
    assert client.post("/api/motion/scenes", json={"about": "x"}).status_code == 400


def test_upscalers_are_listed_as_their_own_kind_beside_the_three_that_make_things(client):
    register(client)
    found = client.get("/api/workflows").json()
    kinds = {w["id"]: w["kind"] for w in found["workflows"]}
    assert kinds["upscaler/utility_seedvr2_3b_int8_upscale_video"] == "upscaler"
    assert found["kinds"] == ["video", "image", "audio"]   # the Create page's tabs: an upscaler is not made from a prompt


def test_motion_templates_are_listed_and_their_forms_are_checked(client):
    from scene import motion
    register(client)
    found = client.get("/api/motion/templates").json()
    assert [t["id"] for t in found["templates"]] == ["title_card", "lower_third", "title_over_video"] and "ready" in found
    card = found["templates"][0]
    assert motion.clean(card, {"title": "  Chapter   one ", "seconds": "8"}) == {
        "title": "Chapter one", "subtitle": "", "seconds": 8, "shape": "landscape", "look": "dark"}
    assert client.post("/api/motion/render", json={"template": "title_card", "values": {"title": " "}}).status_code == 400
    assert client.post("/api/motion/render", json={"template": "title_card", "values": {"title": "x", "look": "pink"}}).status_code == 400
    assert client.post("/api/motion/render", json={"template": "lower_third", "values": {"title": "x"}}).status_code == 400   # no video chosen
    assert client.post("/api/motion/render", json={"template": "nope"}).status_code == 404


def test_prices_follow_what_was_asked_for_at_the_rate_of_each_kind(client):
    register(client)
    quote = lambda **settings: client.post("/api/estimate", json=settings).json()["credits"]
    assert quote(**{**JOB, "values": {"100:value": "She waves.", "102:value": 10}}) == 200             # 10 s at 20 a second
    assert quote(**{**JOB, "options": {"mode": "normal", "quality": "high"}}) == 100                    # slower to render, same price
    # The image and audio workflows are saved without their node settings: they can be read only with the node
    # definitions the studio keeps from the render server, which a machine that never reached it does not have.
    import json
    from pathlib import Path
    import pytest
    definitions = Path(__file__).resolve().parents[2] / "storage" / "cache" / "node_definitions.json"
    if not definitions.is_file():
        pytest.skip("no saved node definitions on this machine")
    client.app.state.catalog.saved = json.loads(definitions.read_text(encoding="utf-8"))
    assert quote(workflow="image/image_sdxl_simple") == 40                                             # a flat price for an image
    assert quote(workflow="audio/audio_minimax_music_3") == 300                                        # 60 s at 5 a second
    assert quote(workflow="audio/audio_minimax_music_3", values={"37:13:max_duration": 30}) == 150
    assert quote(workflow="upscaler/utility_seedvr2_3b_int8_upscale_video") == 100                     # no video named: 5 s is assumed
    assert quote(workflow="upscaler/utility_seedvr2_3b_int8_upscale_video", source_seconds=12) == 240   # a file 12 s long, as the browser read it


def test_admin_sets_rates_workflow_pricing_packages_and_servers(client):
    register(client)
    quote = lambda: client.post("/api/estimate", json=JOB)
    pricing = client.get("/api/admin/pricing").json()
    assert pricing["rates"] == {"image": 40, "video": 20, "audio": 5, "motion": 30, "overlay": 10, "upscaler": 20}
    assert pricing["inr_per_1000_credits"] == 100 and pricing["electricity_inr_per_kwh"] == 8
    assert [(s["name"], s["generation_power_w"], s["renders"]) for s in pricing["servers"]] == [("Lufi", None, 0), ("Zoro", 950, 1)]
    assert {w["id"]: w["example"] for w in pricing["workflows"]}["edit/motion"] == 150 and pricing["rates"]["overlay"] == 10

    assert client.put("/api/admin/pricing", json={"rates": {"video": 10}, "electricity_inr_per_kwh": 9}).json()["rates"]["video"] == 10
    assert quote().json()["credits"] == 50
    assert client.put("/api/admin/pricing", json={"rates": {"video": "lots"}}).status_code == 400

    own = {"workflow": "video/h3_director", "credits_per_second": 4, "base_credits": 6, "quality_multiplier": 2}
    listed = {w["id"]: w for w in client.put("/api/admin/pricing/workflow", json=own).json()["workflows"]}
    assert listed["video/h3_director"]["example"] == 52 and quote().json()["credits"] == 52            # (6 + 4 × 5) × 2
    assert listed["video/video_minimax_h3_i2v"]["per_second"] == 10                                    # the others follow their kind
    client.put("/api/admin/pricing/workflow", json={"workflow": "video/h3_director", "enabled": False})
    assert quote().status_code == 400 and post_job(client).status_code == 400
    assert "video/h3_director" not in [w["id"] for w in client.get("/api/workflows").json()["workflows"]]
    client.put("/api/admin/pricing/workflow", json={"workflow": "video/h3_director"})                  # nothing of its own again
    assert quote().json()["credits"] == 50
    assert client.put("/api/admin/pricing/workflow", json={"workflow": "video/nope"}).status_code == 404

    package = client.post("/api/admin/pricing/packages", json={"name": "Starter", "price_inr": 100, "credits": 1000, "active": True}).json()["id"]
    client.put("/api/admin/pricing/packages/%d" % package, json={"bonus_credits": 50, "active": False})
    assert client.get("/api/admin/pricing").json()["packages"] == [
        {"id": package, "name": "Starter", "price_inr": 100, "credits": 1000, "bonus_credits": 50, "active": 0,
         "created": client.get("/api/admin/pricing").json()["packages"][0]["created"]}]
    assert client.post("/api/admin/pricing/packages", json={"price_inr": 5}).status_code == 400          # no name
    assert client.delete("/api/admin/pricing/packages/%d" % package).json() == {"ok": True}
    zoro = client.get("/api/admin/pricing").json()["servers"][1]["id"]
    client.put("/api/admin/pricing/servers/%d" % zoro, json={"generation_power_w": 820, "idle_power_w": ""})
    assert client.get("/api/admin/pricing").json()["servers"][1]["generation_power_w"] == 820
    actions = [e["action"] for e in client.get("/api/admin/audit").json()["entries"]]
    assert {"Changed pricing", "Changed workflow pricing", "Added a credit package", "Deleted a credit package", "Changed a server"} <= set(actions)


def test_a_job_records_what_became_of_its_credits(client):
    import time
    register(client)
    job = post_job(client).json()["id"]
    for _ in range(100):
        detail = client.get("/api/admin/jobs/" + job).json()
        if detail["status"] == "failed":    # there is no render server in the tests
            break
        time.sleep(0.1)
    assert (detail["credits_required"], detail["credits_reserved"], detail["credits_consumed"], detail["credits_refunded"]) == (100, 0, 0, 100)
    assert detail["seconds_requested"] == 5 and detail["server"] == "Zoro" and client.get("/api/auth/me").json()["credits"] == 500


def test_motion_graphics_are_charged_by_the_second_and_refunded_when_a_render_fails(client, monkeypatch):
    from scene import motion
    register(client)
    card = {"template": "title_card", "values": {"title": "Chapter one", "seconds": 8}}
    assert client.post("/api/motion/estimate", json=card).json() == {"seconds": 8.0, "credits": 240, "balance": 500}   # 8 s at 30 a second

    async def broken(*args, **kwargs):
        raise motion.MotionError("The render stopped.")

    monkeypatch.setattr(motion, "render", broken)
    queued = client.post("/api/motion/render", json=card).json()
    assert queued["credits"] == 240 and after(client, queued["job"])["error"] == "The render stopped."
    assert client.get("/api/auth/me").json()["credits"] == 500
    assert [(e["amount"], e["reason"]) for e in client.get("/api/admin/credits").json()["events"]][:2] == [(240, "refund"), (-240, "generation")]

    async def drawn(template_id, values, target, *args, **kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"video")
        return {"seconds": 8.0, "width": 1920, "height": 1080}

    monkeypatch.setattr(motion, "render", drawn)
    item = made_by(client, client.post("/api/motion/render", json=card))
    assert (item["workflow"], item["summary"], item["cost"]) == ("edit/motion", "Title card · 8 s", 240)
    assert client.get("/api/auth/me").json()["credits"] == 260
    made_by(client, client.post("/api/motion/render", json=card))
    refused = client.post("/api/motion/render", json=card)          # 20 credits are left
    assert refused.status_code == 402 and "240 credits and you have 20" in refused.json()["detail"]


def test_a_video_brought_to_an_upscaler_is_measured_for_its_price(client, tmp_path):
    from scene import media
    from scene.api.studio import _video_seconds
    asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=3:r=24", "-pix_fmt", "yuv420p", tmp_path / "clip.mp4"))
    seconds = asyncio_run(_video_seconds(client.app.state, (tmp_path / "clip.mp4").read_bytes(), "clip.mp4"))
    assert 2.9 < seconds < 3.1
    assert asyncio_run(_video_seconds(client.app.state, b"not a video", "clip.mp4")) is None
    assert not list((tmp_path / "tmp").glob("measure_*"))          # nothing is left behind


def test_one_visitor_cannot_make_account_after_account(client):
    def join(n, **headers):
        client.post("/api/auth/logout")
        return client.post("/api/auth/register", json={"email": "user%d@example.com" % n, "password": "another one"}, headers=headers).status_code

    register(client)                                              # the first account, which owns the installation
    assert [join(n) for n in range(4)] == [200, 200, 429, 429]    # three a day from one address, the first one included
    # The address in Cloudflare's header counts only when the request comes through the tunnel on this machine.
    assert join(9, **{"CF-Connecting-IP": "203.0.113.7"}) == 429
    client.post("/api/auth/login", json=ADMIN)
    assert "Refused a new account" in [e["action"] for e in client.get("/api/admin/audit").json()["entries"]]


def test_a_title_over_a_video_costs_less_a_second_than_a_motion_video(client, tmp_path):
    import json, time
    from scene import media
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True, exist_ok=True)
    asyncio_run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=3:r=24", "-pix_fmt", "yuv420p", folder / "clip.mp4"))
    clip = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) VALUES (?, 'video/x', 'video', 'Clip', 'clip.mp4', '{}', '{}', ?)",
        (me["id"], time.time()))
    over = client.post("/api/motion/estimate", json={"template": "lower_third", "values": {"title": "Ada"}, "source": clip}).json()
    assert over["credits"] == 30 and 2.9 < over["seconds"] < 3.1                        # 3 s at 10 a second
    alone = client.post("/api/motion/estimate", json={"template": "title_card", "values": {"title": "Ada", "seconds": 3}}).json()
    assert alone["credits"] == 90                                                       # 3 s at 30 a second


def test_economics_show_what_each_workflow_earned_and_what_its_electricity_cost(client):
    import time
    me = register(client)
    now = time.time()
    add = lambda job, status, started, cost: client.app.state.db.run(
        "INSERT INTO jobs (id, user_id, name, workflow, kind, settings, status, cost, seconds_requested, server, created, started, finished) "
        "VALUES (?, ?, 'x', 'video/h3_director', 'video', '{}', ?, ?, 5, 'Zoro', ?, ?, ?)", (job, me["id"], status, cost, now - 10, started, now))
    add("a", "done", now - 3600, 100)       # an hour on Zoro: 0.95 kW at 8 a unit
    add("b", "failed", now - 1800, 100)     # half an hour that made nothing
    report = client.get("/api/admin/economics?days=7").json()
    row = report["workflows"][0]
    assert (row["id"], row["title"], row["done"], row["failed"], row["credits"], row["refunded"]) == ("video/h3_director", "H3 Director", 1, 1, 100, 100)
    assert row["revenue_inr"] == 10 and round(row["electricity_inr"], 2) == 11.4 and round(row["margin_inr"], 2) == -1.4
    assert row["runs_per_success"] == 2 and row["success_rate"] == 50 and row["avg_seconds"] == 3600 and row["render_ratio"] == 720
    assert report["totals"]["failure_rate"] == 50 and report["unmeasured"] == ["Lufi"] and report["days"] == 7


def test_a_running_edit_can_be_cancelled_and_gives_its_credits_back(client, monkeypatch):
    import asyncio, time
    from scene import motion
    register(client)

    async def slow(template_id, values, target, *args, **kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"half a video")
        await asyncio.sleep(60)

    monkeypatch.setattr(motion, "render", slow)
    job = client.post("/api/motion/render", json={"template": "title_card", "values": {"title": "Chapter one", "seconds": 8}}).json()["job"]
    post_job(client)                                               # a render that is refused at once: the edit does not wait behind it
    for _ in range(100):
        if next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job)["status"] == "running":
            break
        time.sleep(0.05)
    assert client.get("/api/auth/me").json()["credits"] in (160, 260)   # 240 held for the motion graphic, and 100 until the render fails
    client.delete("/api/jobs/" + job)
    cancelled = after(client, job)
    assert cancelled["status"] == "cancelled" and (cancelled["credits_reserved"], cancelled["credits_refunded"]) == (0, 240)
    assert not list(client.app.state.outputs.folder(1).glob("motion_*"))     # the half-written file is gone
    for _ in range(100):
        if client.get("/api/auth/me").json()["credits"] == 500:
            break
        time.sleep(0.1)
    assert client.get("/api/auth/me").json()["credits"] == 500
