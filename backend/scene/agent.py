"""The agent: turns an instruction into a plan of generations, using a language model served by Ollama.

The model only proposes. Every step is checked against the real workflows and priced here, and
nothing is queued until the user approves the plan in the browser.
"""

import asyncio
import json
import math
import re

import httpx

from . import cast, sequence

MAX_STEPS = 6
MAX_HISTORY = 6     # earlier turns of the conversation sent along with a new message
ORIENTATIONS = ("landscape", "portrait", "square")
EDIT_TOOLS = ("trim", "split", "join")   # done with ffmpeg on videos the user already has: no GPU, no credits
MAX_PARTS = 6
MOTION_TOOLS = ("motion", "overlay")     # drawn by HyperFrames from words: no GPU, priced by the second
SOUND_TOOL = "sound"                     # a sound put on a video with ffmpeg: no GPU, no credits
OVERLAY_KINDS = ("lower_third",)         # a scene kind only an overlay has
CAPTION_CONTEXT = 16384   # tokens: the caption instructions of a workflow run to several thousand

SYSTEM = """You are the production assistant inside Scene.ai, a studio for making images and video with AI.
You do two things: you talk with the user, and you turn what they want to make into a short plan of generation jobs.

Talking:
- When the user greets you, asks a question, wants ideas, or is still working out what to make, answer like a helpful
  colleague in "reply" and return no steps. Be warm and brief: one to four sentences.
- You can help with shot ideas, prompts, story beats, and how Scene.ai works (workflows, the brief, clips, cost).
- Plan steps only when the user asks for something to be made. If it is not clear yet what they want to see, ask.
- The conversation so far is given to you, with your own replies marked "You". Use it: "make that one portrait"
  refers to the last plan, and "it" or "that" in a new message usually means the last thing you wrote.
- When the user says "generate it", "make it", "do it" or "use that prompt" after you wrote a prompt, a description or
  an idea in an earlier reply, plan a "generate" step whose "prompt" is that text from your earlier reply. Do not ask
  for the scene again, and do not ask for items to be selected: a prompt alone is enough for the default workflow.
- Plan only what the newest message asks for. Never repeat the steps of an earlier plan.
- You cannot see or hear the attached items. You only know each one's name, kind, length and the prompt it was made
  with. When asked to analyse or describe them, work from those prompts and say that this is what you are going by.

Editing videos the user already has:
- Every step has a "tool". "generate" makes something new with a workflow. The others edit the selected videos; they
  are instant and free, and they never change what is in the picture.
- When the user wants to cut, trim, shorten, split, halve or join videos they already have, use an editing tool.
  Never use "generate" for that: generating makes a different video.
  - "trim": keep the part of video "source" from "start" to "end" seconds. For the first half of a 6 second video: start 0, end 3.
  - "split": cut video "source" into "parts" equal pieces, each saved as its own video. For two halves: parts 2.
  - "join": join all the selected videos into one, in the order they are listed.
  - "sound": put a sound on a video: background music, or any audio the user has. "source" is the id of the video and
    "audio" is the id of the sound. "replace" is false to mix it under the video's own sound (the usual choice for
    music) and true to take the place of the video's own sound. Both can be attached items, or the newest video and the
    newest sound in "Recent items" when the user says "this video", "the music you made", "attach it".
    This is done with ffmpeg: never answer that you cannot attach audio or cannot use ffmpeg.
- "source" is the id of a selected video; its length is given as "seconds". Editing needs a selected video: when none
  is selected, return no steps and ask the user to select the video on the canvas first. ("sound" may also take the
  video and the sound from "Recent items".)
- For "generate" set source, start, end, parts and audio to 0. For an editing tool set prompt to "" and clips to 1.
- An audio workflow makes music and songs. It does not make a spoken voice-over, and no tool here dubs or translates
  speech. When the user asks for a voice-over, or for a video's speech in another language, do not plan a music step for
  it: say that speech cannot be added to an existing video, and offer to make the shot again with a prompt that says
  which language the people speak. This is only about changing the speech of a video that already exists: "continue the
  conversation" or "add another 5 seconds" asks for a new shot that starts on the attached video ("start_from").
- Never write a tag such as @1 in a prompt: the video model does not know what it means. Describe what is seen.

Motion graphics, made of words and shapes (drawn here, no AI model, priced by the second):
- When the user asks for a motion graphics video, kinetic text, an animated title sequence, an intro or an outro, an
  explainer or promo made of text, a list or a figure animated on screen, use tool "motion". Never use "generate" for
  that: a generating model cannot write readable words.
- A "motion" step is ONE video. Write it as "scenes", shown one after another. Each scene has a "kind":
  "title" (a big heading, with "text" as a smaller line under it), "statement" (one sentence in "text", shown large),
  "list" (a "heading" and up to 5 short "items"), "stat" (a number or short figure in "heading", what it means in "text"),
  "quote" (the words in "text", who said it in "heading"), "end" (closing words in "heading", a smaller line in "text").
- Write the real words the viewer will read. Keep them short: a heading up to 6 words, text up to 14 words, an item up
  to 6 words. A full video has 4 to 8 scenes, starts with a "title" and finishes with an "end". "seconds" is how long a
  scene stays, 2 to 8; use 0 to let it be set from the amount of text.
- "look" is "dark", "light", "warm" or "cool". "orientation" sets the shape of the video. Never ask the user which
  look or shape they want: when they did not say, use "dark" and "landscape" and plan the video.
- To put words over a video the user selected, use tool "overlay": "source" is the video's id and "scenes" has exactly
  one scene, kind "title" (large words in the middle, "heading" and "text") or "lower_third" (a name in "heading" and a
  line under it in "text", at the bottom left).
- For "generate" and the editing tools leave "scenes" empty. For "motion" and "overlay" set prompt to "".

Rules for a plan:
- Each step is one job on one of the listed workflows. Use only those workflow ids. Use the one marked "default" unless
  the instruction names another or needs something only another can do (an image instead of a video, for example).
- Set "orientation" to portrait when the user asks for portrait or vertical, landscape for wide, square for square.
  When the user does not mention it, use the workflow's default orientation.
- For one longer continuous video of the same action, use a single step with "clips" above 1 on a workflow that allows
  it, instead of several steps. "duration" is the length of each clip, so the video lasts duration times clips: for
  15 seconds use duration 5 and clips 3. Otherwise clips is 1.
- A step can start on the result of an earlier step of the same plan: set "after" to that step's number (1 for the first
  step), otherwise 0. The later step then begins on the earlier picture, or on the last frame of the earlier video. Use it:
  when the user asks to make a picture and then animate it (step 1 makes the image, step 2 is a video with "after": 1);
  and when shots follow one another in the same place with the same person ("she arrives, then she waits, then she
  leaves"), so that each shot continues the one before. A step with "after" must be a video on a workflow whose
  "start_from" is allowed or required, and its "start_from" stays 0. Do not chain shots that are in different places.
  A shot takes the shape of the picture it starts on, so decide the orientation in the first step of a chain.
- Write each "prompt" as a concrete shot: subject, action, setting, camera, light, and sound if it matters. One to three sentences.
- A workflow's "prompt_tips" say how its model wants prompts written. Follow them in every prompt for that workflow.
- One shot is ONE action in one place: a 5 second clip cannot show more. When the user lists several actions in a row
  ("she runs through the market, jumps over a crate, turns into an alley and hides behind a door"), plan one step for
  each action, in order (four steps for that example), each prompt describing only its own action.
- When the project has a cast, name its members in the prompt with the words given for them ("the main character",
  "the outfit", "the background") and do not describe their looks: the reference files carry the looks.
- When there is no cast and nothing is attached, never ask for a picture: plan the shot from words. Describe the person
  and the place in a few concrete words (age, hair, clothes; the kind of place), and when a plan has several steps
  with the same person or place, repeat that same description word for word in every step so the shots match.
- Follow the project brief: keep its style, characters and rules in every prompt.
- "start_from" is the id of a selected item the shot should start on, or 0. Use it only when the user asks to continue or animate a selected item.
- The user can attach items and name them in the instruction by their tag: @1, @2 and so on. Each selected item is listed
  with its tag, id and kind. When the user says what an item is for ("use @1 as the background", "@2 is the main
  character", "take the motion from @3"), put it in "uses": the item's id and the "slot" of the workflow's reference
  that fits that purpose, taken from the workflow's "references" list. An image goes in a slot that takes an image, a
  video in one that takes a video (or an image: its last frame is used), a sound in one that takes audio.
  Use each slot once, and copy the "slot" value exactly as it is listed. Never put the same item in both "start_from" and "uses".
  Leave "uses" empty when the user gave the items no purpose or the workflow has no fitting slot.
- Attached items are optional material. Never ask whether to use them. When the instruction does not point at them
  (no tag, no "this", "it", "these"), do not use them: plan the request from scratch, as if nothing were attached.
- A workflow marked "needs_references" only works when its required slots are filled through "uses".
- In the prompt, describe what happens; do not describe again what an attached item already shows.
- Give each step a short "name" of two to four words.
- Plan as few steps as the instruction needs, never more than {max_steps}. Prefer the default resolution and a 5 second duration unless asked.
- If what is asked cannot be done with these workflows, return no steps and say what you can do instead.
- With a plan, "reply" is one or two plain sentences about it. No praise, no filler."""


IMPROVE = """You rewrite prompts for an AI {kind} model inside Scene.ai. You are given the user's prompt and you return a better one.
{tips}
Rules:
- Keep everything the user asked for: the subject, the action, the setting and any style or detail they named. Never change what the {what} is about.
- Add what a good prompt needs and the user left out: {needs}
- Follow the project brief when there is one: keep its style, characters and rules.
- When a project cast is listed, name its members with the words given for them and do not describe their looks. When
  none is listed, describe the people and places in the user's own terms; do not call anyone "the main character".
- Write plain descriptive sentences in the user's language. No lists, no headings, no quotation marks around the whole prompt, no explanations.
- {length}
- If the prompt is already detailed, tighten the wording instead of making it longer."""
IMPROVE_KINDS = {
    "video": {"what": "shot", "needs": "what moves and how, the camera (framing and movement), the light, the mood, and sound if it matters.",
              "length": "Two to four sentences: one shot, one main action."},
    "image": {"what": "picture", "needs": "the framing and viewpoint, the light, the colours, the mood, and the look (photograph, illustration, and so on).",
              "length": "Two to four sentences."},
    "audio": {"what": "music", "needs": "the genre, the tempo, the instruments, the mood, whether there are vocals and what kind, "
                                         "and how the piece develops from start to end.",
              "length": "Three to five sentences."},
}


WRITE_SCENES = """You write motion graphics videos for Scene.ai: videos made of words and shapes, with no pictures.
You are given what the video is about and you return the whole video as "scenes", shown one after another.

- Each scene has a "kind": "title" (a big heading, with "text" as a smaller line under it), "statement" (one sentence
  in "text", shown large, with "heading" as an optional small label above it), "list" (a "heading" and up to 5 short
  "items"), "stat" (a number or short figure in "heading", what it means in "text"), "quote" (the words in "text", who
  said it in "heading"), "end" (closing words in "heading", a smaller line in "text").
- Write the real words the viewer will read, in the user's language. Keep them short: a heading up to 6 words, text up
  to 14 words, an item up to 6 words. Leave "items" empty except in a "list".
- A full video has 4 to 8 scenes, starts with a "title" and finishes with an "end". Vary the kinds in between, and use
  a "stat" or a "quote" only when the user gave that figure or that quotation.
- Never invent facts: no numbers, percentages, prices, opening hours, addresses, people's names or quotations that the
  user did not give. Say what the user told you, in good words.
- When the user gives the words themselves, use their words and only split them into scenes.
- "look" is "dark", "light", "warm" or "cool" and "orientation" is "landscape", "portrait" or "square". Use what the
  user asks for; when they do not say, use "dark" and "landscape".
- Follow the project brief when there is one.
- "name" is a short name for the video, two to four words."""
SCENES_FORMAT = {"type": "object", "required": ["name", "look", "orientation", "scenes"], "properties": {
    "name": {"type": "string"},
    "look": {"type": "string", "enum": list(sequence.LOOKS)},
    "orientation": {"type": "string", "enum": list(ORIENTATIONS)},
    "scenes": {"type": "array", "items": {"type": "object", "required": ["kind", "heading", "text", "items"], "properties": {
        "kind": {"type": "string", "enum": list(sequence.KINDS)}, "heading": {"type": "string"}, "text": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}}}}},
}}


QUOTES = re.compile(r"[\"“”«»]|\b(quote|said|says|told|according to)\b", re.IGNORECASE)


def founded(scene, about):
    """Whether a scene the model wrote can stand on what the user said. A small model likes to make up a figure
    ("100% locally sourced") and a quotation from a customer: a figure has to be in the user's words, and a
    quotation needs the user to have given or asked for one."""
    if not isinstance(scene, dict):
        return False
    if scene.get("kind") == "stat":
        return all(number in about for number in re.findall(r"\d+", str(scene.get("heading") or "") + " " + str(scene.get("text") or "")))
    return scene.get("kind") != "quote" or bool(QUOTES.search(about))


class AgentError(Exception):
    pass


class AgentBusy(AgentError):
    """A hosted model is overloaded or out of quota for the moment: worth another try, or another model."""


BUSY = re.compile(r"high demand|overloaded|try again later|temporarily|unavailable|rate limit|quota|resource.exhausted", re.IGNORECASE)


def reply_format(workflow_ids):
    """The JSON shape the model must answer in."""
    # Every field is required so the model has to decide each one; values a workflow can't take are dropped later.
    step = {"type": "object", "required": ["tool", "workflow", "name", "prompt", "resolution", "orientation", "duration", "clips",
                                           "start_from", "after", "uses", "source", "start", "end", "parts", "audio", "replace", "scenes", "look"], "properties": {
        "tool": {"type": "string", "enum": ["generate", *EDIT_TOOLS, SOUND_TOOL, *MOTION_TOOLS]},
        "workflow": {"type": "string", "enum": workflow_ids},
        "name": {"type": "string"},
        "prompt": {"type": "string"},
        "resolution": {"type": "integer"},
        "orientation": {"type": "string", "enum": list(ORIENTATIONS)},
        "duration": {"type": "integer"},
        "clips": {"type": "integer"},
        "start_from": {"type": "integer"},
        "after": {"type": "integer"},
        "uses": {"type": "array", "items": {"type": "object", "required": ["item", "slot"],
                                            "properties": {"item": {"type": "integer"}, "slot": {"type": "string"}}}},
        "source": {"type": "integer"},
        "start": {"type": "number"},
        "end": {"type": "number"},
        "parts": {"type": "integer"},
        "audio": {"type": "integer"},
        "replace": {"type": "boolean"},
        "scenes": {"type": "array", "items": {"type": "object", "required": ["kind", "heading", "text", "items", "seconds"], "properties": {
            "kind": {"type": "string", "enum": [*sequence.KINDS, *OVERLAY_KINDS]}, "heading": {"type": "string"}, "text": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}}, "seconds": {"type": "number"}}}},
        "look": {"type": "string", "enum": list(sequence.LOOKS)},
    }}
    return {"type": "object", "required": ["reply", "steps"], "properties": {
        "reply": {"type": "string"}, "steps": {"type": "array", "items": step}}}


def service(sid, name, url, key, models="", only=""):
    """One hosted model service that speaks the OpenAI chat API. models: the names to offer, comma separated; when
    empty the service is asked, and `only` (a regular expression) keeps the ones that are chat models.
    models "off" switches the service off without taking its key out of the settings."""
    if str(models).strip().lower() in ("off", "none"):
        key, models = "", ""
    return {"id": sid, "name": name, "url": str(url).rstrip("/"), "key": str(key).strip(),
            "models": [m.strip() for m in str(models).split(",") if m.strip()], "only": only}


def _unfenced(text):
    """A model's answer without the ```json fence some of them put around it."""
    text = str(text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return fenced.group(1) if fenced else text


class Agent:
    """The language model behind the agent. Models come from an Ollama server (local, free) and from any hosted
    services that have a key set, such as Kimi and Gemini. A hosted model is named "<service id>/<model>",
    for example "gemini/gemini-3.8-flash"; the user picks one by name."""

    def __init__(self, url, model="", services=()):
        self.url = url.rstrip("/")
        self.model = model
        self.services = {s["id"]: s for s in services if s["url"] and s["key"]}   # without a key a service is not offered
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5))

    def hosted(self):
        """The hosted services that are set up: [{"id", "name"}]."""
        return [{"id": s["id"], "name": s["name"]} for s in self.services.values()]

    def _service_of(self, model):
        """The service a model name belongs to and the model's own name there, or (None, name) for a local model."""
        sid, _, name = str(model).partition("/")
        return (self.services[sid], name) if name and sid in self.services else (None, model)

    async def _local_models(self):
        try:
            found = (await self.http.get(self.url + "/api/tags")).json().get("models") or []
        except (httpx.HTTPError, ValueError):
            return None   # the Ollama server is not answering
        self.sizes = {m["name"]: m.get("size") or 0 for m in found if isinstance(m, dict) and m.get("name")}
        return list(self.sizes)

    async def _hosted_models(self):
        names = []
        for s in self.services.values():
            if not s["models"]:   # none named in the settings: ask the service once and remember
                try:
                    listed = (await self.http.get(s["url"] + "/models", headers={"Authorization": "Bearer " + s["key"]})).json()
                    ids = sorted(str(m["id"]).split("/")[-1] for m in listed.get("data") or [] if isinstance(m, dict) and m.get("id"))
                    s["models"] = [i for i in ids if not s["only"] or re.search(s["only"], i)]
                except (httpx.HTTPError, ValueError, AttributeError):
                    continue
            names += ["{}/{}".format(s["id"], name) for name in s["models"]]
        return names

    async def models(self):
        """The names of the models there are: Ollama's, then the hosted ones as "<service>/<name>"."""
        local, hosted = await self._local_models(), await self._hosted_models()
        if local is None and not hosted:
            raise AgentError("The agent's model server (Ollama) can't be reached at {}.".format(self.url))
        return (local or []) + hosted

    async def pick_model(self, wanted=None):
        """The model to use: the one asked for if there is such a model, else the configured one, else the first one there."""
        if not wanted and self.model:
            return self.model
        names = await self.models()
        if not names:
            raise AgentError("There is no model for the agent. Pull one in Ollama (ollama pull qwen3.5:9b) or set an API key.")
        return wanted if wanted in names else self.model or names[0]

    async def chat(self, messages, answer_format, context=None, model=None):
        """Send messages to the model and return its answer, which has to be JSON of the given shape.
        context: room for the conversation in tokens, when the instructions are longer than a local model's default.
        model: the model the user picked; the usual one when it is not given or not there."""
        model = await self.pick_model(model)
        hosted, name = self._service_of(model)
        stood_in = None
        if hosted:
            try:
                content = await self._ask_hosted(hosted, name, messages, answer_format)
            except AgentBusy:
                # The hosted model is busy and a second try did not help: the smallest local model answers instead.
                local = await self._local_models()
                if not local:
                    raise
                stood_in = min(local, key=lambda n: self.sizes.get(n) or 0)
                content = await self._ask_local(stood_in, messages, answer_format, context)
        else:
            content = await self._ask_local(model, messages, answer_format, context)
        try:
            answer = json.loads(_unfenced(content))
        except (ValueError, TypeError):
            raise AgentError("The agent's model gave an answer that can't be read. Try again.")
        if not isinstance(answer, dict):
            raise AgentError("The agent's model gave an answer that can't be read. Try again.")
        if stood_in:
            answer["_stood_in"] = "{} was busy, so {} answered.".format(hosted["name"], stood_in)
        return answer

    async def _ask_local(self, model, messages, answer_format, context):
        options = {"temperature": 0.4, **({"num_ctx": context} if context else {})}
        try:
            response = await self.http.post(self.url + "/api/chat", json={
                "model": model, "stream": False, "think": False, "format": answer_format,
                "options": options, "messages": messages})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise AgentError("The agent's model server (Ollama) can't be reached at {}.".format(self.url))
        if body.get("error"):
            raise AgentError("The agent's model failed: {}".format(str(body["error"])[:200]))
        return (body.get("message") or {}).get("content")

    async def _ask_hosted(self, s, model, messages, answer_format):
        """Ask a model of the hosted service `s` through the OpenAI chat API. It is told the shape of the answer in
        words, since services differ in how far they hold a model to a schema; JSON mode makes sure it is JSON at all."""
        shape = ("Answer with one JSON object and nothing else." if not isinstance(answer_format, dict) else
                 "Answer with one JSON object and nothing else. It must fit this JSON schema, with every required key present:\n"
                 + json.dumps(answer_format))
        messages = [dict(messages[0], content=messages[0]["content"] + "\n\n" + shape), *messages[1:]]
        body = {"model": model, "messages": messages, "temperature": 0.4, "response_format": {"type": "json_object"}}
        for attempt in (1, 2, 3):
            try:
                response = await self.http.post(s["url"] + "/chat/completions", json=body, headers={"Authorization": "Bearer " + s["key"]})
                answer = response.json()
            except (httpx.HTTPError, ValueError):
                raise AgentError("{} can't be reached at {}.".format(s["name"], s["url"]))
            if isinstance(answer, list) and answer:   # some services wrap an error in a list
                answer = answer[0]
            problem = answer.get("error") if isinstance(answer, dict) else "an answer that can't be read"
            if not problem and response.status_code < 400:
                try:
                    return answer["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    raise AgentError("{} gave an answer that can't be read. Try again.".format(s["name"]))
            said = str(problem.get("message") if isinstance(problem, dict) else problem or response.status_code)
            if "temperature" in said.lower() and "temperature" in body:
                del body["temperature"]   # some models only run at their own temperature
                continue
            if response.status_code in (429, 500, 502, 503, 504) or BUSY.search(said):
                if attempt < 2:
                    await asyncio.sleep(2)   # a spike in demand often passes in a moment
                    continue
                raise AgentBusy("{} is busy: {}".format(s["name"], said[:200].replace(s["key"], "<key>")))
            if response.status_code in (401, 403):
                raise AgentError("{} refused the API key. Check it in config.json.".format(s["name"]))
            raise AgentError("{} failed: {}".format(s["name"], said[:200].replace(s["key"], "<key>")))

    async def improve(self, prompt, kind="video", brief="", model=None, tips=(), project_cast=None):
        """A fuller version of a prompt the user wrote, for an image, a video or a music model.
        tips: how the chosen workflow's model wants prompts written. project_cast: the project's pinned references."""
        advice = ("\nAdvice on what works with this model. Use it to shape the prompt, but never mention the advice, "
                  "reference images or consistency in the prompt itself:\n{}\n").format("\n".join("- " + str(t)[:220] for t in tips[:6])) if tips else ""
        system = IMPROVE.format(kind=kind, tips=advice, **IMPROVE_KINDS[kind])
        message = "Project brief:\n{}\n\nProject cast:\n{}\n\nPrompt:\n{}".format(
            brief.strip() or "(none)", cast.described(project_cast or {}) or "(none)", prompt)
        answer = await self.chat([{"role": "system", "content": system}, {"role": "user", "content": message}],
                                 {"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string"}}},
                                 **({"model": model} if model else {}))
        better = str(answer.get("prompt") or "").strip().strip('"').strip()
        if not better:
            raise AgentError("The agent's model gave no prompt back. Try again.")
        return better[:2000]

    async def write_scenes(self, about, brief="", model=None):
        """A whole motion graphics video written from what it is about: {"name", "look", "shape", "scenes"}.
        The scenes are as the model gave them, less the ones it made up; sequence.clean_scenes checks them."""
        message = "Project brief:\n{}\n\nThe video is about:\n{}".format(brief.strip() or "(none)", about)
        answer = await self.chat([{"role": "system", "content": WRITE_SCENES}, {"role": "user", "content": message}],
                                 SCENES_FORMAT, **({"model": model} if model else {}))
        return {"name": " ".join(str(answer.get("name") or "").split())[:80],
                "look": answer.get("look") if answer.get("look") in sequence.LOOKS else "dark",
                "shape": answer.get("orientation") if answer.get("orientation") in ORIENTATIONS else "landscape",
                "scenes": [s for s in answer.get("scenes") if founded(s, about)] if isinstance(answer.get("scenes"), list) else []}

    async def caption(self, template, idea, ratio):
        """The structured JSON caption some image models are trained on, written from a plain prompt.

        template: the instructions the workflow ships for this, ending in a [USER] part with
        {{ratio}} and {{original_prompt}} in it.
        """
        system, _, user = template.partition("[USER]")
        user = user.strip() or "TARGET IMAGE ASPECT RATIO: {{ratio}} (width:height).\nUser idea: {{original_prompt}}"
        answer = await self.chat([{"role": "system", "content": system.strip()},
                                  {"role": "user", "content": user.replace("{{ratio}}", ratio).replace("{{original_prompt}}", idea)}],
                                 "json", context=CAPTION_CONTEXT)
        answer.pop("_stood_in", None)   # a note of ours, not part of the caption
        if not answer:
            raise AgentError("The agent's model gave no caption back. Try again.")
        return json.dumps(answer, ensure_ascii=False, separators=(",", ":"))

    async def ask(self, system, message, workflow_ids, history=(), model=None):
        """One question to the model; returns its answer as {"reply": str, "steps": [...]}.
        history: the earlier turns of the conversation, as {"role", "content"} messages."""
        answer = await self.chat([{"role": "system", "content": system}, *history, {"role": "user", "content": message}],
                                 reply_format(workflow_ids), **({"model": model} if model else {}))
        steps = answer.get("steps")
        reply = str(answer.get("reply") or "").strip()[:1200]
        if answer.get("_stood_in"):   # say so when another model answered than the one that was picked
            reply = "{} ({})".format(reply, answer["_stood_in"]).strip()
        return {"reply": reply, "steps": steps if isinstance(steps, list) else []}


# Words that show an instruction is about the items the user selected. Without any, the selection is left out of the
# question: a small model that is shown attached items asks what to do with them instead of making what was asked.
POINTS = re.compile(
    r"@\d|\b(this|these|that|those|it|its|them|they|both|selected|attached|same|here|"
    r"split|trim|cut|join|merge|combine|shorten|halve|continue|extend|animate|"
    r"the (video|image|clip|picture|photo|shot|frame|sound|audio|music|song|first|second|third|last))\b", re.IGNORECASE)


def points_at_selection(instruction):
    """Whether the instruction refers to the selected items. Text that is not in Latin letters always counts:
    the word list is English."""
    return bool(POINTS.search(instruction)) or not instruction.isascii()


FITS = cast.FITS   # what a reference slot of each kind can be filled with from the library


def offer(schema, attached=True):
    """What the model is told about one workflow, or None if the agent can't use it.

    attached: the user selected items. Without any, a workflow that must be given reference files can't run."""
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    first_frame = (schema.get("slots") or {}).get("first_frame")
    required = [r for r in schema["refs"] if not r["optional"] and r["id"] != first_frame]
    if "prompt" not in roles or (required and not attached):
        return None
    needs_start = any(not r["optional"] and r["id"] == first_frame for r in schema["refs"])
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
    if schema.get("hints"):   # how this model likes its prompts written
        info["prompt_tips"] = [str(tip)[:220] for tip in schema["hints"][:6]]
    slots = [{"slot": r["id"], "for": r["label"], "takes": r["kind"], **({} if r["optional"] else {"required": True})}
             for r in schema["refs"]]
    if slots:
        info["references"] = slots
    if required:
        info["needs_references"] = True
    return info


def uses_for(schema, step, selection):
    """The selected items a step puts into reference slots, keeping only what the workflow can take.

    selection: {id: {"name", "kind"}}. Returns [{"id", "name", "slot", "label", "kind"}], kind being what the slot takes.
    An item put in the first-frame slot is written to the step's "start_from" instead."""
    named = schema.get("slots") or {}
    slots = {r["id"]: r for r in schema["refs"]}

    def find(name):
        """The slot the model means: its id, or, as small models shorten ids, the one id that starts with what it wrote."""
        name = str(name or "").strip()
        close = [r for rid, r in slots.items() if rid == name or (name and rid.split(":")[0] == name.split(":")[0])]
        return slots.get(name) or (close[0] if len(close) == 1 else None)

    used, taken = [], set()
    for use in step.get("uses") if isinstance(step.get("uses"), list) else []:
        if not isinstance(use, dict):
            continue
        slot, item = find(use.get("slot")), selection.get(use.get("item"))
        if not slot or not item or slot["id"] in taken or item["kind"] not in FITS.get(slot["kind"], ()):
            continue
        if slot["id"] == named.get("first_frame") or (
                slot["id"] == named.get("last_frame") and item["kind"] == "video" and named.get("first_frame") and not step.get("start_from")):
            # The first frame has its own field; naming its slot means the same. A video named as the last frame is a
            # mix-up: what a video gives is its last frame, and a new shot continues from there, so it is the start.
            step["start_from"] = use["item"]
            continue
        if slot["id"] == named.get("last_frame") and use["item"] == step.get("start_from"):
            continue   # a video that starts and ends on the same picture does not move
        taken.add(slot["id"])
        used.append({"id": use["item"], "name": item["name"], "slot": slot["id"], "label": slot["label"].split(" (")[0], "kind": slot["kind"]})
    return used


# A short message that asks for the thing just talked about to be made: "now generate it", "use the prompt you gave".
GO_AHEAD = re.compile(r"\b(generate|make|create|render|use|do)\b.*\b(it|that|this|prompt|one)\b", re.IGNORECASE)


def carry_over(instruction, history):
    """The message, with the text it points back to spelled out.

    After the agent has written a prompt or a description (a reply with no plan), "now generate it" says nothing
    about what to make. A small model then asks for the scene again, so the reply it points to is put in the message."""
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    reply = str(last.get("reply") or "").strip()
    if not reply or last.get("steps") or len(instruction) > 80 or not GO_AHEAD.search(instruction):
        return instruction
    return ('{}\n(This points to your last reply. Take the prompt from it, leaving out any words that were addressed '
            'to the user, and plan a "generate" step with it. Your last reply was: "{}")').format(instruction, reply[:1500])


def past_turns(history):
    """The last few turns the browser sent, as chat messages. Anything that is not text is left out."""
    turns = []
    for turn in history[-MAX_HISTORY:] if isinstance(history, list) else []:
        if not isinstance(turn, dict):
            continue
        said, answered = str(turn.get("instruction") or "").strip(), str(turn.get("reply") or "").strip()
        if said and answered:
            planned = [str(name)[:80] for name in turn.get("steps") or [] if isinstance(name, str)][:MAX_STEPS]
            if planned:
                answered += "\n(Planned: {})".format(", ".join(planned))
            turns += [{"role": "user", "content": said[:2000]}, {"role": "assistant", "content": answered[:1500]}]
    return turns


def question(instruction, brief, offers, selection, default="", history=(), project_cast=None, recent=()):
    """Everything the model is given for one message. history: the earlier turns, from past_turns().

    The conversation goes inside the message, not before it as separate chat turns: a small model reads the long
    message as the whole task and otherwise answers as if nothing had been said before."""
    offers = sorted(offers, key=lambda o: o["id"] != default)   # the default first; the rest keep their order
    if offers[0]["id"] == default:
        offers[0] = dict(offers[0], default=True)
    said = ["{}: {}".format("User" if turn["role"] == "user" else "You", turn["content"]) for turn in history]
    parts = ["Project brief:\n" + (brief.strip() or "(none)"),
             "Project cast:\n" + (cast.described(project_cast or {}) or "(none)"),
             "Workflows:\n" + "\n".join(json.dumps(o) for o in offers),
             "Conversation so far, oldest first:\n" + ("\n".join(said) or "(this is the first message)"),
             "Recent items, newest first (what was made lately in this project; for the \"sound\" tool only):\n"
             + ("\n".join(json.dumps(r) for r in recent) or "(none)"),
             "Items attached to the new message:\n" + ("\n".join(json.dumps(s) for s in selection)
                                                      or "(none; a prompt alone is enough to generate)"),
             "The user's new message:\n" + instruction]
    return "\n\n".join(parts)


SOUND_WORDS = re.compile(r"\b(attach|add|put|mix|merge|lay|apply|use|set)\b.*\b(audio|music|bgm|sound|soundtrack|track|song)\b"
                         r".*\b(video|clip|shot|vid\w*|it|this|that)\b", re.IGNORECASE)


def wants_sound(instruction, history=()):
    """Whether the message asks for a sound to be put on a video. "Use ffmpeg and do this" counts when the message
    before it asked for that. A small model sometimes answers such a request with words only; the plan uses this to
    make the step the user asked for."""
    if SOUND_WORDS.search(instruction):
        return True
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    return "ffmpeg" in instruction.lower() and bool(SOUND_WORDS.search(str(last.get("instruction") or "")))


def sound_for(step, items):
    """Turn a proposed "sound" step into what the sound endpoint takes, or None if it can't be done.

    items: the attached and the recent items, as {id: {"name", "kind"}}, newest recent ones first. A video or a sound
    the model did not name, or named wrongly, falls back to the newest one of that kind."""
    def pick(wanted, kinds):
        named = items.get(wanted)
        if named and named["kind"] in kinds:
            return wanted
        return next((iid for iid, item in items.items() if item["kind"] in kinds), None)

    video, sound = pick(step.get("source"), ("video",)), pick(step.get("audio"), ("audio",))
    if video is None or sound is None:
        return None
    replace = step.get("replace") is True
    name = " ".join(str(step.get("name") or "").split())[:80] or "{} with sound".format(items[video]["name"])[:80]
    return {"name": name, "facts": "{} {} {}".format(items[sound]["name"], "in place of the sound of" if replace else "under", items[video]["name"]),
            "sound": {"video": video, "audio": sound, "replace": replace, "name": name}}


def motion_for(step, videos):
    """Turn one proposed motion step into what the motion endpoint takes, or None if there is nothing to draw.

    videos: the selected videos, as for edits_for. Returns {"name", "facts", "words", "motion"}; "motion" is the
    body of POST /api/motion/render: scenes with a look and a shape, or a template with its values and source."""
    raw = step.get("scenes") if isinstance(step.get("scenes"), list) else []
    name = " ".join(str(step.get("name") or "").split())[:80]
    if step.get("tool") == "overlay":
        video = next((v for v in videos if v["id"] == step.get("source")), None) or (videos[0] if len(videos) == 1 else None)
        first = next((s for s in raw if isinstance(s, dict)), None)
        if video is None or first is None:
            return None
        heading, text = (" ".join(str(first.get(key) or "").split()) for key in ("heading", "text"))
        title, under = (heading, text) if heading else (text, "")
        if not title:
            return None
        lower = first.get("kind") == "lower_third"
        return {"name": name or title[:80], "words": " · ".join(filter(None, (title, under))),
                "facts": "{} over {}".format("Lower third" if lower else "Title", video["name"]),
                "motion": {"template": "lower_third" if lower else "title_over_video", "source": video["id"],
                           "values": {"title": title[:40 if lower else 60], "subtitle": under[:60 if lower else 90]}}}
    try:
        scenes = sequence.clean_scenes([dict(s, seconds=s.get("seconds") or None) for s in raw if isinstance(s, dict)])
    except sequence.SequenceError:
        return None
    shape = step.get("orientation") if step.get("orientation") in ORIENTATIONS else "landscape"
    look = step.get("look") if step.get("look") in sequence.LOOKS else "dark"
    words = [scene["heading"] or scene["text"] for scene in scenes]
    return {"name": name or words[0][:80], "words": " / ".join(words)[:400],
            "facts": "{} · {:.0f} s · {} · {}".format("1 scene" if len(scenes) == 1 else "{} scenes".format(len(scenes)),
                                                    sum(scene["seconds"] for scene in scenes), shape, look),
            "motion": {"scenes": scenes, "look": look, "shape": shape, "name": name}}


SPLIT_WORDS = re.compile(r"\b(split|halve|divide)\b|\bin(?:to)? (two|2|three|3|four|4|half|halves)\b", re.IGNORECASE)
PART_WORDS = {"two": 2, "2": 2, "half": 2, "halves": 2, "three": 3, "3": 3, "four": 4, "4": 4}


def parts_asked(instruction):
    """How many pieces the user asked a video to be split into, or 0 when the message is not about splitting.

    A small model often answers "split this in two" with a trim of the first half only; the plan uses this to
    turn such a trim back into the split that was asked for."""
    if not SPLIT_WORDS.search(instruction):
        return 0
    counts = [PART_WORDS[word.lower()] for word in re.findall(r"\b(two|2|three|3|four|4|half|halves)\b", instruction, re.IGNORECASE)]
    return counts[0] if counts else 2


def edits_for(step, videos):
    """Turn one proposed editing step into cuts, keeping only what the selected videos allow.

    videos: the selected videos in order, as {"id", "name", "seconds"}. Returns a list of
    {"name", "facts", "clips"}; each becomes one new video made of its clips ({"id", "start", "end"}).
    """
    tool = step.get("tool")
    by_id = {v["id"]: v for v in videos}
    name = str(step.get("name") or "").strip()[:80]
    if tool == "join":
        if len(videos) < 2:
            return []
        return [{"name": name or "Joined", "facts": "{} videos joined · {:.1f} s".format(len(videos), sum(v["seconds"] for v in videos)),
                 "clips": [{"id": v["id"], "start": 0, "end": 0} for v in videos]}]
    video = by_id.get(step.get("source")) or (videos[0] if len(videos) == 1 else None)
    if video is None or video["seconds"] <= 0:
        return []
    length = video["seconds"]

    def number(key):
        return float(step[key]) if isinstance(step.get(key), (int, float)) and not isinstance(step.get(key), bool) else 0.0

    def cut(start, end, label):
        return {"name": label, "facts": "{:.1f} s to {:.1f} s of {}".format(start, end, video["name"]),
                "clips": [{"id": video["id"], "start": round(start, 3), "end": round(end, 3)}]}

    wants_parts = isinstance(step.get("parts"), int) and step["parts"] >= 2
    if tool == "trim":
        start = max(0.0, min(number("start"), length))
        end = min(number("end"), length) if number("end") > 0 else length
        if wants_parts and start == 0 and end == length:
            tool = "split"   # a trim that cuts nothing but names a number of parts: the model meant a split
        elif end - start < 0.1 or (start == 0 and end == length):
            return []   # nothing would be left, or nothing would be cut
        else:
            return [cut(start, end, name or video["name"] + " trimmed")]
    if tool == "split":
        parts = max(2, min(MAX_PARTS, step["parts"] if isinstance(step.get("parts"), int) else 2))
        return [cut(length * i / parts, length * (i + 1) / parts, "{} part {} of {}".format(video["name"], i + 1, parts)[:80])
                for i in range(parts)]
    return []


def _ratio(choice):
    """Width over height of an aspect ratio choice such as "16:9 (Widescreen)", or None."""
    found = re.match(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", str(choice))
    return float(found.group(1)) / float(found.group(2)) if found and float(found.group(2)) else None


def shape_like(schema, settings, shape):
    """Give a job the shape of the picture it starts on, so that picture is not stretched or squashed.

    shape: (width, height) of that picture, or None when it is not known. Sets the orientation, or the nearest
    choice of the workflow's aspect ratio."""
    if not shape or not shape[0] or not shape[1]:
        return
    ratio = shape[0] / shape[1]
    if schema.get("size"):
        settings["orientation"] = "landscape" if ratio > 1.15 else "portrait" if ratio < 0.87 else "square"
    for control in schema["controls"]:
        choices = [c for c in control.get("choices") or [] if _ratio(c)]
        if control["input"] == "aspect_ratio" and choices:
            settings["values"][control["id"]] = min(choices, key=lambda c: abs(math.log(_ratio(c) / ratio)))


def shape_of(schema, settings, ctx):
    """The (width, height) of what a job will make, as far as its settings say, or None."""
    if ctx.get("width") and ctx.get("height"):
        return [ctx["width"], ctx["height"]]
    for control in schema["controls"]:
        if control["input"] == "aspect_ratio" and _ratio(settings["values"].get(control["id"])):
            return [round(1000 * _ratio(settings["values"][control["id"]])), 1000]
    return None


def settings_for(schema, step, selection_ids, project_id, filled=(), used_items=(), chained=False):
    """Turn one proposed step into job settings, keeping only what the workflow really accepts.

    filled: the reference slots the step fills from selected items (see uses_for); used_items: the ids of those items.
    chained: the step starts on the result of an earlier step, which fills its first frame when that is made.
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
    start = step.get("start_from") if first_frame and step.get("start_from") in selection_ids and not chained else None
    if start in used_items and any(r["id"] == first_frame and r["optional"] for r in schema["refs"]):
        start = None   # the item was given another purpose; it is not also the picture the shot starts on
    if any(not r["optional"] and r["id"] not in filled and not ((start or chained) and r["id"] == first_frame) for r in schema["refs"]):
        return None   # this workflow must be given a file it was not given
    clips = max(1, min(6, step["clips"])) if schema.get("chain") and isinstance(step.get("clips"), int) else 1
    settings = {"workflow": schema["id"], "name": str(step.get("name") or schema["id"].split("/", 1)[1]).strip()[:80],
                "values": values, "options": {o["id"]: o["default"] for o in schema["options"]},
                "resolution": resolution, "orientation": orientation, "seed_mode": "random", "clips": clips,
                "project_id": project_id, "refs": {}}
    # A workflow that takes an aspect ratio instead of an orientation gets the ratio that orientation means.
    if not schema.get("size") and step.get("orientation") in ORIENTATIONS:
        shape_like(schema, settings, {"landscape": (16, 9), "portrait": (9, 16), "square": (1, 1)}[step["orientation"]])
    return settings, start
