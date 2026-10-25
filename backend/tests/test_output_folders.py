"""Each user's finished work is kept in a folder per project, with one per module inside it (outputs.py): named after
the project, renamed with it, and deleted with it. The backup's copies are never touched."""

import time

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def upload(client, project_id, name="shot.png"):
    return client.post("/api/library/upload", files={"file": (name, PNG, "image/png")}, data={"project_id": str(project_id)}).json()


def test_work_is_filed_by_project_and_module_and_follows_them(client):
    from test_api import register
    me = register(client)
    state, db = client.app.state, client.app.state.db
    home = state.outputs.folder(me["id"])
    film = client.post("/api/projects", json={"name": "Pocket: Film"}).json()["id"]
    one = client.post("/api/projects", json={"name": "Episode 1", "parent_id": film}).json()["id"]
    other = client.post("/api/projects", json={"name": "Other"}).json()["id"]
    main_item, module_item = upload(client, film), upload(client, one)
    path = lambda item: db.one("SELECT filename FROM generations WHERE id = ?", (item["id"],))["filename"]
    assert path(main_item).startswith("Pocket_ Film ({})/Module 1/".format(film))           # safe on every system
    assert path(module_item).startswith("Pocket_ Film ({})/Episode 1 ({})/".format(film, one))
    assert (home / path(module_item)).is_file()
    assert client.get("/api/library/{}/file".format(module_item["id"])).content == PNG

    client.put("/api/projects/{}".format(film), json={"name": "Pocket"})                       # renamed: the folder follows
    assert path(module_item).startswith("Pocket ({})/Episode 1 ({})/".format(film, one))
    assert not (home / "Pocket_ Film ({})".format(film)).exists()
    assert client.get("/api/library/{}/file".format(module_item["id"])).content == PNG

    client.put("/api/library/{}".format(main_item["id"]), json={"project_id": other})          # moved to another project
    assert path(main_item).startswith("Other ({})/Module 1/".format(other)) and (home / path(main_item)).is_file()
    client.put("/api/library/{}".format(main_item["id"]), json={"project_id": None})
    assert path(main_item).startswith("No project/")

    backup = home.parent.parent / "backup-copy.png"
    backup.write_bytes(PNG)                                                                      # stands for E:\SceneBackups
    client.delete("/api/projects/{}".format(one))                                               # a module: its folder goes
    assert not (home / "Pocket ({})".format(film) / "Episode 1 ({})".format(one)).exists()
    upload(client, film)
    assert (home / "Pocket ({})".format(film)).is_dir()
    client.delete("/api/projects/{}".format(film))                                              # the project: all of it
    assert not (home / "Pocket ({})".format(film)).exists()
    assert (home / path(main_item)).is_file() and backup.is_file()                             # others, and the backup, stay


def test_work_from_before_folders_is_filed_once(client):
    from test_api import register
    me = register(client)
    state, db = client.app.state, client.app.state.db
    home = state.outputs.folder(me["id"])
    film = client.post("/api/projects", json={"name": "Old"}).json()["id"]
    home.mkdir(parents=True, exist_ok=True)
    (home / "flat.png").write_bytes(PNG)
    (home / ".posters").mkdir(exist_ok=True)
    (home / ".posters" / "flat.png.jpg").write_bytes(b"p")
    (home / "loose.png").write_bytes(PNG)
    db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, project_id) "
           "VALUES (?, 'image/x', 'image', 'Flat', 'flat.png', '{}', '{}', ?, ?)", (me["id"], time.time(), film))
    db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
           "VALUES (?, 'image/x', 'image', 'Loose', 'loose.png', '{}', '{}', ?)", (me["id"], time.time()))
    assert state.outputs.file_all() == 2
    names = sorted(r["filename"] for r in db.all("SELECT filename FROM generations WHERE user_id = ?", (me["id"],)))
    assert names == ["No project/loose.png", "Old ({})/Module 1/flat.png".format(film)]
    assert (home / "Old ({})".format(film) / "Module 1" / ".posters" / "flat.png.jpg").is_file()   # its poster went with it
    assert not (home / ".posters").exists()                                                    # nothing left behind
    assert state.outputs.file_all() == 0                                                       # nothing left to file


def test_work_filed_at_the_top_of_a_project_moves_into_its_main_canvas_folder(client):
    from test_api import register
    me = register(client)
    state, db = client.app.state, client.app.state.db
    home = state.outputs.folder(me["id"])
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    (home / "Film ({})".format(film)).mkdir(parents=True)
    (home / "Film ({})".format(film) / "shot.png").write_bytes(PNG)                      # where it was filed before
    db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, project_id) "
           "VALUES (?, 'image/x', 'image', 'Shot', ?, '{}', '{}', ?, ?)", (me["id"], "Film ({})/shot.png".format(film), time.time(), film))
    assert state.outputs.file_all() == 1
    assert db.one("SELECT filename FROM generations WHERE project_id = ?", (film,))["filename"] == "Film ({})/Module 1/shot.png".format(film)
    assert [p.name for p in (home / "Film ({})".format(film)).iterdir()] == ["Module 1"]   # the project folder holds folders only


def test_the_main_canvas_can_be_renamed_and_its_folder_follows(client):
    from test_api import register
    me = register(client)
    state, db = client.app.state, client.app.state.db
    home = state.outputs.folder(me["id"])
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    one = client.post("/api/projects", json={"name": "Episode 1", "parent_id": film}).json()["id"]
    item = upload(client, film)
    path = lambda: db.one("SELECT filename FROM generations WHERE id = ?", (item["id"],))["filename"]
    assert client.get("/api/projects/{}".format(film)).json()["modules"][0]["name"] == "Module 1"
    assert client.put("/api/projects/{}/canvas".format(film), json={"name": "Teaser: cut"}).status_code == 200
    assert client.get("/api/projects/{}".format(film)).json()["modules"][0]["name"] == "Teaser: cut"
    assert path().startswith("Film ({})/Teaser_ cut/".format(film)) and (home / path()).is_file()
    assert not (home / "Film ({})".format(film) / "Module 1").exists()
    assert client.get("/api/projects/{}/analytics".format(film)).json()["modules"][0]["name"] == "Teaser: cut"
    assert next(p for p in client.get("/api/projects").json()["projects"] if p["id"] == film)["canvas_name"] == "Teaser: cut"
    assert client.put("/api/projects/{}/canvas".format(film), json={"name": "Main canvas"}).status_code == 200   # the name of projects from before "Module 1"
    assert path().startswith("Film ({})/Main canvas/".format(film)) and (home / path()).is_file()
    assert client.put("/api/projects/{}/canvas".format(one), json={"name": "X"}).status_code == 400            # a module is renamed as one
    assert client.put("/api/projects/{}/canvas".format(film), json={"name": " "}).status_code == 400


def test_a_new_projects_own_canvas_is_module_1_and_a_copy_keeps_its_name(client):
    from test_api import register
    register(client)
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    assert client.get("/api/projects/{}".format(film)).json()["modules"][0]["name"] == "Module 1"
    client.put("/api/projects/{}/canvas".format(film), json={"name": "Opening"})
    copy = client.post("/api/projects/{}/duplicate".format(film)).json()["id"]
    assert client.get("/api/projects/{}".format(copy)).json()["modules"][0]["name"] == "Opening"
