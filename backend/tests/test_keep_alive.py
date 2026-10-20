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


def test_a_model_is_not_asked_to_read_more_than_it_was_made_for():
    a = agent.Agent("http://127.0.0.1:9", "small", options={"context": 262144})
    assert a.reads("small") == 262144
    a.longest["small"] = 131072
    assert a.reads("small") == 131072 and a.skill_room("small") == int(131072 * agent.CHARS_PER_TOKEN * agent.SKILL_SHARE)


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
