"""The admin console's tools: the queue, retries, the daily limit, two-step sign-in for admins, announcements,
credits for everyone, backups, storage, and what the Overview adds."""

import json

from test_api import ADMIN, console, post_job, register

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
    assert console(client).put("/api/admin/queue", json={"paused": True}).json() == {"paused": True}
    first, second = post_job(client).json()["id"], post_job(client).json()["id"]
    overview = console(client).get("/api/admin/overview").json()
    assert overview["queue"]["paused"] is True and [j["id"] for j in overview["queue"]["waiting"]] == [first, second]
    assert any("paused" in a["text"] for a in overview["attention"])
    assert console(client).post("/api/admin/jobs/%s/front" % second).status_code == 200
    assert [j["id"] for j in console(client).get("/api/admin/overview").json()["queue"]["waiting"]] == [second, first]
    positions = {j["id"]: j["position"] for j in client.get("/api/jobs").json()["jobs"]}
    assert positions[second] == 1 and positions[first] == 2
    assert console(client).delete("/api/admin/jobs/" + first).status_code == 200
    assert console(client).post("/api/admin/jobs/%s/front" % first).status_code == 400    # no longer waiting
    console(client).put("/api/admin/queue", json={"paused": False})
    assert console(client).get("/api/admin/overview").json()["queue"]["paused"] is False


def test_a_failed_job_is_explained_and_can_run_again_charged_or_free(client):
    register(client)
    console(client).put("/api/admin/queue", json={"paused": True})   # so the new runs stay waiting
    job = post_job(client).json()["id"]
    client.app.state.db.run("UPDATE jobs SET status = 'failed', error = ? WHERE id = ?",
                            ("ComfyUI error in node 'KSampler': CUDA out of memory. Tried to allocate 2 GiB", job))
    detail = console(client).get("/api/admin/jobs/" + job).json()
    assert "graphics memory" in detail["explained"]
    assert "graphics memory" in console(client).get("/api/admin/jobs?status=failed").json()["jobs"][0]["explained"]
    before = client.get("/api/auth/me").json()["credits"]
    again = console(client).post("/api/admin/jobs/%s/retry" % job, json={}).json()
    assert again["credits"] == 100 and client.get("/api/auth/me").json()["credits"] == before - 100
    free = console(client).post("/api/admin/jobs/%s/retry" % job, json={"free": True}).json()
    assert free["credits"] == 0 and client.get("/api/auth/me").json()["credits"] == before - 100
    queued = client.app.state.db.one("SELECT settings, status FROM jobs WHERE id = ?", (free["id"],))
    assert queued["status"] == "queued" and json.loads(queued["settings"])["options"]["quality"] == "high"
    assert console(client).post("/api/admin/jobs/%s/retry" % free["id"], json={}).status_code == 400   # it has not failed


def test_the_daily_credit_limit_stops_users_but_not_admins(client):
    bob = with_bob(client)
    console(client).put("/api/admin/queue", json={"paused": True})
    assert console(client).put("/api/admin/settings", json={"daily_cap": 150}).json()["daily_cap"] == 150
    assert post_job(client).status_code == 200 and post_job(client).status_code == 200   # admins have no limit
    as_bob(client)
    assert post_job(client).status_code == 200
    refused = post_job(client)
    assert refused.status_code == 429 and "spend 150 in 24 hours and has spent 100" in refused.json()["detail"]
    as_admin(client)
    limits = console(client).get("/api/admin/users/%d" % bob["id"]).json()["limits"]
    assert limits == {"own": None, "studio": 150, "in_force": 150, "spent_today": 100, "exempt": False}
    console(client).put("/api/admin/users/%d" % bob["id"], json={"daily_cap": 0})    # no limit for Bob
    as_bob(client)
    assert post_job(client).status_code == 200
    as_admin(client)
    console(client).put("/api/admin/users/%d" % bob["id"], json={"daily_cap": None})   # back to the studio's
    assert console(client).get("/api/admin/users/%d" % bob["id"]).json()["limits"]["in_force"] == 150


def test_two_step_sign_in_can_be_required_of_admins(client):
    me = register(client)
    refused = console(client).put("/api/admin/settings", json={"admin_mfa": True})
    assert refused.status_code == 400 and "your own account first" in refused.json()["detail"]
    client.app.state.db.run("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (me["id"],))
    assert console(client).put("/api/admin/settings", json={"admin_mfa": True}).json()["admin_mfa"] is True
    assert console(client).get("/api/admin/admins").json()["admins"][0]["mfa_enabled"] == 1
    client.app.state.db.run("UPDATE users SET mfa_enabled = 0 WHERE id = ?", (me["id"],))
    locked = console(client).get("/api/admin/overview")
    assert locked.status_code == 403 and "two-step sign-in" in locked.json()["detail"]
    client.console.cookies.clear()   # nor can they sign in to it again
    refused = client.console.post("/api/console/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert refused.status_code == 403 and "two-step sign-in" in refused.json()["detail"]
    assert client.get("/api/jobs").status_code == 200    # the rest of the studio still works


def test_an_announcement_shows_to_everyone_until_it_ends(client):
    with_bob(client)
    shown = console(client).put("/api/admin/announcement", json={"text": "  Renders are down   until 6 pm ", "level": "warning", "hours": 2}).json()
    assert shown["text"] == "Renders are down until 6 pm" and shown["level"] == "warning" and shown["until"]
    as_bob(client)
    assert client.get("/api/announcement").json()["text"] == "Renders are down until 6 pm"
    assert client.put("/api/admin/announcement", json={"text": "x"}).status_code in (404, 405)   # not on the studio's port
    assert console(client).get("/api/admin/announcement").json()["text"] == "Renders are down until 6 pm"
    as_admin(client)
    stored = json.loads(client.app.state.db.setting("announcement"))
    client.app.state.db.set_setting("announcement", json.dumps(dict(stored, until=1)))   # it has ended
    assert client.get("/api/announcement").json() == {}
    console(client).put("/api/admin/announcement", json={"text": "Welcome", "hours": 0})
    assert client.get("/api/announcement").json()["until"] is None
    console(client).put("/api/admin/announcement", json={"text": ""})
    assert client.get("/api/announcement").json() == {}


def test_everyone_can_be_given_credits_with_a_reason(client):
    bob = with_bob(client)
    assert console(client).post("/api/admin/credits/everyone", json={"amount": 50}).status_code == 400   # a reason is needed
    console(client).put("/api/admin/users/%d" % bob["id"], json={"disabled": True})
    given = console(client).post("/api/admin/credits/everyone", json={"amount": 50, "note": "Launch week"}).json()
    assert given == {"accounts": 1, "amount": 50}                                               # not the disabled account
    assert client.get("/api/auth/me").json()["credits"] == 550
    notes = [e["note"] for e in console(client).get("/api/admin/credits?reason=admin+grant").json()["events"]]
    assert notes == ["Launch week"]


def test_back_up_now_lists_the_copies_and_storage_is_reported(client):
    register(client)
    listed = console(client).get("/api/admin/backups").json()
    assert listed["on"] is True and listed["keep"] == 14
    made = console(client).post("/api/admin/backups").json()
    assert made["ok"] and made["name"].startswith("scene_")
    names = [c["name"] for c in console(client).get("/api/admin/backups").json()["copies"]]
    assert made["name"] in names
    report = console(client).get("/api/admin/storage").json()
    assert report["people"][0]["email"] == ADMIN["email"] and report["render_server"]["total"] == 0 and report["largest"] == []


def test_the_overview_lists_signups_and_warns_of_many_from_one_address(client):
    register(client)
    client.post("/api/auth/logout")
    for n in range(2):
        client.post("/api/auth/register", json={"email": "guest%d@example.com" % n, "password": "guest password"})
    as_admin(client)
    overview = console(client).get("/api/admin/overview").json()
    signups = overview["signups"]
    assert signups["open"] is True and signups["today"] == 3 and signups["recent"][0]["email"] == "guest1@example.com"
    assert signups["crowded"][0]["accounts"] == 3
    assert any("accounts were made from one address" in a["text"] for a in overview["attention"])
    assert "since" in overview["server"] and overview["online"] == [] and "totals" in overview["economics"]
    assert "since" in overview["attention"][0]["text"]                     # the render server is offline in the tests
    assert console(client).post("/api/admin/server/check").json()["online"] is False


def test_the_overview_shows_who_is_online_and_on_which_page(client):
    register(client)
    with client.websocket_connect("/api/events") as ws:
        ws.receive_text()                                    # the first live message
        ws.send_text(json.dumps({"page": "#/canvas"}))
        ws.send_text(json.dumps({"page": "javascript:alert(1)"}))   # not a page of the studio: ignored
        ws.send_text("not json")
        import time
        for _ in range(50):
            online = console(client).get("/api/admin/overview").json()["online"]
            if online and online[0]["pages"]:
                break
            time.sleep(0.05)
        assert online[0]["email"] == ADMIN["email"] and online[0]["pages"] == ["#/canvas"] and online[0]["tabs"] == 1
    assert console(client).get("/api/admin/overview").json()["online"] == []


def test_the_console_is_told_the_number_of_people_online_as_it_changes():
    import asyncio
    from scene.main import Hub

    class Tab:
        def __init__(self):
            self.heard = []

        async def send_text(self, message):
            self.heard.append(json.loads(message).get("online_users"))

    async def scenario():
        hub, console, admin, user, user_again = Hub(), Tab(), Tab(), Tab(), Tab()
        settle = lambda: asyncio.sleep(0)
        hub.watch(console)              # an open page of the admin console hears the number at once
        await settle()
        hub.add(1, admin)
        await settle()
        hub.add(2, user)
        await settle()
        hub.add(2, user_again)         # a second tab of the same person: still two people
        await settle()
        hub.discard(2, user)
        await settle()
        assert console.heard == [0, 1, 2]
        hub.discard(2, user_again)     # their last tab closed: they are offline
        await settle()
        assert console.heard == [0, 1, 2, 1] and hub.online() == 1   # the console itself is not someone online
        assert admin.heard == [] and user.heard == [] and user_again.heard == []   # only the console is told
        hub.unwatch(console)
        hub.add(3, Tab())
        await settle()
        assert console.heard == [0, 1, 2, 1]
    asyncio.run(scenario())


def test_maintenance_refuses_new_jobs_gives_their_credits_back_and_shows_its_message(client):
    register(client)
    console(client).put("/api/admin/queue", json={"paused": True})   # so the job made before stays waiting
    before = post_job(client).json()["id"]
    credits = client.get("/api/auth/me").json()["credits"]
    on = console(client).put("/api/admin/maintenance", json={"on": True, "text": "Back at 6 pm."}).json()
    assert on["on"] is True and on["text"] == "Back at 6 pm."
    refused = post_job(client)
    assert refused.status_code == 503 and refused.json()["detail"] == "Back at 6 pm."
    assert client.get("/api/auth/me").json()["credits"] == credits          # what was taken for it came back
    assert client.get("/api/announcement").json() == {"text": "Back at 6 pm.", "level": "warning", "until": None, "maintenance": True}
    assert any(j["id"] == before and j["status"] == "queued" for j in client.get("/api/jobs").json()["jobs"])   # it still runs
    overview = console(client).get("/api/admin/overview").json()
    assert any("Maintenance has been on" in a["text"] and "1 job left" in a["text"] for a in overview["attention"])
    system = console(client).get("/api/admin/system").json()
    assert system["maintenance"]["on"] is True and system["maintenance"]["left"] == 1
    assert console(client).put("/api/admin/maintenance", json={"on": False}).json() == {"on": False}
    assert post_job(client).status_code == 200 and client.get("/api/announcement").json() == {}
    actions = [a["action"] for a in console(client).get("/api/admin/audit").json()["entries"]]
    assert "Turned on maintenance mode" in actions and "Turned off maintenance mode" in actions


def test_the_servers_that_do_not_answer_are_problems(client):
    import asyncio
    from scene import health
    register(client)
    found = asyncio.run(health.problems(client.app.state))   # both servers are at an address nothing listens on
    assert [p["key"] for p in found][:2] == ["render", "model"] and found[0]["level"] == "critical"
    attention = console(client).get("/api/admin/overview").json()["attention"]
    assert attention[0]["text"].startswith("The render server") and "model server" in attention[1]["text"]
    model = console(client).get("/api/admin/system").json()["model_server"]
    assert model["online"] is False and model["url"] == "http://127.0.0.1:9" and model["loaded"] == []


def test_the_watcher_sends_a_problem_found_twice_and_says_when_it_is_gone(client, monkeypatch):
    import asyncio
    from scene import health, phone
    register(client)
    sent = []

    async def fake_send(http, db, level, text):
        sent.append((level, text))
        return {}
    monkeypatch.setattr(phone, "send", fake_send)
    watcher = health.Watcher(client.app.state)
    down = [health.problem("render", "critical", "The render server is down.", "system")]

    async def scenario():
        assert await watcher.step(down, now=1000) == []                  # once could be a hiccup
        assert await watcher.step(down, now=1060) == [("critical", "The render server is down.")]
        assert await watcher.step(down, now=1120) == []                  # sent once, not every minute
        assert await watcher.step([], now=1720) == [("resolved", "The render server answers again (after 11 min).")]
        await watcher.http.aclose()
    asyncio.run(scenario())
    assert sent == [("critical", "The render server is down."), ("resolved", "The render server answers again (after 11 min).")]
    alerts = console(client).get("/api/admin/alerts").json()
    assert alerts["open"] == [] and [(a["key"], a["started"], a["ended"]) for a in alerts["recent"]] == [("render", 1060, 1720)]


def test_phone_alerts_are_set_up_tested_and_never_show_the_token(client):
    register(client)
    desk = console(client)
    assert desk.post("/api/admin/alerts/test").status_code == 400                 # nowhere to send yet
    assert desk.put("/api/admin/alerts/phone", json={"telegram_token": "nope"}).status_code == 400
    assert desk.put("/api/admin/alerts/phone", json={"ntfy_url": "ftp://x"}).status_code == 400
    token = "123456789:AAH" + "x" * 30
    shown = desk.put("/api/admin/alerts/phone", json={"telegram_token": token, "telegram_chat": "55501", "ntfy_url": "https://ntfy.sh/scene-test"}).json()
    assert shown == {"telegram_token_end": "xxxx", "telegram_chat": "55501", "ntfy_url": "https://ntfy.sh/scene-test", "on": True}
    assert token not in json.dumps(desk.get("/api/admin/alerts").json())
    assert desk.put("/api/admin/alerts/phone", json={"ntfy_url": ""}).json()["telegram_token_end"] == "xxxx"   # a token left out stays
    assert desk.put("/api/admin/alerts/phone", json={"telegram": False}).json()["on"] is False


def test_an_alert_goes_to_telegram_and_ntfy_in_their_own_forms():
    import asyncio
    import httpx
    from scene import phone

    class Settings:
        def setting(self, name, default=""):
            return json.dumps({"telegram_token": "1:tok", "telegram_chat": "42", "ntfy_url": "https://ntfy.sh/scene-t"})
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200 if "ntfy" in request.url.host else 403, json={"ok": False, "description": "Forbidden: bot was blocked"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
            return await phone.send(http, Settings(), "critical", "The render server is down.")
    results = asyncio.run(scenario())
    assert results == {"telegram": "it answered 403: Forbidden: bot was blocked", "ntfy": None}
    telegram, ntfy = seen
    assert str(telegram.url) == "https://api.telegram.org/bot1:tok/sendMessage"
    assert json.loads(telegram.content) == {"chat_id": "42", "text": "Scene.ai: Critical\nThe render server is down."}
    assert ntfy.content == b"The render server is down." and ntfy.headers["Priority"] == "5" and ntfy.headers["Title"] == "Scene.ai: Critical"


def test_the_console_hears_once_a_second_that_jobs_changed():
    import asyncio
    from scene.main import Hub

    class Tab:
        def __init__(self):
            self.heard = []

        async def send_text(self, message):
            self.heard.append(json.loads(message))

    async def scenario():
        hub, console = Hub(), Tab()
        hub.watch(console)
        for _ in range(5):          # a busy queue
            hub.jobs_changed()
        await asyncio.sleep(1.2)
        assert console.heard == [{"online_users": 0}, {"jobs": True}]
        hub.jobs_changed()
        await asyncio.sleep(1.2)
        assert console.heard[-1] == {"jobs": True} and len(console.heard) == 3
    asyncio.run(scenario())
