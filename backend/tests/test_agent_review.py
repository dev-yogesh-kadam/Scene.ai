"""Review: the agent looks at what it made, says whether it is what was asked for, and prices a retake of a failed shot.
No render server and no model are used: the frames and the model's answer are given."""

import json

from scene import memory, review
from test_api import register

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
FAILED = {"checks": [{"check": "who", "level": "major", "note": "She looks about 13, older than in the reference."},
                     {"check": "clean", "level": "minor", "note": "A small blur on the left hand."},
                     {"check": "made_up", "level": "major", "note": "dropped"}, {"check": "what", "level": "awful", "note": "dropped"}, "junk"],
          "problem": "She looks older than in her reference picture.",
          "fix": {"prompt": "The girl from the reference picture, about nine, keeps her face; she walks home in the rain.",
                  "start_from_previous": True, "why": "the reference face first"}}
PASSED = {"checks": [{"check": "what", "level": "fine", "note": "fine"}, {"check": "clean", "level": "minor", "note": "soft focus"}],
          "problem": "", "fix": {"prompt": "", "start_from_previous": False, "why": ""}}


def made(client, user_id, name, kind="video", prompt="The girl walks home in the rain."):
    folder = client.app.state.outputs.folder(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + ".mp4")).write_bytes(PNG)
    settings = {"workflow": "video/h3_master", "values": {"100:value": prompt}, "options": {"engine": "reference"},
                "prompt": prompt, "refs": {}, "seed_mode": "fixed"}
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, summary, settings, context, seconds, size, created) "
        "VALUES (?, 'video/h3_master', ?, ?, ?, '', ?, '{}', 1, 1, 1)", (user_id, kind, name, name + ".mp4", json.dumps(settings)))


def model_says(monkeypatch, client, answer, seen=None):
    """The frames are given and the model answers `answer`; `seen` gets what it was shown."""
    async def frames(path, kind):
        return [("the result at 0.5 s", "f1"), ("the result at 2.0 s", "f2")]

    async def still(path):
        return "still"

    async def last(path, kind):
        return "last"

    async def fake_review(pictures, labels, prompt, kind="video"):
        if seen is not None:
            seen.update(pictures=pictures, labels=labels, prompt=prompt)
        return answer
    monkeypatch.setattr(review, "result_frames", frames)
    monkeypatch.setattr(review, "_still", still)
    monkeypatch.setattr(review, "last_frame", last)
    monkeypatch.setattr(client.app.state.agent, "review", fake_review)


def test_a_verdict_keeps_only_known_checks_and_fails_only_on_a_major_one():
    failed = review.verdict_from(FAILED)
    assert [(c["check"], c["level"]) for c in failed["checks"]] == [("who", "major"), ("clean", "minor")]
    assert failed["passed"] is False and failed["fix"]["start_from_previous"] is True
    passed = review.verdict_from(PASSED)
    assert passed["passed"] is True and passed["problem"] == "" and passed["fix"] == {}
    assert review.summary(passed) == "Passed the review (minor: soft focus)"
    assert review.summary(failed) == "Failed the review: She looks older than in her reference picture."
    # A major check with no problem written still tells the user what is wrong.
    assert review.verdict_from({"checks": [{"check": "what", "level": "major", "note": "No dog in the shot."}]})["problem"] == "No dog in the shot."


def test_a_failed_shot_is_kept_with_its_verdict_and_comes_with_a_priced_retake(client, monkeypatch):
    me = register(client)
    before = made(client, me["id"], "Lane")
    shot = made(client, me["id"], "Walk home")
    film = client.post("/api/projects", json={"name": "Film"}).json()["id"]
    meera = client.post("/api/kit", files={"file": ("meera.png", PNG, "image/png")},
                        data={"name": "Meera", "type": "character", "project_id": str(film)}).json()["id"]
    seen = {}
    model_says(monkeypatch, client, FAILED, seen)
    found = client.post("/api/agent/review", json={"item": shot, "prompt": "The girl walks home in the rain.",
                                                   "uses": [{"asset": meera}, {"id": 999}], "previous": before}).json()
    # The model saw the reference, the last frame of the shot before and the result, each named.
    assert seen["labels"] == ["reference: Meera", "the last frame of the shot before", "the result at 0.5 s", "the result at 2.0 s"]
    assert seen["pictures"] == ["still", "last", "f1", "f2"]
    assert found["verdict"]["passed"] is False
    retake = found["retake"]
    assert retake["settings"]["values"]["100:value"].startswith("The girl from the reference picture")
    assert retake["settings"]["seed_mode"] == "random" and retake["settings"]["parent"] == shot
    assert retake["credits"] > 0 and retake["start"]["id"] == before and retake["why"] == "the reference face first"
    # Nothing was charged: the retake is only queued when the user approves it.
    assert client.get("/api/auth/me").json()["credits"] == 500
    # The verdict is kept with the item: the agent's book says it failed.
    book = {e["name"]: e for e in memory.book_for_model(memory.book(client.app.state.db, me["id"], 0)) if "item" in e}
    assert book["Walk home"]["review"].startswith("Failed the review")


def test_a_passed_shot_has_no_retake_and_a_shot_can_be_checked_on_its_own(client, monkeypatch):
    me = register(client)
    shot = made(client, me["id"], "Walk home")
    seen = {}
    model_says(monkeypatch, client, PASSED, seen)
    found = client.post("/api/agent/review", json={"item": shot}).json()
    assert found["verdict"]["passed"] is True and found["retake"] is None
    assert seen["prompt"] == "The girl walks home in the rain."   # its own prompt, when none is given
    # A failed one checked with retake false gets no retake (the second take of a shot: one retake per shot).
    model_says(monkeypatch, client, FAILED)
    assert client.post("/api/agent/review", json={"item": shot, "retake": False}).json()["retake"] is None


def test_review_refuses_what_it_cannot_look_at(client, monkeypatch):
    me = register(client)
    model_says(monkeypatch, client, PASSED)
    assert client.post("/api/agent/review", json={"item": 999}).status_code == 404
    song = made(client, me["id"], "Song", kind="audio")
    assert "Only pictures and videos" in client.post("/api/agent/review", json={"item": song}).json()["detail"]
    gone = made(client, me["id"], "Gone")
    (client.app.state.outputs.folder(me["id"]) / "Gone.mp4").unlink()
    assert "missing from storage" in client.post("/api/agent/review", json={"item": gone}).json()["detail"]
