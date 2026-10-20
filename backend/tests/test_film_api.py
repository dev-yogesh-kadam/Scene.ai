"""POST /api/edit/film: the film operations queued as free edits, their results in the library (or kept to their run)."""

import asyncio
import json

from scene import jobs, media
from test_api import after, register


def item(client, me, name, kind, filename, make):
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True, exist_ok=True)
    asyncio.run(media._ffmpeg("-loglevel", "error", *make, folder / filename))
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) "
        "VALUES (?, 'upload/file', ?, ?, ?, '{}', '{}', 1)", (me["id"], kind, name, filename))


def made(client, response, run=""):
    assert response.status_code == 200, response.text
    job = after(client, response.json()["job"])
    assert job["status"] == "done", job["error"]
    found = [i for i in client.get("/api/library", params={"run": run}).json()["items"] if i["job_id"] == job["id"]]
    assert found, "the result is not where it was filed"
    return found


def test_film_operations_run_and_their_working_files_stay_with_the_run(client):
    me = register(client)
    master = item(client, me, "Master", "audio", "master.wav", ["-f", "lavfi", "-i", "sine=frequency=300:duration=4"])
    clip = item(client, me, "Clip", "video", "clip.mp4", ["-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24:d=3", "-pix_fmt", "yuv420p"])
    still = item(client, me, "Still", "image", "still.png", ["-f", "lavfi", "-i", "color=c=red:s=3000x2000", "-frames:v", "1"])
    post = lambda **body: client.post("/api/edit/film", json=body)

    # a slice of a run is a working file: not in the library, but in the run's own listing
    sliced = made(client, post(op="slice", audio=master, f_in=24, f_out=72, run="pm-1"), run="pm-1")[0]
    assert (sliced["kind"], sliced["context"]["duration"]) == ("audio", 2.0)
    assert sliced["id"] not in [i["id"] for i in client.get("/api/library").json()["items"]]
    ref = made(client, post(op="reference", image=still))[0]
    assert (ref["kind"], ref["context"]["width"], ref["context"]["height"]) == ("image", 1500, 1000)
    track = made(client, post(op="track", frames=[30, 40, 50]))[0]
    assert track["context"]["frames"] == 120
    trim = made(client, post(op="trim", video=clip, frames=48, size=[96, 96]))[0]
    assert (trim["context"]["frames"], trim["context"]["width"]) == (48, 96)
    retimed = made(client, post(op="retime", video=clip, frames=72, size=[96, 96],
                                lines=[{"master": [1.0, 2.0], "clip": [0.2, 0.8]}]))[0]
    assert retimed["context"]["frames"] == 72 and retimed["context"]["segments"]
    sheets = made(client, post(op="proof", video=clip, marks=[{"at": i * 0.04, "label": "u%d" % i} for i in range(61)]))
    assert len(sheets) == 2 and {s["kind"] for s in sheets} == {"image"}
    spans = made(client, post(op="speech", audio=master, lines=[{"n": 1, "start": 0, "end": 4, "speaker": "maya"}]))[0]
    assert spans["kind"] == "text"
    folder = client.app.state.outputs.folder(me["id"])
    assert json.loads((folder / spans["filename"]).read_text(encoding="utf-8"))["1"][0] < 0.1
    # the film: two trims of 48 frames on a 4 s master
    joined = made(client, post(op="film", clips=[trim["id"], trim["id"]], audio=master))[0]
    assert joined["context"]["frames"] == 96
    subbed = made(client, post(op="subtitles", video=joined["id"], lines=[{"start": 0, "end": 2, "text": "Hello there", "speaker": "maya"}]))[0]
    assert subbed["context"]["cues"] == 1


def test_film_operations_are_checked_before_anything_is_queued(client):
    me = register(client)
    master = item(client, me, "Master", "audio", "master.wav", ["-f", "lavfi", "-i", "sine=frequency=300:duration=1"])
    post = lambda **body: client.post("/api/edit/film", json=body)
    assert post(op="nonsense").status_code == 400
    assert post(op="slice", audio=master, f_in=48, f_out=24).status_code == 400          # ends before it starts
    assert post(op="slice", audio=999, f_in=0, f_out=24).status_code == 404              # not the user's
    assert post(op="trim", video=master, frames=24).status_code == 404                   # an audio is not a clip
    assert post(op="track", frames=[]).status_code == 400
    assert post(op="track", frames=[24 * 61]).status_code == 400                         # longer than a minute
    assert post(op="slice", audio=master, f_in=0, f_out=24, run="Bad Run!").status_code == 400
    other = register(client, email="other@example.com")
    assert other["id"] != me["id"]
    assert post(op="slice", audio=master, f_in=0, f_out=24).status_code == 404           # another user's sound


def test_a_comfyui_transcript_is_collected_as_text():
    entry = {"outputs": {"9": {"text": [{"filename": "episode.json", "subfolder": "", "type": "output"},
                                        {"filename": "episode.srt", "subfolder": "", "type": "output"}],
                               "audio": [{"filename": "voice.wav", "subfolder": "", "type": "output"}]}}}
    assert [(i["filename"], kind) for i, kind, _ in jobs._outputs(entry)] == [
        ("episode.json", "text"), ("episode.srt", "text"), ("voice.wav", "audio")]
