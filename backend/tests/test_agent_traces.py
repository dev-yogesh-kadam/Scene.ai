"""The admin console's Agent section: every call to the agent's models is written down (traces.py), shown by model, by
purpose and by run, can be read again and replayed with another model, and the models of its roles can be chosen."""

import json
import time

from test_api import console, register


def fake_ollama(monkeypatch, agent, answer=None, error=None):
    """Ollama, answering every chat with `answer` (or failing with `error`)."""
    async def pick(wanted=None):
        return wanted or "local-a:8b"

    async def abilities(name):
        return set()

    async def post(model, payload):
        if error:
            return {"error": error}
        return {"message": {"content": json.dumps(answer or {"reply": "hi"})}, "prompt_eval_count": 120, "eval_count": 30}
    monkeypatch.setattr(agent, "pick_model", pick)
    monkeypatch.setattr(agent, "abilities", abilities)
    monkeypatch.setattr(agent, "_post_local", post)


def test_calls_are_written_down_shown_and_replayed(client, monkeypatch):
    me = register(client)
    state = client.app.state
    call = state.traces.record("plan", "local-a:8b", None, time.time() - 2,
                               [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "A dog.", "images": ["x", "y"]}],
                               {"type": "object"}, content={"tool": "find_items", "reply": ""}, usage={"prompt": 900, "answer": 60}, tool="find_items")
    desk = console(client)
    fake_ollama(monkeypatch, state.agent, {"reply": "A brown dog runs."})
    replay = desk.post("/api/admin/agent/calls/{}/replay".format(call), json={"model": "local-b:4b"}).json()
    assert replay["model"] == "local-b:4b" and replay["answer"] == {"reply": "A brown dog runs."} and replay["pictures_left_out"] == 2
    assert replay["usage"] == {"prompt": 120, "cached": 0, "answer": 30}

    report = desk.get("/api/admin/agent").json()
    assert {r["model"]: r["calls"] for r in report["by_model"]} == {"local-a:8b": 1, "local-b:4b": 1}
    assert {r["purpose"] for r in report["by_purpose"]} == {"plan", "replay"}
    assert report["totals"]["calls"] == 2 and report["totals"]["answer_tokens"] == 90 and report["totals"]["tokens_per_second"]
    first = next(r for r in report["runs"] if "replay" in r["purposes"])
    assert first["models"] == ["local-b:4b"] and first["calls"] == 1 and first["run"]   # a request is a run of its own
    calls = desk.get("/api/admin/agent/runs/" + first["run"]).json()["calls"]
    assert [c["purpose"] for c in calls] == ["replay"] and calls[0]["prompt_tokens"] == 120
    kept = desk.get("/api/admin/agent/calls/{}".format(call)).json()
    assert kept["tool"] == "find_items" and kept["exchange"]["messages"][1] == {"role": "user", "content": "A dog.", "images": 2}
    assert kept["user_id"] is None    # written down outside a request: no one asked
    assert desk.get("/api/admin/agent/runs/nothing").status_code == 404

    fake_ollama(monkeypatch, state.agent, error="model ran out of memory")
    assert desk.post("/api/admin/agent/calls/{}/replay".format(call), json={}).status_code == 400
    failed = state.db.one("SELECT * FROM agent_calls ORDER BY id DESC LIMIT 1")
    assert failed["purpose"] == "replay" and "out of memory" in failed["error"]
    assert desk.get("/api/admin/agent").json()["totals"]["errors"] == 1


def test_the_models_of_the_agents_roles_can_be_chosen(client):
    register(client)
    agent = client.app.state.agent
    desk = console(client)
    before = agent.model
    found = desk.put("/api/admin/agent/roles", json={"main": "qwen3.6:35b", "fast": "qwen3.5:4b", "vision": ""}).json()
    assert found["roles"] == {"main": "qwen3.6:35b", "fast": "qwen3.5:4b", "vision": ""}
    assert (agent.model, agent.fast, agent.vision) == ("qwen3.6:35b", "qwen3.5:4b", found["configured"]["vision"])
    assert desk.get("/api/admin/agent").json()["roles"]["main"] == "qwen3.6:35b"
    desk.put("/api/admin/agent/roles", json={})                          # empty: back to config.json
    assert agent.model == before
    assert "Changed the agent's models" in [a["action"] for a in desk.get("/api/admin/audit").json()["entries"]]


def test_old_calls_are_forgotten(client, tmp_path):
    register(client)
    traces = client.app.state.traces
    old = traces.record("caption", "m", None, time.time() - 40 * 86400, [{"role": "user", "content": "x"}], "json", content={})
    new = traces.record("caption", "m", None, time.time(), [{"role": "user", "content": "x"}], "json", content={})
    traces.prune()
    assert [r["id"] for r in client.app.state.db.all("SELECT id FROM agent_calls")] == [new]
    assert traces.exchange(new) is not None and old != new
