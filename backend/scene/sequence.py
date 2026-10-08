"""A motion graphics video made of scenes of words: titles, statements, lists, figures and quotes, one after another.

The agent (or anything else) describes the video as a list of scenes; this module checks the list and writes the
HyperFrames composition for it. Every word goes into the page escaped, so nothing a user or a model wrote is ever
read as markup or script.
"""

import html
import json

KINDS = ("title", "statement", "list", "stat", "quote", "end")
LOOKS = {   # ground, ink, soft, mark
    "dark": ("#100f0e", "#f2efea", "#a8a39a", "#ffa51f"),
    "light": ("#f4f4f2", "#171614", "#5c5852", "#c77700"),
    "warm": ("#26170f", "#f6e7d3", "#cfae8c", "#ff8a3d"),
    "cool": ("#0b1522", "#e8f1fa", "#9db4c9", "#5cb8ff"),
}
MAX_SCENES = 12
MAX_ITEMS = 5
MAX_SECONDS = 60
SCENE_SECONDS = (2.0, 8.0)   # the shortest and the longest a scene may be


class SequenceError(Exception):
    pass


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _words(scene):
    return len((scene["heading"] + " " + scene["text"] + " " + " ".join(scene["items"])).split())


def _usual_seconds(scene):
    """How long a scene needs to be read when no length is given."""
    return {"title": 3.0, "end": 3.0, "stat": 3.0}.get(scene["kind"], 2.0 + _words(scene) * 0.28)


def clean_scenes(raw):
    """The scenes as the composition takes them: [{"kind", "heading", "text", "items", "seconds"}].

    Anything unknown or empty is dropped; the whole is held to MAX_SCENES and MAX_SECONDS."""
    scenes, total = [], 0.0
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        scene = {"kind": entry.get("kind") if entry.get("kind") in KINDS else "statement",
                 "heading": _text(entry.get("heading"), 70), "text": _text(entry.get("text"), 170),
                 "items": [t for t in (_text(i, 60) for i in (entry.get("items") if isinstance(entry.get("items"), list) else [])) if t][:MAX_ITEMS]}
        if scene["kind"] != "list":
            scene["items"] = []
        elif not scene["items"]:
            scene["kind"] = "statement"
        if scene["kind"] in ("statement", "quote") and not scene["text"]:   # these show their text; a lone heading becomes it
            scene["text"], scene["heading"] = scene["heading"], ""
        if not (scene["heading"] or scene["text"] or scene["items"]):
            continue
        asked = entry.get("seconds")
        seconds = float(asked) if isinstance(asked, (int, float)) and not isinstance(asked, bool) and asked > 0 else _usual_seconds(scene)
        seconds = max(seconds, 1.3 + _words(scene) * 0.2)   # never shorter than it takes to read
        scene["seconds"] = round(max(SCENE_SECONDS[0], min(SCENE_SECONDS[1], seconds)), 1)
        if len(scenes) == MAX_SCENES or total + scene["seconds"] > MAX_SECONDS:
            break
        total += scene["seconds"]
        scenes.append(scene)
    if not scenes:
        raise SequenceError("There is nothing to show: every scene is empty.")
    return scenes


def _scene_markup(scene):
    e = html.escape
    heading, text = e(scene["heading"]), e(scene["text"])
    if scene["kind"] == "list":
        return '{}{}<ul>{}</ul>'.format('<h2 class="a">{}</h2>'.format(heading) if heading else "",
                                        '<p class="a lead">{}</p>'.format(text) if text else "",
                                        "".join('<li class="a"><i></i><span>{}</span></li>'.format(e(item)) for item in scene["items"]))
    if scene["kind"] == "statement":
        words = "".join('<span class="w">{}</span> '.format(e(word)) for word in scene["text"].split())
        return '{}<p class="big">{}</p>'.format('<h3 class="a">{}</h3>'.format(heading) if heading else "", words)
    if scene["kind"] == "stat":
        return '<div class="figure a">{}</div>{}'.format(heading or text, '<p class="a">{}</p>'.format(text) if heading and text else "")
    if scene["kind"] == "quote":
        return '<div class="mark a">&ldquo;</div><p class="said a">{}</p>{}'.format(text, '<h3 class="a">{}</h3>'.format(heading) if heading else "")
    return '<div class="bar"></div><h1 class="a">{}</h1>{}'.format(heading or text, '<p class="a">{}</p>'.format(text) if heading and text else "")


def page(scenes, look, width, height):
    """The HyperFrames composition for the scenes, as one HTML page. Returns (html, seconds)."""
    ground, ink, soft, mark = LOOKS.get(look, LOOKS["dark"])
    parts, plan, at = [], [], 0.0
    for n, scene in enumerate(scenes):
        parts.append('<section id="s{n}" class="clip scene {kind}" data-start="{at}" data-duration="{d}" data-track-index="{n}">{inner}</section>'.format(
            n=n, kind=scene["kind"], at=round(at, 3), d=scene["seconds"], inner=_scene_markup(scene)))
        plan.append({"id": "#s{}".format(n), "at": round(at, 3), "for": scene["seconds"], "kind": scene["kind"]})
        at += scene["seconds"]
    total = round(at, 3)
    return PAGE.format(width=width, height=height, total=total, ground=ground, ink=ink, soft=soft, mark=mark,
                       scenes="\n      ".join(parts), plan=json.dumps(plan)), total


PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="gsap.min.js"></script>
    <style>
      @font-face {{ font-family: Archivo; src: url("Archivo.woff2") format("woff2"); font-weight: 100 900; font-stretch: 62% 125%; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: {ground}; }}
      #root {{ position: relative; width: 100%; height: 100%; font-family: Archivo, ui-sans-serif, system-ui, sans-serif; color: {ink}; }}
      .scene {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 2.6vmin; padding: 9vmin 10vmin; text-align: center; }}
      .bar {{ width: 9vmin; height: 0.7vmin; background: {mark}; transform-origin: center; }}
      h1 {{ font-size: 9vmin; line-height: 1.05; font-weight: 680; letter-spacing: -0.02em; overflow-wrap: anywhere; }}
      h2 {{ font-size: 5.4vmin; line-height: 1.1; font-weight: 650; letter-spacing: -0.01em; margin-bottom: 1.4vmin; }}
      h3 {{ font-size: 2.8vmin; line-height: 1.3; font-weight: 550; color: {mark}; letter-spacing: 0.04em; text-transform: uppercase; }}
      p {{ font-size: 3.5vmin; line-height: 1.35; font-weight: 450; color: {soft}; }}
      p.big {{ font-size: 6.6vmin; line-height: 1.16; font-weight: 620; color: {ink}; letter-spacing: -0.015em; max-width: 92%; }}
      .w {{ display: inline-block; }}
      .end h1 {{ font-size: 7vmin; }}
      .list {{ align-items: flex-start; text-align: left; padding-left: 14vmin; padding-right: 14vmin; }}
      .lead {{ margin: -1.6vmin 0 1.2vmin; }}
      ul {{ list-style: none; display: grid; gap: 2.2vmin; }}
      li {{ display: flex; align-items: baseline; gap: 2.2vmin; font-size: 4.2vmin; line-height: 1.25; font-weight: 520; }}
      li i {{ flex: none; width: 1.5vmin; height: 1.5vmin; background: {mark}; transform: translateY(-0.5vmin); }}
      .figure {{ font-size: 21vmin; line-height: 1; font-weight: 740; letter-spacing: -0.04em; color: {mark}; }}
      .mark {{ font-size: 16vmin; line-height: 0.6; font-weight: 700; color: {mark}; height: 7vmin; }}
      .said {{ font-size: 5.2vmin; line-height: 1.25; font-weight: 520; color: {ink}; max-width: 90%; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{width}" data-height="{height}">
      {scenes}
    </div>
    <script>
      // Each scene brings its parts in one after another, holds, and fades before the next one starts.
      const plan = {plan};
      const tl = gsap.timeline({{ paused: true }});
      for (const scene of plan) {{
        const has = (pick) => document.querySelector(scene.id + " " + pick);
        if (has(".bar")) tl.fromTo(scene.id + " .bar", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.55, ease: "power3.out" }}, scene.at + 0.1);
        if (has(".a")) tl.fromTo(scene.id + " .a", {{ opacity: 0, y: 38 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out", stagger: 0.14 }}, scene.at + 0.18);
        if (has(".w")) tl.fromTo(scene.id + " .w", {{ opacity: 0, y: 26 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power2.out", stagger: 0.055 }}, scene.at + 0.3);
        if (scene.kind === "stat") tl.fromTo(scene.id + " .figure", {{ scale: 0.82 }}, {{ scale: 1, duration: 0.8, ease: "back.out(1.6)" }}, scene.at + 0.18);
        tl.to(scene.id, {{ opacity: 0, duration: 0.35, ease: "power1.in" }}, scene.at + scene.for - 0.35);
      }}
      tl.set({{}}, {{}}, {total});
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
