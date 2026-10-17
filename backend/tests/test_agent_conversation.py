"""The agent's conversation: what it did and thought for a plan (also as a live stream), the pictures its replies name,
the frames shown under a result and the thumbs on a result."""

import asyncio
import json

from scene import agent, media, memory
from scene.api import workspace
from test_api import register

STEP = {"tool": "generate", "workflow": "video/h3_master", "name": "Dog in the park", "prompt": "A dog runs across a park.",
        "duration": 6, "resolution": 480, "orientation": "portrait"}


def item(client, user_id, name, kind="image", filename="missing", rating=0):
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, created, about, rating) "
        "VALUES (?, 'x/y', ?, ?, ?, '', '{}', '{}', 1, 'A brown dog on grass.', ?)", (user_id, kind, name, filename, rating))


def model(monkeypatch, client, *answers, looked=0):
    """The agent's model answers these, in turn; describing pictures is said to have looked at `looked` of them."""
    asked = []

    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        asked.append(message)
        answer = answers[min(len(asked), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def fake_describe(state, user_id, entries, **kwargs):
        return looked
    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    monkeypatch.setattr(workspace.memory, "describe_missing", fake_describe)
    return asked


def test_a_plan_comes_with_what_the_agent_did_and_thought(client, monkeypatch):
    me = register(client)
    dog = item(client, me["id"], "Brown dog")
    model(monkeypatch, client, {"thought": "A pet shop ad: one 6 s portrait shot of a dog.",
                                "reply": "One shot of **the dog** [[item:%d]] and [[item:99999]] [[asset:77]]." % dog,
                                "steps": [STEP, dict(STEP, name="Bad", workflow="video/nope")]}, looked=2)
    plan = client.post("/api/agent/plan", json={"instruction": "a short ad for a pet shop"}).json()
    assert plan["thought"] == "A pet shop ad: one 6 s portrait shot of a dog." and plan["seconds"] >= 0
    said = [(e["type"], e.get("icon"), e.get("text")) for e in plan["activity"]]
    assert ("activity", "book", "Opened the asset book: 1 entry") in said
    assert ("activity", "look", "Looked at 2 new pictures") in said
    assert ("activity", "skill", "Read the skill “An ad, a promo or a product video”") in said
    assert ("activity", "skip", "Left out “Bad”: there is no workflow “video/nope” it can use") in said
    assert said[-1] == ("activity", "plan", "Checked and priced 1 step")
    thought = next(e for e in plan["activity"] if e["type"] == "thought")
    assert thought["text"].startswith("A pet shop ad") and thought["seconds"] >= 0
    # an item the model was given becomes a small picture; ids it made up are taken out
    assert plan["chips"] == {"item:%d" % dog: {"name": "Brown dog", "kind": "image"}}
    assert "[[item:%d]]" % dog in plan["reply"] and "99999" not in plan["reply"] and "asset:77" not in plan["reply"]
    assert [s["name"] for s in plan["steps"]] == ["Dog in the park"]


def test_a_second_try_is_in_the_log(client, monkeypatch):
    register(client)
    model(monkeypatch, client, {"thought": "First go.", "reply": "Generating the clip now.", "steps": []},
          {"thought": "Planned it this time.", "reply": "Here is the shot.", "steps": [STEP]})
    plan = client.post("/api/agent/plan", json={"instruction": "generate a dog clip"}).json()
    kinds = [(e["type"], e.get("icon")) for e in plan["activity"]]
    assert kinds.count(("thought", None)) == 2 and ("activity", "retry") in kinds
    assert plan["thought"] == "Planned it this time." and len(plan["steps"]) == 1


def stream(client, body):
    response = client.post("/api/agent/plan", json=body, headers={"Accept": "application/x-ndjson"})
    return response, [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_the_plan_streams_as_the_agent_works(client, monkeypatch):
    register(client)
    model(monkeypatch, client, {"thought": "A dog shot.", "reply": "Here it is.", "steps": [STEP]})
    response, events = stream(client, {"instruction": "a dog in a park"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/x-ndjson")
    types = [e["type"] for e in events]
    assert types[-1] == "plan" and "status" in types and types.index("status") < types.index("thought")
    plan = events[-1]
    assert plan["steps"][0]["name"] == "Dog in the park" and [e["type"] for e in plan["activity"]][-1] == "activity"
    # what goes wrong once the stream has started arrives as its last line
    model(monkeypatch, client, agent.AgentError("The agent's model server (Ollama) can't be reached."))
    response, events = stream(client, {"instruction": "a dog in a park"})
    assert response.status_code == 200 and events[-1] == {"type": "error", "message": "The agent's model server (Ollama) can't be reached."}
    # and a message that can't be planned at all is refused before the stream starts
    assert client.post("/api/agent/plan", json={"instruction": " "}, headers={"Accept": "application/x-ndjson"}).status_code == 400


def test_a_video_shows_its_frames_and_a_result_can_be_rated(client):
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=2:r=24", "-pix_fmt", "yuv420p", folder / "clip.mp4"))
    clip = item(client, me["id"], "Clip", kind="video", filename="clip.mp4")
    still = item(client, me["id"], "Still")
    frame = client.get("/api/library/%d/frame?at=1" % clip)
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg" and frame.content[:2] == b"\xff\xd8"
    assert (folder / ".posters" / "clip.mp4.10.jpg").is_file()   # kept for the next time
    assert client.get("/api/library/%d/frame?at=0" % clip).status_code == 200
    assert client.get("/api/library/%d/frame" % still).status_code == 400
    assert client.get("/api/library/%d/frame" % (clip + 999)).status_code == 404

    assert client.put("/api/library/%d" % clip, json={"rating": 1}).status_code == 200
    assert client.put("/api/library/%d" % still, json={"rating": -1}).status_code == 200
    rated = {i["name"]: i["rating"] for i in client.get("/api/library").json()["items"]}
    assert rated == {"Clip": 1, "Still": -1}
    for wrong in (5, True, "1"):
        assert client.put("/api/library/%d" % clip, json={"rating": wrong}).status_code == 400
    # the agent's book says which were liked: it reuses those and never the ones turned down
    book = {e["name"]: e for e in memory.book_for_model(memory.book(client.app.state.db, me["id"], 0))}
    assert book["Clip"].get("liked") is True and book["Still"].get("disliked") is True and "liked" not in book["Still"]


def test_a_message_costs_what_its_model_costs(client, monkeypatch):
    me = register(client)
    prices = client.put("/api/admin/pricing/llm", json={"model": "gemini/flash", "credits": 3}).json()
    assert {"model": "gemini/flash", "credits": 3, "available": False} in prices["models"]
    assert client.put("/api/admin/pricing/llm", json={"model": "local:9b", "credits": 1}).status_code == 200
    assert client.put("/api/admin/pricing/llm", json={"model": "x", "credits": 1.5}).status_code == 400   # whole credits only
    assert client.put("/api/admin/pricing/llm", json={"model": "", "credits": 1}).status_code == 400

    async def pick(wanted=None):
        return wanted or "gemini/flash"
    monkeypatch.setattr(client.app.state.agent, "pick_model", pick)
    model(monkeypatch, client, {"thought": "", "reply": "Hello.", "steps": [], "model": "gemini/flash"},
          {"thought": "", "reply": "Hello again.", "steps": [], "model": "local:9b"})
    plan = client.post("/api/agent/plan", json={"instruction": "hi"}).json()
    assert plan["llm"] == {"credits": 3, "model": "gemini/flash"} and plan["balance"] == 497
    # a busy model stood in for: the message costs what the model that answered costs
    plan = client.post("/api/agent/plan", json={"instruction": "hi"}).json()
    assert plan["llm"] == {"credits": 1, "model": "local:9b"} and plan["balance"] == 496
    # without enough credits for the chosen model, the model is not asked
    client.app.state.db.run("UPDATE users SET credits = 2 WHERE id = ?", (me["id"],))
    refused = client.post("/api/agent/plan", json={"instruction": "hi"})
    assert refused.status_code == 400 and "costs 3 cr" in refused.json()["detail"]
    # a free model costs nothing
    assert client.put("/api/admin/pricing/llm", json={"model": "gemini/flash", "credits": 0}).status_code == 200
    model(monkeypatch, client, {"thought": "", "reply": "Hello.", "steps": [], "model": "gemini/flash"})
    assert client.post("/api/agent/plan", json={"instruction": "hi"}).json()["llm"]["credits"] == 0
