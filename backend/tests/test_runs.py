"""The state of a long run (runs.py): a tree of paths per user and conversation, its API, and the agent's tools for it,
including the film tool and question cards."""

import asyncio

import pytest

from scene import agent, media, runs
from test_agent_conversation import STEP
from test_agent_shots import hosted
from test_api import register


def db_of(client):
    return client.app.state.db


def test_leaves_folders_pages_and_coverage(client):
    me = register(client)
    db = db_of(client)
    runs.write(db, me["id"], "pm-1", "/motion/chunks/c1", {"units": "u001–u004"})
    runs.write(db, me["id"], "pm-1", "/motion/chunks/c2", {"units": "u005–u009"})
    runs.write(db, me["id"], "pm-1", "/motion/chunks/c10", {"units": "u010"})
    runs.write(db, me["id"], "pm-1", "/motion/clips/c1", {"clip": 5})
    assert runs.read(db, me["id"], "pm-1", "/motion/chunks/c2")["value"] == {"units": "u005–u009"}
    folder = runs.read(db, me["id"], "pm-1", "/motion/chunks", limit=2)
    assert folder["folder"] and folder["total"] == 3 and len(folder["leaves"]) == 2
    assert runs.children(db, me["id"], "pm-1", "/motion/chunks") == ["c1", "c2", "c10"]   # c2 before c10
    assert runs.coverage(db, me["id"], "pm-1", "/motion/clips", "/motion/chunks") == {"ok": False, "missing": ["c2", "c10"], "extra": [], "count": 3}
    assert runs.read(db, me["id"], "pm-1", "/motion/nothing") == {"path": "/motion/nothing", "missing": True}
    # a path is a leaf or a folder, never both
    with pytest.raises(runs.RunError):
        runs.write(db, me["id"], "pm-1", "/motion/chunks", 1)
    with pytest.raises(runs.RunError):
        runs.write(db, me["id"], "pm-1", "/motion/chunks/c1/x", 1)
    with pytest.raises(runs.RunError):
        runs.write(db, me["id"], "pm-1", "/Motion/../x", 1)
    with pytest.raises(runs.RunError):
        runs.write(db, me["id"], "pm-1", "/motion/big", "x" * (runs.MAX_VALUE + 1))
    # an underscore in a path is not a wildcard: /motion/a_b does not reach /motion/axb
    runs.write(db, me["id"], "pm-1", "/motion/axb/one", 1)
    assert runs.read(db, me["id"], "pm-1", "/motion/a_b") == {"path": "/motion/a_b", "missing": True}
    runs.append(db, me["id"], "pm-1", "/motion/log", "re-rolled c2: wrong face")
    runs.append(db, me["id"], "pm-1", "/motion/log", "re-rolled c3")
    assert runs.read(db, me["id"], "pm-1", "/motion/log")["value"] == ["re-rolled c2: wrong face", "re-rolled c3"]
    assert runs.delete(db, me["id"], "pm-1", "/motion/chunks") == 3
    runs.write(db, me["id"], "pm-1", "/motion/clips/c9", {"item": 42})
    assert runs.resolve(db, me["id"], "pm-1", "$state:/motion/clips/c9") == 42
    with pytest.raises(runs.RunError, match="state_reference_unresolved"):
        runs.resolve(db, me["id"], "pm-1", "$state:/motion/clips/c99")


def test_the_api_keeps_each_users_runs_to_themselves(client):
    register(client)
    assert client.put("/api/runs/pm-1/state", json={"path": "/motion/status", "value": "step 3, next scene 2"}).status_code == 200
    assert client.put("/api/runs/pm-1/state", json={"path": "/motion/log", "value": "one", "append": True}).status_code == 200
    assert client.get("/api/runs/pm-1/state", params={"path": "/motion/status"}).json()["value"] == "step 3, next scene 2"
    assert client.get("/api/runs").json()["runs"][0]["status"] == "step 3, next scene 2"
    assert client.put("/api/runs/pm-1/state", json={"path": "bad path", "value": 1}).status_code == 400
    assert client.put("/api/runs/Bad!/state", json={"path": "/a", "value": 1}).status_code == 400
    assert client.get("/api/runs/pm-1/coverage", params={"path": "/motion/clips", "against": "/motion/chunks"}).json()["ok"] is False
    register(client, email="other@example.com")   # now signed in as someone else
    assert client.get("/api/runs/pm-1/state", params={"path": "/motion/status"}).json()["missing"] is True
    assert client.get("/api/runs").json()["runs"] == []


def test_the_agent_reads_and_writes_its_run_and_cuts_media(client, monkeypatch):
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", folder / "master.wav"))
    master = db_of(client).run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
                               "VALUES (?, 'upload/file', 'audio', 'Master', 'master.wav', '{}', '{}', 1)", (me["id"],))
    seen = hosted(monkeypatch, client,
                  {"tool": "state_write", "path": "/motion/inputs/audio", "value": '{"item": %d, "frames": 72}' % master},
                  {"tool": "state_read", "path": "/motion/inputs"},
                  {"tool": "film", "op": "slice", "settings": '{"audio": "$state:/motion/inputs/audio", "f_in": 0, "f_out": 48}'},
                  {"tool": "film", "op": "slice", "settings": '{"audio": "$state:/motion/inputs/nothing", "f_in": 0, "f_out": 48}'},
                  {"tool": "state_check", "path": "/motion/clips", "against": "/motion/inputs"},
                  {"tool": "finish", "reply": "Here are the assets.", "steps": [],
                   "question": {"text": "Review the anchors — any corrections?", "options": ["I have corrections in the anchors", "Looks good, next step"]}})
    plan = client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-1"}).json()
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("Written: /motion/inputs/audio" in t for t in told)
    assert any('"frames": 72' in t for t in told)
    sliced = next(t for t in told if t.startswith("Result of film") and '"kind": "audio"' in t)
    assert '"duration": 2.0' in sliced
    assert any("state_reference_unresolved" in t for t in told)        # a path not written yet is refused, not guessed
    assert any('"missing": ["audio"]' in t for t in told)
    assert plan["question"] == {"text": "Review the anchors — any corrections?", "options": ["I have corrections in the anchors", "Looks good, next step"]}
    assert plan["run"] == "pm-1"
    # the slice is the run's working file: kept to the run, not in the library
    assert [i["name"] for i in client.get("/api/library", params={"run": "pm-1"}).json()["items"]] == ["Audio slice"]
    assert [i["id"] for i in client.get("/api/library").json()["items"]] == [master]


def test_without_a_run_the_state_tools_say_so(client, monkeypatch):
    register(client)
    seen = hosted(monkeypatch, client, {"tool": "state_read", "path": "/motion/status"}, {"tool": "finish", "reply": "ok", "steps": [STEP]})
    client.post("/api/agent/plan", json={"instruction": "a dog film"})
    assert any("keeps no run state" in m["content"] for m in seen[-1] if m["role"] == "user")


def test_a_question_needs_two_options():
    assert agent.clean_question({"text": "Go on?", "options": ["Yes"]}) is None
    assert agent.clean_question({"text": "", "options": ["Yes", "No"]}) is None
    assert agent.clean_question({"text": "Go on?", "options": ["Yes", "yes", "No", "Later", "Never", "Maybe"]}) == \
        {"text": "Go on?", "options": ["Yes", "No", "Later", "Never"]}


def test_a_model_named_earlier_in_the_conversation_stays_offered(client, monkeypatch):
    register(client)
    monkeypatch.setattr(client.app.state.settings, "default_workflow", "video/h3_master")   # as on the studio PC
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": "ok", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "looks good, next step", "direction": "Models: video H3 Director, image Z-Image Turbo."})
    offered = seen[-1][1]["content"]
    assert '"video/h3_director"' in offered            # named in the notes, so still offered
    assert '"video/video_minimax_h3_i2v"' not in offered  # never named: left for the Create page


def test_the_tools_work_is_streamed_while_the_model_thinks(client, monkeypatch):
    import json as js
    register(client)
    agent_ = client.app.state.agent
    calls = [{"tool": "state_write", "path": "/motion/status", "value": '"step 1"'}, {"tool": "finish", "reply": "ok", "steps": []}]
    asked = []

    async def slow_chat(messages, answer_format, **kwargs):
        asked.append(1)
        if len(asked) == 2:
            await asyncio.sleep(2.2)   # the model takes its time over the second answer
        return dict({"tool": "finish", "thought": "", "reply": "", "steps": [], "direction": ""}, **calls[len(asked) - 1])
    monkeypatch.setattr(agent_, "chat", slow_chat)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    lines = client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-1"}, headers={"Accept": "application/x-ndjson"}).text.splitlines()
    events = [js.loads(line) for line in lines]
    kinds = [(e["type"], e.get("text", "")) for e in events]
    wrote = kinds.index(("activity", "Wrote /motion/status of the run"))
    waiting = [i for i, k in enumerate(kinds) if k == ("status", "Working…")]
    # what the tool did is said while the model is still on its next answer, and the plan comes last
    assert waiting and wrote < waiting[-1] and events[-1]["type"] == "plan"


def test_a_runs_step_may_use_its_own_working_files(client, monkeypatch):
    me = register(client)
    db = db_of(client)
    ref = db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, run, created) "
                 "VALUES (?, 'edit/reference', 'image', 'Maya at 1500', 'maya.png', '{}', '{}', 'pm-1', 1)", (me["id"],))
    use = dict(STEP, uses=[{"item": ref, "asset": 0, "slot": "201:image"}])
    hosted(monkeypatch, client, {"tool": "finish", "reply": "One shot.", "steps": [use]})
    in_run = client.post("/api/agent/plan", json={"instruction": "the anchor", "run": "pm-1"}).json()
    assert [u["name"] for u in in_run["steps"][0]["uses"]] == ["Maya at 1500"]
    # without the run the working file is no one's reference, and it is not in the asset book either
    outside = client.post("/api/agent/plan", json={"instruction": "the anchor"}).json()
    assert outside["steps"][0]["uses"] == []
    from scene import memory
    assert all(e.get("item") != ref for e in memory.book(db, me["id"], 0))


def test_a_runs_budget_is_the_users_and_stops_its_jobs(client, monkeypatch):
    import json as js
    from test_api import JOB
    me = register(client)
    # the agent cannot set or lift it
    seen = hosted(monkeypatch, client, {"tool": "state_write", "path": "/budget", "value": "999999"}, {"tool": "finish", "reply": "ok", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-1"})
    assert any("only the user sets it" in m["content"] for m in seen[-1] if m["role"] == "user")
    assert client.put("/api/runs/pm-1/state", json={"path": "/budget", "value": 5}).status_code == 400
    assert client.put("/api/runs/pm-1/budget", json={"credits": -1}).status_code == 400
    assert client.put("/api/runs/pm-1/budget", json={"credits": 150}).json() == {"credits": 150, "spent": 0}
    post = lambda run: client.post("/api/jobs", data={"settings": js.dumps({**JOB, "run_of": run})})
    first = post("pm-1")
    assert first.status_code == 200 and first.json()["credits"] == 100            # 100 of 150
    second = post("pm-1")
    assert second.status_code == 402 and "budget is 150 credits" in second.json()["detail"]
    assert post("other-run").status_code == 200                                    # another run has no budget
    assert client.put("/api/runs/pm-1/budget", json={"credits": None}).json()["credits"] is None
    assert post("pm-1").status_code == 200                                         # no budget, no limit
    db = db_of(client)
    assert db.one("SELECT run FROM jobs WHERE id = ?", (first.json()["id"],))["run"] == "pm-1"


def test_a_long_skill_goes_first_and_the_tokens_are_counted(client, monkeypatch, tmp_path):
    from scene import skills
    register(client)
    (tmp_path / "pm.md").write_text("---\nname: pm\ndescription: 'Use when the user says \"pocket motion\".'\n---\n\n# Pocket\n\n"
                                    + "A rule of the run. " * 400, encoding="utf-8")
    shipped = skills.load
    monkeypatch.setattr(skills, "load", lambda folder=None: shipped(tmp_path))
    agent_ = client.app.state.agent
    seen = []

    async def counted_chat(messages, answer_format, **kwargs):
        seen.append(messages)
        call = {"tool": "state_read", "path": "/motion/status"} if len(seen) == 1 else {"tool": "finish", "reply": "ok", "steps": []}
        return dict({"tool": "finish", "thought": "", "reply": "", "steps": [], "direction": "",
                     "_usage": {"prompt": 9000, "cached": 8000 if len(seen) > 1 else 0, "answer": 50}}, **call)
    monkeypatch.setattr(agent_, "chat", counted_chat)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    monkeypatch.setattr(agent, "PREFLIGHT_CHARS", 0)
    monkeypatch.setattr(agent_, "preflight", lambda *a, **k: asyncio.sleep(0, {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}))
    plan = client.post("/api/agent/plan", json={"instruction": "run pocket motion", "run": "pm-1"}).json()
    system, message = seen[0][0]["content"], seen[0][1]["content"]
    assert "A rule of the run." in system and "A rule of the run." not in message
    assert plan["tokens"] == {"prompt": 18000, "cached": 8000, "answer": 100}
    assert any(e.get("text") == "Read 18,000 tokens (8,000 from the cache) and wrote 100" for e in plan["activity"])
