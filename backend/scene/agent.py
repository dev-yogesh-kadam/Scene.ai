"""The agent: turns an instruction into a plan of generations, using a language model served by Ollama.

The model only proposes. Every step is checked against the real workflows and priced here, and
nothing is queued until the user approves the plan in the browser.
"""

import json

import httpx

MAX_STEPS = 6
ORIENTATIONS = ("landscape", "portrait", "square")

SYSTEM = """You are the production assistant inside Scene.ai, a studio for making images and video with AI.
You turn the user's instruction into a short plan of generation jobs. You do not chat.

Rules:
- Each step is one job on one of the listed workflows. Use only those workflow ids. Use the one marked "default" unless
  the instruction names another or needs something only another can do (an image instead of a video, for example).
- Set "orientation" to portrait when the user asks for portrait or vertical, landscape for wide, square for square.
- Steps are independent and cannot use each other's results. For one longer continuous video, use a single
  step with "clips" above 1 on a workflow that allows it, instead of several steps. "duration" is the length of
  each clip, so the video lasts duration times clips: for 15 seconds use duration 5 and clips 3. Otherwise clips is 1.
- Write each "prompt" as a concrete shot: subject, action, setting, camera, light, and sound if it matters. One to three sentences.
- Follow the project brief: keep its style, characters and rules in every prompt.
- "start_from" is the id of a selected item the shot should start on, or 0. Use it only when the user asks to continue or animate a selected item.
- Give each step a short "name" of two to four words.
- Plan as few steps as the instruction needs, never more than {max_steps}. Prefer the default resolution and a 5 second duration unless asked.
- If the instruction is unclear or cannot be done with these workflows, return no steps and say what you need.
- "reply" is one or two plain sentences about the plan. No praise, no filler."""


class AgentError(Exception):
    pass


def reply_format(workflow_ids):
    """The JSON shape the model must answer in."""
    # Every field is required so the model has to decide each one; values a workflow can't take are dropped later.
    step = {"type": "object", "required": ["workflow", "name", "prompt", "resolution", "orientation", "duration", "clips", "start_from"], "properties": {
        "workflow": {"type": "string", "enum": workflow_ids},
        "name": {"type": "string"},
        "prompt": {"type": "string"},
        "resolution": {"type": "integer"},
        "orientation": {"type": "string", "enum": list(ORIENTATIONS)},
        "duration": {"type": "integer"},
        "clips": {"type": "integer"},
        "start_from": {"type": "integer"},
    }}
    return {"type": "object", "required": ["reply", "steps"], "properties": {
        "reply": {"type": "string"}, "steps": {"type": "array", "items": step}}}


class Agent:
    def __init__(self, url, model=""):
        self.url = url.rstrip("/")
        self.model = model
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5))

    async def pick_model(self):
        """The configured model, or the first one the Ollama server has."""
        if self.model:
            return self.model
        try:
            models = (await self.http.get(self.url + "/api/tags")).json().get("models") or []
        except (httpx.HTTPError, ValueError):
            raise AgentError("The agent's model server (Ollama) can't be reached at {}.".format(self.url))
        if not models:
            raise AgentError("The Ollama server has no models. Pull one there, for example: ollama pull qwen3.5:9b")
        return models[0]["name"]

    async def ask(self, system, message, workflow_ids):
        """One question to the model; returns its answer as {"reply": str, "steps": [...]}."""
        model = await self.pick_model()
        try:
            response = await self.http.post(self.url + "/api/chat", json={
                "model": model, "stream": False, "think": False, "format": reply_format(workflow_ids),
                "options": {"temperature": 0.4},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}]})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise AgentError("The agent's model server (Ollama) can't be reached at {}.".format(self.url))
        if body.get("error"):
            raise AgentError("The agent's model failed: {}".format(str(body["error"])[:200]))
        try:
            answer = json.loads(body["message"]["content"])
        except (KeyError, ValueError, TypeError):
            raise AgentError("The agent's model gave an answer that can't be read. Try again.")
        steps = answer.get("steps")
        return {"reply": str(answer.get("reply") or "").strip()[:600], "steps": steps if isinstance(steps, list) else []}


def offer(schema):
    """What the model is told about one workflow, or None if the agent can't use it (it needs files only a person can add)."""
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    first_frame = (schema.get("slots") or {}).get("first_frame")
    if "prompt" not in roles or any(not r["optional"] and r["id"] != first_frame for r in schema["refs"]):
        return None
    needs_start = any(not r["optional"] for r in schema["refs"])
    info = {"id": schema["id"], "title": schema["title"], "makes": schema["id"].split("/", 1)[0], "about": schema["description"][:200]}
    if schema.get("size") or "resolution" in roles:
        info["resolutions"] = schema["resolutions"]
    if schema.get("size"):
        info["default_resolution"] = schema["size"]["resolution"]
        info["orientation"] = "landscape, portrait or square; default " + schema["size"]["orientation"]
    if "duration" in roles:
        info["default_duration_seconds"] = roles["duration"]["default"]
    if schema.get("chain"):
        info["clips"] = "1 to 6, for a longer continuous video"
    if first_frame:
        info["start_from"] = "required" if needs_start else "allowed"
    return info


def question(instruction, brief, offers, selection, default=""):
    offers = sorted(offers, key=lambda o: o["id"] != default)   # the default first; the rest keep their order
    if offers[0]["id"] == default:
        offers[0] = dict(offers[0], default=True)
    parts = ["Project brief:\n" + (brief.strip() or "(none)"),
             "Workflows:\n" + "\n".join(json.dumps(o) for o in offers),
             "Selected items:\n" + ("\n".join(json.dumps(s) for s in selection) or "(none)"),
             "Instruction:\n" + instruction]
    return "\n\n".join(parts)


def settings_for(schema, step, selection_ids, project_id):
    """Turn one proposed step into job settings, keeping only what the workflow really accepts.

    Returns (settings, start item id or None), or None if the step can't run.
    """
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    prompt = str(step.get("prompt") or "").strip()
    if "prompt" not in roles or not prompt:
        return None
    values = {c["id"]: c["default"] for c in schema["controls"]}
    values[roles["prompt"]["id"]] = prompt[:4000]
    if "duration" in roles and isinstance(step.get("duration"), int):
        values[roles["duration"]["id"]] = max(1, min(15, step["duration"]))
    resolution = orientation = None
    if schema.get("size"):
        resolution = step.get("resolution") if step.get("resolution") in schema["resolutions"] else schema["size"]["resolution"]
        orientation = step.get("orientation") if step.get("orientation") in ORIENTATIONS else schema["size"]["orientation"]
    elif "resolution" in roles and step.get("resolution") in schema["resolutions"]:
        values[roles["resolution"]["id"]] = step["resolution"]
    first_frame = (schema.get("slots") or {}).get("first_frame")
    start = step.get("start_from") if first_frame and step.get("start_from") in selection_ids else None
    if any(not r["optional"] for r in schema["refs"]) and not start:
        return None   # this workflow has to start on an item and none was given
    clips = max(1, min(6, step["clips"])) if schema.get("chain") and isinstance(step.get("clips"), int) else 1
    return {"workflow": schema["id"], "name": str(step.get("name") or schema["id"].split("/", 1)[1]).strip()[:80],
            "values": values, "options": {o["id"]: o["default"] for o in schema["options"]},
            "resolution": resolution, "orientation": orientation, "seed_mode": "random", "clips": clips,
            "project_id": project_id, "refs": {}}, start
