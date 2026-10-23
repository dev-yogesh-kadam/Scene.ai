"""A failed job explained to its owner (the canvas keeps it, saying why), and seeds every node takes."""

from scene.comfy import workflows
from test_api import JOB, console, post_job, register


def test_seeds_stay_below_two_to_the_32(client):
    wf = __import__("asyncio").run(client.app.state.catalog.load("video/h3_master"))
    seeds = {workflows.build_prompt(wf, dict(JOB, seed_mode="random", clips=1))[1]["seed"] for _ in range(40)}
    assert all(0 <= s < 2 ** 32 for s in seeds) and len(seeds) > 30
    schema = workflows.describe(wf)
    seed_id = next(c["id"] for c in schema["controls"] if c["role"] == "seed")
    big = 2 ** 40 + 5   # a seed from before seeds were kept small
    assert workflows.build_prompt(wf, dict(JOB, values={**JOB["values"], seed_id: big}, seed_mode="fixed", clips=1))[1]["seed"] == big % 2 ** 32


def test_every_seed_of_a_workflow_gets_the_jobs_seed():
    """Random unless one is given, written into every seed (a hidden one, a second sampler's, the presets file's
    targets), never above 2**32 - 1, and a second seed is not a setting of its own."""
    wf = {"id": "image/x", "approximate": False, "info": {}, "profile": {"hide": ["7"], "seed": {"targets": [["9", "value"]], "min": 5, "max": 9}},
          "nodes": {"1": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "a fox"}, "_meta": {"title": "PROMPT"}},
                    "3": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20}},
                    "4": {"class_type": "SamplerCustom", "inputs": {"noise_seed": 42, "sampling_mode.seed": 0}},
                    "7": {"class_type": "PrimitiveInt", "inputs": {"value": 42}, "_meta": {"title": "SEED"}},
                    "9": {"class_type": "PrimitiveInt", "inputs": {"value": 42}, "_meta": {"title": "Noise"}}}}
    schema = workflows.describe(wf)
    assert schema["seeded"] and [c["id"] for c in schema["controls"] if "seed" in c["id"]] == ["3:seed"]
    for _ in range(20):
        graph, ctx = workflows.build_prompt(wf, {"values": {}})   # no seed_mode: random
        assert 5 <= ctx["seed"] <= 9
        assert {graph["3"]["inputs"]["seed"], graph["4"]["inputs"]["noise_seed"], graph["4"]["inputs"]["sampling_mode.seed"],
                graph["7"]["inputs"]["value"], graph["9"]["inputs"]["value"]} == {ctx["seed"]}
    graph, ctx = workflows.build_prompt(wf, {"values": {}, "seed_mode": "fixed", "seed": 3829104772})   # "Reuse seed"
    assert ctx["seed"] == 3829104772 == graph["9"]["inputs"]["value"] == graph["3"]["inputs"]["seed"]


def test_a_failed_job_says_why_in_plain_words(client):
    register(client)
    console(client).put("/api/admin/queue", json={"paused": True})
    job = post_job(client).json()["id"]
    client.app.state.db.run("UPDATE jobs SET status = 'failed', finished = 1, error = ? WHERE id = ?",
                            ("ComfyUI error in node 'SeedVR2VideoUpscaler': Seed must be between 0 and 2**32 - 1", job))
    failed = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job)
    assert "out of the range" in failed["reason"] and "SeedVR2" not in failed["reason"]
    client.app.state.db.run("UPDATE jobs SET error = 'something nobody has seen' WHERE id = ?", (job,))
    assert next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job)["reason"].startswith("Something went wrong")
    assert client.delete("/api/jobs/" + job).status_code == 200            # Remove: it leaves the list, and the canvas
    assert job not in [j["id"] for j in client.get("/api/jobs").json()["jobs"]]
    assert "graphics memory" not in console(client).get("/api/admin/jobs/" + job).json()["explained"]


def test_a_picture_has_a_small_poster_for_its_thumbnail(client):
    import asyncio
    from scene import media
    me = register(client)
    folder = client.app.state.outputs.folder(me["id"])
    folder.mkdir(parents=True, exist_ok=True)
    asyncio.run(media._ffmpeg("-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=2752x1536", "-frames:v", "1", folder / "big.png"))
    item = client.app.state.db.run(
        "INSERT INTO generations (user_id, workflow, kind, name, filename, settings, context, created) VALUES (?, 'image/x', 'image', 'Big', 'big.png', '{}', '{}', 1)",
        (me["id"],))
    poster = client.get("/api/library/{}/poster".format(item))
    assert poster.status_code == 200 and poster.headers["content-type"] == "image/jpeg"
    assert len(poster.content) < (folder / "big.png").stat().st_size / 3
    again = client.get("/api/library/{}/poster".format(item), headers={"If-None-Match": poster.headers["etag"]})
    assert again.status_code == 304                                       # the browser keeps it
