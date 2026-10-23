id: script-to-video-shaurav
title: script-to-video-shaurav
version: 1
words: (?!)
---
---
name: article-to-video
description: Use when an article, interview or blog post (photo, PDF, URL or text) should become a 30–90s vertical explainer for Reels, TikTok or Shorts, with dramatic voiceover, line-art visuals and captions.
---

# Article to Social Explainer Video

Turn a written article into a short vertical video that a cold viewer watches to the end: one sharp angle, a hook in the first seconds, no filler, an expressive voiceover, line-art visuals timed to the words, and captions.

## Principles

- **One story, not a summary.** Pick one angle and drop everything that doesn't serve it. Viewers swipe away from lists.
- **Every line earns its place.** If the viewer wouldn't miss a line, cut it.
- **Drama comes from structure and delivery, not from bending facts.** Real people and real publications are involved, and accuracy is what keeps the video publishable.
- **Time everything from the audio.** Visuals and captions follow the measured word timings, never estimates.
- **Consistency beats novelty.** One style bible, one set of style references, one template.
- **Draw once, reuse everywhere.** The video uses one character, one small symbol library and one anchor image per scene, rather than a new image for every line.
- **Spend late.** Lock the script before generating audio or images. Changes are cheap before that point and expensive after it.

## Tools

Written for: you (with vision) for the text steps, the scene breakdown, the SVG overlays and QA; ElevenLabs v3 for the voice; an image model for the anchor images; HyperFrames to animate the beats; and ffmpeg to join the clips with the audio. Optional: speech-to-text, music and sound-effect generation, and a video model.

If a tool is missing, keep each step's output file and swap the tool: any TTS plus forced alignment, SVG anchors instead of generated ones, or another renderer that reads storyboard.json.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Source | — | Photo(s), PDF, URL or pasted text |
| Platform | TikTok / Reels / Shorts | 1080×1920, 30 fps |
| Length | 90 s | 30, 60 or 90 s |
| Tone | Dramatic | Softens automatically on sensitive parts (step 5) |
| Voice | The channel's ElevenLabs voice | Keep one voice per channel |
| Language | The article's language | |
| Visual style | Monoline line art | Black ink on a flat pale ground, with solid black as the only accent; defined in style.md (step 9) |
| Anchors | Generated, one per scene | SVG anchors as the fallback (step 9) |
| Style references | Asked for at the first checkpoint | The user's line-art images guide every drawing; if none arrive, make your own (step 9) |
| CTA | None | e.g. "Follow for part 2" |
| Mode | Interactive | Interactive stops at checkpoints; autonomous decides, logs assumptions and keeps going |

If the user doesn't specify a setting, use the default and say which defaults you used.

## Pipeline

```
1  Ingest       article → clean text + source info
2  Fact sheet   claims, numbers, exact quotes with speaker
3  Angle        one story + hooks                          ◆ A
4  Script       draft → critique → tighten
5  Lock         accuracy, fairness, sensitivity, credit    ◆ B
6  Audio        speech copy → takes → transcript check → word timings → music/SFX
7  Scenes       scenes by meaning → beats inside each → scenes.json
8  Overlays     overlay symbols + sourcing rules → symbols.json
9  Anchors      style references → character sheet   ◆ C   → one anchor per scene → anchor QA
10 Storyboard   beats × timings × anchors × overlays → storyboard.json → collision check
11 Animate      HyperFrames animates each beat → clips → contact sheet → join with audio   ◆ D
12 Deliver      MP4, SRT, cover, post copy, credits
```

Step 6 and steps 7–9 run in parallel once the script is locked, and both read only the locked script. Step 10 waits for both.

## Working folder

Keep one folder per video so any step can be re-run on its own and a fix re-renders only what changed.

```
<slug>/
  source.md            clean article text
  meta.json            publication, author, date, headline, url
  facts.json           fact sheet
  angles.md            angle options and hooks
  script.md            working script
  script.lock.md       approved script, the only script input downstream
  display.txt          caption copy (real spellings)
  speech.txt           TTS copy (respellings, audio tags)
  pronunciations.json
  audio/               takes, voice.wav (chosen take), sfx, final_mix.wav
  timings.json         word-level timings
  scenes.json          scenes and their beats
  symbols.json         overlay library: id, description, scenes
  style.md             style bible: colours, strokes, font, boil filter
  refs/                style references: the user's, or your own reference sheet
  anchors/             character sheet, one anchor image per scene, keyed character layers
  symbols/             overlay SVGs, one file per symbol, sheet.png
  storyboard.json
  composition/         HyperFrames project
  renders/             beat clips, clips.txt, contact sheet, previews
  deliverables/        video.mp4, captions.srt, cover.png, post.md, credits.md
```

## 1. Ingest

For photos and scans:

- Fix orientation and page order. Magazine pages are often shot sideways or out of sequence.
- Follow the column reading order and rejoin words hyphenated across lines.
- Drop page furniture: running headers, page numbers, photo captions, pull quotes (they repeat the body), ads and "continued on" lines. Remove duplicate pages.
- If one spread holds more than one piece, such as a main story and a sidebar, keep them separate and label each.
- Flag low-confidence words. Check every proper noun against its other appearances, because an OCR typo in a name ends up on screen.

For URLs, keep the article body only: no navigation, comments or related links. If the text is paywalled or incomplete, say so and work only from what you have.

For every source, save the publication, author, date, headline and URL to meta.json. You need them for the credit, and the date tells you whether the article's "now" is still now.

source.md is working material. It never appears verbatim in the video.

## 2. Fact sheet

Extract everything the video could use into facts.json:

```json
{
  "facts": [
    {"id": "F1", "text": "…", "kind": "fact | opinion | allegation | prediction",
     "attributed_to": "reporter or a named person", "surprise": 4}
  ],
  "quotes": [
    {"id": "Q1", "speaker": "…", "text": "exact words",
     "context": "the question or situation it responds to"}
  ]
}
```

The script is written from this sheet and checked against it, which is how accuracy survives a dramatic rewrite. Keep each quote's context: a line lifted away from the question it answered can mean something else.

## 3. Angle and hooks

Score candidate facts and quotes from 1 to 5 on:

- **Surprise:** would a smart viewer not already know this?
- **Stakes:** who wins or loses, and how much?
- **Emotion**
- **Specificity:** names and numbers
- **Fit:** can it be said in one sentence?

Build 2–3 angles. Each angle is a logline, the question it makes the viewer ask, and the 4–6 fact or quote ids that answer it.

Write five hooks for the best angle, mixing types:

- the most surprising number
- a contradiction ("They did X, then the exact opposite")
- a short, attributed quote that's startling but fair in context
- a stakes question the video will answer
- a cold open in the middle of the action

A hook is under about 12 words, makes sense with no context, and gets paid off later. Pick the strongest and keep the runner-up for an A/B test.

> Weak: "Today we're looking at a big change in the restaurant world."
> Strong: "This bakery sells out in nine minutes. It has never run an ad."

◆ **A** (interactive; skip if the user already named an angle): show the angles and top hooks, and let the user choose. In the same message, ask for line-art style references (step 9), unless the user has already sent some.

## 4. Script

Dramatic means tension and pace: short lines, turns, reveals and expressive delivery. It doesn't mean hype words ("insane", "shocking") or claims bigger than the source makes.

**Word budget:** about 2.5 spoken words per second, minus about 10% for pauses and tags.

| Length | Words |
|---|---|
| 30 s | 65–75 |
| 60 s | 130–150 |
| 90 s | 200–225 |

**Story structure** (90 s; scale for other lengths):

| Section | Time | Job |
|---|---|---|
| Hook | 0–3 s | Stop the scroll |
| Stakes | 3–12 s | Who this is about and why the viewer should care |
| Points 1–3 | 12–70 s | Each adds a new fact and ends on a turn ("but", "then", "except") |
| Payoff | 70–85 s | Answer the hook's question with the biggest reveal |
| Close | 85–90 s | A line that loops back to the hook, or the CTA |

Open a loop early by teasing the payoff ("the strangest part is how it ended"), and close it on time.

**Line tests** (run on every line):

- **Cut:** would the viewer miss it? If not, delete it.
- **Specific:** does it carry a name, number, quote, image or consequence? Replace stock lines ("This changes everything", "In today's world", "Let's dive in", "Here's the thing") with the detail they gesture at.
- **Common sense:** does the viewer already know this? Cut it.
- **Ear:** one idea per line, most lines under 15 words, varied length, no parentheses. Round numbers for speech unless the exact figure is the point.
- **Promise:** never tease something the video doesn't deliver.

Format script.md with the section, line id, line and sources:

```
[HOOK]   L1  This bakery sells out in nine minutes.   {F2}
[HOOK]   L2  It has never run an ad.                  {F5}
[STAKES] L3  …                                        {F1, Q2}
```

### Critique pass

Drafting and critiquing are separate passes, so don't skip this one. Score the draft from 1 to 5 on:

- **Hook:** would you stop scrolling?
- **Every line earns it:** the cut, specific and common-sense tests
- **Escalation:** does each point raise the stakes?
- **Payoff:** does the ending answer the hook?
- **Cold viewer:** is it clear with zero background?
- **Pace:** is it inside the word budget?
- **Traceability:** does every line have a fact or quote id?

Rewrite the two weakest lines each pass. Stop when everything scores 4 or more, or after three passes.

## 5. Lock

**Accuracy and fairness**

- Every claim traces to a fact id, and names, numbers and dates match the source.
- Quotes are exact and keep their meaning in context. Never paraphrase inside quotation marks.
- Attribute opinions, allegations and predictions ("according to [publication]", "[name] says"). A reporter's characterization belongs to the reporter.
- Don't invent motives, feelings or cause and effect. Dramatic delivery is fine; dramatic distortion is not.
- Nothing in the words or visuals should show a real person doing or saying something the source doesn't support.
- If the article isn't recent, date it on screen ("in a 2023 interview…") instead of presenting it as news.

**Sensitive topics:** suicide or self-harm, sexual violence, abuse, harm to children, mass violence, death or tragedy.

- Switch that part to a calm, factual tone, or the whole video if it's the main subject. Drop dramatic tags, sound effects and suspense devices there.
- Leave out method details and graphic description, and don't frame a tragedy as a puzzle or a cliffhanger.
- For suicide or self-harm, add a short support line on screen and in the post, with a crisis line for the audience's region.
- Keep graphic words out of captions. They hurt viewers and reach.

**Copyright and credit**

- The video explains and comments; it isn't a reading of the article. Write in your own words, and use only a few short, attributed quotes where the exact words matter.
- Credit the source on screen and in the post.
- Don't reuse the publication's photos or illustrations unless they're licensed for this use.

◆ **B** (interactive): show the locked script with its word count and estimated runtime. This is the last cheap moment to change direction. If ◆A was skipped, ask for style references here.

Save script.lock.md. Every later step reads only this file.

## 6. Audio (ElevenLabs v3)

**Two copies of the script**

- **display.txt** is what appears on screen: real spellings and numerals.
- **speech.txt** is what the voice reads: phonetic respellings, numbers and abbreviations written out as spoken, and audio tags.
- Keep them aligned word for word, with one respelled word standing in for one real word, so the timings map back onto the captions.

**Pronunciations:** list every proper noun, acronym and foreign word in pronunciations.json, and respell any the voice might miss ("Worcester" → "WUSS-ter"). Look up people's names rather than guessing.

**Expressive tags**

- Use v3's inline tags in square brackets, such as [excited], [curious], [whispers], [sighs], [sarcastic] and [laughs], only at emotional turns. Aim for roughly one every two or three lines, placed right before the words they color, never two in a row. Overused tags flatten the delivery and make the model improvise.
- Shape pacing with the text itself: ellipses for suspense, dashes for a turn, short sentences for punch, and line breaks between sections. v3 is steered by text and tags rather than SSML break tags.
- Match the tags to the voice. A calm narrator won't shout convincingly.
- If your setup exposes v3's stability presets, start at Natural. Move to Creative for more drama, or to Robust if the voice improvises or reads tags aloud.

**Takes and QA**

- Generate 2–3 full takes. Whole-script takes keep the delivery consistent. Split at sentence boundaries only if you hit the model's character limit.
- Transcribe each take with speech-to-text and diff it against speech.txt with the tags removed. Reject takes with skipped or extra words, mispronounced names, spoken tags, or stray laughs and noises. To fix one bad sentence, regenerate just that sentence and splice it in at a pause. Save the winning take as audio/voice.wav.
- Check that the duration is within ±10% of the target. If it runs long, cut a line (back to step 4) rather than speeding the voice up by more than about 5%.

**Timings:** create timings.json (word, start, end, line id) from the TTS timestamp output, or by running forced alignment of voice.wav (before music) against speech.txt with the tags removed. Then map each word back to its display.txt spelling, which is why the two copies stay aligned word for word. Every visual cue is timed from this file.

**Music and sound effects**

- Lay a music bed that fits the tone, well under the voice (start about 15–20 dB lower) and ducked further on key lines. Use licensed, royalty-free or generated music.
- Match the sound effects to the visual style. For line art: a soft pop when a symbol enters, a quick pencil scribble under a stat, a swish on transitions, and a riser into the payoff. Put them at scene changes and reveals, not everywhere. ElevenLabs can generate these from a text description.
- Master to about −14 LUFS integrated, with peaks below −1 dBTP.

## 7. Scenes and beats

Before any image is made, divide the locked script into scenes, and each scene into beats.

**Scenes come from meaning, not from lines.** Read the whole script first and decide what the viewer needs to see at each moment of the story. A scene is one picture that holds one idea: a setting, a situation, a comparison or a turning point. Start a new scene only when that picture has to change: a new subject, place or time, a new step in the argument, or the turn into the payoff. Several lines usually share a scene, and a scene never splits a phrase.

> Script: "This bakery sells out in nine minutes. It has never run an ad. The owner bakes every loaf alone, overnight."
> One scene per line would give three. By meaning there are two: the first two lines are one picture (an empty shop window and a queue), and the third needs a new one (a kitchen at night).

**Beats are the changes inside a scene.** A beat lands when something new reaches the viewer: a fact, a number, a reveal, a reaction or an emphasis. Each beat names the words it lands on, so step 10 can time it from timings.json. If a scene has no new beat to give, it has run its course.

For each scene, write:

- **essence:** the one-line idea it shows
- **lines:** the script lines it covers
- **anchor:** a brief for its anchor image, covering the setting, what the character is doing, the framing (wide, medium or close) and the empty areas the beats will fill
- **beats:** in order, each with its trigger words (`on`), what changes (a camera move to part of the anchor, an overlay such as a tag, stat, symbol or quote card, a reveal, or a character reaction) and an optional sound effect

```json
{"scenes": [
  {"id": "S1", "essence": "a tiny bakery that sells out absurdly fast", "lines": ["L1", "L2"],
   "anchor": "wide: the character outside a small bakery, empty shelves in the window, a queue curling off-frame, open sky above",
   "beats": [
     {"id": "S1B1", "on": "sells out", "change": "push in on the empty shelves"},
     {"id": "S1B2", "on": "nine minutes", "change": "stat 9 MIN pops into the sky", "sfx": "pop"},
     {"id": "S1B3", "on": "never run an ad", "change": "tag NO ADS stamps in beside the queue"}
   ]}
]}
```

Check the breakdown before saving scenes.json:

- **Muted test:** with the sound off, would each anchor still show what its scene is about?
- Every beat adds something. Merge or cut the ones that don't.
- Neighbouring scenes change framing (wide, then close) so the cuts feel edited.
- The hook gets its own short scene, with its first beat inside the first second, and the payoff gets its own scene.
- For 90 s, expect about 6–10 scenes of 2–5 beats each, with a beat every 2–4 seconds. Scale for other lengths.

The scene plan is reviewed at ◆C (step 9), together with the style references, before any anchor is generated.

## 8. Overlays and sourcing

Anchors carry the scenes, and overlays are what the beats add on top. List every overlay the beats call for: symbols, tags, stats and quote cards. Keep looking for explicit items, implied items and abstract metaphors (moat → a castle, trust → a padlock, risk → a tightrope). Each one goes into a scene's anchor brief if it's the scene's main picture, or into the overlay library if it pops in during a beat.

Save symbols.json with each overlay symbol's id, a one-line description and the scenes that use it. Reuse symbols across scenes, and keep the library small: no more than about 10–14.

Sourcing is a lookup, not a search:

| Item | Becomes |
|---|---|
| Real person | The video's character, with a name tag |
| Brand or organization | Its name set in type, as a tag |
| Place | Drawn into the anchor (a building, a street, a skyline), tagged if the name matters |
| Object, implied thing or metaphor | Drawn into the anchor, or an overlay symbol |
| Number, date, quote or list | Type: a stat, a tag or a quote card |

Real people, logos and lettering are never drawn, in anchors or in overlays; text is always set in type. When two people share a scene, use the character twice with different name tags, and vary the pose rather than the design. Because every visual is generated or drawn for the video, there are no image licenses to track, and the only images to ask the user for are line-art style references (step 9).

Photos supplied by the user aren't used in this style. If the user wants a real photo, that's a different style, so say so rather than mixing photos into the line art.

## 9. Style references, character and anchors

**Style bible** (style.md), shared by the anchors and the overlays:

- Ink `#111` on a flat pale ground `#EEEEF3`. Solid black is the only accent.
- One stroke weight, plus a thinner weight for detail (for example 6 px and 3 px at 1080 px wide). In SVG, set `vector-effect="non-scaling-stroke"` so a scaled symbol keeps the same weight.
- Round caps and joins.
- Flat fills only: the ground colour (to hide lines behind a shape) or black. No gradients or shading.
- Anton for tags and captions. Load the font file locally so a render never falls back to a default font.
- One filter recipe, the boil (step 11 animates it):

```html
<filter id="boil" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="1" result="noise"/>
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="3"
                     xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

**Style references:** every drawing in the video is built from a small set of line-art references.

- **Ask early.** At the first checkpoint (◆A, or ◆B if A was skipped), ask the user for them, for example: "Do you have line-art style references? Send 2–5 images in the look you want (your own drawings, a character you own, or sample frames), or say 'make your own'." Save whatever arrives in refs/.
- **If the user sends references,** look at them and note what they set: line quality, level of detail, proportions, and how faces and hands are drawn. Take the drawing style from the references, and keep the style bible's colours, font and boil unless the user says otherwise. If the references show the user's own character, it becomes the video's character.
- **Use them for style, not for copying.** Don't reproduce a specific artwork. If a reference shows a well-known character or someone else's mascot, design an original character in that style instead, and never draw a real person from a photo (step 8). If the references aren't line art, take what fits (proportions, character design, mood) and tell the user what you couldn't use. References guide the drawing; they never appear in the video.
- **If no references have arrived by this step,** make your own. Design an original, simple character that suits the topic, generate a reference sheet in the style bible, and save it as refs/own_sheet.png:

```
reference sheet: [original character description] in four poses (neutral, pointing,
reacting, walking), plus [2–3 props from symbols.json], monoline line art,
single-weight #111 ink lines with round caps, flat #EEEEF3 background,
flat fills only, no shading, no gradients, no text, no letters
```

**Character sheet:** make the video's one character in 3–4 poses (neutral, pointing, reacting, walking) on the ground colour, drawn from the style references, and save it as anchors/character.png. If you made your own reference sheet, it doubles as the character sheet. Every anchor uses the sheet as a reference, so the character stays the same in every scene.

◆ **C** (interactive): before any anchor is generated, show the scene plan from step 7 (scenes, essences and anchor briefs) with the style references in use and the character sheet, and say whether the references are the user's or your own. This is the last cheap moment to change the visual plan or the look.

**Anchor route** (choose one per video):

| Route | Anchors | Trade-off |
|---|---|---|
| Generated (default) | One image per scene from the image model, with the style references and the character sheet as references | Expressive and consistent; one generation per scene |
| SVG | Each scene composed from hand-coded SVG symbols | Fully deterministic and cheapest; looks simple and symmetrical |

Use SVG anchors when there's no image model, or when the video has to be fully deterministic.

**Generating anchors:** turn each anchor brief into a prompt. Pass the style references, the character sheet and the first approved anchor as references, so every scene looks like the same video. If the model limits how many references it takes, send the character sheet first, then the closest style reference:

```
[anchor brief: setting, what the character is doing, framing], monoline line art in the style of the references,
single-weight #111 ink lines with round caps, flat #EEEEF3 background, flat fills only,
no shading, no gradients, ground line in the lower middle of the frame,
empty space in the top third, no text, no letters, no logos, vertical 9:16
```

Generate at 9:16, and upscale to 1080×1920 if the model makes smaller images.

**Anchor QA:** vision-check every anchor before a beat uses it.

- It matches the style bible (monoline, black on pale, no shading or gradients) and the style references.
- The character matches the sheet.
- There's no text, lettering, logo or real person.
- The ground line sits near y=1150, and the areas the beats need are empty.
- Counts are right (seven icons must be seven), nothing important overlaps, and it reads at phone size.

Regenerate a failing anchor up to twice, then simplify its brief. Once it passes, look at it and record each beat's focus box: the region, in anchor pixels, that the camera frames or an overlay points at.

**Overlay symbols** are hand-coded SVG in the same style, matched to the references' line weight and level of detail. Keep one file per symbol in symbols/, with a tight viewBox so each is sized by its content. Draw each one once on its own, on a single sheet (symbols/sheet.png), and check the count, overlap and legibility before any beat uses it.

**Layered character (optional):** when a beat needs the character itself to move (a reaction, a blink or a tilt), generate the character on its own from the sheet, key it to transparent, and place it over a version of the anchor without the character. This costs one extra generation per pose. A keyed PNG keeps its margins, so size it by its visible content (see Build rules).

## 10. Storyboard

Merge scenes.json, timings.json, the anchors and the overlays into storyboard.json. Each scene holds its anchor and its beats, and each beat starts on its trigger word:

```json
{
  "canvas": {"w": 1080, "h": 1920, "fps": 30},
  "audio": "audio/final_mix.wav",
  "captions": "timings.json",
  "credit": "Source: [publication], [date]",
  "scenes": [
    {"id": "S4", "lines": ["L5", "L6"], "start": 13.0, "end": 17.2, "anchor": "anchors/S4.png",
     "beats": [
       {"id": "S4B1", "start": 13.0, "camera": "wide",
        "items": [{"symbol": "icons", "x": 505, "y": 740, "scale": 1.25, "at": 13.0}]},
       {"id": "S4B2", "start": 13.8, "camera": {"focus": [180, 160, 720, 1280]},
        "items": [{"stat": "7 APPS", "x": 505, "y": 280, "at": 13.8, "size": 125}]},
       {"id": "S4B3", "start": 15.9,
        "items": [{"tag": "GITHUB", "x": 300, "y": 810, "at": 15.9}]}
     ]}
  ],
  "end_card": {"cta": "Follow for part 2"}
}
```

- `symbol` points to an id in symbols.json. x and y are screen pixels, and `at` is the entry time, taken from the word it lands on in timings.json.
- `camera` is `"wide"` (the whole anchor) or a `focus` box (x, y, w, h in anchor pixels, kept at 9:16 so nothing stretches). A beat without a camera keeps the previous beat's framing.
- Overlays live in screen space and don't move with the camera. If an overlay points at something in the anchor, such as a circle or an arrow, place it after the camera settles and map its target through the camera framing.
- **Frame boundaries:** turn every beat start into a frame number from its absolute time (round(start × fps)). A beat's clip runs from its start frame to the next beat's start frame, and the last beat runs to the end of the audio and the end card. Cutting this way keeps the joined clips in sync with the audio.

**Layout**

- Anchors put their ground line near y=1150, with the character and props standing on it. Tags sit above, and captions go below.
- Everything stays inside the safe zones: out of the top ~10%, bottom ~20% and right ~12%.

**Collision check:** no two items' boxes may overlap, including the caption band, and no overlay may cover the part of the anchor its beat is about. Measure boxes from the rendered elements (for example with getBBox) at their resting position and scale, and pad each by about 12 px so the boil and the overshoot don't make them touch. If two collide, shift the stat up or down and check again.

**Pacing**

- A beat every 2–4 seconds. Scenes usually run 5–15 seconds, and the hook scene 3 seconds or less. The first change lands within the first second.
- Tag a person by name the first time the character stands in for them. Show numbers as stats as they're spoken, and show quotes as quote cards with the speaker's name.
- Leave the last 1–2 seconds clean for the loop line or the CTA.

## 11. Animate and join (HyperFrames)

- Build one reusable scene template: the anchor layer with its camera, the overlay track (symbols, tags, stats and quote cards), the caption track, the source credit, the end card and the boil filter. Fill it from storyboard.json using HyperFrames' render-time composition variables. A fresh composition written from a prompt every time drifts in style and breaks in new ways.
- Check the HyperFrames block catalog before building a component from scratch, and restyle anything you use to match the style bible.
- Drive every cue from timings.json.

**HyperFrames animates each beat.** Render every beat as its own clip: the scene's timeline from the beat's start frame to the next beat's start frame, with both passed in as composition variables. Because each clip picks up the timeline at absolute time, it starts exactly where the previous beat ended, with the same framing, the earlier overlays on screen and the captions in step. Beat clips are short, so every render stays under the render limit (a 90 s render at 1080×1920 exceeds it). If per-beat render overhead gets too slow, render one clip per scene instead; the beat timing doesn't change.

**Motion**

- **Camera:** an eased push-in, pan or pull-out to the beat's focus box over about 0.6 s, then a hold. Use at most one move per beat.
- **Boil:** put the boil filter on the whole frame, anchor included, and re-seed it about 8 times a second, so the lines wobble like hand-drawn animation. Cycle through a few seeds (start with 3). Drive the seed from the video's absolute time, for example with a GSAP tween on a counter, rather than from a timer, so renders stay deterministic and the boil doesn't restart at every cut.
- **Entrances:** a pop-in with overshoot (for example, scale up from 0 with a back-out ease over about 0.3 s), and a short fade-out.
- **Character:** blinks or a slow tilt only on hero moments. These need a layered character or SVG anchors; on a flat generated anchor, use a small camera move instead.
- **Tags:** boxed labels in Anton. Use a black-filled box with ground-colour text for emphasis.
- **Stats:** big type with a scribbled underline, drawn on by animating the stroke.
- **Captions:** black Anton text, at most two lines, taken from display.txt. The spoken word gets a black highlight block, with its letters switched to the ground colour so they stay readable. Keep captions below the ground line and inside the safe zones.
- **Scene changes:** cut on the new scene's first beat, or build the transition into that beat, starting from the previous anchor's last frame.
- **Video model (optional):** use it for one or two hero moments at most, starting from that scene's anchor and matching the line-art style. Everything else stays in HyperFrames, which is consistent, deterministic and cheap.

**Preview, QA and join**

1. Render the beat clips, and list them in playback order in renders/clips.txt.
2. Check each clip's bitrate. Around 15 kb/s means a blank render (see Build rules).
3. Join the clips without audio, make a contact sheet, and look at it before mixing in the audio. Check for overlapping items, blank frames, unreadable text, wrong counts, style breaks and jumps between beats of the same scene. This takes one frame every 2 s, which fits 90 s; adjust the grid for other lengths:
   ```
   ffmpeg -f concat -safe 0 -i renders/clips.txt -c copy renders/silent.mp4
   ffmpeg -i renders/silent.mp4 -vf "fps=1/2,scale=216:-1,tile=5x9" -frames:v 1 renders/contact.png
   ```
4. Run automated checks:
   - the duration is within ±10% of the target
   - captions match display.txt and sit on their words (within about 0.1 s)
   - every anchor and symbol loads, with no empty or frozen frames
   - the collision check passes, and text stays inside the safe zones
   - the source credit is present
5. Fix at the beat level, by editing storyboard.json, an overlay or an anchor, and re-render only the affected clips. A new anchor means re-rendering that scene's beats.
6. Join the clips and the audio in one ffmpeg pass:
   ```
   # renders/clips.txt
   file 'S1B1.mp4'
   file 'S1B2.mp4'
   file 'S1B3.mp4'

   ffmpeg -f concat -safe 0 -i renders/clips.txt -i audio/final_mix.wav \
     -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k deliverables/video.mp4
   ```
7. ◆ **D** (interactive): share the joined video. Apply feedback with steps 5 and 6.

The final video is an MP4 (H.264, AAC) at the configured canvas and frame rate.

## 12. Deliver

Save to deliverables/:

- **video.mp4**
- **captions.srt**, built from display.txt and timings.json
- **cover.png**, a strong frame with the hook in large type, inside the safe zones
- **post.md**, with the hook line, one sentence of context, 3–5 relevant hashtags, the source credit, and the support line if a sensitive topic came up
- **credits.md**, listing the source article and every asset's source and license

Add an AI-generated content label where the platform requires one.

## Build rules

These come from earlier builds. Follow them every time.

- **Name helpers carefully.** Never name a script function or global `top`, `parent` or `name`, or anything else that's already a property of `window`. Browser built-ins can silently kill the whole script and give a blank render. Keeping composition code inside a module or a function scope avoids the clash.
- **A bitrate of about 15 kb/s signals a blank render.** Check every clip before going further: `ffprobe -v error -show_entries format=bit_rate -of csv=p=0 renders/S1B1.mp4`
- **Always look at a contact sheet before mixing in the audio**, and check it for overlap and blank frames.
- **Size by content, not by image width,** whenever keyed images are involved. A keyed PNG keeps its transparent margins, so measure or trim to the visible pixels before placing it.

## Modes

- **Interactive** (default): stop at ◆A (angle, plus the ask for style references), ◆B (locked script), ◆C (scene plan and look) and ◆D (preview).
- **Autonomous:** make each choice yourself and keep going. Use any style references the user attached; otherwise make your own. End with a short list of the assumptions and fallbacks you used.

## Done when

- [ ] One angle, a hook in the first 3 seconds, and a delivered payoff
- [ ] Every line passes the cut, specific and common-sense tests
- [ ] Every claim is traceable, quotes are exact and attributed, and the source is credited
- [ ] Sensitive parts are handled calmly, with a support line where needed
- [ ] Audio is checked against the script, and runtime is within ±10%
- [ ] Scenes follow the story's meaning, not one per line, and every beat lands on its words
- [ ] Every anchor matches the style references (the user's, or your own sheet if none came), the style bible and the character sheet
- [ ] Overlays come from one small library, and there are no real people, logos or drawn lettering
- [ ] No overlapping items or blank frames, and the contact sheet has been checked
- [ ] Captions are synced, correctly spelled and inside the safe zones
- [ ] All five deliverables are present

## Troubleshooting

| Symptom | Fix |
|---|---|
| Script reads like a summary | Re-pick one angle and drop facts that don't serve it |
| The middle sags | Give each point a new fact and a turn, and cut the weakest point |
| Voice reads tags aloud or improvises | Use fewer tags, never adjacent; pick a more stable preset; regenerate that sentence |
| Names are mispronounced | Fix the respelling in speech.txt, regenerate, and re-run alignment |
| Audio runs too long | Cut lines instead of speeding up the voice |
| Scenes feel like one picture per line | Re-split by meaning: merge lines that share a picture, and let beats carry the 2–4 s changes |
| Anchors don't look like the same video | Pass the style references, the character sheet and the first approved anchor with every generation, and regenerate the outliers |
| The user's references clash with the style bible | Take the drawing style from the references, keep the style bible's colours and font, and confirm at ◆C |
| References arrive after anchors exist | Rebuild the character sheet from them, regenerate the anchors, and re-render those scenes' beats |
| Captions drift | Re-run alignment on voice.wav; never time from the script |
| Blank video | Check the browser console for a name collision; look for a tiny bitrate |
| Wobble too strong | Lower the displacement scale or increase the noise frequency |
| Looks stiff | Add more seeds, a camera move per beat, a tilt on hero moments, or a layered character |
| Overlapping tags | Run the collision check and shift stats up or down |
| A jump between beats of one scene | Render each clip from the scene timeline at absolute time, and check the frame boundaries |
| An overlay misses its target after a camera move | Place pointing overlays after the camera settles, and re-mark the focus box |
| It feels static | Add a visual change every 2–4 s: a new symbol, a tag, a stat or a cut |
