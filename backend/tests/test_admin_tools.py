"""The admin console's tools: the queue, retries, the daily limit, two-step sign-in for admins, announcements,
credits for everyone, backups, storage, and what the Overview adds."""

import json

from test_api import ADMIN, post_job, register

BOB = {"email": "bob@example.com", "password": "another one"}


def as_admin(client):
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})


def as_bob(client):
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json=BOB)


def with_bob(client):
    """Ada (the admin) and Bob (a user). Ada is signed in afterwards."""
    register(client)
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json=BOB).json()
    as_admin(client)
    return bob


def test_paused_renders_wait_and_a_job_can_go_to_the_front(client):
    register(client)
    assert client.put("/api/admin/queue", json={"paused": True}).json() == {"paused": True}
    first, second = post_job(client).json()["id"], post_job(client).json()["id"]
    overview = client.get("/api/admin/overview").json()
    assert overview["queue"]["paused"] is True and [j["id"] for j in overview["queue"]["waiting"]] == [first, second]
    assert any("paused" in a["text"] for a in overview["attention"])
    assert client.post("/api/admin/jobs/%s/front" % second).status_code == 200
    assert [j["id"] for j in client.get("/api/admin/overview").json()["queue"]["waiting"]] == [second, first]
    positions = {j["id"]: j["position"] for j in client.get("/api/jobs").json()["jobs"]}
    assert positions[second] == 1 and positions[first] == 2
    assert client.delete("/api/admin/jobs/" + first).status_code == 200
    assert client.post("/api/admin/jobs/%s/front" % first).status_code == 400    # no longer waiting
    client.put("/api/admin/queue", json={"paused": False})
    assert client.get("/api/admin/overview").json()["queue"]["paused"] is False


def test_a_failed_job_is_explained_and_can_run_again_charged_or_free(client):
    register(client)
    client.put("/api/admin/queue", json={"paused": True})   # so the new runs stay waiting
    job = post_job(client).json()["id"]
    client.app.state.db.run("UPDATE jobs SET status = 'failed', error = ? WHERE id = ?",
                            ("ComfyUI error in node 'KSampler': CUDA out of memory. Tried to allocate 2 GiB", job))
    detail = client.get("/api/admin/jobs/" + job).json()
    assert "graphics memory" in detail["explained"]
    assert "graphics memory" in client.get("/api/admin/jobs?status=failed").json()["jobs"][0]["explained"]
    before = client.get("/api/auth/me").json()["credits"]
    again = client.post("/api/admin/jobs/%s/retry" % job, json={}).json()
    assert again["credits"] == 100 and client.get("/api/auth/me").json()["credits"] == before - 100
    free = client.post("/api/admin/jobs/%s/retry" % job, json={"free": True}).json()
    assert free["credits"] == 0 and client.get("/api/auth/me").json()["credits"] == before - 100
    queued = client.app.state.db.one("SELECT settings, status FROM jobs WHERE id = ?", (free["id"],))
    assert queued["status"] == "queued" and json.loads(queued["settings"])["options"]["quality"] == "low"
    assert client.post("/api/admin/jobs/%s/retry" % free["id"], json={}).status_code == 400   # it has not failed


def test_the_daily_credit_limit_stops_users_but_not_admins(client):
    bob = with_bob(client)
    client.put("/api/admin/queue", json={"paused": True})
    assert client.put("/api/admin/settings", json={"daily_cap": 150}).json()["daily_cap"] == 150
    assert post_job(client).status_code == 200 and post_job(client).status_code == 200   # admins have no limit
    as_bob(client)
    assert post_job(client).status_code == 200
    refused = post_job(client)
    assert refused.status_code == 429 and "spend 150 in 24 hours and has spent 100" in refused.json()["detail"]
    as_admin(client)
    limits = client.get("/api/admin/users/%d" % bob["id"]).json()["limits"]
    assert limits == {"own": None, "studio": 150, "in_force": 150, "spent_today": 100, "exempt": False}
    client.put("/api/admin/users/%d" % bob["id"], json={"daily_cap": 0})    # no limit for Bob
    as_bob(client)
    assert post_job(client).status_code == 200
    as_admin(client)
    client.put("/api/admin/users/%d" % bob["id"], json={"daily_cap": None})   # back to the studio's
    assert client.get("/api/admin/users/%d" % bob["id"]).json()["limits"]["in_force"] == 150


def test_two_step_sign_in_can_be_required_of_admins(client):
    me = register(client)
    refused = client.put("/api/admin/settings", json={"admin_mfa": True})
    assert refused.status_code == 400 and "your own account first" in refused.json()["detail"]
    client.app.state.db.run("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (me["id"],))
    assert client.put("/api/admin/settings", json={"admin_mfa": True}).json()["admin_mfa"] is True
    assert client.get("/api/admin/admins").json()["admins"][0]["mfa_enabled"] == 1
    client.app.state.db.run("UPDATE users SET mfa_enabled = 0 WHERE id = ?", (me["id"],))
    locked = client.get("/api/admin/overview")
    assert locked.status_code == 403 and "two-step sign-in" in locked.json()["detail"]
    assert client.get("/api/jobs").status_code == 200    # the rest of the studio still works


def test_an_announcement_shows_to_everyone_until_it_ends(client):
    with_bob(client)
    shown = client.put("/api/admin/announcement", json={"text": "  Renders are down   until 6 pm ", "level": "warning", "hours": 2}).json()
    assert shown["text"] == "Renders are down until 6 pm" and shown["level"] == "warning" and shown["until"]
    as_bob(client)
    assert client.get("/api/announcement").json()["text"] == "Renders are down until 6 pm"
    assert client.put("/api/admin/announcement", json={"text": "x"}).status_code == 403
    as_admin(client)
    stored = json.loads(client.app.state.db.setting("announcement"))
    client.app.state.db.set_setting("announcement", json.dumps(dict(stored, until=1)))   # it has ended
    assert client.get("/api/announcement").json() == {}
    client.put("/api/admin/announcement", json={"text": "Welcome", "hours": 0})
    assert client.get("/api/announcement").json()["until"] is None
    client.put("/api/admin/announcement", json={"text": ""})
    assert client.get("/api/announcement").json() == {}


def test_everyone_can_be_given_credits_with_a_reason(client):
    bob = with_bob(client)
    assert client.post("/api/admin/credits/everyone", json={"amount": 50}).status_code == 400   # a reason is needed
    client.put("/api/admin/users/%d" % bob["id"], json={"disabled": True})
    given = client.post("/api/admin/credits/everyone", json={"amount": 50, "note": "Launch week"}).json()
    assert given == {"accounts": 1, "amount": 50}                                               # not the disabled account
    assert client.get("/api/auth/me").json()["credits"] == 550
    notes = [e["note"] for e in client.get("/api/admin/credits?reason=admin+grant").json()["events"]]
    assert notes == ["Launch week"]


def test_back_up_now_lists_the_copies_and_storage_is_reported(client):
    register(client)
    listed = client.get("/api/admin/backups").json()
    assert listed["on"] is True and listed["keep"] == 14
    made = client.post("/api/admin/backups").json()
    assert made["ok"] and made["name"].startswith("scene_")
    names = [c["name"] for c in client.get("/api/admin/backups").json()["copies"]]
    assert made["name"] in names
    report = client.get("/api/admin/storage").json()
    assert report["people"][0]["email"] == ADMIN["email"] and report["render_server"]["total"] == 0 and report["largest"] == []


def test_the_overview_lists_signups_and_warns_of_many_from_one_address(client):
    register(client)
    client.post("/api/auth/logout")
    for n in range(2):
        client.post("/api/auth/register", json={"email": "guest%d@example.com" % n, "password": "guest password"})
    as_admin(client)
    overview = client.get("/api/admin/overview").json()
    signups = overview["signups"]
    assert signups["open"] is True and signups["today"] == 3 and signups["recent"][0]["email"] == "guest1@example.com"
    assert signups["crowded"][0]["accounts"] == 3
    assert any("accounts were made from one address" in a["text"] for a in overview["attention"])
    assert "since" in overview["server"] and overview["online"] == [] and "totals" in overview["economics"]
    assert "since" in overview["attention"][0]["text"]                     # the render server is offline in the tests
    assert client.post("/api/admin/server/check").json()["online"] is False


def test_the_overview_shows_who_is_online_and_on_which_page(client):
    register(client)
    with client.websocket_connect("/api/events") as ws:
        ws.receive_text()                                    # the first live message
        ws.send_text(json.dumps({"page": "#/canvas"}))
        ws.send_text(json.dumps({"page": "javascript:alert(1)"}))   # not a page of the studio: ignored
        ws.send_text("not json")
        import time
        for _ in range(50):
            online = client.get("/api/admin/overview").json()["online"]
            if online and online[0]["pages"]:
                break
            time.sleep(0.05)
        assert online[0]["email"] == ADMIN["email"] and online[0]["pages"] == ["#/canvas"] and online[0]["tabs"] == 1
    assert client.get("/api/admin/overview").json()["online"] == []


def test_admins_are_told_the_number_of_people_online_as_it_changes():
    import asyncio
    from scene.main import Hub

    class Tab:
        def __init__(self):
            self.heard = []

        async def send_text(self, message):
            self.heard.append(json.loads(message).get("online_users"))

    async def scenario():
        hub, admin, user, user_again = Hub(), Tab(), Tab(), Tab()
        settle = lambda: asyncio.sleep(0)
        hub.add(1, admin, admin=True)
        await settle()
        hub.add(2, user)
        await settle()
        hub.add(2, user_again)         # a second tab of the same person: still two people
        await settle()
        hub.discard(2, user)
        await settle()
        assert admin.heard == [1, 2]
        hub.discard(2, user_again)     # their last tab closed: they are offline
        await settle()
        assert admin.heard == [1, 2, 1] and hub.online() == 1
        assert user.heard == [] and user_again.heard == []   # only admins are told
        admin_tab = Tab()
        hub.add(1, admin_tab, admin=True)   # an admin's new tab hears the number at once
        await settle()
        assert admin_tab.heard == [1] and admin.heard == [1, 2, 1]
        hub.discard(1, admin_tab)
        await settle()
        assert admin.heard == [1, 2, 1]
    asyncio.run(scenario())
