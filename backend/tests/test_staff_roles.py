"""Staff roles in the admin console (staff.py): support, finance and moderators each see part of it and may change less
than they see; only an admin does everything, and only an admin changes roles or an admin's account."""

from scene import staff
from test_api import ADMIN, console, register

BOB = {"email": "bob@example.com", "password": "another one"}
CAROL = {"email": "carol@example.com", "password": "third one!"}


def staff_member(client, role):
    """Bob, a user, and Carol, given `role` by the admin. Returns (Carol's console, Bob's id, Carol's id)."""
    register(client)
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json=BOB).json()
    client.post("/api/auth/logout")
    carol = client.post("/api/auth/register", json=CAROL).json()
    assert console(client).put("/api/admin/users/{}".format(carol["id"]), json={"role": role}).status_code == 200
    from fastapi.testclient import TestClient
    desk = TestClient(client.app.state.console)   # Carol's own console, beside the admin's
    assert desk.post("/api/console/login", json=CAROL).status_code == 200
    return desk, bob["id"], carol["id"]


def test_the_table_of_who_may_do_what():
    assert staff.may("admin", "/api/admin/settings", "PUT")
    assert staff.may("support", "/api/admin/jobs/abc/retry", "POST") and not staff.may("support", "/api/admin/pricing", "PUT")
    assert staff.may("finance", "/api/admin/pricing", "PUT") and not staff.may("finance", "/api/admin/library", "GET")
    assert staff.may("moderator", "/api/admin/library/3", "DELETE") and not staff.may("moderator", "/api/admin/credits/everyone", "POST")
    assert staff.may("moderator", "/api/admin/users/3/sign-out", "POST") and not staff.may("finance", "/api/admin/users/3/sign-out", "POST")
    assert not staff.may("user", "/api/admin/overview", "GET")
    assert staff.sections("finance") == ["overview", "jobs", "users", "credits", "projects", "pricing", "economics"]
    assert "settings" not in staff.sections("support") and staff.sections("admin")[-1] == "settings"


def test_support_helps_people_but_does_not_run_the_studio(client):
    desk, bob, carol = staff_member(client, "support")
    me = desk.get("/api/console/me").json()
    assert me["role"] == "support" and me["role_label"] == "Support" and "users" in me["sections"] and "settings" not in me["sections"]
    assert client.get("/api/auth/me").json()["console"]["port"] == 8090      # the studio links staff to the console
    assert desk.get("/api/admin/users").status_code == 200 and desk.get("/api/admin/jobs").status_code == 200
    for path in ("/api/admin/settings", "/api/admin/pricing", "/api/admin/economics", "/api/admin/admins"):
        refused = desk.get(path)
        assert refused.status_code == 403 and "Support" in refused.json()["detail"], path
    assert desk.put("/api/admin/maintenance", json={"on": True}).status_code == 403
    assert desk.put("/api/admin/users/{}".format(bob), json={"add_credits": 50, "note": "sorry"}).status_code == 200
    assert desk.put("/api/admin/users/{}".format(bob), json={"role": "admin"}).status_code == 403          # no roles
    admin_id = client.app.state.db.one("SELECT id FROM users WHERE email = ?", (ADMIN["email"],))["id"]
    assert desk.put("/api/admin/users/{}".format(admin_id), json={"add_credits": 5}).status_code == 403   # nor an admin
    assert desk.post("/api/admin/users/{}/sign-out".format(admin_id), json={}).status_code == 403
    assert desk.post("/api/admin/users/{}/sign-out".format(bob), json={}).status_code == 200


def test_finance_and_moderators_see_their_parts(client):
    desk, bob, carol = staff_member(client, "finance")
    assert desk.get("/api/admin/economics").status_code == 200 and desk.get("/api/admin/pricing").status_code == 200
    assert desk.get("/api/admin/library").status_code == 403
    assert desk.put("/api/admin/users/{}".format(bob), json={"daily_cap": 300}).status_code == 200
    refused = desk.put("/api/admin/users/{}".format(bob), json={"disabled": True})
    assert refused.status_code == 403 and "disabled" in refused.json()["detail"]
    console(client).put("/api/admin/users/{}".format(carol), json={"role": "moderator"})
    assert desk.get("/api/admin/pricing").status_code == 403                    # the role in force at once
    assert desk.get("/api/admin/library").status_code == 200
    assert desk.put("/api/admin/users/{}".format(bob), json={"disabled": True}).status_code == 200
    assert desk.put("/api/admin/users/{}".format(bob), json={"add_credits": 10}).status_code == 403
    console(client).put("/api/admin/users/{}".format(carol), json={"role": "user"})
    assert desk.get("/api/admin/overview").status_code == 403                   # no longer staff: no console
    assert console(client).put("/api/admin/users/{}".format(carol), json={"role": "boss"}).status_code == 400
    staffers = console(client).get("/api/admin/users?show=admins").json()["users"]
    assert [u["email"] for u in staffers] == [ADMIN["email"]]


def test_an_admin_views_the_studio_as_a_user_read_only(client):
    from fastapi.testclient import TestClient
    me = register(client)
    client.post("/api/auth/logout")
    bob = client.post("/api/auth/register", json=BOB).json()
    project = client.post("/api/projects", json={"name": "Bob's film"}).json()["id"]
    desk = console(client)
    assert desk.post("/api/admin/users/{}/view".format(me["id"])).status_code == 400          # not an admin's account
    view = desk.post("/api/admin/users/{}/view".format(bob["id"])).json()
    assert view["path"].startswith("/api/auth/view/") and view["port"] == 8080
    browser = TestClient(client.app)                                   # the admin's browser, opening the link
    landed = browser.get(view["path"], follow_redirects=False)
    assert landed.status_code == 303 and landed.headers["location"] == "/projects"
    seen = browser.get("/api/auth/me").json()
    assert seen["email"] == BOB["email"] and seen["viewing"] == {"by": "Ada"}
    assert [p["id"] for p in browser.get("/api/projects").json()["projects"]] == [project]      # what Bob sees
    refused = browser.post("/api/projects", json={"name": "Not allowed"})
    assert refused.status_code == 403 and "read-only" in refused.json()["detail"]
    assert browser.put("/api/auth/password", json={"current": "x", "new": "yyyyyyyyyy"}).status_code == 403
    again = TestClient(client.app).get(view["path"], follow_redirects=False)
    assert again.headers["location"] == "/signin"                       # the code works once
    sessions = desk.get("/api/admin/users/{}".format(bob["id"])).json()["sessions"]
    assert len(sessions) == 2                                           # Bob's own, and the view
    actions = [a["action"] for a in desk.get("/api/admin/audit").json()["entries"]]
    assert "Viewed the studio as a user" in actions
    assert browser.post("/api/auth/logout").status_code == 200 and browser.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").json()["email"] == BOB["email"] and "viewing" not in client.get("/api/auth/me").json()
