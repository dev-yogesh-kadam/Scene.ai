"""Projects shared with other people (sharing.py): an owner adds people by email with a role, and each sees and does in
the project what their role allows. Run on PostgreSQL too, where the database itself keeps each user's rows apart."""

from test_api import ADMIN, register

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
BOB = {"name": "Bob", "email": "bob@example.com", "password": "correct horse 2"}
CAT = {"name": "Cat", "email": "cat@example.com", "password": "correct horse 3"}


def as_(client, who):
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": who["email"], "password": who["password"]}).status_code == 200


def upload(client, project_id):
    return client.post("/api/library/upload", files={"file": ("shot.png", PNG, "image/png")}, data={"project_id": str(project_id)})


def setup(client):
    """Ada owns "Film" with one item; Bob and Cat have accounts. Ada is signed in."""
    register(client, **BOB)
    register(client, **CAT)
    ada = register(client)
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    assert upload(client, film).status_code == 200
    return ada, film


def test_people_are_added_by_email_with_a_role(client):
    _, film = setup(client)
    found = client.post("/api/projects/{}/members".format(film), json={"people": [
        {"email": "BOB@example.com", "role": "creator"}, {"email": "nobody@example.com", "role": "viewer"}]}).json()
    assert [a["email"] for a in found["added"]] == ["bob@example.com"]
    assert found["problems"][0]["email"] == "nobody@example.com" and "sign up" in found["problems"][0]["problem"]
    assert [(m["email"], m["role"]) for m in found["members"]] == [("ada@example.com", "owner"), ("bob@example.com", "creator")]
    page = client.get("/api/projects/{}".format(film)).json()["project"]
    assert page["role"] == "owner" and len(page["members"]) == 2


def test_a_creator_works_in_the_project_and_sees_everyones_work(client):
    _, film = setup(client)
    client.post("/api/projects/{}/members".format(film), json={"people": [{"email": BOB["email"], "role": "creator"}]})
    client.put("/api/boards/canvas", json={"project": film, "data": {"rows": ["by ada"]}})
    as_(client, BOB)
    listed = {p["id"]: p for p in client.get("/api/projects").json()["projects"]}
    assert listed[film]["role"] == "creator" and listed[film]["owner_name"] == "Ada" and listed[film]["items"] == 1
    assert client.get("/api/projects/{}".format(film)).json()["project"]["role"] == "creator"
    assert upload(client, film).status_code == 200                                            # makes something there
    items = client.get("/api/library?project={}".format(film)).json()["items"]
    assert sorted(i["mine"] for i in items) == [False, True]                                  # Ada's and Bob's
    theirs = next(i for i in items if not i["mine"])
    assert theirs["made_by"] == "Ada" and client.get("/api/library/{}/file".format(theirs["id"])).status_code == 200
    assert client.get("/api/boards/canvas?project={}".format(film)).json()["data"] == {"rows": ["by ada"]}   # the owner's canvas
    client.put("/api/boards/canvas", json={"project": film, "data": {"rows": ["by bob"]}})
    module = client.post("/api/projects", json={"name": "Episode 1", "parent_id": film}).json()["id"]
    assert client.post("/api/kit", json={"project_id": film, "text": "INT. NIGHT", "name": "Script"}).status_code == 200
    assert client.put("/api/projects/{}".format(film), json={"name": "Mine now"}).status_code == 403   # a manager's
    assert client.delete("/api/projects/{}".format(film)).status_code == 403                           # the owner's
    as_(client, ADMIN)
    assert client.get("/api/boards/canvas?project={}".format(film)).json()["data"] == {"rows": ["by bob"]}
    assert len(client.get("/api/library?project={}".format(film)).json()["items"]) == 2
    assert [m["name"] for m in client.get("/api/projects/{}".format(film)).json()["modules"]] == ["Module 1", "Episode 1"]
    assert module in [p["id"] for p in client.get("/api/projects").json()["projects"]]                # the owner's module
    assert [e["name"] for e in client.get("/api/kit?project={}".format(film)).json()["entries"]] == ["Script"]
    assert len(client.get("/api/library").json()["items"]) == 1   # Ada's own library is still hers alone


def test_what_each_role_may_do(client):
    _, film = setup(client)
    client.post("/api/projects/{}/members".format(film), json={"people": [{"email": BOB["email"], "role": "viewer"}]})
    as_(client, BOB)
    assert client.get("/api/projects/{}".format(film)).status_code == 200
    assert upload(client, film).status_code == 403                                             # a viewer only looks
    assert client.put("/api/boards/canvas", json={"project": film, "data": {}}).status_code == 403
    assert client.post("/api/projects/{}/members".format(film), json={"people": [{"email": CAT["email"]}]}).status_code == 403
    as_(client, ADMIN)
    client.put("/api/projects/{}/members/{}".format(film, bob_id(client, film)), json={"role": "manager"})
    as_(client, BOB)
    found = client.post("/api/projects/{}/members".format(film), json={"people": [
        {"email": CAT["email"], "role": "creator"}, {"email": "ada@example.com", "role": "viewer"}]}).json()
    assert [a["email"] for a in found["added"]] == [CAT["email"]] and "owner" in found["problems"][0]["problem"]
    assert client.post("/api/projects/{}/members".format(film), json={"people": [{"email": CAT["email"], "role": "manager"}]}).json()["problems"]
    assert client.put("/api/projects/{}".format(film), json={"name": "Film 2"}).status_code == 200   # a manager renames
    assert client.delete("/api/projects/{}".format(film)).status_code == 403                         # but only the owner deletes
    assert client.delete("/api/projects/{}/members/{}".format(film, bob_id(client, film))).status_code == 200   # leaves
    assert client.get("/api/projects/{}".format(film)).status_code == 404
    assert film not in [p["id"] for p in client.get("/api/projects").json()["projects"]]


def test_someone_not_in_a_project_sees_nothing_of_it(client):
    _, film = setup(client)
    item = client.get("/api/library?project={}".format(film)).json()["items"][0]["id"]
    as_(client, CAT)
    assert client.get("/api/projects/{}".format(film)).status_code == 404
    assert client.get("/api/library?project={}".format(film)).status_code == 404
    assert client.get("/api/library/{}/file".format(item)).status_code == 404
    assert client.get("/api/boards/canvas?project={}".format(film)).status_code == 404
    assert client.get("/api/kit?project={}".format(film)).status_code == 404
    assert upload(client, film).status_code == 404


def test_deleting_a_shared_project_deletes_everyones_work_in_it(client):
    _, film = setup(client)
    client.post("/api/projects/{}/members".format(film), json={"people": [{"email": BOB["email"], "role": "creator"}]})
    as_(client, BOB)
    made = upload(client, film).json()
    state = client.app.state
    bobs_file = state.outputs.folder(made["user_id"]) / made["filename"]
    assert bobs_file.is_file()
    as_(client, ADMIN)
    assert client.delete("/api/projects/{}".format(film)).json()["items_deleted"] == 2
    assert not bobs_file.exists()
    as_(client, BOB)
    assert client.get("/api/projects").json()["projects"] == []


def bob_id(client, film):
    return next(m["user_id"] for m in client.get("/api/projects/{}/members".format(film)).json()["members"] if m["email"] == BOB["email"])
