"""The agent decides a shot's length, shape, resolution and the workflow's own settings; the server keeps what is allowed."""

from test_api import register

SHOT = {"tool": "generate", "workflow": "video/h3_master", "uses": [], "clips": 1, "start_from": 0, "after": 0}


def plan(client, monkeypatch, *steps, instruction="an ad for Reels"):
    async def fake_ask(system, message, workflow_ids, history=(), model=None):
        plan.asked = message
        return {"reply": "Planned.", "steps": list(steps)}
    monkeypatch.setattr(client.app.state.agent, "ask", fake_ask)
    return client.post("/api/agent/plan", json={"instruction": instruction}).json()["steps"]


MUSIC = {"tool": "generate", "workflow": "audio/audio_minimax_music_3", "name": "Music", "prompt": "Upbeat pop.", "uses": [], "clips": 1,
         "start_from": 0, "after": 0, "duration": 300, "choices": [{"setting": "37:13:max_duration", "value": "300"}]}


def test_music_lasts_what_was_asked_or_what_the_shots_add_up_to_not_what_the_model_wants(client, monkeypatch):
    register(client)
    # The model asks for the longest song; the user named 25 seconds, so it is 30, the shortest length that covers it.
    song = plan(client, monkeypatch, MUSIC, instruction="Make upbeat music for a 25 second ad.")[0]
    assert song["settings"]["values"]["37:13:max_duration"] == 30 and song["credits"] == 150    # 30 s at 5 cr a second
    # Music for the shots of the same plan: 7 + 8 seconds of video, so 30 seconds of music.
    steps = plan(client, monkeypatch, dict(SHOT, name="One", prompt="A pour.", duration=7), dict(SHOT, name="Two", prompt="A smile.", duration=8),
                 MUSIC, instruction="two shots and music for them")
    assert steps[2]["settings"]["values"]["37:13:max_duration"] == 30
    # Nothing to go by: the model's choice stands.
    assert plan(client, monkeypatch, MUSIC, instruction="a long ambient piece")[0]["settings"]["values"]["37:13:max_duration"] == 300


def test_the_agent_sets_length_shape_resolution_and_the_workflows_own_settings(client, monkeypatch):
    register(client)
    step = plan(client, monkeypatch, dict(SHOT, name="Pour", prompt="Coffee pours into a cup.", duration=7, orientation="portrait",
                                          resolution=480, why="7 s for the pour; portrait for Reels; a draft",
                                          choices=[{"setting": "quality", "value": "high"}, {"setting": "mode", "value": "normal"},
                                                   {"setting": "engine", "value": "first_frame"}, {"setting": "quality", "value": "ultra"},
                                                   {"setting": "made_up", "value": "x"}, "junk"]))[0]
    settings = step["settings"]
    assert settings["values"]["102:value"] == 7 and settings["orientation"] == "portrait" and settings["resolution"] == 480
    # "ultra" and the made-up setting are ignored, and first-frame mode needs a picture to start on, which this shot has not
    assert settings["options"] == {"engine": "reference", "mode": "normal", "quality": "high"}
    assert step["why"] == "7 s for the pour; portrait for Reels; a draft"
    assert "7 s" in step["facts"]
    # What the model was told: the length it may choose and the settings it may set, with what each value means.
    assert '"duration_seconds": "4 to 15' in plan.asked and '"setting": "quality"' in plan.asked and "40 steps" in plan.asked


def test_a_shot_is_long_enough_for_its_dialogue_and_stays_within_4_to_15_seconds(client, monkeypatch):
    register(client)
    words = "Every morning I open this shop before the town wakes up, and the first cup is always mine to enjoy"   # 20 words
    steps = plan(client, monkeypatch,
                 dict(SHOT, name="Talk", prompt='She smiles. Audio: "{}"'.format(words), duration=4),
                 dict(SHOT, name="Blink", prompt="A quick glance.", duration=2),
                 dict(SHOT, name="Epic", prompt="A long crane move.", duration=99, resolution=1080),
                 dict(SHOT, name="Hero", prompt="The cup on the counter.", duration=8, resolution=1080))
    lengths = {s["name"]: s["settings"]["values"]["102:value"] for s in steps}
    assert lengths == {"Talk": 10, "Blink": 4, "Epic": 15, "Hero": 8}   # 20 words need 10 s; 2 s is raised to 4; 99 is cut to 15
    sizes = {s["name"]: s["settings"]["resolution"] for s in steps}
    assert sizes["Epic"] == 768 and sizes["Hero"] == 1080    # a shot over 10 s is not made at the largest size


def test_the_settings_offered_include_choice_lists_and_unknown_values_are_ignored():
    from scene import agent
    schema = {"options": [{"id": "quality", "label": "Quality", "default": "medium",
                           "choices": [{"id": "low", "label": "Low", "hint": "a draft"}, {"id": "high", "label": "High"}]}],
              "controls": [{"id": "37:13:max_duration", "role": None, "label": "Length in seconds", "default": 60, "choices": [30, 60, 120]},
                           {"id": "1:text", "role": "prompt", "label": "Prompt", "default": "", "choices": None}]}
    offered = agent.choosable_settings(schema)
    assert [s["setting"] for s in offered] == ["quality", "37:13:max_duration"]
    assert offered[0]["choices"][0] == {"value": "low", "means": "a draft"} and offered[1]["choices"][2] == {"value": "120"}
    settings = {"options": {"quality": "medium"}, "values": {"37:13:max_duration": 60}}
    agent.apply_choices(schema, settings, [{"setting": "37:13:max_duration", "value": "120"}, {"setting": "37:13:max_duration", "value": "45"},
                                           {"setting": "quality", "value": "low"}, {"setting": "1:text", "value": "sneaky"}])
    assert settings == {"options": {"quality": "low"}, "values": {"37:13:max_duration": 120}}   # a number stays a number
    # A setting named by its label is found too, but an id always wins over a label ("mode" is the speed, not the Mode).
    both = dict(schema, options=[{"id": "mode", "label": "Speed", "choices": [{"id": "fast"}, {"id": "normal"}]},
                                 {"id": "engine", "label": "Mode", "choices": [{"id": "reference"}, {"id": "first_frame"}]}])
    named = {"options": {"mode": "fast", "engine": "reference"}, "values": {}}
    agent.apply_choices(both, named, [{"setting": "Speed", "value": "normal"}, {"setting": "mode", "value": "first_frame"}])
    assert named["options"] == {"mode": "normal", "engine": "reference"}
    assert agent.spoken_seconds('Audio: "Hello there."') == 3 and agent.spoken_seconds("No one speaks.") == 0
    assert agent.spoken_seconds("She says: 'This is the best latte in town, I come here every morning before work'.") == 8
    assert agent.spoken_seconds("The dog's bowl is empty and it doesn't care.") == 0      # apostrophes, not quotes


def test_only_the_local_models_named_in_the_settings_are_offered():
    import asyncio
    import httpx
    from scene.agent import Agent
    tags = {"models": [{"name": "qwen3.5:9b", "size": 6}, {"name": "qwen3.6:35b", "size": 23}, {"name": "nemotron3:33b", "size": 26},
                       {"name": "nomic-embed-text:latest", "size": 1}]}
    for local, offered in (("", ["qwen3.5:9b", "qwen3.6:35b", "nemotron3:33b", "nomic-embed-text:latest"]),
                           ("qwen3.6:35b, nemotron3:33b", ["qwen3.6:35b", "nemotron3:33b"])):
        brain = Agent("http://ollama", local=local)
        brain.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=tags)))
        assert asyncio.run(brain.models()) == offered
    # A busy hosted model falls back to the smallest local model offered: with the list, never the embedding model.
    assert min(brain.sizes, key=brain.sizes.get) == "qwen3.6:35b"


def test_a_reply_that_says_it_is_making_something_without_a_plan_is_caught():
    from scene import agent
    assert agent.claims_work("generate", "Generating the 480p clip now.")
    assert agent.claims_work("approve", "I have generated the low-quality clip.")
    assert not agent.claims_work("what did you generate last time?", "I generated a car clip.")   # a question is answered in words
    assert not agent.claims_work("hi", "Hello. What are we making?")
    # the history tells the model that such a reply made nothing; a plain answer is left as it was
    turns = agent.past_turns([{"instruction": "start", "reply": "Generating it now.", "steps": []},
                              {"instruction": "hi", "reply": "Hello.", "steps": []}])
    assert turns[1]["content"].endswith("(No plan with this reply: nothing was made or queued.)")
    assert turns[3]["content"] == "Hello."


def test_a_bare_go_ahead_after_a_reply_without_a_plan_carries_that_reply():
    from scene import agent
    history = [{"instruction": "a pet ad", "reply": "A puppy runs across a lawn chasing a red ball.", "steps": []}]
    for said in ("start", "approve", "generate", "go ahead", "generate your own", "from scratch"):
        assert "A puppy runs across a lawn" in agent.carry_over(said, history), said
    assert agent.carry_over("make the dog brown and add rain to the whole scene please", history).startswith("make the dog")
    assert agent.carry_over("start", [dict(history[0], steps=["Puppy"])]) == "start"   # after a plan, Approve is the button


def test_an_empty_section_of_the_prompt_structure_is_left_out():
    from scene import agent
    assert agent.EMPTY_SECTION.match("REFERENCES:") and agent.EMPTY_SECTION.match("LIGHT AND LOOK: none")
    assert not agent.EMPTY_SECTION.match("SCENE CONTEXT: a fox in a den.") and not agent.EMPTY_SECTION.match("She says: ")
