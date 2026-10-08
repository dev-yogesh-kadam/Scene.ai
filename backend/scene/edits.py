"""Work done on this machine, not on the render server: joining a timeline, putting a sound on a video, and
drawing motion graphics. Each is a job in the queue, filed under an "edit/..." workflow that has no workflow file.

The request that queues one checks it and writes what is to be done into the job's settings; `run` carries it out.
"""

import time

from . import credits, media, motion

TIMELINE = "edit/timeline"   # the clips of a timeline joined into one video
SOUND = "edit/sound"         # a sound put on a video
MOTION = credits.MOTION      # a motion graphic drawn by HyperFrames
TITLES = {TIMELINE: "Timeline export", SOUND: "Sound on a video", MOTION: "Motion graphics"}


def is_edit(workflow_id):
    return workflow_id.startswith("edit/")


async def run(job, folder, db, node_path="", tmp_dir=None):
    """Carry out one edit job. `folder` is where the user's finished work is kept.
    Returns (the file that was made, its context: length and frame size)."""
    def item(item_id, kind="video"):
        """One of the user's library items and its file. It may have been deleted since the job was queued."""
        row = db.one("SELECT * FROM generations WHERE id = ? AND user_id = ? AND kind = ?", (item_id, job["user_id"], kind))
        if row is None or not (folder / row["filename"]).is_file():
            raise media.MediaError("{} this was to be made from is no longer in the library.".format("A video" if kind == "video" else "The sound"))
        return folder / row["filename"]

    make = {TIMELINE: _timeline, SOUND: _sound, MOTION: _motion}.get(job["workflow"])
    if make is None:
        raise media.MediaError("There is no edit named '{}'.".format(job["workflow"]))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "{}_{}_{}.mp4".format(job["workflow"].split("/", 1)[1], time.strftime("%Y%m%d_%H%M%S"), job["id"][:4])
    try:
        made = await make(job["settings"], item, target, node_path, tmp_dir)
    except BaseException:   # a failure or a cancel: leave no half-written file behind
        target.unlink(missing_ok=True)
        raise
    return target, {"duration": round(made["seconds"], 1), "width": made["width"], "height": made["height"]}


async def _timeline(settings, item, target, node_path, tmp_dir):
    parts = [(item(clip["id"]), clip["start"], clip["end"]) for clip in settings["clips"]]
    seconds = await media.sequence(parts, target)
    return dict(await media.probe(target), seconds=seconds)


async def _sound(settings, item, target, node_path, tmp_dir):
    seconds = await media.add_sound(item(settings["video"]), item(settings["audio"], "audio"), target, settings["replace"])
    return dict(await media.probe(target), seconds=seconds)


async def _motion(settings, item, target, node_path, tmp_dir):
    if "scenes" in settings:
        return await motion.render_sequence(settings["scenes"], settings["look"], settings["shape"], target, node_path, tmp_dir)
    source = item(settings["parent"]) if settings.get("parent") else None
    return await motion.render(settings["template"], dict(settings["values"]), target, source, node_path, tmp_dir)
