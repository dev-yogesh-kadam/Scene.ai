"""Workflow handling for Scene.ai.

Reads ComfyUI workflows in either format (the normal "UI" save or the API export), finds the
controls and reference slots the studio can show, and builds the graph sent to ComfyUI for one job.
An optional "<name>.studio.json" file next to a workflow adds presets, time estimates and hints.
"""

import copy
import json
import os
import re
from pathlib import Path

# Short edge -> long edge for 16:9 / 9:16. All sizes are multiples of 32, as H3 needs.
LONG_EDGE = {480: 864, 720: 1280, 768: 1344, 1080: 1920}
SHORT_EDGE = {480: 480, 720: 736, 768: 768, 1080: 1088}

CONTROL_AFTER_GENERATE = {"fixed", "increment", "decrement", "randomize"}
NOTE_TYPES = {"Note", "MarkdownNote"}
PRIMITIVES = {
    "PrimitiveStringMultiline": "text",
    "PrimitiveString": "string",
    "PrimitiveInt": "int",
    "PrimitiveFloat": "float",
    "PrimitiveBoolean": "bool",
}
# Settings typed straight into a node (no primitive node in front): input name -> (type, role)
KNOWN_INPUTS = {
    "prompt": ("text", "prompt"),
    "text": ("text", "prompt"),
    "width": ("int", "width"),
    "height": ("int", "height"),
    "steps": ("int", None),
    "cfg": ("float", None),
    "seed": ("int", "seed"),
    "noise_seed": ("int", "seed"),
}
REF_CLASS = re.compile(r"(?:Load|Optional)(Image|Video|Audio)")
# Reference slots the app treats specially, found by the loader node's title.
EXTRA_LOADERS = {"image": ("LoadImage", "image"), "audio": ("LoadAudio", "audio")}
SLOT_WORDS = {"first_frame": "first frame", "last_frame": "last frame", "voice_track": "voice track"}
MAX_CLIPS = 8
DURATION_WARNING = {
    "when": {"duration": 15},
    "message": "15 s clips can overflow the GPU memory and get very slow. 5-6 s clips give the best results.",
    "alt": {"label": "Use 5 s instead", "set": {"duration": 5}},
}


class WorkflowError(Exception):
    def __init__(self, message, needs_info=False):
        super().__init__(message)
        self.needs_info = needs_info


def video_size(resolution, orientation):
    short, long_ = SHORT_EDGE[resolution], LONG_EDGE[resolution]
    if orientation == "landscape":
        return long_, short
    if orientation == "portrait":
        return short, long_
    return short, short


def _is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) \
        and isinstance(value[1], int) and not isinstance(value[1], bool)


# ---------------------------------------------------------------- loading

def load_workflow(path, object_info=None, workflow_id=None):
    """Read a workflow file. Returns {"id", "nodes", "info", "profile", "approximate"}.

    "nodes" is the graph in API format, including bypassed nodes. "info" holds what the API format
    can't: each node's mode (0 on, 2 muted, 4 bypassed) and socket types, used by finalize().
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise WorkflowError("Can't read {}: {}".format(path.name, e))
    approximate = False
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        nodes, info, approximate = _from_ui(data, object_info)
    elif isinstance(data, dict) and data and all(isinstance(v, dict) and "class_type" in v for v in data.values()):
        nodes, info = data, {}
    else:
        raise WorkflowError("{} is not a ComfyUI workflow.".format(path.name))

    profile = {}
    sidecar = path.with_name(path.stem + ".studio.json")
    if sidecar.is_file():
        try:
            profile = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError as e:
            raise WorkflowError("Can't read {}: {}".format(sidecar.name, e))
    return {"id": workflow_id or path.stem, "nodes": nodes, "info": info, "profile": profile, "approximate": approximate}


DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"
WIDGET_TYPES = ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")
_UNBOUND = object()


def _from_ui(data, object_info):
    """Turn a ComfyUI save into API format. Subgraphs are unpacked: a node inside the subgraph
    instance 105 gets the id "105:<inner id>", the same naming ComfyUI's own API export uses."""
    subgraphs = {s["id"]: s for s in (data.get("definitions") or {}).get("subgraphs") or []}
    state = {"nodes": {}, "info": {}, "approximate": False, "alias": {}}
    _add_graph(data["nodes"], data.get("links") or [], "", {}, subgraphs, object_info, state, 0)
    # A link to a subgraph's output now points at the node inside that produces it.
    for node in state["nodes"].values():
        for name, value in list(node["inputs"].items()):
            for _ in range(10):
                if not _is_link(value) or (str(value[0]), value[1]) not in state["alias"]:
                    break
                value = state["alias"][(str(value[0]), value[1])]
            if value is None:
                del node["inputs"][name]
            else:
                node["inputs"][name] = value
    return state["nodes"], state["info"], state["approximate"]


def _add_graph(node_list, link_list, prefix, outer, subgraphs, object_info, state, depth):
    """Add one graph's nodes. `outer` maps a subgraph input slot to what feeds it from outside:
    a link, or a plain value set on the subgraph node."""
    if depth > 8:
        raise WorkflowError("This workflow nests subgraphs too deeply.")
    links = {}
    for link in link_list:
        if isinstance(link, dict):
            links[link["id"]] = (link["origin_id"], link["origin_slot"])
        else:
            links[link[0]] = (link[1], link[2])

    for n in node_list:
        nid, ntype = prefix + str(n["id"]), n.get("type")
        if ntype in NOTE_TYPES:
            continue
        if ntype == "PrimitiveNode":  # old-style value node: its value is copied into whatever it feeds
            state["info"][nid] = {"literal": (n.get("widgets_values") or [None])[0]}
            continue
        ins = n.get("inputs") or []
        inputs = {}
        for i in ins:
            if i.get("link") in links:
                origin, slot = links[i["link"]]
                value = outer.get(slot, _UNBOUND) if origin == -10 else [prefix + str(origin), slot]
                if value is not _UNBOUND:
                    inputs[i["name"]] = value

        if ntype in subgraphs:
            if n.get("mode", 0) != 0:
                continue  # a muted or bypassed subgraph contributes nothing
            graph = subgraphs[ntype]
            named = n.get("widgets_values_named")
            if not isinstance(named, dict):  # values are listed in the order of the subgraph's value inputs
                names = [i["name"] for i in graph.get("inputs", []) if i.get("type") in WIDGET_TYPES]
                named = dict(zip(names, n.get("widgets_values") or []))
            bindings = {}
            for index, graph_input in enumerate(graph.get("inputs", [])):
                name = graph_input["name"]
                if name in inputs:
                    bindings[index] = inputs[name]
                elif named.get(name) is not None:
                    bindings[index] = named[name]
            _add_graph(graph.get("nodes", []), graph.get("links", []), nid + ":", bindings, subgraphs, object_info, state, depth + 1)
            for link in graph.get("links", []):
                if isinstance(link, dict) and link["target_id"] == -20:
                    inside = bindings.get(link["origin_slot"]) if link["origin_id"] == -10 \
                        else ["{}:{}".format(nid, link["origin_id"]), link["origin_slot"]]
                    state["alias"][(nid, link["target_slot"])] = inside
            continue

        widgets, exact = _widget_values(n, object_info)
        state["approximate"] = state["approximate"] or not exact
        for name, value in widgets.items():
            inputs.setdefault(name, value)
        state["nodes"][nid] = {"class_type": ntype, "inputs": inputs}
        if n.get("title"):
            state["nodes"][nid]["_meta"] = {"title": n["title"]}
        state["info"][nid] = {
            "mode": n.get("mode", 0),
            "virtual": ntype == "Reroute",
            "ins": [(i["name"], i.get("type")) for i in ins],
            "outs": [o.get("type") for o in n.get("outputs") or []],
        }


def _widget_values(node, object_info):
    """Map a UI node's widgets_values list to input names. Returns (values, exact)."""
    values = node.get("widgets_values")
    if not values:
        return {}, True
    if isinstance(values, dict):
        return {k: v for k, v in values.items() if v is not None}, True
    embedded = [(i["name"], i.get("type")) for i in node.get("inputs") or [] if "widget" in i]
    out, complete = _assign(embedded, values)
    if complete:
        return out, True
    if object_info and node.get("type") in object_info:
        return _assign(_widgets_from_info(object_info[node["type"]]), values)[0], True
    if embedded:
        return out, False
    raise WorkflowError(
        "Can't read the settings of node '{}'. Start ComfyUI so the studio can look the node up, "
        "or export this workflow with Workflow > Export (API).".format(node.get("title") or node.get("type")),
        needs_info=True)


def _assign(widgets, values):
    out, pos = {}, 0
    widgets = list(widgets)
    while widgets:
        name, wtype = widgets.pop(0)
        if pos >= len(values):
            break
        value = values[pos]
        pos += 1
        # Seed-like numbers are followed by a "fixed / randomize" value that is not a node input.
        if wtype in ("INT", "FLOAT") and pos < len(values) and isinstance(values[pos], str) \
                and values[pos] in CONTROL_AFTER_GENERATE:
            pos += 1
        # A dynamic combo is followed by the widgets of the option that is chosen, named "<combo>.<widget>".
        if isinstance(wtype, list):
            chosen = next((o for o in wtype if o.get("key") == value), None)
            if chosen:
                widgets[:0] = _widgets_from_info(chosen, name + ".")
        if value is None or str(wtype).endswith("UPLOAD"):
            continue
        out[name] = value
    return out, not any(v is not None for v in values[pos:])


def _widgets_from_info(node_info, prefix=""):
    """The widgets of a node (or of one dynamic combo option), in order. A dynamic combo's type is its option list."""
    inputs = node_info.get("input") or node_info.get("inputs") or {}
    spec = {}
    for group in ("required", "optional"):
        spec.update(inputs.get(group) or {})
    order = [n for group in ("required", "optional") for n in (node_info.get("input_order", {}).get(group) or [])]
    widgets = []
    for name in order or list(spec):
        entry = spec.get(name)
        if not entry:
            continue
        wtype = entry[0]
        opts = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
        if isinstance(wtype, list):
            wtype = "COMBO"
        if wtype == DYNAMIC_COMBO:
            wtype = opts.get("options") or []
        elif wtype not in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO") or opts.get("forceInput"):
            continue
        widgets.append((prefix + name, wtype))
        if opts.get("image_upload") or opts.get("video_upload") or opts.get("audio_upload"):
            widgets.append(("upload", "IMAGEUPLOAD"))
    return widgets


def finalize(nodes, info, enabled=(), disabled=()):
    """Drop muted and bypassed nodes the way ComfyUI does, passing links through bypassed ones.

    Nodes in `enabled` run even if they were saved bypassed (a reference slot that now has a file).
    Nodes in `disabled` are left out (an optional reference slot with no file).
    """
    enabled = {n for n in enabled if info.get(n, {}).get("mode") == 4}
    changed = True
    while changed:  # a bypassed node fed by a switched-on one is switched on too (e.g. a video splitter)
        changed = False
        for nid, node in nodes.items():
            meta = info.get(nid, {})
            if meta.get("mode") == 4 and not meta.get("virtual") and nid not in enabled \
                    and any(_is_link(v) and str(v[0]) in enabled for v in node["inputs"].values()):
                enabled.add(nid)
                changed = True

    def mode(nid):
        if nid in disabled:
            return 2
        return 0 if nid in enabled else info.get(nid, {}).get("mode", 0)

    def passthrough(nid):
        return info.get(nid, {}).get("virtual") or mode(nid) == 4

    def resolve(link, depth=0):
        src, slot = str(link[0]), link[1]
        meta = info.get(src, {})
        if "literal" in meta:
            return meta["literal"]
        if src not in nodes or mode(src) == 2 or depth > 50:
            return None
        if not passthrough(src):
            return [src, slot]
        outs, ins = meta.get("outs", []), meta.get("ins", [])
        want = outs[slot] if slot < len(outs) else "*"
        for name, typ in ([ins[slot]] if slot < len(ins) else []) + ins:
            upstream = nodes[src]["inputs"].get(name)
            if _is_link(upstream) and (typ == want or "*" in (typ, want)):
                return resolve(upstream, depth + 1)
        return None

    out = {}
    for nid, node in nodes.items():
        if mode(nid) == 2 or passthrough(nid):
            continue
        inputs = {}
        for name, value in node["inputs"].items():
            if _is_link(value):
                value = resolve(value)
                if value is None:
                    continue
            inputs[name] = value
        out[nid] = dict(node, inputs=inputs)
    return out


# ---------------------------------------------------------------- what the studio shows

def _role_from_title(title, ctype):
    t = title.lower()
    if ctype in ("text", "string"):
        return "prompt" if ctype == "text" and "prompt" in t else None
    if ctype == "bool":
        return None
    if "seed" in t:
        return "seed"
    if t.startswith("width"):
        return "width"
    if t.startswith("height"):
        return "height"
    if "resolution" in t:
        return "resolution"
    if "duration" in t or "seconds" in t:
        return "duration"
    return None


def _type_ok(ctype, value):
    if ctype in ("text", "string", "choice"):
        return isinstance(value, str)
    if ctype == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    return isinstance(value, int) if ctype == "int" else isinstance(value, (int, float))


def describe(wf):
    """List the controls, reference slots and presets of a workflow for the web page."""
    nodes, info, profile = wf["nodes"], wf["info"], wf["profile"]
    hide = {str(h) for h in profile.get("hide", [])}
    labels = profile.get("labels", {})
    controls, refs, plain, taken = [], [], [], set()

    def add_control(nid, name, ctype, label, role, extra=None):
        cid = "{}:{}".format(nid, name)
        if nid in hide or cid in hide or any(c["id"] == cid for c in controls):
            return
        if role in taken:
            role = None
        if role:
            taken.add(role)
        control = {"id": cid, "node": nid, "input": name, "type": ctype, "role": role,
                   "label": labels.get(cid, label), "default": nodes[nid]["inputs"].get(name)}
        control.update(extra or {})
        controls.append(control)

    for nid, node in nodes.items():
        meta = info.get(nid, {})
        mode = meta.get("mode", 0)
        if meta.get("virtual") or mode == 2:
            continue
        cls = node["class_type"]
        title = node.get("_meta", {}).get("title") or cls
        ref = REF_CLASS.search(cls)
        if ref:
            kind = ref.group(1).lower()
            name = next((k for k in (kind, "file") if isinstance(node["inputs"].get(k), str)), None)
            if name and nid not in hide:
                rid = "{}:{}".format(nid, name)
                optional_class = "Optional" in cls
                refs.append({
                    "id": rid, "node": nid, "input": name, "kind": kind,
                    "label": labels.get(rid, re.sub(r"\s*-\s*optional$", "", title, flags=re.I)),
                    "optional": optional_class or mode == 4,
                    "empty": "none" if optional_class else None,
                    "default": None if optional_class or mode == 4 else node["inputs"][name],
                })
                continue
        if mode == 4:
            continue
        if cls in PRIMITIVES:
            ctype = PRIMITIVES[cls]
            if _type_ok(ctype, node["inputs"].get("value")):
                add_control(nid, "value", ctype, title, _role_from_title(title, ctype))
        else:
            plain.append((nid, node, cls, title))

    # Settings typed straight into a node come second, so a labelled SEED or PROMPT node wins the role.
    for nid, node, cls, title in plain:
        for name, (ctype, role) in KNOWN_INPUTS.items():
            if name in node["inputs"] and _type_ok(ctype, node["inputs"][name]):
                label = "{} ({})".format(name, cls) if title == cls else "{}: {}".format(title, name)
                add_control(nid, name, ctype, label, role)

    for extra in profile.get("controls", []):
        nid, name = str(extra["node"]), extra["input"]
        if nid in nodes:
            # "primary" keeps the field in view instead of under "More settings".
            add_control(nid, name, extra.get("type", "string"), extra.get("label", name), extra.get("role"),
                        {k: extra[k] for k in ("choices", "primary") if k in extra})

    # Per-workflow adjustments from the presets file.
    for control in controls:
        if control["id"] in profile.get("defaults", {}):
            control["default"] = profile["defaults"][control["id"]]
    for ref_slot in refs:
        if ref_slot["id"] in profile.get("optional_refs", []):   # left out of the job when empty
            ref_slot.update(optional=True, default=None, drop=True)
        elif ref_slot["id"] in profile.get("required_refs", []):  # the job needs a file here
            ref_slot.update(optional=False, default=None, required=True)
    for extra in profile.get("extra_refs", []):  # a slot with no loader node in the workflow: one is added when it is filled
        if str(extra["node"]) in nodes and extra.get("kind") in EXTRA_LOADERS:
            rid = "extra:" + extra["id"]
            refs.append({"id": rid, "node": None, "input": None, "kind": extra["kind"], "label": labels.get(rid, extra["label"]),
                         "optional": True, "empty": None, "default": None, "connect": [str(extra["node"]), extra["input"]]})

    roles = {c["role"]: c for c in controls if c["role"]}
    if ("width" in roles) != ("height" in roles):
        for c in controls:
            if c["role"] in ("width", "height"):
                c["role"] = None
    size = None
    if "width" in roles and "height" in roles:
        w, h = roles["width"]["default"], roles["height"]["default"]
        size = {
            "orientation": "landscape" if w > h else "portrait" if h > w else "square",
            "resolution": min(SHORT_EDGE, key=lambda r: abs(SHORT_EDGE[r] - min(w, h))),
        }

    confirm = profile.get("confirm")
    if confirm is None:
        confirm = [DURATION_WARNING] if "duration" in roles else []
    slots = {}
    for slot, words in SLOT_WORDS.items():
        match = next((r["id"] for r in refs if words in r["label"].lower()), None)
        if match:
            slots[slot] = match
    slots.update(profile.get("slots", {}))
    return {
        "id": wf["id"],
        "title": profile.get("title") or wf["id"].rsplit("/", 1)[-1].replace("_", " "),
        "description": profile.get("description", ""),
        "controls": controls,
        "refs": refs,
        "options": profile.get("options", []),
        "hints": profile.get("hints", []),
        "confirm": confirm,
        "size": size,
        "slots": slots,
        # A long video is made as several clips, each starting on the last frame of the one before.
        "chain": "duration" in roles and "first_frame" in slots and "prompt" in roles,
        "max_clips": MAX_CLIPS,
        "resolutions": sorted(SHORT_EDGE),
        "approximate": wf["approximate"],
    }


def context(schema, settings):
    """The settings that presets, warnings and estimates look at."""
    values = settings.get("values") or {}
    chosen = settings.get("options") or {}
    ctx = {o["id"]: chosen.get(o["id"], o.get("default")) for o in schema["options"]}
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    if "duration" in roles:
        ctx["duration"] = _cast("float", values.get(roles["duration"]["id"], roles["duration"]["default"]))
    if schema["size"]:
        resolution = int(settings.get("resolution") or schema["size"]["resolution"])
        if resolution not in SHORT_EDGE:
            raise WorkflowError("Unknown resolution: {}".format(resolution))
        ctx["resolution"] = resolution
        ctx["orientation"] = settings.get("orientation") or schema["size"]["orientation"]
        ctx["width"], ctx["height"] = video_size(resolution, ctx["orientation"])
    elif "resolution" in roles:
        ctx["resolution"] = _cast("int", values.get(roles["resolution"]["id"], roles["resolution"]["default"]))
    clips = clip_count(schema, settings)
    if clips > 1:
        ctx["clips"] = clips
    return ctx


def clip_count(schema, settings):
    clips = _cast("int", settings.get("clips") or 1)
    if clips < 1 or clips > MAX_CLIPS:
        raise WorkflowError("A long video can have 2 to {} clips.".format(MAX_CLIPS))
    if clips > 1 and not schema["chain"]:
        raise WorkflowError("This workflow can't make chained long videos. It needs a prompt, a duration and a first-frame slot.")
    return clips


def summary(schema, ctx):
    parts = [str(ctx[o["id"]]) for o in schema["options"]]
    if "resolution" in ctx:
        parts.append("{}p{}".format(ctx["resolution"], " " + ctx["orientation"] if "orientation" in ctx else ""))
    if "duration" in ctx:
        clips = "{} × ".format(ctx["clips"]) if ctx.get("clips", 1) > 1 else ""
        parts.append("{}{:g} s".format(clips, ctx["duration"]))
    return " · ".join(parts)


def _cast(ctype, value):
    try:
        if ctype == "int":
            return int(float(value))
        if ctype == "float":
            return float(value)
    except (TypeError, ValueError):
        raise WorkflowError("'{}' is not a number.".format(value))
    if ctype == "bool":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes")
    return "" if value is None else str(value)


def _matches(when, ctx):
    return all(ctx.get(k) in (v if isinstance(v, list) else [v]) for k, v in when.items())


# ---------------------------------------------------------------- building a job

def build_prompt(wf, settings):
    """Return (graph to send to ComfyUI, context incl. the seed that was used)."""
    schema = describe(wf)
    ctx = context(schema, settings)
    nodes = copy.deepcopy(wf["nodes"])
    values = settings.get("values") or {}

    for c in schema["controls"]:
        value = values.get(c["id"], c["default"])
        if c["role"] in ("width", "height"):
            value = ctx[c["role"]]
        elif c["role"] == "seed":
            if settings.get("seed_mode") == "random":
                value = int.from_bytes(os.urandom(6), "big")
            ctx["seed"] = _cast("int", value)
        value = _cast(c["type"], value)
        if c["role"] == "prompt" and not value.strip():
            raise WorkflowError("The prompt is empty.")
        if "choices" in c and value not in c["choices"]:
            raise WorkflowError("'{}' is not a choice for {}.".format(value, c["label"]))
        nodes[c["node"]]["inputs"][c["input"]] = value

    enabled, disabled = set(), set()
    given = settings.get("refs") or {}
    for r in schema["refs"]:
        ref = given.get(r["id"])
        if r.get("connect"):
            if ref:
                loader, loader_input = EXTRA_LOADERS[r["kind"]]
                loader_id = "ref_" + re.sub(r"\W+", "_", r["id"])
                nodes[loader_id] = {"class_type": loader, "inputs": {loader_input: ref["comfy_name"]}}
                nodes[r["connect"][0]]["inputs"][r["connect"][1]] = [loader_id, 0]
        elif ref:
            nodes[r["node"]]["inputs"][r["input"]] = ref["comfy_name"]
            enabled.add(r["node"])
        elif r.get("required"):
            raise WorkflowError("Add a file for \"{}\".".format(r["label"]))
        elif r.get("drop"):
            disabled.add(r["node"])
        elif r["empty"] is not None:
            nodes[r["node"]]["inputs"][r["input"]] = r["empty"]

    for rule in wf["profile"].get("rules", []):
        if not _matches(rule.get("when", {}), ctx):
            continue
        for nid, node in rule.get("add", {}).items():
            nodes[nid] = copy.deepcopy(node)
        for key, value in rule.get("set", {}).items():
            nid, name = key.split(".", 1)  # input names can contain dots, node ids can't
            if nid not in nodes:
                raise WorkflowError("{}.studio.json sets node {}, which is not in the workflow.".format(wf["id"], nid))
            nodes[nid]["inputs"][name] = value
    return finalize(nodes, wf["info"], enabled, disabled), ctx


# ---------------------------------------------------------------- time estimates

def format_estimate(minutes, measured):
    text = "{:.0f} min".format(minutes) if minutes >= 10 else "{:.1f} min".format(minutes)
    if minutes >= 90:
        text = "{:.1f} h".format(minutes / 60)
    return ("about " if measured else "~") + text + ("" if measured else " (est.)")


def estimate(wf, settings, history=()):
    """Expected minutes for one job: from earlier runs with the same settings, else the profile's table."""
    schema = describe(wf)
    ctx = context(schema, settings)
    same = [h["seconds"] for h in history if h.get("workflow") == wf["id"] and h.get("seconds")
            and {k: v for k, v in (h.get("context") or {}).items() if k != "seed"} == ctx]
    if same:
        minutes = sum(same[:3]) / len(same[:3]) / 60
        return {"minutes": minutes, "measured": True, "text": format_estimate(minutes, True) + ", from your earlier runs"}

    table = wf["profile"].get("estimate")
    row = table and table["table"].get("/".join(str(ctx.get(k)) for k in table.get("key", [])))
    duration = ctx.get("duration")
    if not row or not duration:
        return {"minutes": None, "measured": False, "text": "no estimate yet (it appears after the first run)"}
    nearest = min(row, key=lambda d: abs(float(d) - duration))
    minutes, measured = row[nearest]
    if float(nearest) != duration:
        minutes, measured = minutes * duration / float(nearest), False
    if "width" in ctx and table.get("base_pixels"):
        ratio = ctx["width"] * ctx["height"] / float(table["base_pixels"])
        if abs(ratio - 1.0) > 0.02:
            minutes, measured = minutes * ratio ** 1.5, False
    minutes *= ctx.get("clips", 1)
    return {"minutes": minutes, "measured": measured, "text": format_estimate(minutes, measured)}
