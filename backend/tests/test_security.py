"""The security measures: forged requests, headers, uploads, other users' files, rate limits, passwords and two-step sign-in."""

import json
import time

from scene import security

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def account(client, email="ada@example.com", password="correct horse"):
    client.cookies.clear()
    return client.post("/api/auth/register", json={"email": email, "password": password}).json()


def test_a_change_sent_from_another_site_is_refused(client):
    account(client)
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}, {"Origin": "https://evil.example"}):
        response = client.post("/api/projects", json={"name": "Forged"}, headers=headers)
        assert response.status_code == 403, headers
    assert client.post("/api/projects", json={"name": "Mine"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/api/projects", json={"name": "Mine too"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.get("/api/projects", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200   # reading is not a change


def test_every_answer_carries_the_security_headers_and_the_api_map_is_hidden(client):
    page = client.get("/")
    policy = page.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy and "unsafe-inline" not in policy.split("style-src")[0]
    assert page.headers["x-content-type-options"] == "nosniff" and page.headers["x-frame-options"] == "DENY"
    assert "<script>" not in page.text   # no inline script, which the policy would block
    assert "strict-transport-security" not in page.headers   # plain http here
    assert client.get("/", headers={"X-Forwarded-Proto": "https"}).headers.get("strict-transport-security") is None   # not believed from afar
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_an_upload_must_be_what_its_name_says(client):
    account(client)
    page = b"<html><script>alert(1)</script></html>"
    assert client.post("/api/assets", files={"file": ("face.png", page, "image/png")}).status_code == 400
    assert client.post("/api/assets", files={"file": ("face.png", PNG, "image/png")}).status_code == 200
    assert security.sniff(b"\x00\x00\x00\x18ftypmp42") == "video/audio"
    assert security.content_matches("audio", b"ID3\x04" + b"0" * 20) and not security.content_matches("image", b"ID3\x04")


def test_a_reference_file_of_another_user_cannot_be_used_or_seen(client, monkeypatch):
    sent = []

    async def upload(name, data, content_type=None):
        sent.append(name)
        return name
    monkeypatch.setattr(client.app.state.comfy, "upload", upload)
    account(client)
    settings = {"workflow": "video/h3_master", "values": {"100:value": "She waves."}, "options": {"engine": "reference"}}
    made = client.post("/api/jobs", data={"settings": json.dumps(settings)}, files={"ref:201:image": ("face.png", PNG, "image/png")})
    assert made.status_code == 200
    mine = sent[0]
    again = dict(settings, refs={"201:image": {"comfy_name": mine}})
    assert client.post("/api/jobs", data={"settings": json.dumps(again)}).status_code == 200   # the owner may reuse it

    account(client, "eve@example.com")
    assert client.post("/api/jobs", data={"settings": json.dumps(again)}).status_code == 400
    assert client.get("/api/ref-preview", params={"name": mine}).status_code == 404
    traversal = dict(settings, refs={"201:image": {"comfy_name": "scene_0123456789_../../secret.png"}})
    assert client.post("/api/jobs", data={"settings": json.dumps(traversal)}).status_code == 400


def test_signing_in_is_rate_limited_per_address(client):
    account(client)
    client.cookies.clear()
    codes = [client.post("/api/auth/login", json={"email": "x{}@example.com".format(i), "password": "wrong one"}).status_code
             for i in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429


def test_an_old_password_hash_still_signs_in_and_is_upgraded(client):
    account(client)
    db = client.app.state.db
    old = security.OLD_SCRYPT
    salt = b"s" * 16
    legacy = "scrypt${}${}".format(salt.hex(), security._scrypt("correct horse", salt, old).hex())
    db.run("UPDATE users SET password_hash = ?", (legacy,))
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct horse"}).status_code == 200
    upgraded = db.one("SELECT password_hash FROM users")["password_hash"]
    assert upgraded != legacy and not security.needs_rehash(upgraded) and security.verify_password("correct horse", upgraded)
    assert not security.verify_password("x" * (security.MAX_PASSWORD + 1), upgraded)


def test_two_step_sign_in(client):
    account(client)
    assert client.get("/api/auth/mfa").json() == {"enabled": False, "recovery_left": 0}
    assert client.post("/api/auth/mfa/setup", json={"password": "wrong"}).status_code == 400
    secret = client.post("/api/auth/mfa/setup", json={"password": "correct horse"}).json()["secret"]
    now = int(time.time() // security.TOTP_STEP)
    valid = {security.totp_code(secret, step) for step in range(now - 1, now + 3)}
    wrong = next(c for c in ("000000", "111111", "222222", "333333", "444444") if c not in valid)
    assert client.post("/api/auth/mfa/enable", json={"code": wrong}).status_code == 400
    codes = client.post("/api/auth/mfa/enable", json={"code": security.totp_code(secret, now)}).json()["recovery_codes"]
    assert len(codes) == 8 and client.get("/api/auth/mfa").json() == {"enabled": True, "recovery_left": 8}

    client.cookies.clear()
    password = {"email": "ada@example.com", "password": "correct horse"}
    asked = client.post("/api/auth/login", json=password)
    assert asked.status_code == 401 and asked.json()["mfa_required"] is True and "scene_session" not in asked.cookies
    assert client.post("/api/auth/login", json=dict(password, code="123")).status_code == 401
    # The code just used to turn it on is spent; the next one works, once.
    assert client.post("/api/auth/login", json=dict(password, code=security.totp_code(secret, now))).status_code == 401
    assert client.post("/api/auth/login", json=dict(password, code=security.totp_code(secret, now + 1))).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json=dict(password, code=codes[0])).status_code == 200   # a recovery code
    client.cookies.clear()
    assert client.post("/api/auth/login", json=dict(password, code=codes[0])).status_code == 401   # only once
    assert client.post("/api/auth/login", json=dict(password, code=codes[1].upper())).status_code == 200
    assert client.get("/api/auth/mfa").json()["recovery_left"] == 6

    # An admin can turn it off for someone who lost their phone, which signs them out.
    users = client.get("/api/admin/users").json()["users"]
    assert users[0]["mfa_enabled"] == 1
    assert client.put("/api/admin/users/{}".format(users[0]["id"]), json={"mfa_off": True}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json=password).status_code == 200


def test_the_first_account_is_made_only_on_this_machine(client):
    client.app.state.settings.first_account_local = True
    made = client.post("/api/auth/register", json={"email": "ada@example.com", "password": "correct horse"})
    assert made.status_code == 403 and "localhost" in made.json()["detail"]


def test_totp_matches_the_rfc_test_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # "12345678901234567890", RFC 6238 appendix B
    assert security.totp_code(secret, 59 // 30) == "287082"
    assert security.check_totp(secret, "287082", now=59) == 1
    assert security.check_totp(secret, "287082", last_step=1, now=59) is None


def test_row_level_security_keeps_each_user_to_their_own_rows(client):
    """PostgreSQL only: the database itself refuses other users' rows, even to SQL that forgot to ask for one user's."""
    import pytest
    from scene import db as storage
    db = client.app.state.db
    if db.kind != "postgres":
        pytest.skip("row-level security is PostgreSQL's")
    ada = account(client)["id"]
    client.post("/api/projects", json={"name": "Ada's"})
    eve = account(client, "eve@example.com")["id"]
    client.post("/api/projects", json={"name": "Eve's"})
    try:
        storage.act_for(ada)
        assert [p["name"] for p in db.all("SELECT name FROM projects")] == ["Ada's"]        # no user_id in the SQL
        assert [u["id"] for u in db.all("SELECT id FROM users")] == [ada]
        assert db.change("UPDATE projects SET name = 'taken' WHERE user_id = ?", (eve,)) == 0
        with pytest.raises(Exception):   # a row written for another user is refused
            db.run("INSERT INTO projects (user_id, name, created) VALUES (?, ?, ?)", (eve, "planted", 0))
        with storage.as_everyone():
            assert sorted(p["name"] for p in db.all("SELECT name FROM projects")) == ["Ada's", "Eve's"]
    finally:
        storage.act_for_everyone()
    # A connection that never says whose rows it wants sees none.
    import psycopg
    with psycopg.connect(db.url) as raw:
        assert raw.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert raw.execute("SELECT COUNT(*) FROM settings").fetchone()[0] >= 0   # tables of the whole installation are open

