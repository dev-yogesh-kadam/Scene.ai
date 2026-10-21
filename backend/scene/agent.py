"""The agent: turns an instruction into a plan of generations, using a language model served by Ollama.

The model only proposes. Every step is checked against the real workflows and priced here, and
nothing is queued until the user approves the plan in the browser.
"""

import asyncio
import json
import math
import re

import httpx

from . import camera, gpu, kit, sequence

MAX_STEPS = 12   # a longer film runs in stages (cast, stills, clips), each priced and approved on its own
SHOT_SECONDS = (4, 15)  # the length the agent may give one video shot; the workflow takes any number of seconds
WORDS_PER_SECOND = 2.5  # how fast people speak in a shot, for the time spoken words need
LONG_SHOT = 10          # a shot longer than this is not made at the largest resolution: it may not fit in memory
MAX_HISTORY = 40    # earlier turns of the conversation sent along with a new message
HISTORY_CHARS = 48_000   # ...but no more than this much of them (about 12k tokens): the newest turns are kept
LOCAL_CONTEXT = 32768    # tokens a local model reads, the same for every call, unless ollama_context says otherwise
CHARS_PER_TOKEN = 3.0    # a careful guess of how many characters one token holds (prose, JSON and code mixed)
SKILL_SHARE = 0.45       # the share of a local model's context a skill may take whole; a longer one is read in parts
KEEP_RESULTS = 6         # the newest tool results kept whole when a long run must be shortened to fit the context
LOAD_RETRIES = (2, 5, 10)   # seconds between tries while Ollama loads a model or is busy
FIX_ROUNDS = 2   # how many times a finished plan with steps that cannot run goes back to the model to be put right
ORIENTATIONS = ("landscape", "portrait", "square")
EDIT_TOOLS = ("trim", "split", "join")   # done with ffmpeg on videos the user already has: no GPU, no credits
MAX_PARTS = 6
MOTION_TOOLS = ("motion", "overlay")     # drawn by HyperFrames from words: no GPU, priced by the second
ASSEMBLE_TOOL = "assemble"                 # the finished cut: shots in order, music, a title and an end card; ffmpeg, no credits
SOUND_TOOL = "sound"                     # a sound put on a video with ffmpeg: no GPU, no credits
OVERLAY_KINDS = ("lower_third",)         # a scene kind only an overlay has
CAPTION_CONTEXT = 16384   # tokens: the caption instructions of a workflow run to several thousand

SYSTEM = """You are the production assistant inside Scene.ai, a studio for making images and video with AI.
You do two things: you talk with the user, and you turn what they want to make into a short plan of generation jobs.

Talking:
- When the user greets you, asks a question, wants ideas, or is still working out what to make, answer like a helpful
  colleague in "reply" and return no steps. Be warm and brief: one to four sentences.
- You can help with shot ideas, prompts, story beats, and how Scene.ai works (workflows, clips, cost).
- Plan steps only when the user asks for something to be made. If it is not clear yet what they want to see, ask.
- The conversation so far is given to you, with your own replies marked "You". Use it: "make that one portrait"
  refers to the last plan, and "it" or "that" in a new message usually means the last thing you wrote.
- When the user says "generate it", "make it", "do it" or "use that prompt" after you wrote a prompt, a description or
  an idea in an earlier reply, plan a "generate" step whose "prompt" is that text from your earlier reply. Do not ask
  for the scene again, and do not ask for items to be selected: a prompt alone is enough for the default workflow.
- Plan only what the newest message asks for. Never repeat the steps of an earlier plan.
- Nothing is made until the user approves a plan with steps. Never write that you are generating, creating, starting or
  have made something unless this answer has steps; with steps, say what the plan makes and that it runs when approved.
  "start", "go", "approve", "generate" or "yes" after a reply of yours that had no plan means: plan it now, with steps.
- Keep the subject the user asked for. When they say "from scratch", "generic", "your own" or "anything", invent the
  details yourself for that same subject (an ad for a pet page shows a pet) and plan it; do not ask again. Never put in
  its place an item from the asset book or an earlier plan that is about something else.
- You know what is in an item from its "shows": a description written by looking at it. When an item has no "shows",
  you only know its name, kind, length and the prompt it was made with; when asked to analyse or describe it, work from
  those and say that this is what you are going by. You cannot hear sounds.

The asset book (the project's memory):
- "Asset book" lists what is kept for reuse: the user's saved assets (each with "asset", its id) and the pictures and
  videos made in this project (each with "item", its id). Each has a "name", a "type" (character, outfit, location,
  prop, voice, style, other), a "kind" (image, video, audio), "shows" (what is in it) and sometimes "use": the user's
  own note on when and how to use it. Follow "use" like an instruction from the user.
- When the message names an asset, by its name or by what it is ("Meera", "the girl", "our logo", "the cafe"), or a
  shot shows a character, place or prop the book has, use that asset: put it in "uses" with the slot of the workflow
  that fits its type (a character in a character slot, a location in a background or location slot, an outfit in an
  outfit slot, a voice in a voice slot). For a saved asset write {{"item": 0, "asset": <its id>, "slot": ...}}; for an
  item of the project write {{"item": <its id>, "asset": 0, "slot": ...}}. An entry marked "always" is attached to every
  shot already, in its slot: never put it in "uses"; a shot it does not belong in (no location in a close-up on white)
  lists its asset id in "leave_out". An entry marked "unnamed" was attached without a name: before you use it, ask the
  user once who or what it is (a question), and when they say, save its name and type with kit_save.
- A step that makes something meant for reuse in later shots (a character, an outfit, a location, a prop, a style
  picture, or a voice sample) fills "keep": {{"as": its type, "name": its short name, "Maya" or "the cafe"}}. Its result
  is kept in the project's kit under that name, for every agent tab. Every other step writes {{"as": "", "name": ""}}.
  Name a kept asset by who or what it is, never "Maya Character Asset". When the user names one ("use Maya"), find it in the
  book by its name and put it in "uses"; a shot with several characters puts each in its own character slot.
- In the prompt, call a used asset by what it is in plain words ("the girl", "the cafe"), never by its name in the book
  or a number, and do not describe its look again: the reference carries it.
- Use an entry only when it is what the shot is about. An entry about something else (a car when the user wants a pet)
  is never used as a stand-in: make the shot from words instead.
- Never ask the user to attach or select something the book has. When they ask what assets or characters there are,
  answer from the book. An entry marked "uploaded" is a file the user dropped into a job in this project.
- An item with "review" was checked by you after it was made. Do not start a shot on, or use as a reference, an item
  that failed its review, and do not repeat the mistake it names in a new prompt.
- An item marked "liked" got the user's thumbs up: prefer it as a reference or a picture to start on. Never use one
  marked "disliked", and do not make the same picture again.

Tools, and which to use:
- Every step has a "tool". "generate" makes something new with a workflow. The others work on videos the user already
  has, or draw text on screen; they are instant and free, and they never change what is in a generated picture.
- "trim", "split", "join" and "sound" edit a selected video the user already has (cut, shorten, halve, join, or put
  music or audio on it). Never use "generate" for that: generating makes a different video. Editing needs a selected
  video: when none is selected, return no steps and ask the user to select the video on the canvas first. "sound" only
  puts an audio file on a video. Work on a sound file itself (separate the voice, transcribe it) is a "generate" step
  with the workflow made for it: those take an audio file, no video.
- "motion" makes a video of words and shapes (a title sequence, kinetic text, an intro or outro, an explainer, a list
  or a figure on screen); "overlay" puts words over a selected video. Never use "generate" for readable text: a
  generating model cannot write words.
- When the message asks for editing or for motion graphics, a skill with the exact rules for that tool is given below
  under "How to do this kind of work"; follow it. The field defaults always hold: for "generate" set source, start,
  end, parts and audio to 0 and leave "scenes" empty; for an editing tool set prompt to "" and clips to 1; for "motion"
  and "overlay" set prompt to "" and fill "scenes".
- Camera: for a "generate" step that shows a scene, fill "shot_size" (ECU, CU, MCU, MS, WS, EWS), "angle" (eye, low, high,
  top, OTS), "move" (static, push in, pull back, pan, track, crane, handheld, orbit) and "end_state" (where the people and
  the camera end up, in a few words). They are turned into words in the prompt for you, so do not repeat them there. Open
  a scene wide, go closer for the action, keep the people moving the same way across shots. For anything that is not a
  scene (an edit, text, music) leave them "" .
- "assemble" is the last step of a film: it puts the shots of this plan (the takes the user keeps) in order, with music
  under them, a title card and an end card, into one video. "scenes" may hold one scene of kind "title" and one of kind
  "end" (heading and text); "audio" is the id of music that exists, or "after" is the step number of a music step in this
  plan; leave "prompt" empty. Use it when the user wants the finished film, not for a single shot. Free and quick.
- Never write a tag such as @1 in a prompt: the video model does not know what it means. Describe what is seen.

Rules for a plan:
- Each step is one job on one of the listed workflows. Use only those workflow ids. Use the one marked "default" unless
  the instruction names another or needs something only another can do (an image instead of a video, for example).
Deciding the settings of every step. What the user says always wins: a length, a shape, a resolution or a quality they
name is used exactly. Everything they leave open you decide from the script and the conversation. Never ask
the user to choose a setting.
- "duration" (a video shot, from 4 to 15 seconds; whole seconds, unless the workflow says decimals are allowed): the
  time the action really takes, not a round number.
  A glance, a reaction, a logo or a product turning: 4 to 5. One walk, one gesture, a reveal, a pour: 5 to 7. A slow
  establishing shot or a camera move across a place: 6 to 9. Spoken words need about 2.5 words a second, plus a second
  before and after: 12 spoken words is 7 seconds. When someone speaks, write their exact words in the prompt in
  quotation marks after "Audio:", as the user gave them, and give the shot the time they need. Go over 10 seconds only when one unbroken action needs it; 5 to 8
  seconds gives the best picture on the default workflow.
- "orientation": from where it will be shown. Reels, Shorts, TikTok, Stories, WhatsApp status, a phone screen, a poster or
  a person seen at full height: portrait. YouTube, a film, a TV ad, a website banner, a landscape, a wide scene or a
  group: landscape. An Instagram feed post, a profile picture, a product tile, an album or podcast cover: square.
  When nothing says, follow the earlier plans of this conversation, then the workflow's default. All the
  shots of one piece keep one shape.
- "resolution": 480 for a test, a draft or a quick look; the workflow's default resolution for normal work; 1080 for a
  final, a hero shot or a big screen, only for shots of 10 seconds or less.
- "choices": the workflow's own settings, listed under its "settings". Set one only when the script or the user calls
  for it, by copying its "setting" and one of its "value"s; leave the rest out and they keep their defaults.
  - Quality: low for a draft, a test or "quickly"; medium for normal work; high for a final, a client or "best quality".
  - Speed: normal together with high quality for a final; fast otherwise.
  - Mode (engine): first_frame only when the shot starts on a picture ("start_from", "after", or an attached first frame)
    that must stay exactly as it is and only move (a podcast set, a fixed product shot, "animate this photo"); reference
    in every other case, including a shot made from words alone.
  - Music: put the seconds it must last in "duration" (the shots of this plan added up, the attached video, or what the
    user asked for); the length is then set to the shortest choice that covers it.
  - An image model's aspect ratio or size: the one that fits where the picture will be used, as for "orientation".
- "why": one short line for the user saying what you decided that they did not tell you, and why, in plain words:
  "7 s for two lines of dialogue; portrait for Reels". Leave it empty when the user set everything themselves.
- For one longer continuous video of the same action, use a single step with "clips" above 1 on a workflow that allows
  it, instead of several steps. "duration" is the length of each clip, so the video lasts duration times clips: for
  30 seconds use duration 6 and clips 5, and keep each clip between 5 and 8 seconds. Otherwise clips is 1.
- A step can start on the result of an earlier step of the same plan: set "after" to that step's number (1 for the first
  step), otherwise 0. The later step then begins on the earlier picture, or on the last frame of the earlier video. Use it:
  when the user asks to make a picture and then animate it (step 1 makes the image, step 2 is a video with "after": 1);
  and when shots follow one another in the same place with the same person ("she arrives, then she waits, then she
  leaves"), so that each shot continues the one before. A step with "after" must be a video on a workflow whose
  "start_from" is allowed or required, and its "start_from" stays 0. Do not chain shots that are in different places.
  A shot takes the shape of the picture it starts on, so decide the orientation in the first step of a chain.
- Write each "prompt" as a concrete shot: subject, action, setting, camera, light, and sound if it matters. One to three sentences.
- Never write the settings into a prompt: no resolution ("480p"), quality ("low quality", "draft"), length, orientation or
  aspect ratio. Those are set by the step's fields; in the prompt the model would try to draw them.
- A workflow's "prompt_tips" say how its model wants prompts written. Follow them in every prompt for that workflow.
- One shot is ONE action in one place: a 5 second clip cannot show more. When the user lists several actions in a row
  ("she runs through the market, jumps over a crate, turns into an alley and hides behind a door"), plan one step for
  each action, in order (four steps for that example), each prompt describing only its own action.
- When the kit has always-on entries, name them in the prompt with the words given for them ("the main character",
  "the outfit", "the background") and do not describe their looks: the reference files carry the looks.
- When the kit has nothing for a shot and nothing is attached, never ask for a picture: plan the shot from words. Describe the person
  and the place in a few concrete words (age, hair, clothes; the kind of place), and when a plan has several steps
  with the same person or place, repeat that same description word for word in every step so the shots match.
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
- Plan as few steps as the instruction needs, never more than {max_steps}.
- If what is asked cannot be done with these workflows, return no steps and say what you can do instead.
- With a plan, "reply" is one or two plain sentences about it. No praise, no filler. Speak only of the steps this answer
  has: never list steps you did not plan, never number them in the reply, and never ask the user to type "approve": the
  plan shows its own Approve button.

Your answer:
- "thought": two to four short sentences for the user about what you weighed before answering: what they asked for, and
  what you chose and why (the workflow, the length, the shape, the references). Plain words, no lists. It is shown
  folded above your reply, so do not say it again in "reply".
- "reply" may use **bold** for a few key words and a short list with "- " at the start of each line. No headings and no
  tables. To show an item of the asset book or an attached item as a small picture, write [[item:<its id>]]; for a
  saved asset write [[asset:<its id>]]. Use only ids you were given."""


IMPROVE = """You rewrite prompts for an AI {kind} model inside Scene.ai. You are given the user's prompt and you return a better one.
{tips}
Rules:
- Keep everything the user asked for: the subject, the action, the setting and any style or detail they named. Never change what the {what} is about.
- Add what a good prompt needs and the user left out: {needs}
- When always-on references are listed, name them with the words given for them and do not describe their looks. When
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
- "name" is a short name for the video, two to four words."""
DESCRIBE = """You look at pictures for the asset book of Scene.ai, a studio for making images and video with AI. The
description you write is all the planning assistant will know about the picture when it later decides where to use it
as a reference, so say what matters for that.
- Say what it is first: a person, an outfit, a place, an object or product, a logo, a style sample.
- For a person: apparent age, gender as seen, hair, face, skin tone, build, clothes and their colours.
- For a place: indoor or outdoor, what kind of place, time of day, weather, the main colours.
- For an object: what it is, its colours, materials, any words or logo printed on it.
- Then the look: photograph, 3D render, illustration, painting; the light and the mood; the framing (close-up, full body, wide).
- Two or three plain sentences, at most 60 words. No guesses about who a real person is, no names, no opinions."""

REVIEW = """You review shots for Scene.ai, a studio for making images and video with AI, the way a film director checks
a take. You are given the prompt the shot was made from and pictures, each named in the message: reference pictures
the shot was made with (a character, a place, a product), sometimes the last frame of the shot before, and the result:
one picture, or four frames of a clip in order.

Make five checks, each "fine", "minor" or "major":
- "who": the people are the right ones. Compare faces, age, hair, skin and clothes with their reference pictures. A
  different face or a clearly different age is major.
- "what": the result shows what the prompt asked: the action, the place, the framing and the camera. A missing
  action, the wrong place or the wrong number of people is major; a small difference in framing is minor.
- "clean": no broken or extra fingers, melted faces, garbled letters or watermarks, nothing important cut off at the
  edge. Broken hands or a broken face in plain view are major.
- "coherence": through the frames of a clip, the same face, clothes, props and light; people and things move in a way
  that could happen. A face or an outfit that changes during the clip is major.
- "continuity": only when the last frame of the shot before is given: the same outfit, props, place and time of day,
  and a cut from it that does not jump. Otherwise "fine" with the note "no shot before".
Each check has a "note": what you saw, in a few plain words. Do not invent problems: when it is right, say "fine".
Small flaws a viewer would not notice are "minor".

"problem": when any check is major, one plain sentence for the user saying what is wrong, naming the shot's subject
("She looks about 13, older than in her reference picture"). Empty otherwise.
"fix": when any check is major, how to retake it: "prompt" is the shot's prompt rewritten to avoid the problem (keep
everything that was right; for a wrong face say plainly to keep the face of the person in the reference picture; for
garbled text remove the text from the prompt; for broken hands frame the shot so the hands are out of view or
resting); "start_from_previous" is true only when the cut from the shot before jumps and the retake should start on
its last frame; "why" is a few words on what the fix changes. With no major check, leave the fix empty."""

SCENES_FORMAT = {"type": "object", "required": ["name", "look", "orientation", "scenes"], "properties": {
    "name": {"type": "string"},
    "look": {"type": "string", "enum": list(sequence.LOOKS)},
    "orientation": {"type": "string", "enum": list(ORIENTATIONS)},
    "scenes": {"type": "array", "items": {"type": "object", "required": ["kind", "heading", "text", "items"], "properties": {
        "kind": {"type": "string", "enum": list(sequence.KINDS)}, "heading": {"type": "string"}, "text": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}}}}},
}}


# The one structure every prompt of a picture or a video follows, whoever writes it: the agent's plans and Improve prompt.
STRUCTURE_GUIDE = """Prompt structure. Write every "prompt" of a picture or a video in this structure: these sections in this
order, with these labels written the same way. Fill each <...> with what this shot needs and keep the angle brackets out.
When the shot has reference pictures, say in REFERENCES what to take from each and for whom. Leave out a section that has
nothing in this shot. This structure wins over any other advice on how to lay out a prompt.
<<<
{structure}
>>>"""
PROMPT_STRUCTURE = """SCENE CONTEXT: <who the shot is about> <what they do> at <the place> during <the moment> — <what is going on around them>.
REFERENCES: <the person or thing in it> reference — take only <what to take: face, outfit, look, layout> for <who or what in the shot>; <the next one> reference — take only <...> for <...>.
ACTION: <what happens, beat by beat, in the order it happens; who moves, how, and what they react to>.
CAMERA: <framing and lens feel; how the camera moves, or that it stays still>.
LIGHT AND LOOK: <light sources, time of day, colours, texture, mood>.
AUDIO: <what is heard: room sound, effects, music; spoken words in quotation marks>, or "silent"."""


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


TOOLS = ("find_assets", "look", "check_shots", "review", "save_note", "kit_save", "state_read", "state_write", "state_check",
         "film", "import_url", "transcript", "timing", "read_text", "read_skill", "finish")
TOOL_ROUNDS = 6   # a message is answered in at most this many calls to the model
RUN_ROUNDS = 40   # ...or this many while a long skill runs: it reads and writes its state and cuts its media as it goes
TOOL_RESULT = 8000   # characters of a tool's result the model is given back
QUESTION_OPTIONS = 4

TOOL_RULES = """How you work now: you answer in steps, one call at a time, and each answer names a "tool". The server runs
the tool and tells you the result, and then you answer again. Fill every field; the ones the tool does not read stay
"", 0 or []. The tools:
- find_assets: "query" is words; you get the asset book's entries that match. Use it before you say the book has nothing.
- look: "item" or "asset" is an id; you get what is in that picture or clip.
- check_shots: "steps" is your plan; you get each step checked and priced, and the ones that cannot run with the reason.
  Do this before you finish when a plan is more than one or two steps, and fix what it says.
- review: "item" is an id of something made; you get the checks of it.
- save_note: "text" is the whole direction (see "Direction" in the message), kept for the next messages.
- kit_save: keeps something in the project's kit, or names an entry. "text" is its name ("Violet"), "op" its type
  (character, location, prop, outfit, voice, style, script); "item" a library id to add (a sheet you made, a file the
  user attached) or "asset" the kit entry to change; "value" what it shows, when you know better than the kit; and
  "settings" "always" to attach it to every shot of the project. You get its asset id.
- state_read: "path" (/motion/chunks/c3) and "offset"; you get the value kept there, or every leaf under a folder, a
  page at a time. state_write: "path" and "value", the JSON text to keep there (it replaces what was there); a path
  ending in /* and a value that is an object of name: value write every leaf of that folder at once. A run's
  state is the one place its steps take their inputs from: read it, never what you remember of the chat. state_check:
  "path" and "against" (two folders); you get which names under "against" have nothing under "path".
- film: "op" and "settings", JSON text of the operation's fields; it is done on this machine, costs nothing, and you
  get the library ids of what it made. op: reference {"image"} (longer side 1500 px) · slice {"audio", "f_in", "f_out"}
  · track {"frames": [per block]} · trim {"video", "frames", "stretch"?, "size"?} · retime {"video", "frames",
  "lines": [{"master": [s, e], "clip": [s, e]}]} · proof {"video", "marks": [{"at", "label"}]} · subtitles {"video",
  "lines": [{"start", "end", "text", "speaker", "lead"}]} · film {"clips": [ids], "audio"} · speech {"audio", "lines":
  [{"n", "start", "end", "speaker"}], "narrator"?: the narrator's speaker label, "save_to"?: a folder for the spans}
  or {"audio", "windows": [[a, b]]}. Ids are library ids; "$state:/path" stands for the id kept at that path, and
  "$state:/folder/*" for every leaf of a folder (lines: "$state:/motion/transcript/lines/*").
- import_url: "text" is a link to a picture, clip or sound on another site (a link in the chat, a tracker row) and
  "query" the name to file it under; you get its library id. Only public web links are fetched.
- read_skill: "op" is a skill's id and "query" one of its parts (its number or heading), "offset" where to start; you get
  that part, a page at a time. A skill too long to give you whole lists its parts: read each before you act on it.
- read_text: "item" is a text in the library (a script or a document the user attached, a transcript) and "offset"
  where to start; you get its words, a page at a time. With "path" as well, the whole text is kept in the run's state
  there (the script: /motion/inputs/script), word for word, so you need not copy it.
- transcript: "item" is a transcript in the library (a transcription's JSON, or an .srt) and "path" a folder; every
  line is written there as path/<n> = {"start", "end", "speaker", "text"}, n from 1, times exactly as the file has them.
  With "item" 0 and "value" the JSON text {"<n>": "<speaker>"}, it names who speaks the lines at "path" (a
  transcription without speakers says SPEAKER_00 for all): only the speakers change, never a time or a word.
- timing: "settings" is JSON text {"units", "lines", "speech", "length", "save_to"} — the folders of the plan's units
  (each with "from": L<n>, sfx@<s>, gap@L<n>, gap@start or gap@end), of the lines and of the speech spans, the
  master's length in seconds, and the folder for the result; every unit's {"f_in", "f_out"} is written there by the
  clock rules, and you get the problems to fix (a shot too short or too long, a line that is not there).
- finish: your answer for the user: "thought", "reply", "steps" and "direction". If a step cannot run you get the reason
  back instead, and you finish again.
Nothing is generated by these tools (film only cuts what exists): generating starts only when the user approves the
steps you finish with. Finish as soon as
you know enough; most messages need one or two tool calls, or none."""


CALL_FIELDS = ("query", "item", "asset", "text", "path", "value", "against", "offset", "op", "settings")

COMPACT_RULES = """Each answer of yours now is one tool call: {"tool": <its name>, "args": {<that tool's fields>}}. Put only the
fields the tool reads in "args" ("query", "item", "path", "value", "settings" and so on, as the tools above say; "steps" for
check_shots). When you have all you need, answer {"tool": "finish", "args": {}}: you are then asked for your answer to the
user in a call of its own."""

FINISH_NOW = ("Now give your answer to the user: thought, reply, steps, direction and question, in the shape asked. Plan only what "
              "the work so far supports.")


S, I = {"type": "string"}, {"type": "integer"}
# Each tool's own fields, the required ones first: (required, optional). A local model is held to exactly these, so a
# field cannot land in the wrong place (a part number in "settings", say).
TOOL_ARGS = {
    "find_assets": ({"query": S}, {}),
    "look": ({}, {"item": I, "asset": I}),
    "check_shots": ({"steps": {"type": "array", "items": {"type": "object"}}}, {}),
    "review": ({"item": I}, {}),
    "save_note": ({"text": S}, {}),
    "kit_save": ({"text": S, "op": S}, {"item": I, "asset": I, "value": S, "settings": S}),
    "state_read": ({"path": S}, {"offset": I}),
    "state_write": ({"path": S, "value": S}, {}),
    "state_check": ({"path": S, "against": S}, {}),
    "film": ({"op": S, "settings": S}, {}),
    "import_url": ({"text": S}, {"query": S}),
    "transcript": ({"path": S}, {"item": I, "value": S}),
    "timing": ({"settings": S}, {}),
    "read_text": ({"item": I}, {"offset": I, "path": S}),
    "read_skill": ({"op": S, "query": S}, {"offset": I}),
    "finish": ({}, {}),
}


def compact_tool_format(names=None):
    """The small shape of one tool call, for a local model: one of the tools, with exactly that tool's fields in
    "args". names: the tools on offer (finish is always one)."""
    shapes = []
    for name in [n for n in TOOLS if names is None or n in names or n == "finish"]:
        required, optional = TOOL_ARGS.get(name, ({}, {}))
        shapes.append({"type": "object", "required": ["tool", "args"], "additionalProperties": False, "properties": {
            "tool": {"type": "string", "enum": [name]},
            "args": {"type": "object", "required": list(required), "additionalProperties": False, "properties": {**required, **optional}}}})
    return {"anyOf": shapes}


def tool_format(workflow_ids):
    """The JSON shape of one call: the tool and its fields beside the fields of a finished answer."""
    base = reply_format(workflow_ids)
    extra = {"tool": {"type": "string", "enum": list(TOOLS)}, "query": {"type": "string"}, "item": {"type": "integer"},
             "asset": {"type": "integer"}, "text": {"type": "string"}, "path": {"type": "string"}, "value": {"type": "string"},
             "against": {"type": "string"}, "offset": {"type": "integer"}, "op": {"type": "string"}, "settings": {"type": "string"}}
    return {"type": "object", "required": [*extra, *base["required"]], "properties": {**extra, **base["properties"]}}


REPLY_CHARS = 8000   # a reply may carry a table a skill posts for review: an asset, anchor or clips table


def clean_question(question):
    """A question the user answers with a button: {"text", "options"} with two to four short options, or None."""
    if not isinstance(question, dict):
        return None
    text = " ".join(str(question.get("text") or "").split())[:300]
    options = []
    for option in question.get("options") if isinstance(question.get("options"), list) else []:
        option = " ".join(str(option or "").split())[:80]
        if option and option.lower() not in (o.lower() for o in options):
            options.append(option)
    return {"text": text, "options": options[:QUESTION_OPTIONS]} if text and len(options) >= 2 else None


def shaped(answer):
    """A model's answer as the agent returns it: {"thought", "reply", "steps", "model", "direction", "question"}."""
    steps = answer.get("steps")
    reply = str(answer.get("reply") or "").strip()[:REPLY_CHARS]
    if answer.get("_stood_in"):   # say so when another model answered than the one that was picked
        reply = "{} ({})".format(reply, answer["_stood_in"]).strip()
    thought = str(answer.get("thought") or "").strip()[:800]   # shown folded above the reply
    return {"thought": thought, "reply": reply, "steps": steps if isinstance(steps, list) else [], "model": answer.get("_model"),
            "direction": clean_direction(answer.get("direction")), "question": clean_question(answer.get("question"))}


def tokens_of(answer):
    """What one answer of a hosted model cost: {"prompt", "cached" (of the prompt, read from the service's cache),
    "answer"} in tokens, as the OpenAI chat API reports them (zeros when the service does not say)."""
    usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    number = lambda v: int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    return {"prompt": number(usage.get("prompt_tokens")), "cached": number(details.get("cached_tokens") or usage.get("cached_tokens")),
            "answer": number(usage.get("completion_tokens"))}


def add_tokens(total, more):
    for key in ("prompt", "cached", "answer"):
        total[key] = total.get(key, 0) + int((more or {}).get(key) or 0)
    return total


class AgentBusy(AgentError):
    """A hosted model is overloaded or out of quota for the moment: worth another try, or another model."""


BUSY = re.compile(r"high demand|overloaded|try again later|temporarily|unavailable|rate limit|quota|resource.exhausted", re.IGNORECASE)


DIRECTION_CHARS = 3000   # the durable notes of a conversation, kept whole and sent with every message

COMPACT = """You keep the notes of a film studio's assistant. Fold the conversation into the Direction: short durable notes
that the assistant reads before every message, in place of the old turns. Keep: what is being made and for whom, the style
and look, the people and places with the names they were given, the shot list as agreed (numbered, one line each, marking
which are made), the length and shape, and what the user turned down or insisted on. Keep names exactly. Drop greetings,
repeats and anything that was changed later. Plain lines, no more than 2,500 characters. Write only the notes."""


PREFLIGHT_CHARS = 40_000   # how much of a skill the check reads: the inputs and the rules come first in a skill

PREFLIGHT = """You check whether a studio's assistant can start the work a skill describes. The skill is a procedure someone wrote;
it may say what must be in hand before it starts, and it may name models and tools. Decide from the skill, what the studio can
do, what is attached, the conversation so far and the new message.
- "missing": what the skill itself says it must have before it starts and the user has not given: files (audio, video, images),
  a script or text, a link. Only what the skill really requires, in the skill's own words. A script, an article or any text is
  given when it is pasted in the conversation (a few lines at least) or attached as a text (a document the user uploaded);
  audio, video and images are given only when attached or already in the project. Never treat a summary as the thing itself.
  An attached sound is the audio the skill asks for, and an attached text the script, unless what is said of it shows it is
  something else (a sound of a few seconds is no episode; a text that begins like a list or a letter is no script). A file's
  name proves nothing either way, and whether a sound is the "final mix" cannot be heard here: take the user's word for it.
- "unsupported": parts the skill depends on that the studio cannot do: anything that "What the studio can do" does not list
  (a workflow, a tool, an ability), judged by what it does, not by its name: a skill's own tool names (ffmpeg jobs, a sandbox, a
  state store, structured questions) are supported when the list has a tool that does the same. Name each plainly. Leave out
  what a plain generation, edit or timeline step can stand in for only when the skill does not insist on it.
- If the conversation shows the user was already told about a gap and chose to go on (or gave the thing now), it is not blocking
  any more: say in "adaptation" what will be done instead, in one or two sentences.
- "ready" is true only when nothing is missing and every unsupported part has been agreed or is not essential.
- "message": what to say to the user when not ready. Plain and short. First ask for exactly what is missing, as a list. Then
  say what this studio cannot do from the skill and what it can do instead, and ask whether to go on that way. No plan, no
  promises of work."""


def clean_direction(text):
    """The direction as kept: one string, lines trimmed, at most DIRECTION_CHARS."""
    if not isinstance(text, str):
        return ""
    return chr(10).join(line.rstrip() for line in text.strip().splitlines())[:DIRECTION_CHARS]


def reply_format(workflow_ids):
    """The JSON shape the model must answer in."""
    # Every field is required so the model has to decide each one; values a workflow can't take are dropped later.
    step = {"type": "object", "required": ["tool", "workflow", "name", "prompt", "resolution", "orientation", "duration", "clips",
                                           "start_from", "after", "uses", "source", "start", "end", "parts", "audio", "replace", "scenes", "look",
                                           "choices", "keep", "shot_size", "angle", "move", "end_state", "why"], "properties": {
        "tool": {"type": "string", "enum": ["generate", *EDIT_TOOLS, SOUND_TOOL, ASSEMBLE_TOOL, *MOTION_TOOLS]},
        "workflow": {"type": "string", "enum": workflow_ids},
        "name": {"type": "string"},
        "prompt": {"type": "string"},
        "resolution": {"type": "integer"},
        "orientation": {"type": "string", "enum": list(ORIENTATIONS)},
        "duration": {"type": "number"},
        "clips": {"type": "integer"},
        "start_from": {"type": "integer"},
        "after": {"type": "integer"},
        "uses": {"type": "array", "items": {"type": "object", "required": ["item", "asset", "slot"],
                                            "properties": {"item": {"type": "integer"}, "asset": {"type": "integer"}, "slot": {"type": "string"}}}},
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
        "choices": {"type": "array", "items": {"type": "object", "required": ["setting", "value"],
                                               "properties": {"setting": {"type": "string"}, "value": {"type": "string"}}}},
        "leave_out": {"type": "array", "items": {"type": "integer"}},
        "keep": {"type": "object", "required": ["as", "name"], "properties": {
            "as": {"type": "string", "enum": ["", "character", "outfit", "location", "prop", "voice", "style"]}, "name": {"type": "string"}}},
        "shot_size": {"type": "string", "enum": camera.choices("shot_size")},
        "angle": {"type": "string", "enum": camera.choices("angle")},
        "move": {"type": "string", "enum": camera.choices("move")},
        "end_state": {"type": "string"},
        "why": {"type": "string"},
    }}
    # "question": one the run must stop for, answered by a button (two to four short options); "" and [] otherwise
    question = {"type": "object", "required": ["text", "options"], "properties": {
        "text": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}}}
    return {"type": "object", "required": ["thought", "reply", "steps", "direction", "question"], "properties": {
        "thought": {"type": "string"}, "reply": {"type": "string"}, "steps": {"type": "array", "items": step},
        "direction": {"type": "string"}, "question": question}}


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

    def __init__(self, url, model="", services=(), local="", options=None):
        self.url = url.rstrip("/")
        self.model = model
        # The local models to offer, when not every model Ollama has (it may also hold models for other uses).
        self.local = [m.strip() for m in str(local or "").split(",") if m.strip()]
        self.services = {s["id"]: s for s in services if s["url"] and s["key"]}   # without a key a service is not offered
        # How local models are run (config.json: ollama_context, ollama_timeout, ollama_keep_alive, ollama_vision_model,
        # ollama_fast_model, ollama_think, local_tools).
        options = options or {}
        self.context = max(4096, int(options.get("context") or LOCAL_CONTEXT))
        self.keep_alive = str(options.get("keep_alive") or "2h")
        self.vision = str(options.get("vision") or "").strip()
        self.fast = str(options.get("fast") or "").strip()
        self.think = bool(options.get("think"))
        self.tools = options.get("tools", True) is not False
        self.seen = {}   # local model -> what it can do ("vision", "tools", "thinking"), as Ollama says
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(max(60, int(options.get("timeout") or 600)), connect=5))
        self.gpu = gpu.Gate(lambda: False)   # the GPU it may share with the renders (main.py sets the real one)

    def is_local(self, model):
        return self._service_of(model or self.model)[0] is None

    def uses_tools(self, model):
        """Whether a model works in the loop of tool calls: a hosted one always, a local one unless local_tools is off."""
        return not self.is_local(model) or self.tools

    def reads(self, model):
        """The tokens a local model reads at once: ollama_context, the same for every model (the user's choice)."""
        return self.context

    def skill_room(self, model):
        """How many characters of a skill a model is given whole; a longer skill is read in parts (read_skill)."""
        return None if not self.is_local(model) else int(self.reads(model) * CHARS_PER_TOKEN * SKILL_SHARE)

    def helper(self, model):
        """The model for the small jobs (a better prompt, a caption, the notes, the check of a skill): the fast local model
        when one is set and a local model is in use, else the one in use."""
        return self.fast if self.fast and self.is_local(model) else model

    async def abilities(self, name):
        """What a local model can do, as Ollama says ({"vision", "tools", "thinking", ...}); remembered."""
        if name not in self.seen:
            try:
                shown = (await self.http.post(self.url + "/api/show", json={"model": name})).json()
                found = set(shown.get("capabilities") or [])
                if not found and "clip" in ((shown.get("details") or {}).get("families") or []):
                    found = {"completion", "vision"}   # an older Ollama: a model with an image encoder can see
                self.seen[name] = found
            except (httpx.HTTPError, ValueError, AttributeError):
                return set()
        return self.seen[name]

    async def seeing(self, model):
        """The model that looks at pictures for this one: itself when it can see (or is hosted), else ollama_vision_model,
        else the first local model that can see. Raises AgentError when no local model can."""
        if not self.is_local(model) or "vision" in await self.abilities(model):
            return model
        if self.vision and "vision" in await self.abilities(self.vision):   # the one set, while Ollama still has it
            return self.vision
        try:
            every = [m["name"] for m in (await self.http.get(self.url + "/api/tags")).json().get("models") or [] if m.get("name")]
        except (httpx.HTTPError, ValueError, AttributeError):
            every = []
        offered = [m for m in every if not self.local or m in self.local]
        for name in offered + [m for m in every if m not in offered]:
            if "vision" in await self.abilities(name):
                return name
        raise AgentError("No local model can look at pictures. Pull one that can (a vision model) in Ollama, or set ollama_vision_model.")

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
        self.sizes = {m["name"]: m.get("size") or 0 for m in found if isinstance(m, dict) and m.get("name")
                      and (not self.local or m["name"] in self.local)}
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
        """The model to use: the one asked for if Ollama (or a hosted service) has it, else the configured one if it is
        there, else the first one there is. Models come and go as they are pulled and removed: none is assumed."""
        try:
            names = await self.models()
        except AgentError:
            if wanted or self.model:
                return wanted or self.model   # the server is not answering: the call itself says so
            raise
        if not names:
            raise AgentError("There is no model for the agent. Pull one in Ollama (ollama pull <model>) or set an API key.")
        return next((name for name in (wanted, self.model) if name and name in names), names[0])

    async def chat(self, messages, answer_format, context=None, model=None, images=(), think=False):
        """Send messages to the model and return its answer, which has to be JSON of the given shape.
        context: room for the conversation in tokens, when the instructions are longer than a local model's default.
        model: the model the user picked; the usual one when it is not given or not there.
        images: JPEG pictures (base64) the model looks at with the last message. A model that cannot see fails."""
        model = await self.pick_model(model)
        if images:   # a local model that cannot see hands the pictures to one that can
            model = await self.seeing(model)
        hosted, name = self._service_of(model)
        stood_in = None
        # Ollama takes pictures beside the words of a message; the OpenAI chat API takes them as parts of its content.
        local_messages = [*messages[:-1], dict(messages[-1], images=list(images))] if images else messages
        hosted_messages = [*messages[:-1], dict(messages[-1], content=[{"type": "text", "text": messages[-1]["content"]}, *(
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + picture}} for picture in images)])] if images else messages
        if hosted:
            try:
                content, usage = await self._ask_hosted(hosted, name, hosted_messages, answer_format)
            except AgentBusy:
                # The hosted model is busy and a second try did not help: the smallest local model answers instead.
                local = await self._local_models()
                if not local:
                    raise
                stood_in = min(local, key=lambda n: self.sizes.get(n) or 0)
                content, usage = await self._ask_local(stood_in, local_messages, answer_format, context)
        else:
            content, usage = await self._ask_local(model, local_messages, answer_format, context, think=think and self.think)
        try:
            answer = json.loads(_unfenced(content))
        except (ValueError, TypeError):
            raise AgentError("The agent's model gave an answer that can't be read. Try again.")
        if not isinstance(answer, dict):
            raise AgentError("The agent's model gave an answer that can't be read. Try again.")
        if stood_in:
            answer["_stood_in"] = "{} was busy, so {} answered.".format(hosted["name"], stood_in)
        answer["_model"] = stood_in or model   # what the message is charged at
        answer["_usage"] = usage
        return answer

    async def _ask_local(self, model, messages, answer_format, context, think=False):
        # One context size for every call. Without one Ollama cuts a long prompt from its start (the instructions), and a
        # call with another size than the last makes it load the model again and lose what it had already read.
        size = max(self.context, context or 0)
        # Ollama does not refuse a prompt longer than its context: it drops the start, which is the instructions. So a
        # prompt that cannot fit is refused here, saying what to do, instead of being answered without them.
        guess = sum(len(str(m.get("content") or "")) for m in messages) / CHARS_PER_TOKEN
        if guess > size * 0.97:
            raise AgentError("This message is too long for {}: about {:,} tokens, and it reads {:,}. Compact the conversation, "
                             "or give it a larger context (ollama_context in config.json).".format(model, int(guess), size))
        # Thinking is asked only of a model that can think: Ollama refuses it from one that cannot.
        think = bool(think) and "thinking" in await self.abilities(model)
        payload = {"model": model, "stream": False, "think": think, "format": answer_format, "keep_alive": self.keep_alive,
                   "options": {"temperature": 0.4, "num_ctx": size}, "messages": messages}
        async with self.gpu.use("llm"):
            body = await self._post_local(model, payload)
        if body.get("error"):
            raise AgentError("The agent's model failed: {}".format(str(body["error"])[:200]))
        usage = {"prompt": int(body.get("prompt_eval_count") or 0), "cached": 0, "answer": int(body.get("eval_count") or 0)}
        return (body.get("message") or {}).get("content"), usage

    async def _post_local(self, model, payload):
        """Send one chat to Ollama, trying again while it starts or loads the model."""
        for wait in (*LOAD_RETRIES, None):
            try:
                body = (await self.http.post(self.url + "/api/chat", json=payload)).json()
            except httpx.TimeoutException:
                raise AgentError("{} took longer than {:.0f} s to answer. Raise ollama_timeout in config.json, or use a quicker "
                                 "model.".format(model, self.http.timeout.read or 0))
            except (httpx.HTTPError, ValueError):
                if wait is None:
                    raise AgentError("The agent's model server (Ollama) can't be reached at {}.".format(self.url))
                await asyncio.sleep(wait)   # it may be starting
                continue
            problem = str(body.get("error") or "")
            if problem and wait is not None and re.search(r"load|busy|try again|unavailable|server.*(overload|not ready)", problem, re.I):
                await asyncio.sleep(wait)   # the model is being loaded, or another call has it
                continue
            break
        return body

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
                    return answer["choices"][0]["message"]["content"], tokens_of(answer)
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

    async def improve(self, prompt, kind="video", model=None, tips=(), project_cast=None, structure=""):
        """A fuller version of a prompt the user wrote, for an image, a video or a music model.
        tips: how the chosen workflow's model wants prompts written. project_cast: the project's pinned references.
        structure: the prompt structure the new prompt follows (PROMPT_STRUCTURE)."""
        advice = ("\nAdvice on what works with this model. Use it to shape the prompt, but never mention the advice, "
                  "reference images or consistency in the prompt itself:\n{}\n").format("\n".join("- " + str(t)[:220] for t in tips[:6])) if tips else ""
        system = IMPROVE.format(kind=kind, tips=advice, **IMPROVE_KINDS[kind])
        if structure:   # the studio's prompt structure wins over "plain sentences, no headings"
            system += "\n\n" + STRUCTURE_GUIDE.format(structure=structure)
        message = "Always-on references:\n{}\n\nPrompt:\n{}".format(kit.described(project_cast or []) or "(none)", prompt)
        answer = await self.chat([{"role": "system", "content": system}, {"role": "user", "content": message}],
                                 {"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string"}}},
                                 **({"model": self.helper(model)} if self.helper(model) else {}))
        better = str(answer.get("prompt") or "").strip().strip('"').strip()
        if not better:
            raise AgentError("The agent's model gave no prompt back. Try again.")
        return better[:2000]

    async def write_scenes(self, about, model=None):
        """A whole motion graphics video written from what it is about: {"name", "look", "shape", "scenes"}.
        The scenes are as the model gave them, less the ones it made up; sequence.clean_scenes checks them."""
        message = "The video is about:\n{}".format(about)
        answer = await self.chat([{"role": "system", "content": WRITE_SCENES}, {"role": "user", "content": message}],
                                 SCENES_FORMAT, **({"model": model} if model else {}))
        return {"name": " ".join(str(answer.get("name") or "").split())[:80],
                "look": answer.get("look") if answer.get("look") in sequence.LOOKS else "dark",
                "shape": answer.get("orientation") if answer.get("orientation") in ORIENTATIONS else "landscape",
                "scenes": [s for s in answer.get("scenes") if founded(s, about)] if isinstance(answer.get("scenes"), list) else []}

    async def describe(self, picture, name="", kind="image"):
        """What a picture shows, in two or three sentences, for the asset book. picture: a JPEG, base64.
        kind: "image", or "video" when the picture is a frame of one. Uses the usual model, which must be able to see."""
        answer = await self.chat([{"role": "system", "content": DESCRIBE},
                                  {"role": "user", "content": "The {} is called \"{}\". Describe it.".format(
                                      "video this frame is from" if kind == "video" else "picture", name or "untitled")}],
                                 {"type": "object", "required": ["shows"], "properties": {"shows": {"type": "string"}}}, images=[picture])
        shows = " ".join(str(answer.get("shows") or "").split())
        if not shows:
            raise AgentError("The agent's model gave no description back.")
        return shows[:600]

    async def review(self, pictures, labels, prompt, kind="video"):
        """The model's checks of a result, as review.verdict_from reads them. pictures: JPEGs (base64), in the order of
        labels, which say what each one is ("reference: Meera", "the result at 2.0 s")."""
        named = "\n".join("Picture {}: {}".format(number, label) for number, label in enumerate(labels, start=1))
        message = "The {} was made from this prompt:\n{}\n\nThe pictures, in order:\n{}\n\nReview it.".format(
            "clip" if kind == "video" else "picture", prompt or "(no prompt)", named)
        check = {"type": "object", "required": ["check", "level", "note"], "properties": {
            "check": {"type": "string", "enum": ["who", "what", "clean", "coherence", "continuity"]},
            "level": {"type": "string", "enum": ["fine", "minor", "major"]}, "note": {"type": "string"}}}
        shape = {"type": "object", "required": ["checks", "problem", "fix"], "properties": {
            "checks": {"type": "array", "items": check}, "problem": {"type": "string"},
            "fix": {"type": "object", "required": ["prompt", "start_from_previous", "why"], "properties": {
                "prompt": {"type": "string"}, "start_from_previous": {"type": "boolean"}, "why": {"type": "string"}}}}}
        return await self.chat([{"role": "system", "content": REVIEW}, {"role": "user", "content": message}], shape, images=pictures)

    async def caption(self, template, idea, ratio):
        """The structured JSON caption some image models are trained on, written from a plain prompt.

        template: the instructions the workflow ships for this, ending in a [USER] part with
        {{ratio}} and {{original_prompt}} in it.
        """
        system, _, user = template.partition("[USER]")
        user = user.strip() or "TARGET IMAGE ASPECT RATIO: {{ratio}} (width:height).\nUser idea: {{original_prompt}}"
        answer = await self.chat([{"role": "system", "content": system.strip()},
                                  {"role": "user", "content": user.replace("{{ratio}}", ratio).replace("{{original_prompt}}", idea)}],
                                 "json", context=CAPTION_CONTEXT, **({"model": self.helper(None)} if self.helper(None) else {}))
        answer.pop("_stood_in", None)   # a note of ours, not part of the caption
        if not answer:
            raise AgentError("The agent's model gave no caption back. Try again.")
        return json.dumps(answer, ensure_ascii=False, separators=(",", ":"))

    async def ask(self, system, message, workflow_ids, history=(), model=None):
        """One question to the model; returns its answer as {"thought": str, "reply": str, "steps": [...]}.
        history: the earlier turns of the conversation, as {"role", "content"} messages."""
        answer = await self.chat([{"role": "system", "content": system}, *history, {"role": "user", "content": message}],
                                 reply_format(workflow_ids), think=True, **({"model": model} if model else {}))
        return dict(shaped(answer), tokens=add_tokens({}, answer.get("_usage")))

    async def ask_with_tools(self, system, message, workflow_ids, tools, finishing=None, model=None, rounds=TOOL_ROUNDS):
        """The same question as ask(), answered in a loop of tool calls: the model looks things up, checks its shots and
        only then finishes. tools: {name: async function(call) -> str}, called with the model's answer; what it returns
        goes back to the model. finishing: async function(answer) -> a hint, when the finishing answer is wrong; the
        model is then asked to put it right. Nothing is made in the loop: the steps it ends with still wait for Approve.
        Returns what ask() returns, and "tools": the names of the tools it used.

        A local model calls its tools in a small shape ({"tool", "args"}) and gives its plan in a call of its own when it
        finishes: one large shape for every call is slow for it, and easy to get wrong. A long run is kept within a local
        model's context by shortening the oldest tool results."""
        compact = self.is_local(model)   # by its name: a hosted model is "<service>/<name>"
        messages = [{"role": "system", "content": system + "\n\n" + TOOL_RULES + ("\n\n" + COMPACT_RULES if compact else "")},
                    {"role": "user", "content": message}]
        shape, used, tokens = compact_tool_format(tools) if compact else tool_format(workflow_ids), [], {}
        answer, fixes, noticed = {}, 0, []
        for round_ in range(1, rounds + 1):
            if compact:
                self._fit(messages, model)
            asked = await self.chat(messages, shape, model=model, think=True)
            add_tokens(tokens, asked.get("_usage"))
            if compact:
                args = asked.get("args") if isinstance(asked.get("args"), dict) else {}
                call_in = {k: args.get(k) for k in CALL_FIELDS if args.get(k) not in ("", None)}
                call_in["steps"] = args.get("steps") if isinstance(args.get("steps"), list) else []
                call_in["tool"] = asked.get("tool")
            else:
                call_in = asked
            name = call_in.get("tool") if call_in.get("tool") in tools else "finish"
            last = round_ == rounds
            if name == "finish":
                if compact:   # the plan itself, in its own call with the plan's shape
                    self._fit(messages, model)
                    answer = await self.chat(messages + [{"role": "user", "content": FINISH_NOW}], reply_format(workflow_ids),
                                             model=model, think=True)
                    add_tokens(tokens, answer.get("_usage"))
                else:
                    answer = asked
                # A plan it cannot put right after FIX_ROUNDS hints stands as it is: what cannot run is left out.
                # An answer with nothing in it (a model that stops while it means to go on) is sent back first.
                # (a local model always sends a question, {"text": "", "options": []} when it has none to ask)
                empty = not str(answer.get("reply") or "").strip() and not answer.get("steps") and not clean_question(answer.get("question"))
                if last or fixes >= FIX_ROUNDS:
                    hint = None
                elif empty:
                    hint = EMPTY_FINISH.format(" ".join(str(answer.get("thought") or "").split())[:400] or "nothing")
                    noticed.append("empty")
                else:
                    hint = await finishing(answer) if finishing else None
                if not hint:
                    break
                fixes += 1
                result = hint
                call = {"steps": answer.get("steps") if isinstance(answer.get("steps"), list) else []}
            else:
                try:
                    result = await tools[name](call_in)
                except (KeyError, ValueError, TypeError):
                    result = "That call could not be run. Check its fields."
                call = {k: call_in[k] for k in CALL_FIELDS if call_in.get(k) not in ("", 0, None)}
                if name == "check_shots":
                    call["steps"] = call_in.get("steps") if isinstance(call_in.get("steps"), list) else []
                if not compact:   # a hosted model's every call carries a whole answer: the last one stands if the rounds run out
                    answer = asked
            used.append(name)
            messages += [{"role": "assistant", "content": json.dumps(dict(call, tool=name), ensure_ascii=False)[:6000]},
                         {"role": "user", "content": "Result of {}:\n{}".format(name, str(result)[:TOOL_RESULT])}]
        if not answer.get("reply") and not answer.get("steps") and compact and name != "finish":
            # the rounds ran out while it was still working: it gives its answer now, from what it has
            self._fit(messages, model)
            answer = await self.chat(messages + [{"role": "user", "content": FINISH_NOW}], reply_format(workflow_ids), model=model)
            add_tokens(tokens, answer.get("_usage"))
        return dict(shaped(answer), tools=used, tokens=tokens, empty_sent_back=len(noticed))

    def _fit(self, messages, model=None):
        """Keep a long run within a local model's context: the oldest tool results are shortened first (the newest
        KEEP_RESULTS stay whole), as the instructions and the question must stay as they are."""
        room = int(self.reads(model or self.model) * CHARS_PER_TOKEN * 0.9)
        size = lambda: sum(len(str(m.get("content") or "")) for m in messages)
        results = [i for i, m in enumerate(messages) if m["role"] == "user" and str(m["content"]).startswith("Result of ")]
        for i in results[:-KEEP_RESULTS] if len(results) > KEEP_RESULTS else []:
            if size() <= room:
                return
            content = messages[i]["content"]
            if len(content) > 500:
                messages[i] = dict(messages[i], content=content[:400] + "\n[... shortened to keep within the model's context: call the tool again if you need it]")

    async def preflight(self, skill, instruction, attached, available, turns=(), model=None):
        """Whether a skill can be started: {"ready", "missing", "unsupported", "adaptation", "message"}. skill: the skill as
        skills.load() gives it. attached: lines naming what is attached and what the asset book holds. available: what the
        studio can do (workflows and tools). turns: the conversation so far, from past_turns()."""
        said = "\n".join("{}: {}".format("User" if t["role"] == "user" else "You", t["content"]) for t in turns)
        message = ("The skill \"{}\":\n{}\n\nWhat the studio can do:\n{}\n\nAttached to the message and kept in the project:\n{}\n\n"
                   "The conversation so far:\n{}\n\nThe user's new message:\n{}").format(
            skill["title"], skill["text"][:self._preflight_chars(model)], available, attached or "(nothing)", said or "(none)", instruction)
        shape = {"type": "object", "required": ["ready", "missing", "unsupported", "adaptation", "message"], "properties": {
            "ready": {"type": "boolean"}, "missing": {"type": "array", "items": {"type": "string"}},
            "unsupported": {"type": "array", "items": {"type": "string"}}, "adaptation": {"type": "string"}, "message": {"type": "string"}}}
        answer = await self.chat([{"role": "system", "content": PREFLIGHT}, {"role": "user", "content": message}], shape,
                                 **({"model": self.helper(model)} if self.helper(model) else {}))
        lists = {k: [" ".join(str(x).split())[:200] for x in answer.get(k) or [] if str(x).strip()][:8] for k in ("missing", "unsupported")}
        ready = answer.get("ready") is True and not lists["missing"]
        return {"ready": ready, **lists, "adaptation": " ".join(str(answer.get("adaptation") or "").split())[:600],
                "message": str(answer.get("message") or "").strip()[:1500]}

    def _preflight_chars(self, model):
        """How much of a skill its check reads: its first PREFLIGHT_CHARS, or what the checking model holds, if less."""
        room = self.skill_room(self.helper(model))
        return PREFLIGHT_CHARS if room is None else min(PREFLIGHT_CHARS, room)

    async def compact(self, turns, direction="", model=None):
        """The conversation boiled down to a Direction: the durable notes (what the film is, the style, the people, the
        shot list, what was turned down) that replace the old turns. turns: from past_turns(). Returns the new text."""
        said = "\n".join("{}: {}".format("User" if t["role"] == "user" else "You", t["content"]) for t in turns)
        message = "Current direction:\n{}\n\nConversation to fold in, oldest first:\n{}\n\nWrite the new direction.".format(
            direction or "(none yet)", said or "(nothing)")
        answer = await self.chat([{"role": "system", "content": COMPACT}, {"role": "user", "content": message}],
                                 {"type": "object", "required": ["direction"], "properties": {"direction": {"type": "string"}}},
                                 **({"model": self.helper(model)} if self.helper(model) else {}))
        text = clean_direction(answer.get("direction"))
        if not text:
            raise AgentError("The agent's model gave no summary back. Try again.")
        return text


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


FITS = kit.FITS   # what a reference slot of each kind can be filled with from the library


def offer(schema, attached=True):
    """What the model is told about one workflow, or None if the agent can't use it.

    attached: the user selected items. Without any, a workflow that must be given reference files can't run."""
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    first_frame = (schema.get("slots") or {}).get("first_frame")
    required = [r for r in schema["refs"] if not r["optional"] and r["id"] != first_frame]
    if ("prompt" not in roles and not required) or (required and not attached):
        return None   # a workflow with no prompt works on a file it is given: without one it makes nothing
    needs_start = any(not r["optional"] and r["id"] == first_frame for r in schema["refs"])
    info = {"id": schema["id"], "title": schema["title"], "makes": schema["id"].split("/", 1)[0], "about": schema["description"][:200]}
    if "prompt" not in roles:
        info["prompt"] = "none: it works on the files it is given; leave the step's prompt empty"
    elif schema.get("prompt_optional"):
        info["prompt"] = "optional: notes only, may be empty"
    if schema.get("size") or "resolution" in roles:
        info["resolutions"] = schema["resolutions"]
    if schema.get("size"):
        info["default_resolution"] = schema["size"]["resolution"]
        info["orientation"] = "landscape, portrait or square; default " + schema["size"]["orientation"]
    if "duration" in roles:
        info["duration_seconds"] = "{} to {}: decide it from the shot (default {:g}){}".format(
            *SHOT_SECONDS, roles["duration"]["default"],
            "; decimals allowed: the clip has round(24 x seconds) frames" if roles["duration"]["type"] == "float" else "")
    choosable = choosable_settings(schema)
    if choosable:
        info["settings"] = choosable
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


def choosable_settings(schema):
    """The workflow's own settings the agent may decide: its option groups (mode, speed, quality) and its controls that
    offer a list of values (the length of a song, an aspect ratio). Each as {"setting", "about", "default", "choices"}."""
    found = [{"setting": o["id"], "about": o["label"], "default": o["default"],
              "choices": [{"value": c["id"], "means": str(c.get("hint") or c.get("label") or "")[:110]} for c in o["choices"]]}
             for o in schema["options"]]
    found += [{"setting": c["id"], "about": c["label"][:90], "default": str(c["default"]), "choices": [{"value": str(v)} for v in c["choices"]]}
              for c in schema["controls"] if not c["role"] and c.get("choices")]
    # Switches and words the workflow takes (lips follow the voice, the frames where shots cut, a song's lyrics, a
    # script): the model may set them too. Number knobs (steps, cfg) are left as the workflow has them.
    found += [{"setting": c["id"], "about": c["label"][:120], "default": str(c["default"])[:80],
               "value": "true or false" if c["type"] == "bool" else "any words"}
              for c in schema["controls"] if not c["role"] and not c.get("choices") and c["type"] in FREE_TYPES]
    return found


FREE_TYPES = ("bool", "string", "text")   # the kinds of a workflow's setting the model may set to its own value
FREE_CHARS = 4000


# Words in quotation marks: "double", curly, ‘single curly’ or 'single'. A single quote must not touch a letter on its
# outer side, so the apostrophe in "don't" or "the dog's bowl" is not taken for one.
QUOTED = re.compile("\"([^\"]+)\"|“([^”]+)”|‘([^’]+)’|(?<!\\w)'([^']+)'(?!\\w)")


def spoken_seconds(prompt):
    """The seconds the words spoken in a shot need: the words in quotation marks (double, curly or single), at a talking
    pace, with a beat before and after. 0 when nothing is said. An apostrophe inside a word ("don't") is not a quote."""
    said = " ".join(next(part for part in found if part) for found in QUOTED.findall(prompt))
    words = len(said.split())
    return math.ceil(words / WORDS_PER_SECOND + 2) if words else 0


def why(step):
    """The model's short reason for the settings it decided, as the plan shows it; empty when it gave none."""
    return " ".join(str(step.get("why") or "").split())[:200]


def apply_choices(schema, settings, choices):
    """Put the settings the model chose into job settings, keeping only settings the workflow has and values it offers."""
    options = {o["id"]: {c["id"] for c in o["choices"]} for o in schema["options"]}
    controls = {c["id"]: c["choices"] for c in schema["controls"] if not c["role"] and c.get("choices")}
    free = {c["id"]: c["type"] for c in schema["controls"] if not c["role"] and not c.get("choices") and c["type"] in FREE_TYPES}
    # A model sometimes names a setting by its label ("speed") instead of its id ("mode").
    labels = {o["label"].strip().lower(): o["id"] for o in schema["options"]}
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict):
            continue
        key, value = str(choice.get("setting") or ""), str(choice.get("value") or "").strip()
        if key not in options and key not in controls:   # an id always wins: H3's speed is "mode", its Mode is "engine"
            key = labels.get(key.strip().lower(), key)
        if key in options and value in options[key]:
            settings["options"][key] = value
        elif key in controls:
            match = next((v for v in controls[key] if str(v) == value), None)
            if match is not None:
                settings["values"][key] = match
        elif key in free:
            if free[key] == "bool":
                if value.lower() in ("true", "false", "on", "off", "yes", "no"):
                    settings["values"][key] = value.lower() in ("true", "on", "yes")
            else:
                settings["values"][key] = str(choice.get("value") or "")[:FREE_CHARS]


def uses_for(schema, step, selection, assets=None):
    """The selected items a step puts into reference slots, keeping only what the workflow can take.

    selection: {id: {"name", "kind"}}: library items. assets: the same for the user's saved assets, which the model
    names with "asset" instead of "item". Returns [{"id", "name", "slot", "label", "kind"}], kind being what the slot
    takes; a saved asset has "id" 0 and its own id in "asset". A library item put in the first-frame slot is written to
    the step's "start_from" instead."""
    assets = assets or {}
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
        saved = assets.get(use.get("asset")) if isinstance(use.get("asset"), int) and use.get("asset") > 0 else None
        slot, item = find(use.get("slot")), saved or selection.get(use.get("item"))
        if not slot or not item or slot["id"] in taken or item["kind"] not in FITS.get(slot["kind"], ()):
            continue
        if saved:   # a saved asset goes to the job by its id, whatever the slot, the first frame included
            if any(u.get("asset") == use["asset"] for u in used):
                continue
            taken.add(slot["id"])
            used.append({"id": 0, "asset": use["asset"], "name": saved["name"], "slot": slot["id"],
                         "label": slot["label"].split(" (")[0], "kind": slot["kind"]})
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
    # A workflow that works on a sound or a video (separate a voice, transcribe, lip sync) must be given it, and a model
    # often leaves the slot out: the item the step names in "audio" or "source" fills it, or else the only one of that
    # kind there is. Pictures are never guessed: there are usually several.
    for slot in slots.values():
        if slot["optional"] or slot["id"] in taken or slot["kind"] not in ("audio", "video") or slot["id"] == named.get("first_frame"):
            continue
        fits = [iid for iid, item in selection.items() if item["kind"] == slot["kind"] and all(u["id"] != iid for u in used)]
        wanted = step.get("audio" if slot["kind"] == "audio" else "source")
        pick = wanted if wanted in fits else fits[0] if len(fits) == 1 else None
        if pick is not None:
            taken.add(slot["id"])
            used.append({"id": pick, "name": selection[pick]["name"], "slot": slot["id"], "label": slot["label"].split(" (")[0], "kind": slot["kind"]})
    return used


# A short message that asks for the thing just talked about to be made: "now generate it", "use the prompt you gave".
GO_AHEAD = re.compile(r"\b(generate|make|create|render|use|do)\b.*\b(it|that|this|prompt|one)\b"
                      r"|^\W*(start|go|go ahead|approve|approved|yes|ok|okay|sure|proceed|generate|create|make|render|"
                      r"(generate|make|create)?\s*(your own|from scratch))\W*$", re.IGNORECASE)
# A reply that says work is being done, which is only true when it comes with a plan.
CLAIMS = re.compile(r"\b(generating|generated|creating|created|rendering|rendered|queued|queuing|approved|starting|"
                    r"making (it|the|this|that|a|your))\b", re.IGNORECASE)


def carry_over(instruction, history):
    """The message, with the text it points back to spelled out.

    After the agent has written a prompt or a description (a reply with no plan), "now generate it" says nothing
    about what to make. A small model then asks for the scene again, so the reply it points to is put in the message."""
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    reply = str(last.get("reply") or "").strip()
    if not reply or last.get("steps") or len(instruction) > 80 or not GO_AHEAD.search(instruction):
        return instruction
    return ('{}\n(This points to your last reply, which had no plan, so nothing was made yet. Take what to make from it, '
            'leaving out any words that were addressed to the user, and plan it now with steps. Your last reply was: "{}")').format(instruction, reply[:1500])


MAKE = re.compile(r"\b(generate|make|create|render|produce|start|go|approve|proceed|do it|yes|ok|okay)\b", re.IGNORECASE)


CHIP = re.compile(r"\[\[(item|asset):(\d+)\]\]")


def chips_in(reply, items, assets):
    """The items and assets a reply names as [[item:12]] or [[asset:3]], for the browser to show as small pictures:
    ({"item:12": {"name", "kind"}}, the reply). A token with an id the model was not given is taken out."""
    found = {}

    def keep(match):
        table, number = match.group(1), int(match.group(2))
        known = (items if table == "item" else assets).get(number)
        if not known:
            return ""
        found["{}:{}".format(table, number)] = {"name": known["name"], "kind": known["kind"]}
        return match.group(0)
    return found, re.sub(r"[ \t]{2,}", " ", CHIP.sub(keep, str(reply or ""))).strip()


def claims_work(instruction, reply):
    """Whether the user asked for something to be made and the reply says it is being made. Without steps that is not
    true: nothing runs until a plan is approved. A question ("what did you generate?") is answered in words: left alone."""
    asked = str(instruction or "").strip()
    return bool(MAKE.search(asked)) and not asked.endswith("?") and bool(CLAIMS.search(str(reply or "")))


NO_STEPS = ("(Your answer said you are making something, but it had no steps, so nothing was made. Nothing runs without "
            "steps. Plan the steps for what the user asked now. If it is truly unclear what to make, return no steps and "
            "ask one short question instead, without saying that anything is being made.)")
EMPTY_CLAIM = "I didn't put a plan together that time, so nothing was made. Say once more what you'd like and I'll plan it for you to approve."


def past_turns(history):
    """The earlier turns the browser sent, as chat messages, the newest that fit in HISTORY_CHARS. Anything that is not
    text is left out. A turn says what it planned and which assets each step used, so "use those three" still knows."""
    turns = []
    for turn in history[-MAX_HISTORY:] if isinstance(history, list) else []:
        if not isinstance(turn, dict):
            continue
        said, answered = str(turn.get("instruction") or "").strip(), str(turn.get("reply") or "").strip()
        if said and answered:
            planned = []
            for step in (turn.get("steps") or [])[:MAX_STEPS]:
                if isinstance(step, str):
                    planned.append(step[:80])
                elif isinstance(step, dict) and step.get("name"):
                    used = [str(u)[:60] for u in step.get("uses") or [] if isinstance(u, str)][:6]
                    planned.append(str(step["name"])[:80] + (" using " + ", ".join(used) if used else ""))
            # A reply that came without a plan made nothing, whatever its words said ("Generating it now"): the model
            # is told so, or it believes the work was done and only talks about it from then on.
            if planned:
                answered += "\n(Planned: {})".format(", ".join(planned))
            elif CLAIMS.search(answered):
                answered += "\n(No plan with this reply: nothing was made or queued.)"
            turns += [{"role": "user", "content": said[:2000]}, {"role": "assistant", "content": answered[:1500]}]
    size = 0
    for start in range(len(turns) - 2, -1, -2):   # from the newest pair back, while they fit
        size += len(turns[start]["content"]) + len(turns[start + 1]["content"])
        if size > HISTORY_CHARS:
            return turns[start + 2:]
    return turns


def skills_part(guides):
    """The skills of a message, as the model is given them: in the message, or first in the system prompt (a long run)."""
    return ("Skills for this message. A skill is a procedure the user or the studio wrote: follow it step by step, in its order, with its checks and "
            "its rules. Do not skip what it asks for first. When it needs something the user has not given, ask for exactly that and plan nothing. "
            "When it names a model or tool that is not in the workflows listed, say so in \"reply\" and do not swap it for another without asking:\n" + guides)


def question(instruction, offers, selection, default="", history=(), project_cast=None, recent=(), book=(), guides="", direction=""):
    """Everything the model is given for one message. history: the earlier turns, from past_turns().
    book: the project's asset book, from memory.book(). guides: the skills that fit the message, from skills.guide().

    The conversation goes inside the message, not before it as separate chat turns: a small model reads the long
    message as the whole task and otherwise answers as if nothing had been said before."""
    offers = sorted(offers, key=lambda o: o["id"] != default)   # the default first; the rest keep their order
    if offers[0]["id"] == default:
        offers[0] = dict(offers[0], default=True)
    said = ["{}: {}".format("User" if turn["role"] == "user" else "You", turn["content"]) for turn in history]
    parts = ["Always on:\n" + (kit.described(project_cast or []) or "(none)"),
             "Asset book, the project's kit (its characters, locations, props, voices, scripts by name) and items:\n" + ("\n".join(json.dumps(entry, ensure_ascii=False) for entry in book)
                                                       or "(empty: nothing is saved for reuse yet)"),
             *([skills_part(guides)] if guides else []),
             "Workflows:\n" + "\n".join(json.dumps(o) for o in offers),
             "Direction, the notes of this conversation that you keep (they stand in for turns no longer shown; when "
             "something durable changes, answer with the whole updated direction in \"direction\", else repeat it as it is):\n"
             + (clean_direction(direction) or "(empty)"),
             "Conversation so far, oldest first:\n" +("\n".join(said) or "(this is the first message)"),
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


EMPTY_FINISH = ("You finished with no reply, no steps and no question, so the user would get nothing. You were thinking: "
                "\"{}\". Do that now: call the tool you need next, or finish with the steps to make, a reply, or a question.")
# A reply that says what it is about to do ("Let me check the spans first", "I need to name the speakers").
ABOUT_TO = re.compile(r"\b(let me|let's|i need to|i will|i'll|i am going to|i'm going to|i'm now|i am now|next,? i|now i|first,? i|"
                      r"i should|i have to|i must)\b", re.IGNORECASE)
SAID_NOT_DONE = ("Your reply says what you are about to do (\"{}\"), but you finished without doing it: no steps, no "
                 "question, nothing saved, so the run would stop here. Do it now: call the tools it takes (state_write, "
                 "transcript, film, …), plan the steps, and finish again.")
SAVE_FIRST = ("Nothing of this run is saved yet, and the next message only knows what the run state holds. Before you "
              "finish, save what the skill says to keep at this point (the models and cutting the user chose, the inventory of "
              "what is attached, what you worked out) with state_write, then finish again.")
NO_SOUND_EDIT = ("the sound tool only puts an audio file on a video, and there was no video and sound to put together; to "
                 "separate a voice, transcribe or otherwise work on a sound file, make a \"generate\" step with that workflow")


def takes_sound(offers):
    """The ids of the offered workflows that must be given a sound file: they work on a sound (separate, transcribe)."""
    return {o["id"] for o in offers if any(r.get("required") and r["takes"] == "audio" for r in o.get("references") or [])}


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


def assemble_for(step, planned, videos, known, music_planned=False, shape=None):
    """Turn a proposed "assemble" step into what the assemble endpoint takes, or None if there is nothing to put together.

    planned: the numbers (positions in the plan) of the video shots the plan makes before this step. videos: the selected
    videos. known: {id: {"name", "kind"}} for the music the step may name. music_planned: the step's "after" names an audio
    step of the plan, which makes the music. shape: the orientation of the first shot. The shots of the plan come first;
    with none, the selected videos are cut together in the order given. "scenes" may hold a "title" and an "end" card."""
    if not planned and not videos:
        return None
    try:
        scenes = sequence.clean_scenes([dict(s, seconds=s.get("seconds") or None) for s in step.get("scenes") or [] if isinstance(s, dict)])
    except sequence.SequenceError:
        scenes = []
    card = lambda kind: next(({"kind": kind, "heading": s["heading"], "text": s["text"], "seconds": s["seconds"]} for s in scenes if s["kind"] == kind), None)
    title, end = card("title"), card("end")
    music = step.get("audio") if (known.get(step.get("audio")) or {}).get("kind") == "audio" else None
    name = " ".join(str(step.get("name") or "").split())[:80] or "Final cut"
    orientation = step.get("orientation") if step.get("orientation") in ORIENTATIONS else shape if shape in ORIENTATIONS else "landscape"
    count = len(planned) + (0 if planned else len(videos))
    parts = ["{} {}".format(count, "shot" if count == 1 else "shots"), "title card" if title else "", "music" if music or music_planned else "",
             "end card" if end else ""]
    return {"name": name, "facts": " · ".join(p for p in parts if p),
            "assemble": {"name": name, "steps": list(planned), "clips": [{"id": v["id"], "start": 0, "end": 0} for v in videos] if not planned else [],
                         "music": music, "title": title, "end": end, "shape": orientation,
                         "look": step.get("look") if step.get("look") in sequence.LOOKS else "dark"}}


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


EMPTY_SECTION = re.compile(r"^\s*[A-Z][A-Z &/-]{1,30}:\s*(none|n/a|-)?\s*$")


def settings_for(schema, step, selection_ids, project_id, filled=(), used_items=(), chained=False):
    """Turn one proposed step into job settings, keeping only what the workflow really accepts.

    filled: the reference slots the step fills from selected items (see uses_for); used_items: the ids of those items.
    chained: the step starts on the result of an earlier step, which fills its first frame when that is made.
    Returns (settings, start item id or None), or None if the step can't run.
    """
    roles = {c["role"]: c for c in schema["controls"] if c["role"]}
    # A section of the prompt structure with nothing in it ("REFERENCES:" on its own) says nothing to the video model.
    prompt = "\n".join(line for line in str(step.get("prompt") or "").strip().splitlines() if not EMPTY_SECTION.match(line)).strip()
    if "prompt" in roles and not prompt and not schema.get("prompt_optional"):
        return None
    values = {c["id"]: c["default"] for c in schema["controls"]}
    if "prompt" in roles:
        values[roles["prompt"]["id"]] = prompt[:4000]
    if "duration" in roles:
        given = step.get("duration")
        asked = given if isinstance(given, (int, float)) and not isinstance(given, bool) and given > 0 else roles["duration"]["default"]
        # Spoken words need their time: a shot is never shorter than its dialogue, whatever the model said. A workflow
        # that takes decimals gets them (a clip of exactly 151 frames is 151 / 24 s); the others whole seconds.
        seconds = max(float(asked), spoken_seconds(prompt))
        seconds = round(seconds, 4) if roles["duration"]["type"] == "float" else int(seconds)
        values[roles["duration"]["id"]] = max(SHOT_SECONDS[0], min(SHOT_SECONDS[1], seconds))
    resolution = orientation = None
    if schema.get("size"):
        resolution = step.get("resolution") if step.get("resolution") in schema["resolutions"] else schema["size"]["resolution"]
        orientation = step.get("orientation") if step.get("orientation") in ORIENTATIONS else schema["size"]["orientation"]
        if "duration" in roles and values[roles["duration"]["id"]] > LONG_SHOT and resolution > schema["size"]["resolution"]:
            resolution = schema["size"]["resolution"]   # a long shot at the largest size may not fit in the render server's memory
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
    # Then the workflow's own settings the model chose: an aspect ratio it named wins over the one its orientation means.
    apply_choices(schema, settings, step.get("choices"))
    # A mode that animates a first picture needs one: without a picture to start on, the shot keeps the default mode.
    for option in schema["options"]:
        if settings["options"].get(option["id"]) == "first_frame" and not (start or chained):
            settings["options"][option["id"]] = option["default"]
    # A workflow whose length is a list of choices (a song) gets the shortest one that covers the seconds asked for.
    length = length_control(schema)
    if length and "duration" not in roles and isinstance(step.get("duration"), (int, float)) and not isinstance(step.get("duration"), bool) \
            and step["duration"] > 0:
        numbers = sorted(v for v in length["choices"] if isinstance(v, (int, float)))
        settings["values"][length["id"]] = next((v for v in numbers if v >= step["duration"]), numbers[-1]) if numbers else settings["values"][length["id"]]
    return settings, start


LENGTH_ASKED = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(seconds?|secs?|s\b|minutes?|mins?)", re.IGNORECASE)


def seconds_asked(instruction):
    """The length the user named in their own words ("a 25 second ad", "2 minutes of music"), in seconds, or None.
    With several lengths named, the longest."""
    found = [float(n) * (60 if unit.lower().startswith("m") else 1) for n, unit in LENGTH_ASKED.findall(str(instruction or ""))]
    return max(found) if found else None


def length_control(schema):
    """A control without a role that sets how long the result is, from a list of seconds (the length of a song)."""
    return next((c for c in schema["controls"] if not c["role"] and c.get("choices") and re.search(r"\b(seconds|length|duration)\b", c["label"], re.I)), None)
