"""The render PC's new workflows (19 October): they load, the agent is offered them and builds their steps, and their
results are filed apart. Read with the node definitions the render PC gave (tests/fixtures/node_definitions.json)."""

import asyncio
import json

import pytest

from scene import agent, jobs, runs
from scene.api import studio
from scene.comfy import workflows
from test_agent_shots import hosted
from test_api import register

NEW = ["image/image_ref_edit", "image/image_location_rebuild", "video/h3_chunk", "video/video_lipsync",
       "audio/audio_separate_voice", "audio/audio_transcribe", "audio/audio_transcribe_video"]


def schema_of(client, workflow_id):
    return workflows.describe(asyncio.run(client.app.state.catalog.load(workflow_id)))


def test_the_new_workflows_load_and_build(client):
    listed = {w["id"]: w for w in asyncio.run(client.app.state.catalog.listing())}
    for wid in NEW:
        assert wid in listed and not listed[wid].get("error"), wid
        schema = schema_of(client, wid)
        settings = {"workflow": wid, "values": {}, "clips": 1, "options": {o["id"]: o["default"] for o in schema["options"]},
                    "refs": {r["id"]: {"comfy_name": "scene_x.png"} for r in schema["refs"] if not r["optional"]}}
        workflows.build_prompt(asyncio.run(client.app.state.catalog.load(wid)), settings)   # raises if anything is wrong
    chunk = schema_of(client, "video/h3_chunk")
    roles = {c["role"]: c for c in chunk["controls"] if c["role"]}
    assert roles["duration"]["type"] == "float" and chunk["slots"]["voice_track"] == "211:audio"
    assert [o["id"] for o in chunk["options"]] == ["quality"]   # the size follows the studio's resolution and shape
    assert next(r for r in chunk["refs"] if r["id"] == "205:image")["optional"] is False
    assert {c["id"] for c in schema_of(client, "audio/audio_transcribe")["controls"]} >= {"10:value", "12:language"}
    assert schema_of(client, "image/image_location_rebuild")["prompt_optional"] is True


def test_the_agent_is_offered_the_tools_without_a_prompt_when_given_a_file(client):
    transcribe, lipsync = schema_of(client, "audio/audio_transcribe"), schema_of(client, "video/video_lipsync")
    assert agent.offer(transcribe, attached=False) is None          # nothing to work on
    offered = agent.offer(transcribe, attached=True)
    assert offered["prompt"].startswith("none") and any(s["setting"] == "10:value" for s in offered["settings"])
    assert agent.offer(lipsync, attached=True)["references"][0]["slot"] == "1:file"
    chunk = agent.offer(schema_of(client, "video/h3_chunk"), attached=True)
    assert "decimals allowed" in chunk["duration_seconds"]
    free = {s["setting"]: s for s in chunk["settings"]}
    assert free["215:value"]["value"] == "true or false" and free["301:value"]["value"] == "any words"


def test_a_step_on_them_takes_decimals_switches_and_words(client):
    chunk = schema_of(client, "video/h3_chunk")
    step = {"name": "c3", "prompt": "Character 1 turns to the window.", "duration": 151 / 24, "resolution": 480, "orientation": "square",
            "choices": [{"setting": "215:value", "value": "true"}, {"setting": "301:value", "value": "48, 84"},
                        {"setting": "402:value", "value": "nonsense"}, {"setting": "quality", "value": "final"}]}
    settings, _ = agent.settings_for(chunk, step, [], 0, filled={"205:image"})
    assert settings["values"]["102:value"] == round(151 / 24, 4)    # round(24 x 6.2917) = 151 frames
    assert settings["values"]["215:value"] is True and settings["values"]["301:value"] == "48, 84"
    keep_sound = next(c for c in chunk["controls"] if c["id"] == "402:value")["default"]
    assert settings["values"]["402:value"] == keep_sound               # a switch given nonsense keeps its default
    assert settings["options"]["quality"] == "final"
    assert (settings["resolution"], settings["orientation"]) == (480, "square")
    whole = agent.settings_for(schema_of(client, "video/h3_master"), dict(step, duration=6.6), [], 0)[0]
    assert isinstance(whole["values"][next(c["id"] for c in schema_of(client, "video/h3_master")["controls"] if c["role"] == "duration")], (int, float))
    transcribe = schema_of(client, "audio/audio_transcribe")
    made = agent.settings_for(transcribe, {"name": "Listen", "prompt": "", "choices": [{"setting": "12:language", "value": "hi"},
                                                                                        {"setting": "10:value", "value": "EXT. ROOFTOP — DUSK"}]},
                              [], 0, filled={"1:audio"})[0]
    assert made["values"]["12:language"] == "hi" and made["values"]["10:value"] == "EXT. ROOFTOP — DUSK"
    rebuild = agent.settings_for(schema_of(client, "image/image_location_rebuild"), {"name": "Suite", "prompt": ""}, [], 0, filled={"20:image"})
    assert rebuild is not None                                        # its prompt is only notes
    assert agent.settings_for(schema_of(client, "image/image_ref_edit"), {"name": "x", "prompt": ""}, [], 0, filled={"20:image"}) is None


def test_several_outputs_of_one_run_are_told_apart():
    wf = {"nodes": {"3": {"_meta": {"title": "VOICE STEM"}}, "4": {"_meta": {"title": "MUSIC AND EFFECTS STEM"}}, "12": {"_meta": {"title": "Transcribe"}}}}
    stems = {"outputs": {"3": {"audio": [{"filename": "v.wav", "type": "output"}]}, "4": {"audio": [{"filename": "m.wav", "type": "output"}]}}}
    assert jobs._output_labels(wf, list(jobs._outputs(stems))) == ["VOICE STEM", "MUSIC AND EFFECTS STEM"]
    text = {"outputs": {"12": {"transcripts": [{"filename": "t.json", "type": "output"}, {"filename": "t.srt", "type": "output"}]}}}
    found = list(jobs._outputs(text))
    assert [k for _, k, _ in found] == ["text", "text"] and jobs._output_labels(wf, found) == ["JSON", "SRT"]
    assert jobs._output_labels(wf, list(jobs._outputs({"outputs": {"9": {"images": [{"filename": "a.png", "type": "output"}]}}}))) == [None]


def test_a_lip_sync_is_billed_by_the_video_it_is_given(client):
    me = register(client)
    clip = client.app.state.db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
                                   "VALUES (?, 'video/h3_chunk', 'video', 'c3', 'c3.mp4', '{}', ?, 1)", (me["id"], json.dumps({"duration": 6.3})))
    wf = asyncio.run(client.app.state.catalog.load("video/video_lipsync"))
    seconds = asyncio.run(studio.billed_seconds(client.app.state, wf, workflows.describe(wf), {"parent": clip, "values": {}}, me["id"]))
    assert seconds == 6.3
    assert studio.by_source(wf) and not studio.by_source(asyncio.run(client.app.state.catalog.load("audio/audio_transcribe")))


def test_the_agent_names_the_speakers_without_touching_a_time(client, monkeypatch):
    me = register(client)
    db = client.app.state.db
    runs.write_many(db, me["id"], "pm-1", "/motion/transcript/lines", {
        "1": {"start": 0.5, "end": 2.0, "speaker": "SPEAKER_00", "text": "The storm came."},
        "2": {"start": 2.4, "end": 3.1, "speaker": "SPEAKER_00", "text": "Run!"}})
    seen = hosted(monkeypatch, client, {"tool": "transcript", "item": 0, "path": "/motion/transcript/lines", "value": '{"1": "narrator", "2": "Maya", "9": "Nobody"}'},
                  {"tool": "finish", "reply": "ok", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-1"})
    assert any('"named": 2' in m["content"] for m in seen[-1] if m["role"] == "user")
    lines = dict(runs.leaves(db, me["id"], "pm-1", "/motion/transcript/lines"))
    assert lines["2"] == {"start": 2.4, "end": 3.1, "speaker": "Maya", "text": "Run!"} and lines["1"]["speaker"] == "narrator"


def test_a_step_on_a_workflow_without_a_prompt_is_planned_and_shown(client, monkeypatch):
    me = register(client)
    sound = client.app.state.db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
                                    "VALUES (?, 'upload/file', 'audio', 'Episode', 'episode.mp3', '{}', '{}', 1)", (me["id"],))
    step = {"tool": "generate", "workflow": "audio/audio_transcribe", "name": "Listen", "prompt": "",
            "uses": [{"item": sound, "asset": 0, "slot": "1:audio"}], "choices": [{"setting": "12:language", "value": "en"}]}
    hosted(monkeypatch, client, {"tool": "finish", "reply": "Transcribing.", "steps": [step]})
    plan = client.post("/api/agent/plan", json={"instruction": "@1 transcribe it", "selection": [sound]}).json()
    shown = plan["steps"][0]
    assert shown["name"] == "Listen" and shown["prompt"] == "" and shown["settings"]["values"]["12:language"] == "en"


def test_a_sound_step_on_a_workflow_that_takes_a_sound_is_that_workflow(client, monkeypatch):
    # a model often calls separating a voice "sound": it is the workflow's step, not a sound put on a video
    me = register(client)
    sound = client.app.state.db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
                                    "VALUES (?, 'upload/file', 'audio', 'Episode', 'episode.mp3', '{}', '{}', 1)", (me["id"],))
    step = {"tool": "sound", "workflow": "audio/audio_separate_voice", "name": "Voice stem", "prompt": "", "audio": sound,
            "uses": [{"item": sound, "asset": 0, "slot": "1:audio"}]}
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": "Separating.", "steps": [step]})
    plan = client.post("/api/agent/plan", json={"instruction": "@1 separate the voice", "selection": [sound]}).json()
    assert [s["name"] for s in plan["steps"]] == ["Voice stem"] and plan["steps"][0]["settings"]
    assert len(seen) == 1   # it could run as it was: no hint went back
    assert "audio/audio_separate_voice" in agent.takes_sound([agent.offer(schema_of(client, "audio/audio_separate_voice"))])
    assert not agent.takes_sound([agent.offer(schema_of(client, "video/h3_chunk"), True)])


def test_a_plan_that_cannot_be_put_right_goes_back_at_most_twice(client, monkeypatch):
    register(client)
    bad = {"tool": "sound", "workflow": "video/h3_master", "name": "Nothing to put together", "prompt": ""}
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": "Here.", "steps": [bad]})
    plan = client.post("/api/agent/plan", json={"instruction": "put music on it"}).json()
    assert len(seen) == 1 + agent.FIX_ROUNDS and plan["steps"] == []
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("generate" in t and "sound tool only puts" in t for t in told)


def test_a_long_skill_run_is_reminded_once_to_save_its_work(client, monkeypatch):
    me = register(client)
    db = client.app.state.db
    assert not runs.saved_any(db, me["id"], "pm-2")
    runs.keep_skill(db, me["id"], "pm-2", "pocket-motion-seedance-v2")
    assert not runs.saved_any(db, me["id"], "pm-2")   # what the studio keeps for it is not the agent's work
    seen = hosted(monkeypatch, client, {"tool": "finish", "reply": "Pick the models.", "steps": []})
    ready = {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
    monkeypatch.setattr(client.app.state.agent, "preflight", lambda *a, **k: asyncio.sleep(0, ready))
    plan =client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-2"}).json()
    assert plan["reply"] == "Pick the models." and len(seen) == 2
    assert any(agent.SAVE_FIRST in m["content"] for m in seen[-1] if m["role"] == "user")
    runs.write(db, me["id"], "pm-2", "/motion/models", {"image": "image/image_ref_edit"}, "agent")
    assert runs.saved_any(db, me["id"], "pm-2")


def test_the_one_sound_attached_fills_a_slot_the_step_left_out(client):
    schema = schema_of(client, "audio/audio_transcribe")
    one = {7: {"name": "Episode", "kind": "audio"}, 8: {"name": "Maya", "kind": "image"}}
    assert [(u["id"], u["slot"]) for u in agent.uses_for(schema, {"uses": []}, one)] == [(7, "1:audio")]
    two = {**one, 9: {"name": "Voice stem", "kind": "audio"}}
    assert agent.uses_for(schema, {"uses": []}, two) == []   # two sounds: it is not guessed
    assert [u["id"] for u in agent.uses_for(schema, {"uses": [], "audio": 9}, two)] == [9]
    assert [u["id"] for u in agent.uses_for(schema, {"uses": [{"item": 7, "asset": 0, "slot": "1:audio"}], "audio": 9}, two)] == [7]
