"""Transcripts and the clock (transcript.py), bulk state, and the agent's transcript and timing tools: a run of a whole
episode keeps hundreds of lines and shots, and their times are copied by code, never retyped by the model."""

import asyncio
import io
import json

import pytest

from scene import media, runs, transcript
from test_agent_shots import hosted
from test_api import after, register

SRT = """1
00:00:01,000 --> 00:00:03,500
NARRATOR: The storm came over the hills.

2
00:00:04,250 --> 00:00:05,100
Maya: Run!

3
00:00:06,000 --> 00:00:07,000
and nobody listened
"""


def test_an_srt_and_a_json_transcript_give_their_lines_exactly():
    lines = transcript.parse(SRT)
    assert lines == [{"start": 1.0, "end": 3.5, "speaker": "NARRATOR", "text": "The storm came over the hills."},
                     {"start": 4.25, "end": 5.1, "speaker": "Maya", "text": "Run!"},
                     {"start": 6.0, "end": 7.0, "speaker": "", "text": "and nobody listened"}]
    whisper = json.dumps({"segments": [{"start": 0.512, "end": 2.98, "speaker": "SPEAKER_00", "text": " Charles said,  his voice cracking"},
                                       {"start": 3, "end": 4, "text": ""}], "words": []})
    assert transcript.parse(whisper) == [{"start": 0.512, "end": 2.98, "speaker": "SPEAKER_00", "text": "Charles said, his voice cracking"}]
    for bad in ("", "{not json", '{"segments": 3}', "no times here"):
        with pytest.raises(transcript.TranscriptError):
            transcript.parse(bad)


def test_the_clock_follows_lines_speech_and_gaps():
    lines = {1: {"start": 1.0, "end": 3.0}, 2: {"start": 4.0, "end": 5.0}, 3: {"start": 10.0, "end": 12.0}}
    speech = {2: [4.6, 5.0]}                     # the character's real speech starts later than the transcript says
    units = [{"id": "u001", "from": "gap@start"}, {"id": "u002", "from": "L1"}, {"id": "u003", "from": "L2"},
             {"id": "u004", "from": "gap@L2"}, {"id": "u005", "from": "gap@L2"}, {"id": "u006", "from": "L3"}]
    frames, problems = transcript.grid(units, lines, speech, 14.0)
    assert frames["u001"] == {"f_in": 0, "f_out": 24}                     # the lead-in up to line 1
    assert frames["u003"]["f_in"] == round(4.6 * 24)                      # the measured speech wins
    assert frames["u004"]["f_in"] == round(5.5 * 24)                      # the gap starts half a second after line 2
    assert frames["u005"]["f_in"] == round((5.5 + 4.5 / 2) * 24)          # and its shots share it evenly
    assert frames["u006"] == {"f_in": 240, "f_out": 336}                  # the last ends at the master's end
    assert sum(f["f_out"] - f["f_in"] for f in frames.values()) == 336    # no gap, no overlap
    assert any("u002" in p and "over 3.5" in p for p in problems)         # 1.0-4.6 s is a pace break
    _, bad = transcript.grid([{"id": "u1", "from": "L9"}, {"id": "u2", "from": "soon"}], lines, {}, 14.0)
    assert any("L9 is not in the transcript" in p for p in bad) and any("is not L<n>" in p for p in bad)


def test_many_leaves_at_once_and_a_folder_reference(client):
    me = register(client)
    db = client.app.state.db
    written = runs.write_many(db, me["id"], "pm-1", "/motion/timing", {"u%03d" % i: {"f_in": i, "f_out": i + 1} for i in range(1, 501)})
    assert written == {"path": "/motion/timing", "written": 500}
    assert runs.read(db, me["id"], "pm-1", "/motion/timing")["total"] == 500
    runs.write_many(db, me["id"], "pm-1", "/motion/timing", {"u001": {"f_in": 0, "f_out": 5}}, replace=True)   # done again
    assert runs.children(db, me["id"], "pm-1", "/motion/timing") == ["u001"]
    with pytest.raises(runs.RunError):
        runs.write_many(db, me["id"], "pm-1", "/motion/x", {"a/b": 1})            # one level only
    with pytest.raises(runs.RunError):
        runs.write_many(db, me["id"], "pm-1", "/budget", {"x": 1})                # never the budget
    runs.write_many(db, me["id"], "pm-1", "/motion/lines", {"2": {"start": 2.0}, "10": {"start": 9.0}, "1": {"start": 0.5}})
    assert runs.resolve(db, me["id"], "pm-1", "$state:/motion/lines/*") == [{"start": 0.5, "n": 1}, {"start": 2.0, "n": 2}, {"start": 9.0, "n": 10}]
    with pytest.raises(runs.RunError, match="state_reference_unresolved"):
        runs.resolve(db, me["id"], "pm-1", "$state:/motion/nothing/*")


def test_a_transcript_is_uploaded_read_into_the_run_and_timed(client, monkeypatch):
    register(client)
    made = client.post("/api/library/upload", files={"file": ("episode.srt", io.BytesIO(SRT.encode()), "text/plain")}).json()
    assert made["kind"] == "text"
    assert client.post("/api/library/upload", files={"file": ("x.srt", io.BytesIO(b"\x00\x01binary"), "text/plain")}).status_code == 400
    assert client.post(f"/api/library/{made['id']}/reference").status_code == 400      # a text is no reference (and no crash)
    units = {"u001": {"from": "gap@start"}, "u002": {"from": "L1"}, "u003": {"from": "L2"}, "u004": {"from": "L3"}}
    seen = hosted(monkeypatch, client,
                  {"tool": "transcript", "item": made["id"], "path": "/motion/transcript/lines"},
                  {"tool": "state_write", "path": "/motion/plan/units/*", "value": json.dumps(units)},
                  {"tool": "timing", "settings": json.dumps({"units": "/motion/plan/units", "lines": "/motion/transcript/lines",
                                                             "length": 8.0, "save_to": "/motion/timing"})},
                  {"tool": "finish", "reply": "Timed.", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "go", "run": "pm-1"})
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any('"written": 3' in t and '"NARRATOR"' in t for t in told)
    assert any("Written: 4 leaves under /motion/plan/units" in t for t in told)
    assert any('"timed": 4' in t and '"frames": 192' in t for t in told)
    lines = client.get("/api/runs/pm-1/state", params={"path": "/motion/transcript/lines/2"}).json()["value"]
    assert lines == {"start": 4.25, "end": 5.1, "speaker": "Maya", "text": "Run!"}
    timing = client.get("/api/runs/pm-1/state", params={"path": "/motion/timing/u003"}).json()["value"]
    assert timing == {"f_in": round(4.25 * 24), "f_out": 144}


def test_the_speech_scan_takes_its_lines_from_the_run_and_keeps_its_spans_there(client):
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True)
    graph = "sine=frequency=300:duration=2,volume=0.5[a];sine=duration=1,volume=0[b];sine=frequency=300:duration=1.5,volume=0.5[c];[a][b][c]concat=n=3:v=0:a=1[o]"
    asyncio.run(media._ffmpeg("-loglevel", "error", "-filter_complex", graph, "-map", "[o]", "-ar", "16000", folder / "voice.wav"))
    voice = client.app.state.db.run("INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
                                    "VALUES (?, 'audio/sep', 'audio', 'Voice', 'voice.wav', '{}', '{}', 1)", (me["id"],))
    runs.write_many(client.app.state.db, me["id"], "pm-1", "/motion/transcript/lines", {
        "1": {"start": 0.0, "end": 2.2, "speaker": "SPEAKER_00", "text": "narration"},
        "2": {"start": 2.4, "end": 4.6, "speaker": "SPEAKER_01", "text": "the line"}})
    lines = runs.resolve(client.app.state.db, me["id"], "pm-1", "$state:/motion/transcript/lines/*")
    job = client.post("/api/edit/film", json={"op": "speech", "audio": voice, "lines": lines, "narrator": "SPEAKER_00",
                                              "save_to": "/motion/transcript/speech", "run": "pm-1"}).json()["job"]
    assert after(client, job)["status"] == "done"
    span = client.get("/api/runs/pm-1/state", params={"path": "/motion/transcript/speech/2"}).json()["value"]
    assert span[0] == pytest.approx(3.0, abs=0.03) and span[1] == pytest.approx(4.5, abs=0.03)
    assert client.get("/api/runs/pm-1/state", params={"path": "/motion/transcript/speech/1"}).json().get("missing")   # the narrator: no span
    assert client.post("/api/edit/film", json={"op": "speech", "audio": voice, "lines": lines, "save_to": "/x"}).status_code == 400   # no run
