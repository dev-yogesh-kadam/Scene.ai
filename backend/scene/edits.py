"""Work done on this machine, not on the render server: joining a timeline, putting a sound on a video, drawing
motion graphics, and the frame-exact work of a film made on its audio (film.py). Each is a job in the queue, filed
under an "edit/..." workflow that has no workflow file.

The request that queues one checks it and writes what is to be done into the job's settings; `run` carries it out.
"""

import time
from pathlib import Path

from . import credits, film, media, motion, runs

TIMELINE = "edit/timeline"   # the clips of a timeline joined into one video
SOUND = "edit/sound"         # a sound put on a video
MOTION = credits.MOTION      # a motion graphic drawn by HyperFrames
ASSEMBLE = "edit/assemble"   # the finished cut: shots in order with a title card, an end card and music
# The film operations: op -> (workflow, title, the result's file type, its kind in the library)
FILM = {
    "reference": ("edit/reference", "Reference at 1500 px", ".png", "image"),
    "slice": ("edit/slice", "Audio slice", ".wav", "audio"),
    "track": ("edit/track", "Timing track", ".mp4", "video"),
    "trim": ("edit/trim", "Trim to frames", ".mp4", "video"),
    "retime": ("edit/retime", "Lips retimed to the master", ".mp4", "video"),
    "proof": ("edit/proof", "Proof sheets", ".png", "image"),
    "subtitles": ("edit/subtitles", "Subtitles burned in", ".mp4", "video"),
    "film": ("edit/film", "Film on the master audio", ".mp4", "video"),
    "speech": ("edit/speech", "Speech spans", ".json", "text"),
}
TITLES = {TIMELINE: "Timeline export", SOUND: "Sound on a video", MOTION: "Motion graphics", ASSEMBLE: "Final cut",
          **{workflow: title for workflow, title, _, _ in FILM.values()}}


def is_edit(workflow_id):
    return workflow_id.startswith("edit/")


async def run(job, folder, db, node_path="", tmp_dir=None):
    """Carry out one edit job. `folder` is where the user's finished work is kept.
    Returns what was made: [(file, kind in the library, context: length and frame size)], most often one file."""
    def item(item_id, kind="video"):
        """One of the user's library items and its file. It may have been deleted since the job was queued.
        kind: "video", "image", "audio", or "sound" for an audio item or a video whose sound is wanted."""
        kinds = ("audio", "video") if kind == "sound" else (kind,)
        row = db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind IN ({})".format(", ".join("?" * len(kinds))),
                     (item_id, job["user_id"], *kinds))
        if row is None or not (folder / row["filename"]).is_file():
            raise media.MediaError("{} this was to be made from is no longer in the library.".format(
                {"video": "A video", "image": "A picture"}.get(kind, "The sound")))
        return folder / row["filename"]

    op = next((name for name, entry in FILM.items() if entry[0] == job["workflow"]), None)
    make = {TIMELINE: _timeline, SOUND: _sound, MOTION: _motion, ASSEMBLE: _assemble}.get(job["workflow"]) or (_film if op else None)
    if make is None:
        raise media.MediaError("There is no edit named '{}'.".format(job["workflow"]))
    suffix, kind = (FILM[op][2], FILM[op][3]) if op else (".mp4", "video")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "{}_{}_{}{}".format(job["workflow"].split("/", 1)[1], time.strftime("%Y%m%d_%H%M%S"), job["id"][:4], suffix)
    try:
        made = await make(dict(job["settings"], op=op) if op else job["settings"], item, target, node_path, tmp_dir)
    except BaseException:   # a failure or a cancel: leave no half-written file behind
        for path in [target, *target.parent.glob(target.stem + "_*" + suffix)]:
            path.unlink(missing_ok=True)
        raise
    files = made.pop("files", None) or [target]
    found = made.pop("found", None)
    if found and job["settings"].get("save_to") and job["settings"].get("run"):   # the speech spans, kept in the run
        runs.write_many(db, job["user_id"], job["settings"]["run"], job["settings"]["save_to"],
                        {str(n): span for n, span in found.items()}, "speech", replace=True)
    context = {"duration": round(made["seconds"], 1), "width": made["width"], "height": made["height"],
               **{k: v for k, v in made.items() if k not in ("seconds", "width", "height")}}
    return [(path, kind, context) for path in files]


async def _timeline(settings, item, target, node_path, tmp_dir):
    parts = [(item(clip["id"]), clip["start"], clip["end"]) for clip in settings["clips"]]
    seconds = await media.sequence(parts, target)
    return dict(await media.probe(target), seconds=seconds)


async def _assemble(settings, item, target, node_path, tmp_dir):
    """The shots in order, a title card before and an end card after, music mixed under all of it. The cards are drawn
    by HyperFrames in the shape of the shots; the files made on the way are removed."""
    spare = []

    async def card(scene, label):
        path = Path(target).with_name("{}_{}.mp4".format(Path(target).stem, label))
        spare.append(path)
        await motion.render_sequence([scene], settings["look"], settings["shape"], path, node_path, tmp_dir)
        return path

    try:
        parts = []
        if settings.get("title"):
            parts.append((await card(settings["title"], "title"), 0.0, 0.0))
        parts += [(item(clip["id"]), clip["start"], clip["end"]) for clip in settings["clips"]]
        if settings.get("end"):
            parts.append((await card(settings["end"], "end"), 0.0, 0.0))
        joined = Path(target).with_name(Path(target).stem + "_joined.mp4") if settings.get("music") else target
        if joined is not target:
            spare.append(joined)
        seconds = await media.sequence(parts, joined)
        if settings.get("music"):
            await media.add_sound(joined, item(settings["music"], "audio"), target, False)
    finally:
        for path in spare:
            path.unlink(missing_ok=True)
    return dict(await media.probe(target), seconds=seconds)


async def _sound(settings, item, target, node_path, tmp_dir):
    seconds = await media.add_sound(item(settings["video"]), item(settings["audio"], "audio"), target, settings["replace"])
    return dict(await media.probe(target), seconds=seconds)


async def _motion(settings, item, target, node_path, tmp_dir):
    if "scenes" in settings:
        return await motion.render_sequence(settings["scenes"], settings["look"], settings["shape"], target, node_path, tmp_dir)
    source = item(settings["parent"]) if settings.get("parent") else None
    return await motion.render(settings["template"], dict(settings["values"]), target, source, node_path, tmp_dir)


async def _film(settings, item, target, node_path, tmp_dir):
    """One film operation (film.py), its settings checked when it was queued (api/film.py)."""
    op = settings["op"]
    if op == "reference":
        return await film.reference(item(settings["image"], "image"), target)
    if op == "slice":
        return await film.audio_slice(item(settings["audio"], "sound"), settings["f_in"], settings["f_out"], target)
    if op == "track":
        return await film.timing_track(settings["frames"], target)
    if op == "trim":
        return await film.trim(item(settings["video"]), settings["frames"], target, settings["stretch"], settings["size"], settings["max_pad"])
    if op == "retime":
        video = item(settings["video"])
        segments = film.segment_map(settings["lines"], settings["frames"] / media.FPS, (await media.probe(video))["seconds"])
        return dict(await film.retime(video, segments, settings["frames"], target, settings["size"]), segments=segments)
    if op == "proof":
        sheets = await film.proof_sheets(item(settings["video"]), settings["marks"], target)
        found = await media.probe(sheets[0])
        return {"seconds": 0, "width": found["width"], "height": found["height"], "files": sheets}
    if op == "subtitles":
        cues = film.subtitle_cues(settings["lines"], settings["narrator"])
        return dict(await film.burn_subtitles(item(settings["video"]), cues, target), cue_list=cues)
    if op == "film":
        return await film.join_on_master([item(i) for i in settings["clips"]], item(settings["audio"], "sound"), target)
    if op == "speech":
        source = item(settings["audio"], "sound")
        if settings.get("lines"):
            found = await film.speech_spans(source, settings["lines"])
        else:
            found = {"runs": await film.speech_runs(source, settings["windows"])}
        film.write_json(found, target)
        return {"seconds": 0, "width": 0, "height": 0, "spans": len(found) if settings.get("lines") else None,
                "found": found if settings.get("save_to") else None}
    raise media.MediaError("There is no film operation named '{}'.".format(op))
