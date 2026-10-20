"""Everything on local models: one context for every call, kept loaded, retried while loading, never silently cut; pictures
to a model that can see; small jobs to a quick model; the loop of tool calls in a small shape; and a skill of any length
read in parts. Ollama is faked: each test says what it answers."""

import asyncio
import json

import pytest

from scene import agent as agent_module
from scene.agent import Agent, AgentError
from test_api import register


class Answer:
    def __init__(self, body):
        self.body = body
        self.status_code = 200

    def json(self):
        return self.body


def ollama(monkeypatch, brain, chats, shows=None, tags=("qwen3.6:35b", "qwen3.5:9b")):
    """Fake Ollama for `brain`: /api/chat answers `chats` in turn (dicts are the model's JSON; a str is an error), and
    records every request; /api/show says what each model can do; /api/tags lists `tags`."""
    sent = []

    async def post(url, json=None, **kwargs):
        if url.endswith("/api/show"):
            return Answer({"capabilities": (shows or {}).get(json["model"], ["completion"])})
        sent.append(json)
        said = chats[min(len(sent), len(chats)) - 1]
        if isinstance(said, str):
            return Answer({"error": said})
        return Answer({"message": {"content": __import__("json").dumps(said)}, "prompt_eval_count": 100, "eval_count": 10})

    async def get(url, **kwargs):
        return Answer({"models": [{"name": n, "size": 1} for n in tags]})
    monkeypatch.setattr(brain.http, "post", post)
    monkeypatch.setattr(brain.http, "get", get)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(agent_module.asyncio, "sleep", lambda seconds, *result: real_sleep(0, *result))   # no real waiting
    return sent


def run(coro):
    return asyncio.run(coro)


def test_one_context_kept_loaded_and_thinking_only_when_asked(monkeypatch):
    brain = Agent("http://ollama", "qwen3.6:35b", options={"context": 262144, "keep_alive": "3h", "think": True})
    sent = ollama(monkeypatch, brain, [{"ok": 1}, {"ok": 2}], shows={"qwen3.6:35b": ["completion", "thinking"]})
    run(brain.chat([{"role": "user", "content": "hi"}], "json", think=True))
    run(brain.chat([{"role": "user", "content": "hi"}], "json", context=16384))
    assert [s["options"]["num_ctx"] for s in sent] == [262144, 262144]   # one size: no reload between calls
    assert [s["keep_alive"] for s in sent] == ["3h", "3h"] and [s["think"] for s in sent] == [True, False]
    plain = Agent("http://ollama", "qwen3.6:35b", options={"think": True})
    sent = ollama(monkeypatch, plain, [{"ok": 1}])   # a model that cannot think is never asked to (Ollama refuses it)
    run(plain.chat([{"role": "user", "content": "hi"}], "json", think=True))
    assert sent[0]["think"] is False
    quiet = Agent("http://ollama", "qwen3.6:35b")
    sent = ollama(monkeypatch, quiet, [{"ok": 1}])
    run(quiet.chat([{"role": "user", "content": "hi"}], "json", think=True))
    assert sent[0]["think"] is False and sent[0]["options"]["num_ctx"] == agent_module.LOCAL_CONTEXT   # thinking off unless set


def test_retried_while_the_model_loads_and_never_silently_cut(monkeypatch):
    brain = Agent("http://ollama", "qwen3.6:35b", options={"context": 4096})
    sent = ollama(monkeypatch, brain, ["model is loading, try again", {"ok": 1}])
    assert run(brain.chat([{"role": "user", "content": "hi"}], "json"))["ok"] == 1 and len(sent) == 2
    with pytest.raises(AgentError, match="too long for qwen3.6:35b.*ollama_context"):
        run(brain.chat([{"role": "user", "content": "x" * 20000}], "json"))   # ~6,700 tokens into 4,096: refused, not cut
    sent = ollama(monkeypatch, brain, ["model failed to load: out of memory"])
    with pytest.raises(AgentError, match="out of memory"):
        run(brain.chat([{"role": "user", "content": "hi"}], "json"))


def test_pictures_go_to_a_local_model_that_can_see(monkeypatch):
    brain = Agent("http://ollama", "qwen3.6:35b")
    sent = ollama(monkeypatch, brain, [{"shows": "a dog"}], shows={"qwen3.5:9b": ["completion", "vision"]})
    assert run(brain.describe("BASE64", "Rex")) == "a dog" and sent[0]["model"] == "qwen3.5:9b"
    named = Agent("http://ollama", "qwen3.6:35b", options={"vision": "qwen3.5:27b"})
    sent = ollama(monkeypatch, named, [{"shows": "a cat"}], shows={"qwen3.5:27b": ["completion", "vision"]})
    run(named.describe("BASE64", "Tom"))
    assert sent[0]["model"] == "qwen3.5:27b"
    gone = Agent("http://ollama", "qwen3.6:35b", options={"vision": "removed:7b"})   # set, but no longer in Ollama
    sent = ollama(monkeypatch, gone, [{"shows": "a cat"}], shows={"qwen3.5:9b": ["completion", "vision"]})
    run(gone.describe("BASE64", "Tom"))
    assert sent[0]["model"] == "qwen3.5:9b"
    blind = Agent("http://ollama", "qwen3.6:35b")
    ollama(monkeypatch, blind, [{"shows": "x"}], tags=("qwen3.6:35b",))
    with pytest.raises(AgentError, match="No local model can look at pictures"):
        run(blind.describe("BASE64", "Rex"))


def test_small_jobs_go_to_the_quick_model(monkeypatch):
    gemini = agent_module.service("gemini", "Gemini", "https://g.example.com", "g-key", "gemini-3.6-flash")
    brain = Agent("http://ollama", "qwen3.6:35b", services=[gemini], options={"fast": "qwen3.5:9b"})
    sent = ollama(monkeypatch, brain, [{"direction": "A dog film."}, {"prompt": "A dog runs."}])
    run(brain.compact([{"role": "user", "content": "a dog film"}], model="qwen3.6:35b"))
    run(brain.improve("dog", model="qwen3.6:35b"))
    assert [s["model"] for s in sent] == ["qwen3.5:9b", "qwen3.5:9b"]
    assert brain.helper("gemini/gemini-3.6-flash") == "gemini/gemini-3.6-flash"   # a hosted model does its own small jobs


def test_a_long_run_is_kept_within_the_context():
    brain = Agent("http://ollama", "qwen3.6:35b", options={"context": 8192})
    messages = [{"role": "system", "content": "rules " * 500}, {"role": "user", "content": "the question"}]
    for n in range(12):
        messages += [{"role": "assistant", "content": '{"tool": "state_read"}'}, {"role": "user", "content": "Result of state_read:\n" + "y" * 2000}]
    brain._fit(messages)
    results = [m["content"] for m in messages if m["content"].startswith("Result of")]
    assert all("shortened" in r for r in results[:4]) and all(len(r) > 2000 for r in results[4:])
    assert messages[0]["content"] == "rules " * 500 and messages[1]["content"] == "the question"   # never the instructions
    assert sum(len(m["content"]) for m in messages) <= 8192 * agent_module.CHARS_PER_TOKEN * 0.9


def test_a_local_model_runs_a_long_skill_with_its_tools(client, monkeypatch, tmp_path):
    from scene import runs, skills
    register(client)
    (tmp_path / "pm.md").write_text("---\nname: pm\nlabel: Pocket Motion\n---\n\nThe rules of the run.\n\n## 1 - Inputs\nSave the script first.\n\n"
                                    "## 2 - Render\n" + "Render the film. " * 3000, encoding="utf-8")
    shipped = skills.load
    monkeypatch.setattr(skills, "load", lambda folder=None: shipped(tmp_path))
    brain = client.app.state.agent
    brain.tools, brain.context = True, 16384   # a small context: the skill (51k characters) is read in parts
    monkeypatch.setattr(brain, "preflight", lambda *a, **k: asyncio.sleep(0, {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}))
    sent = ollama(monkeypatch, brain, [
        {"tool": "read_skill", "args": {"op": "pm", "query": "1"}},
        {"tool": "state_write", "args": {"path": "/motion/status", "value": '"step 1"'}},
        {"tool": "finish", "args": {}},
        {"thought": "", "reply": "Send me the audio.", "steps": [], "direction": "", "question": {"text": "", "options": []}}])
    plan = client.post("/api/agent/plan", json={"instruction": "/pm go", "run": "pm-1", "model": "qwen3.6:35b"}).json()
    assert plan["reply"] == "Send me the audio."
    shapes = [s["format"] for s in sent]
    assert all(any(o["properties"]["tool"]["enum"] == ["read_skill"] for o in f["anyOf"]) for f in shapes[:3])   # one shape per tool
    assert "steps" in shapes[3]["required"]                                         # the plan in its own call
    system = sent[0]["messages"][0]["content"]
    assert "The rules of the run." in system and "Render the film. " * 50 not in system and "2. 2 - Render" in system
    told = [m["content"] for m in sent[3]["messages"] if m["role"] == "user"]
    assert any("Save the script first." in t for t in told)                         # the part it read
    assert runs.read(client.app.state.db, 1, "pm-1", "/motion/status")["value"] == "step 1"
    assert any("is long (" in e.get("text", "") and "parts" in e.get("text", "") for e in plan["activity"])


def test_the_model_is_whatever_ollama_has_now(monkeypatch):
    configured = Agent("http://ollama", "removed:7b")   # the configured one was removed from Ollama
    sent = ollama(monkeypatch, configured, [{"ok": 1}, {"ok": 2}], tags=("new:70b", "qwen3.5:9b"))
    run(configured.chat([{"role": "user", "content": "hi"}], "json"))
    run(configured.chat([{"role": "user", "content": "hi"}], "json", model="qwen3.5:9b"))
    assert [s["model"] for s in sent] == ["new:70b", "qwen3.5:9b"]   # the first there is, then the one the user picked
    unset = Agent("http://ollama", "")
    sent = ollama(monkeypatch, unset, [{"ok": 1}], tags=("just-pulled:12b",))
    assert run(unset.models()) == ["just-pulled:12b"]   # a model pulled a moment ago is offered, with nothing to set
    run(unset.chat([{"role": "user", "content": "hi"}], "json"))
    assert sent[0]["model"] == "just-pulled:12b"
