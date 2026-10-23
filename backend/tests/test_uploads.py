"""What the user brings in: a script as a Word document (kept as its words), a plain text, and a sound that arrived
dressed as a video (kept as the sound it is). And the agent reading a document, or keeping it in the run's state."""

import asyncio
import io
import json
import zipfile

import pytest

from scene import media, runs
from test_agent_shots import hosted
from test_api import register

DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>EXT. ROOFTOP – DUSK</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">MAYA: </w:t></w:r><w:r><w:t>Direct your scene.</w:t></w:r></w:p>
<w:p><w:r><w:t>She turns</w:t><w:tab/><w:t>to camera.</w:t><w:br/><w:t>CUT TO:</w:t></w:r></w:p>
</w:body></w:document>"""


def docx(xml=DOCUMENT):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", xml)
    return buffer.getvalue()


def upload(client, name, data, mime="application/octet-stream"):
    return client.post("/api/library/upload", files={"file": (name, data, mime)})


def test_a_word_document_is_kept_as_its_words(client):
    register(client)
    made = upload(client, "sceneaites-doc.docx", docx()).json()
    assert (made["kind"], made["name"]) == ("text", "sceneaites-doc") and made["filename"].endswith(".txt")
    words = client.get(f"/api/library/{made['id']}/file").content.decode("utf-8")
    assert words == "EXT. ROOFTOP – DUSK\nMAYA: Direct your scene.\nShe turns\tto camera.\nCUT TO:\n"
    assert upload(client, "fake.docx", b"not a zip at all").status_code == 400
    assert upload(client, "empty.docx", docx("<w:document xmlns:w='x'><unclosed>")).status_code == 400
    assert upload(client, "notes.txt", "Fade in.".encode()).json()["kind"] == "text"
    assert upload(client, "plan.md", b"# Scene 1").json()["kind"] == "text"
    assert upload(client, "tool.exe", b"MZ\x90\x00").status_code == 400


def test_a_sound_dressed_as_a_video_is_kept_as_the_sound(client, tmp_path):
    register(client)
    run = asyncio.run
    # one black frame held for 3 s, with a tone: what some apps export when they save audio "as a video"
    run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=384x384:r=25:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                      "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", tmp_path / "voice.mp4"))
    run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=3", "-f", "lavfi", "-i", "sine=duration=3",
                      "-shortest", "-pix_fmt", "yuv420p", tmp_path / "moving.mp4"))
    sound = upload(client, "sceneaitest1.mp4", (tmp_path / "voice.mp4").read_bytes(), "video/mp4").json()
    assert (sound["kind"], sound["name"]) == ("audio", "sceneaitest1") and sound["filename"].endswith(".m4a")
    assert sound["context"]["duration"] >= 2.9
    clip = upload(client, "moving.mp4", (tmp_path / "moving.mp4").read_bytes(), "video/mp4").json()
    assert clip["kind"] == "video" and clip["context"]["width"] == 320


def test_the_agent_reads_a_document_and_keeps_the_script(client, monkeypatch):
    me = register(client)
    script = upload(client, "episode.docx", docx()).json()
    seen = hosted(monkeypatch, client, {"tool": "read_text", "item": script["id"]},
                  {"tool": "read_text", "item": script["id"], "path": "/motion/inputs/script"},
                  {"tool": "finish", "reply": "ok", "steps": []})
    client.post("/api/agent/plan", json={"instruction": "pocket motion", "run": "pm-1", "selection": [script["id"]]})
    told = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert any("MAYA: Direct your scene." in t for t in told)
    kept = runs.read(client.app.state.db, me["id"], "pm-1", "/motion/inputs/script")["value"]
    assert kept.startswith("EXT. ROOFTOP – DUSK\n") and "CUT TO:" in kept


def long_skill(tmp_path, monkeypatch):
    from scene import skills
    (tmp_path / "pocket-motion-seedance-v2.md").write_text(
        "---\nname: pocket-motion-seedance-v2\nlabel: Pocket Motion\n---\n\nAudio and script are mandatory.\n" + "A rule of the run. " * 2500,
        encoding="utf-8")
    (tmp_path / "social-video.md").write_text("id: social-video\ntitle: A Reel\nwords: " + r"\b(vlog|camera)\b" + "\n---\nShort and vertical.\n",
                                              encoding="utf-8")
    shipped = skills.load
    monkeypatch.setattr(skills, "load", lambda folder=None: shipped(tmp_path))


def test_the_check_is_told_what_each_attachment_is(client, monkeypatch, tmp_path):
    register(client)
    long_skill(tmp_path, monkeypatch)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=5", tmp_path / "episode.mp3"))
    sound = upload(client, "scenetest1.mp3", (tmp_path / "episode.mp3").read_bytes(), "audio/mpeg").json()
    script = upload(client, "sceneaites-doc.docx", docx()).json()
    pictures = []   # ten of them: with the sound and the script, more than the eight read before
    for i in range(10):
        asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1", tmp_path / f"p{i}.png"))
        pictures.append(upload(client, f"cast{i}.png", (tmp_path / f"p{i}.png").read_bytes(), "image/png").json()["id"])
    told = []

    async def hosted_check(messages, answer_format, **kwargs):
        told.append(messages[-1]["content"])
        return {"ready": False, "missing": [], "unsupported": ["x"], "adaptation": "", "message": "stop here"}
    agent_ = client.app.state.agent
    monkeypatch.setattr(agent_, "chat", hosted_check)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    tags = " ".join("@%d" % (i + 1) for i in range(12))
    plan = client.post("/api/agent/plan", json={"instruction": tags + " /pocket-motion-seedance-v2 Madelyn's Vlog Camera",
                                                "selection": [sound["id"], script["id"], *pictures], "run": "pm-1"}).json()
    message = next(m for m in told if "Attached to the message" in m)   # the check of the skill (pictures are described first)
    assert "@1 scenetest1 (a sound, 5.0 s long)" in message
    assert "@2 sceneaites-doc (a text of 74 characters, which begins: “EXT. ROOFTOP – DUSK MAYA: Direct your scene." in message
    assert "@12 cast9" in message                                     # every attachment, not the first eight
    assert [e["text"] for e in plan["activity"] if e["text"].startswith("Read the skill")] == ["Read the skill “Pocket Motion”"]   # no Reel skill beside it


def test_a_long_skill_without_tools_says_how_to_turn_them_on(client, monkeypatch, tmp_path):
    from test_agent_conversation import model
    register(client)
    long_skill(tmp_path, monkeypatch)
    asked = model(monkeypatch, client, {"thought": "", "reply": "planned", "steps": []})   # the test app runs local models without tools
    plan = client.post("/api/agent/plan", json={"instruction": "/pocket-motion-seedance-v2 here are my files"}).json()
    assert "Turn local_tools on" in plan["reply"] and "your files stay attached" in plan["reply"]
    assert asked == [] and plan["steps"] == []


def test_what_the_check_calls_missing_but_is_attached_is_set_aside(client, monkeypatch, tmp_path):
    register(client)
    long_skill(tmp_path, monkeypatch)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", tmp_path / "episode.mp3"))
    sound = upload(client, "scenetest1.mp3", (tmp_path / "episode.mp3").read_bytes(), "audio/mpeg").json()
    script = upload(client, "sceneaites-doc.docx", docx()).json()
    planned = []

    async def strict(messages, answer_format, **kwargs):
        if "ready" in (answer_format.get("properties") or {}):   # the check: wrongly says both are missing
            return {"ready": False, "missing": ["master audio (final mix)", "full script"], "unsupported": [], "adaptation": "",
                    "message": "I need the episode audio (final mix) and the full script."}
        planned.append(1)
        return {"tool": "finish", "thought": "", "reply": "Here is the inventory.", "steps": [], "direction": "", "question": None}
    agent_ = client.app.state.agent
    monkeypatch.setattr(agent_, "chat", strict)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    plan = client.post("/api/agent/plan", json={"instruction": "@1 @2 /pocket-motion-seedance-v2", "selection": [sound["id"], script["id"]],
                                                "run": "pm-1"}).json()
    assert plan["reply"] == "Here is the inventory." and planned
    assert any("Set aside what the check called missing but you attached" in e["text"] for e in plan["activity"])
    # with nothing attached, the check still stops the run
    plan = client.post("/api/agent/plan", json={"instruction": "/pocket-motion-seedance-v2 go"}).json()
    assert plan["reply"].startswith("I need the episode audio")


def test_a_run_keeps_its_skill_after_the_message_that_named_it(client, monkeypatch, tmp_path):
    register(client)
    long_skill(tmp_path, monkeypatch)
    asked = []

    async def answer(messages, answer_format, **kwargs):
        if "ready" in (answer_format.get("properties") or {}):
            return {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
        asked.append(messages[0]["content"])
        return {"tool": "finish", "thought": "", "reply": "ok", "steps": [], "direction": "", "question": None}
    agent_ = client.app.state.agent
    monkeypatch.setattr(agent_, "chat", answer)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    client.post("/api/agent/plan", json={"instruction": "/pocket-motion-seedance-v2 here is the episode", "run": "pm-1"})
    # "go": no command, and words that would pick another skill (vlog, camera) — the run carries on with its own
    plan = client.post("/api/agent/plan", json={"instruction": "Recommended, one clip per shot. go. Madelyn's vlog camera", "run": "pm-1"}).json()
    read = [e["text"] for e in plan["activity"] if e["text"].startswith(("Read the skill", "Carried on"))]
    assert read == ["Carried on with “Pocket Motion”, the skill of this run", "Read the skill “Pocket Motion”"]
    assert "A rule of the run." in asked[-1]
    # the agent cannot change the skill its run follows
    from scene import runs
    with pytest.raises(runs.RunError):
        runs.write(client.app.state.db, 1, "pm-1", "/skill", "social-video")
    # another conversation starts fresh
    other = client.post("/api/agent/plan", json={"instruction": "a vlog camera shot", "run": "other"}).json()
    assert not any(e["text"].startswith("Carried on") for e in other["activity"])


def test_a_run_keeps_its_files_for_the_messages_after(client, monkeypatch, tmp_path):
    register(client)
    long_skill(tmp_path, monkeypatch)
    asyncio.run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", tmp_path / "episode.mp3"))
    sound = upload(client, "scenetest1.mp3", (tmp_path / "episode.mp3").read_bytes(), "audio/mpeg").json()
    script = upload(client, "sceneaites-doc.docx", docx()).json()
    asked = []

    async def answer(messages, answer_format, **kwargs):
        if "ready" in (answer_format.get("properties") or {}):
            asked.append(("check", messages[-1]["content"]))
            return {"ready": True, "missing": [], "unsupported": [], "adaptation": "", "message": ""}
        asked.append(("plan", messages[-1]["content"]))
        return {"tool": "finish", "thought": "", "reply": "ok", "steps": [], "direction": "", "question": None}
    agent_ = client.app.state.agent
    monkeypatch.setattr(agent_, "chat", answer)
    monkeypatch.setattr(agent_, "_service_of", lambda name: ({"name": "Test"}, name))
    client.post("/api/agent/plan", json={"instruction": "@1 @2 /pocket-motion-seedance-v2", "selection": [sound["id"], script["id"]], "run": "pm-1"})
    asked.clear()
    plan = client.post("/api/agent/plan", json={"instruction": "Recommended. go", "selection": [], "run": "pm-1"}).json()
    assert not any(kind == "check" for kind, _ in asked)   # the skill was checked when the run began, not again
    told = next(text for kind, text in asked if kind == "plan")
    assert "scenetest1" in told and "sceneaites-doc" in told   # still there after "go"
    assert any("scenetest1" in e["text"] and "sceneaites-doc" in e["text"] for e in plan["activity"] if e["text"].startswith("Read what you attached"))
    from scene import runs
    assert runs.kept_attached(client.app.state.db, 1, "pm-1") == [sound["id"], script["id"]]
