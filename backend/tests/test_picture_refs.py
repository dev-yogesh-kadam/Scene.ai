"""Picture references of the image workflows the ComfyUI agent hands over (an API export, its sidecar and its UI save
in workflows/image): the catalog reads them from their sidecars, a job carries exactly the references given (an empty reference node is never sent),
and the prompt's names for them come from each model's hints."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from scene.catalog import Catalog
from scene.comfy import workflows
from scene.comfy.client import Comfy

ROOT = Path(__file__).resolve().parents[2] / "workflows"
WITH_REFS = {   # workflow: (most references, the first one required, REF 1's and REF 2's names in a prompt)
    "image_t2i_flux2_klein_9b": (16, False, ["image 1", "image 2"]),
    "image_t2i_flux2_dev": (16, False, ["image 1", "image 2"]), "image_t2i_flux3_klein": (16, False, ["<ref_image_0>", "<ref_image_1>"]),
    "image_t2i_qwen_image_21": (16, False, ["<image1>", "<image2>"]),
    "image_t2i_krea2_turbo": (1, False, ["the reference"]),
}
WORDS_ONLY = ["image_t2i_hunyuan_image_21"]


def catalog(directory=ROOT):
    return Catalog(directory, Comfy(lambda: "http://127.0.0.1:9"), None)


def load(name):
    return asyncio.run(catalog().load("image/" + name))


def place(slot):   # a list of references (ref_1, ref_2 ...) in its order, else by node
    return slot.get("order") or float(slot["node"])


def loader(slot):   # the node that carries a slot's file: the slot's own, or the one added for a list's reference
    return slot["id"] if slot.get("order") else slot["node"]


def test_the_picture_workflows_run_from_their_api_export():
    files = catalog().files()
    for name in [*WITH_REFS, *WORDS_ONLY]:
        path = files["image/" + name]
        assert path == ROOT / "image" / (name + ".json") and "class_type" in path.read_text(encoding="utf-8"), name   # an API export
        assert path.with_name(name + ".ui.json").is_file() and path.with_name(name + ".studio.json").is_file(), name
    assert not any(i.endswith(".ui") or i.startswith(("archive/", "reports/")) for i in files)   # never offered
    wf = load("image_t2i_flux2_klein_9b")
    assert wf["profile"]["title"].startswith("Text to Image: FLUX.2 Klein 9B")   # its sidecar


def test_a_new_workflow_shows_on_the_next_look_and_its_ui_save_is_not_one(tmp_path):
    (tmp_path / "image").mkdir()
    assert catalog(tmp_path).files() == {}
    for ending in (".json", ".studio.json", ".ui.json"):
        shutil.copy(ROOT / "image" / ("image_t2i_hunyuan_image_21" + ending), tmp_path / "image")
    found = catalog(tmp_path).files()
    assert found == {"image/image_t2i_hunyuan_image_21": tmp_path / "image" / "image_t2i_hunyuan_image_21.json"}
    assert catalog(tmp_path).sidecar_of(found["image/image_t2i_hunyuan_image_21"]) == tmp_path / "image" / "image_t2i_hunyuan_image_21.studio.json"


@pytest.mark.parametrize("name", list(WITH_REFS))
def test_a_job_carries_exactly_the_references_given(name):
    most, required, names = WITH_REFS[name]
    wf = load(name)
    schema = workflows.describe(wf)
    slots = sorted((r for r in schema["refs"] if r["kind"] == "image"), key=place)
    assert len(slots) == most and bool(slots[0].get("required")) == required
    naming = schema["ref_naming"]
    assert naming["tokens"][:2] == names[:2] and (naming["unique"] or most == 1)
    prompt = next(c["id"] for c in schema["controls"] if c["role"] == "prompt")
    for count in sorted({0 if not required else 1, 1, most}):
        given = {s["id"]: {"comfy_name": "ref{}.png".format(i + 1), "name": "r"} for i, s in enumerate(slots[:count])}
        graph, _ = workflows.build_prompt(wf, {"workflow": wf["id"], "values": {prompt: "a test"}, "options": {}, "refs": given})
        sent = {loader(s) for s in slots if loader(s) in graph}
        assert sent == {loader(s) for s in slots[:count]}, (name, count)   # an empty reference node is never sent
        assert all(graph[loader(s)]["inputs"]["image"] == given[s["id"]]["comfy_name"] for s in slots[:count])
        for i, s in enumerate(slots):   # a list's reference is linked to its input; an empty one is not
            if s.get("connect"):
                target, name_in = s["connect"]
                assert graph[target]["inputs"].get(name_in) == ([s["id"], 0] if i < count else None), (name, count, s["id"])
        dangling = [(nid, k) for nid, node in graph.items() for k, v in node["inputs"].items()
                    if isinstance(v, list) and len(v) == 2 and str(v[0]) not in graph]
        assert not dangling, (name, count, dangling)
    if required:
        with pytest.raises(workflows.WorkflowError, match="Add a file"):
            workflows.build_prompt(wf, {"workflow": wf["id"], "values": {prompt: "a test"}, "options": {}, "refs": {}})


def test_a_list_of_references_is_sent_with_no_gaps():
    """FLUX: ref_1 -> 210 images.image0, ref_2 -> images.image1. Qwen counts from 1: images.image_1. Files given in boxes
    1 and 3 go in as the first and the second."""
    for name, target, first, second in (("image_t2i_flux2_klein_9b", "210", "images.image0", "images.image1"),
                                         ("image_t2i_qwen_image_21", "501", "images.image_1", "images.image_2")):
        wf = load(name)
        schema = workflows.describe(wf)
        prompt = next(c["id"] for c in schema["controls"] if c["role"] == "prompt")
        graph, _ = workflows.build_prompt(wf, {"workflow": wf["id"], "values": {prompt: "a test"}, "options": {},
                                               "refs": {"ref_1": {"comfy_name": "a.png"}, "ref_3": {"comfy_name": "c.png"}}})
        assert graph["ref_1"] == {"class_type": "LoadImage", "inputs": {"image": "a.png"}}
        assert graph["ref_2"] == {"class_type": "LoadImage", "inputs": {"image": "c.png"}} and "ref_3" not in graph
        linked = {k: v for k, v in graph[target]["inputs"].items() if k.startswith("images.")}
        assert linked == {first: ["ref_1", 0], second: ["ref_2", 0]}, name


@pytest.mark.parametrize("name", WORDS_ONLY)
def test_a_words_only_model_has_no_references(name):
    schema = workflows.describe(load(name))
    assert not [r for r in schema["refs"] if r["kind"] == "image"] and schema["ref_naming"]["tokens"] == []


def test_a_model_with_a_research_license_says_so():
    assert workflows.describe(load("image_t2i_qwen_image_21"))["ref_naming"]["license"] == "Research license: not for monetized content"
    assert workflows.describe(load("image_t2i_flux2_klein_9b"))["ref_naming"]["license"] == ""


def test_the_list_says_how_many_references_each_model_takes():
    listed = {w["id"]: w for w in asyncio.run(catalog().listing())}
    for name, (most, _, _) in WITH_REFS.items():
        assert listed["image/" + name]["picture_refs"] == most, name
    assert all(listed["image/" + name]["picture_refs"] == 0 for name in WORDS_ONLY)
