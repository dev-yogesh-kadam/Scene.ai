import json
from pathlib import Path

from conftest import ROOT
from scene.comfy import workflows

VIDEO = ROOT / "workflows" / "video"
ARCHIVE = ROOT / "workflows" / "archive"
# ComfyUI's definitions of the node types some workflows can't be read without (saved from a real server).
NODES = json.loads((Path(__file__).parent / "fixtures" / "node_definitions.json").read_text(encoding="utf-8"))


def test_ui_workflow_converts_to_the_api_export():
    """A normal ComfyUI save must turn into the same graph ComfyUI's own API export gives."""
    ui = workflows.load_workflow(ARCHIVE / "h3_director_draft_backup.json")
    mine = workflows.finalize(ui["nodes"], ui["info"])
    exported = json.loads((ARCHIVE / "h3_director_draft_api.json").read_text(encoding="utf-8"))
    assert set(mine) == set(exported)
    for node_id, node in exported.items():
        for name, value in node["inputs"].items():
            if (node_id, name) != ("100", "value"):  # the prompt text differs between the two files
                assert mine[node_id]["inputs"][name] == value, (node_id, name)


def test_h3_director_controls_and_reference_slots():
    schema = workflows.describe(workflows.load_workflow(VIDEO / "h3_director.json"))
    roles = {c["role"] for c in schema["controls"]}
    assert {"prompt", "duration", "width", "height", "seed"} <= roles
    assert len(schema["refs"]) == 11 and all(r["optional"] for r in schema["refs"])
    assert [o["id"] for o in schema["options"]] == ["mode", "quality"]


def build(mode, quality, **extra):
    wf = workflows.load_workflow(VIDEO / "h3_director.json")
    settings = {"values": {"100:value": "She waves."}, "options": {"mode": mode, "quality": quality}, **extra}
    return workflows.build_prompt(wf, settings)


def test_low_quality_uses_the_draft_model_and_vsa_only_in_fast_mode():
    fast, _ = build("fast", "low")
    normal, _ = build("normal", "low")
    assert fast["108"]["inputs"]["value"] is False and fast["109"]["inputs"]["value"] is True
    assert normal["109"]["inputs"]["value"] is False
    assert "400" not in fast


def test_fast_medium_and_high_add_sparse_attention():
    medium, _ = build("fast", "medium")
    high, _ = build("normal", "high")
    assert medium["105"]["inputs"]["value"] == 20 and medium["27"]["inputs"]["on_true"] == ["400", 0]
    assert high["105"]["inputs"]["value"] == 40 and "400" not in high


def test_size_seed_and_references():
    graph, ctx = build("fast", "low", resolution=720, orientation="portrait", seed_mode="random",
                       refs={"201:image": {"comfy_name": "scene_abc_face.png"}})
    assert (graph["103"]["inputs"]["value"], graph["104"]["inputs"]["value"]) == (736, 1280)
    assert graph["106"]["inputs"]["value"] == ctx["seed"] != 42
    assert graph["201"]["inputs"]["image"] == "scene_abc_face.png"
    assert graph["202"]["inputs"]["image"] == "none"


def test_a_filled_slot_switches_on_a_bypassed_loader():
    wf = workflows.load_workflow(VIDEO / "MiniMax_H3_AI_Influencer.json")
    asked = {"values": {"1:value": "She dances."}, "refs": {"21:image": {"comfy_name": "scene_x_face.png"}}}
    without, _ = workflows.build_prompt(wf, asked)
    with_video, _ = workflows.build_prompt(wf, dict(asked, refs=dict(asked["refs"], **{"25:file": {"comfy_name": "scene_x_move.mp4"}})))
    assert "25" not in without
    assert "25" in with_video and "27" in with_video  # the loader and the splitter behind it


def test_estimates_come_from_the_table_then_from_history():
    wf = workflows.load_workflow(VIDEO / "h3_director.json", workflow_id="video/h3_director")
    settings = {"options": {"mode": "normal", "quality": "high"}, "values": {"102:value": 10}}
    assert workflows.estimate(wf, settings)["minutes"] == 27.0
    ctx = workflows.context(workflows.describe(wf), settings)
    history = [{"workflow": "video/h3_director", "context": dict(ctx, seed=1), "seconds": 600}]
    assert workflows.estimate(wf, settings, history)["minutes"] == 10.0


def test_chain_slots_are_found_and_clip_count_is_in_the_summary():
    wf = workflows.load_workflow(VIDEO / "h3_director.json")
    schema = workflows.describe(wf)
    assert schema["chain"] and schema["slots"] == {"first_frame": "209:image", "last_frame": "210:image", "voice_track": "211:audio"}
    ctx = workflows.context(schema, {"clips": 3})
    assert ctx["clips"] == 3 and workflows.summary(schema, ctx).endswith("3 × 5 s")
    assert "clips" not in workflows.context(schema, {})


def test_media_join_and_last_frame(tmp_path):
    """Two generated test clips are joined; the shared frame between them is dropped."""
    import asyncio
    from scene import media

    async def go():
        clips = []
        for i, colour in enumerate(("red", "blue")):
            clip = tmp_path / "clip{}.mp4".format(i)
            await media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color={}:s=64x64:r=24:d=1".format(colour),
                                "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest", "-pix_fmt", "yuv420p", clip)
            clips.append(clip)
        frame = await media.last_frame(clips[0], tmp_path / "last.png")
        joined = await media.join(clips, tmp_path / "joined.mp4")
        piece = await media.cut_audio(clips[0], 0.25, 0.5, tmp_path / "piece.wav")
        return frame, await media.probe(joined), await media.probe(piece)

    frame, joined, piece = asyncio.run(go())
    assert frame.stat().st_size > 0
    assert joined["audio"] and 1.9 < joined["seconds"] < 2.05   # 2 s minus the one shared frame
    assert 0.45 < piece["seconds"] < 0.55


def test_a_subgraph_is_unpacked_into_its_inner_nodes():
    """The image-to-video template keeps its whole pipeline inside one subgraph node (id 105)."""
    wf = workflows.load_workflow(VIDEO / "video_minimax_h3_i2v.json", NODES)
    nodes = wf["nodes"]
    assert "105" not in nodes and nodes["105:104"]["class_type"] == "MiniMaxH3ImageToVideo"
    inside = nodes["105:104"]["inputs"]
    assert inside["first_frame"] == ["114", 0] and inside["width"] == ["115", 0]      # fed from outside the subgraph
    assert inside["prompt"].startswith("Create a")                                    # a value set on the subgraph node
    assert nodes["92"]["inputs"]["video"] == ["105:91", 0]                            # the subgraph's output
    assert nodes["105:15"]["inputs"]["noise_seed"] == 757358688076805


def test_a_dynamic_combo_keeps_the_settings_of_its_chosen_option():
    """SaveVideo's "format" is a dynamic combo: its codec is sent as "format.codec". Without it the render fails at the save."""
    saved = workflows.load_workflow(VIDEO / "video_minimax_h3_i2v.json", NODES)["nodes"]["92"]["inputs"]
    assert saved["format"] == "auto" and saved["format.codec"] == "auto" and saved["filename_prefix"] == "video/MiniMax_H3"
    widgets = [("format", [{"key": "mp4", "inputs": {"required": {"crf": ["FLOAT", {}]}}}, {"key": "auto", "inputs": {"required": {}}}]), ("after", "INT")]
    assert workflows._assign(widgets, ["mp4", 16, 3])[0] == {"format": "mp4", "format.crf": 16, "after": 3}
    assert workflows._assign(widgets, ["auto", 3])[0] == {"format": "auto", "after": 3}


def test_presets_add_optional_and_extra_reference_slots():
    wf = workflows.load_workflow(VIDEO / "video_minimax_h3_i2v.json", NODES)
    schema = workflows.describe(wf)
    assert schema["chain"] and schema["slots"] == {"first_frame": "114:image", "last_frame": "extra:last_frame"}
    values = {"105:104:prompt": "She waves."}
    text_only, _ = workflows.build_prompt(wf, {"values": values, "options": {"speed": "turbo"}})
    assert "114" not in text_only and "first_frame" not in text_only["105:104"]["inputs"]
    assert text_only["105:126"]["inputs"]["value"] is True and text_only["105:111"]["inputs"]["value"] == 5.0
    both, _ = workflows.build_prompt(wf, {"values": values, "refs": {
        "114:image": {"comfy_name": "scene_a.png"}, "extra:last_frame": {"comfy_name": "scene_b.png"}}})
    assert both["114"]["inputs"]["image"] == "scene_a.png"
    assert both[both["105:104"]["inputs"]["last_frame"][0]] == {"class_type": "LoadImage", "inputs": {"image": "scene_b.png"}}


def test_a_required_reference_slot_must_be_filled():
    import pytest
    wf = workflows.load_workflow(VIDEO / "video_minimax_h3_r2v.json", NODES)
    with pytest.raises(workflows.WorkflowError, match="Add a file"):
        workflows.build_prompt(wf, {"values": {"138:value": "A dragon lands."}})
    graph, _ = workflows.build_prompt(wf, {"values": {"138:value": "A dragon lands."}, "refs": {"137:image": {"comfy_name": "scene_a.png"}}})
    assert "139" not in graph and "ref_images.ref_image_1" not in graph["136"]["inputs"]


# ---------------------------------------------------------------- h3_master, the one MiniMax H3 workflow

def master(**settings):
    wf = workflows.load_workflow(VIDEO / "h3_master.json", NODES, "video/h3_master")
    return workflows.build_prompt(wf, {"values": {"100:value": "She waves."}, **settings})


def test_every_video_workflow_has_a_presets_file_and_only_drafts_stay_archived():
    flows = sorted(p.stem for p in VIDEO.glob("*.json") if not p.name.endswith(".studio.json"))
    assert len(flows) == 11 and "h3_master" in flows and "h3_chunk" in flows
    for name in flows:
        profile = json.loads((VIDEO / (name + ".studio.json")).read_text(encoding="utf-8"))
        assert profile["title"] and not profile.get("replaces"), name
    assert sorted(p.name for p in ARCHIVE.glob("*.json")) == [
        "ai_influencer_seedvr2_backup.json", "h3_director_draft_api.json", "h3_director_draft_backup.json"]


def influencer(name, **settings):
    wf = workflows.load_workflow(VIDEO / (name + ".json"), NODES, "video/" + name)
    return workflows.build_prompt(wf, settings)[0]


def test_ai_influencer_voice_track_is_a_choice():
    face = {"1:image": {"comfy_name": "scene_x_face.png"}}
    off = influencer("ai_influencer", values={"100:value": "She talks."}, refs=face)
    # off: the switch takes the plain conditioning and the voice loader is left out, so no file is needed
    assert off["130"]["inputs"]["value"] is False and off["72"]["inputs"]["on_true"] == ["34", 0] and "70" not in off
    import pytest
    with pytest.raises(workflows.WorkflowError, match="Voice track"):
        influencer("ai_influencer", values={"100:value": "She talks."}, options={"voice": "on"}, refs=face)
    on = influencer("ai_influencer", values={"100:value": "She talks."}, options={"voice": "on"},
                    refs=dict(face, **{"70:audio": {"comfy_name": "scene_x_voice.wav"}}))
    assert on["130"]["inputs"]["value"] is True and on["70"]["inputs"]["audio"] == "scene_x_voice.wav" and on["71"]["inputs"]["audio"] == ["70", 0]


def test_a_required_slot_of_the_other_mode_is_not_asked_for():
    # first-frame mode does not read the character image, which reference mode requires
    graph = influencer("MiniMax_H3_AI_Influencer", values={"1:value": "She dances."}, options={"engine": "first_frame"})
    assert graph["5"]["inputs"]["value"] is False and "21" not in graph
    import pytest
    with pytest.raises(workflows.WorkflowError, match="Character 1"):
        influencer("MiniMax_H3_AI_Influencer", values={"1:value": "She dances."}, options={"engine": "reference"})


def test_h3_master_speed_and_quality_set_the_three_switches():
    table = {("fast", "low"): (False, None, True), ("fast", "medium"): (True, 20, True), ("fast", "high"): (True, 40, True),
             ("normal", "low"): (False, None, False), ("normal", "medium"): (True, 20, False), ("normal", "high"): (True, 40, False)}
    for engine in ("reference", "first_frame"):
        for (mode, quality), (final, steps, fast) in table.items():
            graph, _ = master(options={"engine": engine, "mode": mode, "quality": quality})
            value = {node: graph[node]["inputs"]["value"] for node in ("105", "107", "108", "109")}
            assert (value["107"], value["108"], value["109"]) == (engine == "reference", final, fast), (engine, mode, quality)
            assert steps is None or value["105"] == steps
    import pytest
    with pytest.raises(workflows.WorkflowError, match="not a choice for Quality"):
        master(options={"quality": "ultra"})


def test_h3_master_form_values_reach_their_nodes():
    graph, ctx = master(name="Rooftop: take 2", resolution=1080, orientation="portrait", seed_mode="random",
                        values={"100:value": "She waves.", "102:value": 10, "144:sparsity": 0.5, "6:ref_image_size": "max"})
    inputs = {node: graph[node]["inputs"] for node in graph}
    assert inputs["100"]["value"] == "She waves." and inputs["102"]["value"] == 10.0 and isinstance(inputs["102"]["value"], float)
    assert (inputs["103"]["value"], inputs["104"]["value"]) == (1088, 1920)
    assert inputs["106"]["value"] == ctx["seed"] >= 0 and ctx["seed"] != 42            # random unless a seed is fixed
    assert inputs["144"]["sparsity"] == 0.5 and inputs["6"]["ref_image_size"] == "max"
    assert inputs["16"]["filename_prefix"] == "video/Rooftop_take_2"                    # filed on the render server under the job's name
    assert master(seed_mode="fixed")[0]["106"]["inputs"]["value"] == 42 and master()[0]["144"]["inputs"]["sparsity"] == 0.6
    sizes = {480: (864, 480), 720: (1280, 736), 768: (1344, 768), 1080: (1920, 1088)}
    for resolution, (long_edge, short_edge) in sizes.items():
        assert workflows.video_size(resolution, "landscape") == (long_edge, short_edge)
        assert workflows.video_size(resolution, "portrait") == (short_edge, long_edge)
        assert workflows.video_size(resolution, "square") == (short_edge, short_edge)
        assert long_edge % 32 == 0 and short_edge % 32 == 0


def test_h3_master_first_frame_mode_leaves_the_reference_slots_empty():
    refs = {"201:image": {"comfy_name": "scene_face.png"}, "207:video": {"comfy_name": "scene_move.mp4"}, "208:audio": {"comfy_name": "scene_voice.wav"},
            "209:image": {"comfy_name": "scene_first.png"}, "211:audio": {"comfy_name": "scene_track.wav"}}
    slots = {"201": "image", "202": "image", "203": "image", "204": "image", "205": "image", "206": "image", "207": "video",
             "208": "audio", "209": "image", "210": "image", "211": "audio"}
    for engine, filled in (("reference", {"201", "207", "208", "209", "211"}), ("first_frame", {"209", "211"})):
        graph, _ = master(options={"engine": engine}, refs=refs)
        for node, key in slots.items():   # a slot with no file, or one the mode does not read, is the word "none"
            given = refs.get("{}:{}".format(node, key), {}).get("comfy_name")
            assert graph[node]["inputs"][key] == (given if node in filled else "none"), (engine, node)
    schema = workflows.describe(workflows.load_workflow(VIDEO / "h3_master.json", NODES))
    assert workflows.refs_in_use(schema, {"options": {"engine": "first_frame"}}) == {"209:image", "210:image", "211:audio"}
    assert len(workflows.refs_in_use(schema, {})) == 11                                # reference mode is the default
