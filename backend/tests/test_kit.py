"""The kit of a project: what it is made from by name (characters, locations, props, voices, scripts), and what is always
on in its shots (what the cast was). One store for what the cast and the shared memory were."""

import asyncio
import json

from scene import kit, memory
from test_agent_conversation import model
from test_agent_shots import hosted
from test_api import register

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def schema_of(client, workflow_id):
    from scene.comfy import workflows
    return workflows.describe(asyncio.run(client.app.state.catalog.load(workflow_id)))


def picture(client, user_id, name, kind="image", project=None, about=""):
    """A library item with a real file."""
    folder = client.app.state.outputs.folder(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = {"image": ".png", "audio": ".mp3", "video": ".mp4"}[kind]
    (folder / (name + suffix)).write_bytes(PNG + name.encode())
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, about, project_id) "
        "VALUES (?, 'upload/file', ?, ?, ?, '{}', '{}', 1, ?, ?)", (user_id, kind, name, name + suffix, about, project))


def add(client, item, name, type_, always=False, project=None):
    return client.post("/api/kit", json={"item": item, "name": name, "type": type_, "always": always, "project_id": project}).json()


def test_entries_come_in_from_a_canvas_item_a_file_and_a_script_and_can_be_changed(client):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    violet = add(client, picture(client, me["id"], "v", project=project), "Violet", "character", True, project)
    assert (violet["name"], violet["type"], violet["always"], violet["named"]) == ("Violet", "character", True, True)
    clearing = client.post("/api/kit", files={"file": ("clearing.png", PNG + b"c", "image/png")},
                           data={"name": "Bonfire Clearing", "type": "location", "project_id": str(project)}).json()
    assert clearing["type"] == "location" and not clearing["always"]
    script = client.post("/api/kit", json={"text": "VIOLET: Do I know you?", "name": "Ep 135", "project_id": project}).json()
    assert (script["type"], script["kind"]) == ("script", "text")
    assert client.get("/api/assets/%d/file" % script["id"]).content == b"VIOLET: Do I know you?"
    # the same file again is the same entry
    again = client.post("/api/kit", files={"file": ("other-name.png", PNG + b"c", "image/png")}, data={"project_id": str(project)}).json()
    assert again["id"] == clearing["id"]
    listed = client.get("/api/kit?project=%d" % project).json()
    assert [e["name"] for e in listed["entries"]] == ["Violet", "Bonfire Clearing", "Ep 135"]   # always-on first
    assert client.get("/api/kit").json()["entries"] == []   # only in its own project
    # change, reorder, remove
    changed = client.put("/api/kit/%d" % clearing["id"], json={"name": "The Clearing", "always": True, "about": "Night, string lights."}).json()
    assert (changed["name"], changed["always"], changed["about"]) == ("The Clearing", True, "Night, string lights.")
    client.post("/api/kit/order", json={"project_id": project, "ids": [clearing["id"], violet["id"]]})
    assert [e["name"] for e in client.get("/api/kit?project=%d" % project).json()["entries"]] == ["The Clearing", "Violet", "Ep 135"]
    assert client.delete("/api/kit/%d" % script["id"]).status_code == 200
    assert client.put("/api/kit/999999", json={"name": "x"}).status_code == 404


def test_the_always_on_entries_fill_the_slots_meant_for_them_in_order(client):
    me = register(client)
    db = client.app.state.db
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    items = {n: picture(client, me["id"], n, project=project) for n in ("violet", "violet-side", "alice", "lily", "hazel", "madelyn", "clearing", "camera")}
    for name, item, type_ in (("Violet", "violet", "character"), ("Violet", "violet-side", "character"), ("Alice", "alice", "character"),
                              ("Lily", "lily", "character"), ("Hazel", "hazel", "character"), ("Madelyn", "madelyn", "character"),
                              ("Clearing", "clearing", "location"), ("Vlog Camera", "camera", "prop")):
        add(client, items[item], name, type_, always=True, project=project)
    on = kit.always(db, me["id"], project)
    master = kit.fills(schema_of(client, "video/h3_master"), on)
    # one main character and her other angle, one second person, the place and the prop: as many as the slots take
    assert [(f["name"], f["slot"], f["said_as"]) for f in master] == [
        ("Violet", "201:image", "the main character"), ("Violet", "202:image", "the main character"),
        ("Alice", "203:image", "the second person"), ("Clearing", "205:image", "the background"), ("Vlog Camera", "206:image", "the prop")]
    chunk = kit.fills(schema_of(client, "video/h3_chunk"), on)
    assert [(f["name"], f["slot"]) for f in chunk if f["role"] == "character"] == [
        ("Violet", "201:image"), ("Alice", "202:image"), ("Lily", "203:image"), ("Hazel", "204:image"), ("Madelyn", "212:image")]
    # a shot that leaves the place out, and one that has Alice in a slot already (by her library item)
    alice = next(e for e in on if e["name"] == "Alice")
    fewer = kit.fills(schema_of(client, "video/h3_master"), on, left_out={next(e["id"] for e in on if e["name"] == "Clearing")},
                      used_items={alice["made_from"]})
    assert [(f["name"], f["slot"]) for f in fewer] == [("Violet", "201:image"), ("Violet", "202:image"), ("Lily", "203:image"),
                                                       ("Vlog Camera", "206:image")]
    words = kit.described(on)
    assert 'character "Violet" (asset %d): in prompts call it "the main character"' % on[0]["id"] in words
    assert words.count('"Violet"') == 1 and '"leave_out"' in words


def test_the_cast_of_before_becomes_the_always_on_entries_of_the_kit(client):
    me = register(client)
    db = client.app.state.db
    project = client.post("/api/projects", json={"name": "Old"}).json()["id"]
    mira, side, harbour, song = (picture(client, me["id"], n, k, project) for n, k in
                                 (("mira", "image"), ("mira-side", "image"), ("harbour", "image"), ("song", "audio")))
    client.put("/api/boards/cast", json={"project": project, "data": {"character_1": mira, "character_2": side,
                                                                      "background": harbour, "voice": song, "prop": 999}})
    db.set_setting("kit_migrated", "0")
    from scene.db import as_everyone
    with as_everyone():
        moved = kit.migrate_cast(db, client.app.state.assets_dir, client.app.state.outputs)
    assert moved == 4 and kit.migrate_cast(db, client.app.state.assets_dir, client.app.state.outputs) == 0   # once
    on = kit.always(db, me["id"], project)
    assert [(e["name"], e["type"]) for e in on] == [("mira", "character"), ("mira", "character"), ("harbour", "location"), ("song", "voice")]
    fills = client.get("/api/cast?project=%d&workflow=video/h3_master" % project).json()["fills"]
    assert [(f["name"], f["slot"]) for f in fills] == [("mira", "201:image"), ("mira", "202:image"), ("harbour", "205:image"), ("song", "208:audio")]


def test_a_planned_shot_gets_the_always_on_entries_but_those_it_leaves_out(client, monkeypatch):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    violet = add(client, picture(client, me["id"], "v", project=project), "Violet", "character", True, project)
    clearing = add(client, picture(client, me["id"], "c", project=project), "Clearing", "location", True, project)
    shot = {"tool": "generate", "workflow": "video/h3_master", "name": "Close-up", "prompt": "The main character smiles at the camera."}
    asked = model(monkeypatch, client, {"thought": "", "reply": "Two shots.", "steps": [
        dict(shot, name="Wide"), dict(shot, leave_out=[clearing["id"]])]})
    plan = client.post("/api/agent/plan", json={"instruction": "two shots of Violet", "project_id": project}).json()
    wide, close = plan["steps"]
    assert [(u["asset"], u["slot"], u["cast"]) for u in wide["uses"]] == [(violet["id"], "201:image", True), (clearing["id"], "205:image", True)]
    assert [u["asset"] for u in close["uses"]] == [violet["id"]]
    assert 'character "Violet" (asset %d)' % violet["id"] in asked[0] and '"always": true' in asked[0]


def test_the_agent_keeps_and_names_entries_itself(client, monkeypatch):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    sheet = picture(client, me["id"], "sheet", project=project)
    seen = hosted(monkeypatch, client, {"tool": "kit_save", "item": sheet, "text": "Maya", "op": "character", "settings": "always"},
                  {"tool": "finish", "reply": "Kept Maya.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "keep that sheet as Maya", "project_id": project}).json()
    assert plan["reply"] == "Kept Maya." and any(e["text"] == "Kept “Maya” (character) in the NeuralCore" for e in plan["activity"])
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    entry = json.loads(next(t for t in told if t.startswith("Result of kit_save")).split("\n", 1)[1])
    assert entry["name"] == "Maya" and entry["always"] is True
    # and renames one
    hosted(monkeypatch, client, {"tool": "kit_save", "asset": entry["asset"], "text": "Maya Rao", "op": "character"},
           {"tool": "finish", "reply": "Renamed.", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "her name is Maya Rao", "project_id": project})
    assert [e["name"] for e in kit.entries(client.app.state.db, me["id"], project)] == ["Maya Rao"]
    # outside a project there is no NeuralCore: the agent is told so, and nothing is kept
    seen = hosted(monkeypatch, client, {"tool": "kit_save", "item": sheet, "text": "Lone", "op": "character"},
                  {"tool": "finish", "reply": "No project.", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "keep it as Lone"})
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("There is no NeuralCore here" in t for t in told)
    assert not client.app.state.db.one("SELECT 1 FROM assets WHERE name = 'Lone'")


def test_a_long_run_keeps_pictures_nobody_named_and_the_agent_is_told_to_ask(client, monkeypatch):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    named, unnamed = picture(client, me["id"], "maya", project=project), picture(client, me["id"], "stranger", project=project)
    ready = {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
    monkeypatch.setattr(client.app.state.agent, "preflight", lambda *a, **k: asyncio.sleep(0, ready))
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": "Who is the second picture?", "steps": [],
                                        "question": {"text": "Who is this?", "options": ["A friend", "A stranger"]}})
    plan = client.post("/api/agent/plan", json={"instruction": "@1 @2 /pocket-motion-seedance-v2\nMaya - @1", "selection": [named, unnamed],
                                                "run": "pm-k", "project_id": project}).json()
    entries = {e["name"]: e for e in kit.entries(client.app.state.db, me["id"], project)}
    assert entries["Maya"]["named"] == 1 and entries["stranger"]["named"] == 0
    assert any(e["text"] == "Kept 1 picture without a name in the NeuralCore" for e in plan["activity"])
    told = seen[0][1]["content"]
    assert '"unnamed": true' in told and "ask the" in seen[0][0]["content"]
    # named later, it is an entry like any other
    kit.update(client.app.state.db, me["id"], entries["stranger"]["id"], {"name": "Hazel", "type": "character"})
    assert {e["name"]: e["named"] for e in kit.entries(client.app.state.db, me["id"], project)}["Hazel"] == 1


def test_assets_of_no_project_are_not_used_anywhere(client):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    for origin in ("saved", "kit", "upload"):   # what was kept before every NeuralCore belonged to a project
        client.app.state.db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin) "
                                "VALUES (?, 'Meera', 'character', 'image', 'meera.png', 1, 1, ?)", (me["id"], origin))
    listed = client.get("/api/kit?project=%d" % project).json()
    assert listed["entries"] == [] and "earlier" not in listed
    assert client.get("/api/kit").json() == {"entries": [], "project": False, "types": listed["types"]}
    assert memory.book(client.app.state.db, me["id"], project) == [] and memory.book(client.app.state.db, me["id"], 0) == []
    assert client.post("/api/kit/import", json={"project_id": project, "ids": [1]}).status_code in (404, 405)
    # and they are deleted, files too, while a project's entry with the same file keeps it
    folder = client.app.state.assets_dir / str(me["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meera.png").write_bytes(PNG)
    (folder / "lone.png").write_bytes(PNG)
    db = client.app.state.db
    db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin) VALUES (?, 'Lone', 'other', 'image', 'lone.png', 1, 1, 'saved')", (me["id"],))
    db.run("INSERT INTO assets (user_id, name, tag, kind, filename, size, created, origin, project_id) "
           "VALUES (?, 'Meera', 'character', 'image', 'meera.png', 1, 1, 'kit', ?)", (me["id"], project))
    assert kit.remove_global(db, client.app.state.assets_dir) == 4
    assert not db.one("SELECT 1 FROM assets WHERE project_id IS NULL") and kit.remove_global(db, client.app.state.assets_dir) == 0
    assert not (folder / "lone.png").exists() and (folder / "meera.png").exists()


def test_at_names_in_a_prompt_go_into_the_slots_that_fit_them(client, monkeypatch):
    me = register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    violet = add(client, picture(client, me["id"], "v", project=project, about="A woman with wavy purple hair."), "Violet", "character", False, project)
    clearing = add(client, picture(client, me["id"], "c", project=project), "Bonfire Clearing", "location", False, project)
    schema = schema_of(client, "video/h3_master")
    on = kit.entries(client.app.state.db, me["id"], project)
    said, placed = kit.mentions(schema, "@Violet walks into @bonfire clearing at night. @Violet smiles. @Nobody waves.", on)
    assert said == "the main character walks into the background at night. the main character smiles. @Nobody waves."
    assert placed == {"201:image": violet["id"], "205:image": clearing["id"]}
    # a slot the user filled already is left alone: the next one that fits is used
    said, placed = kit.mentions(schema, "@Violet", on, taken={"201:image"})
    assert (said, placed) == ("the second person", {"203:image": violet["id"]})   # 202 is the main character's other angle
    # with no slot for her, she is said by what she shows
    plain = dict(schema, refs=[])
    assert kit.mentions(plain, "@Violet dances.", on) == ("A woman with wavy purple hair dances.", {})

    # through the Create page: the job gets her as its reference, and the prompt the words for her slot
    sent = []

    async def upload(name, data, content_type=None):
        sent.append(name)
        return name
    monkeypatch.setattr(client.app.state.comfy, "upload", upload)
    settings = {"workflow": "video/h3_master", "values": {"100:value": "@Violet waves at the camera."}, "options": {"engine": "reference"},
                "project_id": project}
    made = client.post("/api/jobs", data={"settings": json.dumps(settings)})
    assert made.status_code == 200, made.text
    job = client.app.state.db.one("SELECT settings FROM jobs WHERE id = ?", (made.json()["id"],))
    kept = json.loads(job["settings"])
    assert kept["values"]["100:value"] == "the main character waves at the camera." and "201:image" in kept["refs"]


def test_a_model_that_takes_no_pictures_is_told_what_the_always_on_entries_show():
    on = [{"id": 1, "name": "Violet", "tag": "character", "about": "A woman with wavy purple hair, black lace top."},
          {"id": 2, "name": "Violet", "tag": "character", "about": "Violet from the side."},
          {"id": 3, "name": "Alice", "tag": "character", "about": "Curly red hair, pink satin dress."},
          {"id": 4, "name": "Hazel", "tag": "character", "about": "Blonde, maroon jumpsuit."},
          {"id": 5, "name": "Clearing", "tag": "background", "about": "A forest clearing at night with bonfires."},
          {"id": 6, "name": "Song", "tag": "voice", "about": "A sung line."}]
    words = kit.in_words(on)
    assert words == ("The main character: A woman with wavy purple hair, black lace top. The second person: Curly red hair, pink satin dress. "
                     "The background: A forest clearing at night with bonfires.")
    assert "bonfires" not in kit.in_words(on, left_out={5})


def test_the_agent_reads_a_script_kept_in_the_kit(client, monkeypatch):
    register(client)
    project = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    script = client.post("/api/kit", json={"text": "VIOLET: Do I know you?", "name": "Ep 135", "project_id": project}).json()
    seen = hosted(monkeypatch, client, {"tool": "read_text", "asset": script["id"]}, {"tool": "finish", "reply": "Read it.", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "read the script", "project_id": project})
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("VIOLET: Do I know you?" in t for t in told)
