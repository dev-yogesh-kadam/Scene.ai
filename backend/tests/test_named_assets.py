"""Pictures the user names in a message ("Maya - @3", "location - Clearing - @10") are kept in shared memory under
those names, so a new agent tab, or another project, knows them."""

from scene import memory
from test_agent_conversation import model
from test_api import register

MESSAGE = ("@1 @2 /pocket-motion-seedance-v2\ncharacters-\nVoilet - @3 ,\nAlice Parker - @4 ,\n"
           "Madelyn Hill - @5 , Madelyn's Vlog Camera - @6 ,\nlocation - Bonfire Party Clearing - @7 ,\n\n"
           "i provided characters , props and location let me know if any thing needed")


def attached(*kinds):
    return [{"tag": "@{}".format(n), "id": 100 + n, "kind": kind} for n, kind in enumerate(kinds, start=1)]


def test_the_names_and_types_are_read_from_the_message():
    found = memory.named_in(MESSAGE, attached("audio", "text", "image", "image", "image", "image", "image"))
    assert [(f["item"], f["name"], f["type"], f["said"]) for f in found] == [
        (103, "Voilet", "character", False), (104, "Alice Parker", "character", False), (105, "Madelyn Hill", "character", False),
        (106, "Madelyn's Vlog Camera", "character", False), (107, "Bonfire Party Clearing", "location", True)]
    # a name after the tag, a prop line, and things that are not names
    found = memory.named_in("@1 = Maya\nprop: red umbrella @2\n@3 @4\nmake it rain - @5", attached("image", "image", "image", "image", "audio"))
    assert [(f["name"], f["type"]) for f in found] == [("Maya", "character"), ("red umbrella", "prop")]


def picture(client, user_id, name, about=""):
    folder = client.app.state.outputs.folder(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + ".png")).write_bytes(b"\x89PNG not really " + name.encode())
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created, about) "
        "VALUES (?, 'upload/file', 'image', ?, ?, '{}', '{}', 1, ?)", (user_id, name, name + ".png", about))


def test_named_pictures_are_kept_once_and_an_object_is_a_prop(client):
    me = register(client)
    db = client.app.state.db
    girl, cam, place = (picture(client, me["id"], "v", "A girl with wavy purple hair."), picture(client, me["id"], "c", ""),
                        picture(client, me["id"], "b", "A clearing at night with a bonfire."))
    named = [{"item": girl, "name": "Voilet", "type": "character", "said": False},
             {"item": cam, "name": "Madelyn's Vlog Camera", "type": "character", "said": False},
             {"item": place, "name": "Bonfire Party Clearing", "type": "location", "said": True}]
    folder, outputs = client.app.state.assets_dir / str(me["id"]), client.app.state.outputs.folder(me["id"])
    kept = memory.keep_named(db, folder, outputs, me["id"], named)
    assert [(k["name"], k["type"]) for k in kept] == [("Voilet", "character"), ("Madelyn's Vlog Camera", "prop"), ("Bonfire Party Clearing", "location")]
    assert memory.keep_named(db, folder, outputs, me["id"], named) == []   # named again: kept already
    shown = memory.panel(db, me["id"], None)["assets"]
    assert sorted((a["name"], a["type"]) for a in shown) == [("Bonfire Party Clearing", "location"), ("Madelyn's Vlog Camera", "prop"), ("Voilet", "character")]
    assert next(a for a in shown if a["name"] == "Voilet")["about"] == "A girl with wavy purple hair."
    # the book has each once, by its name, with its library id too
    book = memory.book(db, me["id"], None)
    voilet = [e for e in book if e.get("item") == girl]
    assert len(voilet) == 1 and voilet[0]["name"] == "Voilet" and voilet[0]["type"] == "character" and voilet[0]["asset"]


def test_a_message_that_names_its_pictures_keeps_them_for_every_tab(client, monkeypatch):
    me = register(client)
    maya = picture(client, me["id"], "maya", "A woman in a red coat.")
    model(monkeypatch, client, {"thought": "", "reply": "Got it.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "characters-\nMaya - @1", "selection": [maya]}).json()
    assert any(e["text"] == "Kept in the kit: Maya (character)" for e in plan["activity"])
    # a new tab, with nothing attached, finds her in the book by name
    asked = model(monkeypatch, client, {"thought": "", "reply": "Maya it is.", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "a shot of Maya walking", "run": "tab-2"})
    assert '"name": "Maya"' in asked[-1] and '"type": "character"' in asked[-1]
