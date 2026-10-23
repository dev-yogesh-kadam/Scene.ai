"""A slow answer through a proxy that closes quiet requests (the Cloudflare tunnel): signs of life, then the answer."""

import asyncio
import json

from scene import agent
from scene.api import workspace
from test_agent_conversation import model
from test_api import register


def test_a_slow_single_answer_sends_spaces_then_its_answer(monkeypatch):
    monkeypatch.setattr(workspace, "PATIENT", 0.05)
    monkeypatch.setattr(workspace, "KEEP_ALIVE", 0.05)

    async def slow(answer=None, error=None):
        await asyncio.sleep(0.3)
        if error:
            raise error
        return answer

    async def read(response):
        return b"".join([chunk async for chunk in response.body_iterator]).decode()

    async def go():
        quick = await workspace._patient(asyncio.sleep(0, {"ok": 1}))
        late = await read(await workspace._patient(slow({"ok": 2})))
        failed = await read(await workspace._patient(slow(error=workspace.HTTPException(404, "Not there."))))
        return quick, late, failed
    quick, late, failed = asyncio.run(go())
    assert quick == {"ok": 1}
    assert late.startswith(" ") and json.loads(late) == {"ok": 2}
    assert json.loads(failed) == {"detail": "Not there.", "failed": 404}


def test_a_quiet_plan_pings_and_still_answers(client, monkeypatch):
    register(client)
    monkeypatch.setattr(workspace, "KEEP_ALIVE", 0.05)
    asked = model(monkeypatch, client, {"thought": "", "reply": "Here.", "steps": []})
    fast = client.app.state.agent.ask

    async def slow_ask(*args, **kwargs):
        await asyncio.sleep(0.4)
        return await fast(*args, **kwargs)
    monkeypatch.setattr(client.app.state.agent, "ask", slow_ask)
    response = client.post("/api/agent/plan", json={"instruction": "hello"}, headers={"Accept": "application/x-ndjson"})
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert any(e["type"] == "ping" for e in events) and events[-1]["type"] == "plan" and events[-1]["reply"] == "Here."
    assert len(asked) == 1


def test_every_model_reads_the_same_context():
    a = agent.Agent("http://127.0.0.1:9", "small", options={"context": 262144})
    assert a.reads("small") == a.reads("big") == 262144
    assert a.skill_room("small") == int(262144 * agent.CHARS_PER_TOKEN * agent.SKILL_SHARE)


def test_a_model_that_stops_with_nothing_is_asked_to_carry_on(client, monkeypatch):
    from test_agent_shots import hosted
    register(client)
    seen = hosted(monkeypatch, client, {"tool": "finish", "thought": "I will read the transcript, then name the speakers."},
                  {"tool": "finish", "reply": "Named them.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "go"}).json()
    assert plan["reply"] == "Named them." and len(seen) == 2
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("You were thinking" in t and "name the speakers" in t for t in told)
    assert any(e["text"].startswith("The model stopped with nothing to show") for e in plan["activity"])


def test_a_long_run_that_only_says_what_it_will_do_is_asked_to_do_it(client, monkeypatch):
    from scene import runs
    from test_agent_shots import hosted
    me = register(client)
    db = client.app.state.db
    runs.keep_skill(db, me["id"], "pm-3", "pocket-motion-seedance-v2")
    runs.write(db, me["id"], "pm-3", "/motion/status", "name the speakers", "agent")   # saved before this message
    ready = {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
    monkeypatch.setattr(client.app.state.agent, "preflight", lambda *a, **k: asyncio.sleep(0, ready))
    said = "Picking up where we left off. Let me check the speech spans output first."
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": said, "steps": []},
                  {"tool": "state_write", "path": "/motion/transcript/speakers", "value": '{"16": "Madelyn"}'},
                  {"tool": "finish", "reply": "Named the speakers.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-3"}).json()
    assert plan["reply"] == "Named the speakers." and len(seen) == 3
    assert any("you finished without doing it" in m["content"] for m in seen[1] if m["role"] == "user")
    assert any(e["text"].startswith("The model said what it would do but did not do it") for e in plan["activity"])
    # once it has done something, a reply about what comes next is a reply
    seen = hosted(monkeypatch, client, {"tool": "state_write", "path": "/motion/status", "value": '"anchor next"'},
                  {"tool": "finish", "reply": "Saved. Next I will plan the anchor.", "steps": []})
    plan = client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-3"}).json()
    assert plan["reply"] == "Saved. Next I will plan the anchor." and len(seen) == 2


NO_QUESTION = {"text": "", "options": []}   # what a local model sends when it has nothing to ask


def test_an_empty_question_is_no_question(client, monkeypatch):
    from scene import runs
    from test_agent_shots import hosted
    me = register(client)
    db = client.app.state.db
    runs.keep_skill(db, me["id"], "pm-4", "pocket-motion-seedance-v2")
    runs.write(db, me["id"], "pm-4", "/motion/status", "plan the units", "agent")
    ready = {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
    monkeypatch.setattr(client.app.state.agent, "preflight", lambda *a, **k: asyncio.sleep(0, ready))
    said = "Anchor approved. Now I'll plan the shots. This is a planning step; no generation yet."
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": said, "steps": [], "question": NO_QUESTION},
                  {"tool": "state_write", "path": "/motion/units/1", "value": '{"text": "Violet arrives"}', "question": NO_QUESTION},
                  {"tool": "finish", "reply": "Planned the units.", "steps": [], "question": NO_QUESTION})
    plan = client.post("/api/agent/plan", json={"instruction": "Looks good, next step", "run": "pm-4"}).json()
    assert plan["reply"] == "Planned the units." and len(seen) == 3
    # it saved its work and made nothing: the run goes on by itself
    assert plan["continues"] is True and plan["question"] is None
    # an empty answer with an empty question is sent back too
    seen = hosted(monkeypatch, client, {"tool": "finish", "thought": "I will plan chunk 1.", "question": NO_QUESTION},
                  {"tool": "finish", "reply": "Asked.", "steps": [], "question": {"text": "Which take?", "options": ["A", "B"]}})
    plan = client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-4"}).json()
    assert len(seen) == 2 and plan["question"]["text"] == "Which take?" and plan["continues"] is False
