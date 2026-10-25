"""The console's Servers & APIs: servers and APIs are added, changed and removed while the app runs; a waiting render
goes to a ComfyUI server that is free; a call to a local model goes to the least busy Ollama server that has it."""

import asyncio

from test_api import console, register


def test_servers_are_added_changed_and_removed_in_the_console(client):
    register(client)
    desk = console(client)
    listed = desk.get("/api/admin/endpoints").json()["endpoints"]
    assert [(e["kind"], e["url"]) for e in listed] == [("comfy", "http://127.0.0.1:9"), ("ollama", "http://127.0.0.1:9")]   # config.json's
    desk.post("/api/admin/endpoints", json={"kind": "comfy", "name": "", "url": " 127.0.0.8188 "})   # nothing is refused
    loose = client.app.state.db.one("SELECT * FROM endpoints ORDER BY id DESC LIMIT 1")
    assert (loose["name"], loose["url"]) == ("ComfyUI", "http://127.0.0.8188")
    desk.delete("/api/admin/endpoints/%d" % loose["id"])
    desk.post("/api/admin/endpoints", json={"kind": "ollama", "name": "Kaggle", "url": "https://kaggle.example/"})
    desk.post("/api/admin/endpoints", json={"kind": "openai", "name": "Kimi", "url": "https://api.moonshot.ai/v1", "api_key": "sk-1", "models": "kimi-k2.6"})
    agent = client.app.state.agent
    assert agent.servers == ["http://127.0.0.1:9", "https://kaggle.example"] and "kimi" in agent.services
    listed = desk.get("/api/admin/endpoints").json()["endpoints"]
    kimi = next(e for e in listed if e["name"] == "Kimi")
    assert "api_key" not in kimi and kimi["has_key"]   # the key is never sent back
    desk.put("/api/admin/endpoints/%d" % kimi["id"], json={"active": False})
    assert "kimi" not in agent.services
    assert client.app.state.db.one("SELECT api_key FROM endpoints WHERE id = ?", (kimi["id"],))["api_key"] == "sk-1"   # kept
    kaggle = next(e for e in listed if e["name"] == "Kaggle")
    desk.delete("/api/admin/endpoints/%d" % kaggle["id"])
    assert agent.servers == ["http://127.0.0.1:9"]


def test_a_render_goes_to_a_server_that_is_free(client):
    register(client)
    console(client).post("/api/admin/endpoints", json={"kind": "comfy", "name": "Zoro 2", "url": "http://127.0.0.1:8"})
    pool = client.app.state.comfy_pool

    async def answers(url):
        return True
    first, _ = asyncio.run(pool.free(answers))
    assert first["url"] == "http://127.0.0.1:9"   # the main one first
    pool.busy["http://127.0.0.1:9"] = "job1"
    second, _ = asyncio.run(pool.free(answers))
    assert second["name"] == "Zoro 2" and pool.client(second["url"]) is not client.app.state.comfy
    pool.busy["http://127.0.0.1:8"] = "job2"
    assert asyncio.run(pool.free(answers)) == (None, True)   # all busy: it waits for one
    pool.busy.clear()


def test_a_local_model_is_asked_on_the_least_busy_server_that_has_it():
    from scene.agent import Agent
    brain = Agent("http://a")
    brain.set_servers(["http://a", "http://b", "http://c"])
    brain.where = {"qwen3:14b": ["http://b", "http://c"]}
    brain.calls = {"http://b": 2, "http://c": 0}
    assert brain.server_for("qwen3:14b") == "http://c"
    brain.calls["http://c"] = 3
    assert brain.server_for("qwen3:14b") == "http://b"
    assert brain.server_for("other") == "http://a"
