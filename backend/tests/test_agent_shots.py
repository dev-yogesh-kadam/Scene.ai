"""The shot board: camera fields said in the prompt, a shot id on every generation, takes of a shot."""

from scene import camera, memory
from scene.api import workspace
from test_agent_conversation import STEP, model
from test_api import register


def test_camera_fields_become_prompt_words_once():
    cam = camera.clean({"shot_size": "CU", "angle": "low", "move": "push in", "end_state": "she ends kneeling", "x": 1})
    assert cam == {"shot_size": "CU", "angle": "low", "move": "push in", "end_state": "she ends kneeling"}
    said = camera.apply("A girl opens a door.", cam)
    assert "close-up shot" in said and "low angle looking up" in said and "slow push in" in said
    assert said.endswith("It ends with she ends kneeling.")
    # words the prompt already has are not added again
    again = camera.apply("A close-up of a girl, slow push in on her face.", dict(cam, end_state=""))
    assert again.count("close-up") == 1 and "push in" in again and "slow push in on" in again and "Camera: low angle" in again
    assert camera.clean({"shot_size": "nonsense"})["shot_size"] == ""
    assert camera.apply("A still.", {"shot_size": "WS", "move": "pan"}, "image") == "A still. Camera: wide shot."
    assert camera.apply("", cam) == ""


def test_a_planned_shot_has_an_id_and_the_camera_in_its_prompt(client, monkeypatch):
    register(client)
    model(monkeypatch, client, {"thought": "", "reply": "One shot.", "steps": [dict(STEP, shot_size="WS", angle="high", move="crane", end_state="the camera above the roofs")]})
    plan = client.post("/api/agent/plan", json={"instruction": "a wide shot of a town"}).json()
    step = plan["steps"][0]
    assert step["camera"]["shot_size"] == "WS" and step["camera"]["move"] == "crane"
    assert "wide shot" in step["prompt"] and "crane move" in step["prompt"] and "the camera above the roofs" in step["prompt"]
    assert step["shot_id"] and step["settings"]["shot"] == {"id": step["shot_id"], "take": 1}


def test_shot_clean_keeps_only_an_id_and_a_take():
    assert memory.clean_shot({"id": "AB12-cd!", "take": 2, "x": 1}) == {"id": "ab12-cd", "take": 2}
    assert memory.clean_shot({"id": "a", "take": 99}) == {"id": "a", "take": 1}
    assert memory.clean_shot({"id": ""}) is None and memory.clean_shot("x") is None


def test_storyboard_then_animate_then_reroll(client, monkeypatch):
    me = register(client)
    shots = [dict(STEP, name="Shot %d" % n, shot_size="WS") for n in (1, 2)]
    model(monkeypatch, client, {"thought": "", "reply": "Two shots.", "steps": shots})
    plan = client.post("/api/agent/plan", json={"instruction": "a film"}).json()
    assert all(s["proposal"]["workflow"] == "video/h3_master" for s in plan["steps"])
    sent = [{"shot_id": s["shot_id"], "proposal": s["proposal"]} for s in plan["steps"]]
    # the picture workflows need node definitions the test fixture lacks: a video workflow stands in for the still's
    async def stand_in(state):
        return "video/h3_master"
    monkeypatch.setattr(workspace, "_still_workflow", stand_in)
    board = client.post("/api/agent/storyboard", json={"shots": sent})
    assert board.status_code == 200, board.text
    stills = board.json()["steps"]
    assert len(stills) == 2 and all(s["stage"] == "still" and s["proposal"] for s in stills)
    assert [s["shot_id"] for s in stills] == [s["shot_id"] for s in plan["steps"]]
    assert stills[0]["name"].startswith("Still · Shot 1") and "wide shot" in stills[0]["prompt"]
    assert board.json()["total"] == sum(s["credits"] for s in stills)
    assert client.post("/api/agent/storyboard", json={"shots": []}).status_code == 400
    # animate: a still that is not the user's is left out, a real one starts its clip
    still = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, created) "
        "VALUES (?, 'image/z_image_turbo', 'image', 'Still · Shot 1', 'x.png', '', '{}', '{\"width\": 720, \"height\": 1280}', 1)", (me["id"],))
    animated = client.post("/api/agent/animate", json={"shots": [
        {"shot_id": sent[0]["shot_id"], "item": still, "proposal": sent[0]["proposal"]},
        {"shot_id": sent[1]["shot_id"], "item": 99999, "proposal": sent[1]["proposal"]}]}).json()
    assert len(animated["steps"]) == 1 and animated["steps"][0]["start"]["id"] == still
    assert animated["steps"][0]["shot_id"] == sent[0]["shot_id"] and animated["dropped"][0][1] == "its still is not there"


def test_reroll_makes_take_two_of_the_same_shot(client, monkeypatch):
    import json
    me = register(client)
    model(monkeypatch, client, {"thought": "", "reply": "One.", "steps": [STEP]})
    step = client.post("/api/agent/plan", json={"instruction": "a dog"}).json()["steps"][0]
    made = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, created) "
        "VALUES (?, 'video/h3_master', 'video', 'Dog', 'x.mp4', '', ?, '{}', 1)", (me["id"], json.dumps(step["settings"])))
    again = client.post("/api/agent/reroll", json={"item": made}).json()["retake"]
    assert again["settings"]["shot"] == {"id": step["shot_id"], "take": 2} and again["settings"]["seed_mode"] == "random"
    assert again["credits"] == step["credits"] and "dog" in again["prompt"].lower()
    assert client.post("/api/agent/reroll", json={"item": 99999}).status_code == 404


# ---------------------------------------------------------------- tool calling (hosted models)

def hosted(monkeypatch, client, *calls):
    """The agent's model is a hosted one that answers with these calls, in turn."""
    seen = []

    async def fake_chat(messages, answer_format, **kwargs):
        seen.append(messages)
        call = calls[min(len(seen), len(calls)) - 1]
        return dict({"tool": "finish", "query": "", "item": 0, "asset": 0, "text": "", "thought": "", "reply": "", "steps": [], "direction": ""}, **call)
    agent = client.app.state.agent
    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setattr(agent, "_service_of", lambda name: ({"name": "Test"}, name))
    return seen


def test_a_hosted_model_looks_checks_and_then_finishes(client, monkeypatch):
    me = register(client)
    client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, created, about) "
        "VALUES (?, 'x/y', 'image', 'Meera', 'x.png', '', '{}', '{}', 1, 'A girl with a red scarf.')", (me["id"],))
    seen = hosted(monkeypatch, client,
                  {"tool": "find_assets", "query": "meera"},
                  {"tool": "check_shots", "steps": [STEP, dict(STEP, workflow="video/nope", name="Bad")]},
                  {"tool": "finish", "reply": "One shot.", "steps": [dict(STEP, workflow="video/nope", name="Bad")], "direction": "a"},
                  {"tool": "finish", "reply": "One shot.", "steps": [STEP], "direction": "Film: dog"})
    plan = client.post("/api/agent/plan", json={"instruction": "a dog film"}).json()
    assert [s["name"] for s in plan["steps"]] == ["Dog in the park"] and plan["direction"] == "Film: dog"
    said = [e["text"] for e in plan["activity"] if e["type"] == "activity"]
    assert any(t.startswith("Looked in the asset book for “meera”: 1 found") for t in said)
    assert any(t.startswith("Checked 1 step, 1 left out") for t in said)
    assert any("A step could not run" in t for t in said)
    # the model was told what each tool found, and the hint when its finishing answer was wrong
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("Meera" in t and "red scarf" in t for t in told)
    assert any("Left out “Bad”" in t for t in told)
    assert any("These steps cannot run" in t for t in told)
    assert len(seen) == 4


def test_a_local_model_still_answers_once(client, monkeypatch):
    register(client)
    asked = model(monkeypatch, client, {"thought": "", "reply": "Hi.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "hello"}).json()
    assert plan["reply"] == "Hi." and len(asked) == 1
