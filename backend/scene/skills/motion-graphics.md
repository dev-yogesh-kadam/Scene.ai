id: motion-graphics
title: Motion graphics — words and shapes, no AI model
version: 1
desc: Use for titles, kinetic text, intros, outros and explainers made of words and shapes.
words: \b(motion graphic\w*|kinetic|title|titles|title sequence|title card|intro|outro|explainer|lower.?third|caption\w*|subtitle\w*|animated text|text animation|typographic|typography)\b
---
These are videos made of words and shapes, drawn here with no AI model and priced by the second. Use tool "motion" for
a standalone one; use tool "overlay" to put words over a video the user selected. Never use "generate" for text on
screen: a generating model cannot write readable words.

A "motion" step is ONE video, written as "scenes" shown one after another. Each scene has a "kind":
- "title": a big heading, with "text" as a smaller line under it.
- "statement": one sentence in "text", shown large.
- "list": a "heading" and up to 5 short "items".
- "stat": a number or short figure in "heading", what it means in "text".
- "quote": the words in "text", who said it in "heading".
- "end": closing words in "heading", a smaller line in "text".

Write the real words the viewer will read. Keep them short: a heading up to 6 words, text up to 14 words, an item up to
6 words. A full video has 4 to 8 scenes, starts with a "title" and finishes with an "end". "seconds" is how long a
scene stays, 2 to 8; use 0 to let it be set from the amount of text.

"look" is "dark", "light", "warm" or "cool" — decide it, never ask. It follows the mood of the words: "warm" for food,
cosy, family or handmade things; "cool" for tech, health, science or night; "light" for clean, bright, daytime or
minimal; "dark" for cinematic, premium or dramatic, and when nothing points elsewhere. "orientation" follows where it
will be shown, the same way a shot's shape is chosen.

For "overlay": "source" is the selected video's id and "scenes" has exactly one scene — kind "title" (large words in
the middle, "heading" and "text") or "lower_third" (a name in "heading" and a line under it in "text", bottom left).

For "motion" and "overlay" set prompt to "". Leave "scenes" empty for every other tool.
