"""Moderation (moderation.py): a word list that flags prompts for review or refuses them, the review queue of what was
made, and verdicts that keep an item or remove it from its owner's library."""

import json
import time

from scene import moderation
from test_api import JOB, console, post_job, register


def item(client, user_id, name, prompt):
    return client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, "image/x", "image", name, name + ".png", json.dumps({"prompt": prompt}), "{}", time.time()))


def test_words_match_whole_words_in_the_prompt_and_its_values():
    assert moderation.matches("A Gory scene, very gory.", ["gory", "gore"]) == ["gory"]
    assert moderation.matches("Gorilla in the mist", ["gore", "gor"]) == []
    assert moderation.prompt_of({"prompt": "a fox", "values": {"1:value": "a fox", "2:value": "in snow", "3:seed": 4}}) == "a fox · in snow"


def test_the_review_queue_flags_first_and_verdicts_keep_or_remove(client):
    me = register(client)
    desk = console(client)
    calm, bad = item(client, me["id"], "Calm", "a quiet lake"), item(client, me["id"], "Bad", "a gory battle")
    assert desk.put("/api/admin/moderation/settings", json={"words": "Gory\n  battle  axe \n", "mode": "flag"}).json() == {
        "words": ["battle axe", "gory"], "mode": "flag"}
    queue = desk.get("/api/admin/moderation").json()
    assert [i["id"] for i in queue["items"]] == [bad, calm] and queue["items"][0]["words"] == ["gory"] and queue["flagged"] == 1
    assert desk.post("/api/admin/moderation/{}".format(calm), json={"verdict": "fine"}).status_code == 200
    assert desk.post("/api/admin/moderation/{}".format(bad), json={"verdict": "removed"}).status_code == 200
    assert desk.post("/api/admin/moderation/{}".format(bad), json={"verdict": "maybe"}).status_code in (400, 404)
    assert desk.get("/api/admin/moderation").json()["items"] == []
    assert client.app.state.db.one("SELECT 1 FROM generations WHERE id = ?", (bad,)) is None     # gone from the library
    done = desk.get("/api/admin/moderation?show=done").json()["items"]
    assert [(d["verdict"], d["words"], d["by_name"]) for d in done] == [("removed", "gory", "Ada"), ("fine", "", "Ada")]


def test_a_prompt_with_a_listed_word_is_refused_and_its_credits_given_back(client):
    register(client)
    desk = console(client)
    desk.put("/api/admin/queue", json={"paused": True})
    desk.put("/api/admin/moderation/settings", json={"words": ["waves"], "mode": "refuse"})   # JOB's prompt: "She waves."
    credits = client.get("/api/auth/me").json()["credits"]
    refused = post_job(client)
    assert refused.status_code == 400 and "can't be made here" in refused.json()["detail"]
    assert client.get("/api/auth/me").json()["credits"] == credits
    listed = desk.get("/api/admin/moderation?show=refused").json()["items"]
    assert [(r["words"], r["prompt"]) for r in listed] == [("waves", "She waves.")]
    desk.put("/api/admin/moderation/settings", json={"words": ["waves"], "mode": "flag"})       # flagging alone lets it run
    assert post_job(client).status_code == 200
    assert desk.put("/api/admin/moderation/settings", json={"words": [], "mode": "ban"}).status_code == 400
    assert JOB["values"]["100:value"] == "She waves."
