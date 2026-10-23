"""What a failed job's error means, in plain words: for the admin console (the job's details) and for the person whose
job it was (the canvas shows a failed job with its reason)."""

import re

# What a failed job's error means, in words for the admin: (part of the message, explanation). The first match wins.
PLAIN_ERRORS = [
    ("out of memory", "The render PC ran out of graphics memory. A shorter clip, a lower resolution or a lower quality fits."),
    ("allocation on device", "The render PC ran out of graphics memory. A shorter clip, a lower resolution or a lower quality fits."),
    ("app was restarted", "The studio app was restarted while this job ran, so it could not finish."),
    ("lost the connection to comfyui", "The render server stopped answering while this job ran: it was turned off, restarted or lost its network."),
    ("can't be reached", "The render server could not be reached."),
    ("interrupted in comfyui", "It was stopped in ComfyUI itself, not from the studio."),
    ("saved no", "The workflow finished but saved no picture, video or sound. Its Save node may be missing or switched off."),
    ("value not in list", "The workflow asked for a model or file the render server does not have."),
    ("prompt outputs failed validation", "ComfyUI refused the workflow before running it: a setting or a model file is missing on the render server."),
    ("hyperframes", "The motion graphic could not be drawn on this machine."),
    ("ffmpeg", "Joining or cutting the video failed on this machine."),
    ("seed must be between", "A setting of the workflow was out of the range one of its steps takes (the seed)."),
]


def explain(error):
    if not error:
        return ""
    low = error.lower()
    for words, meaning in PLAIN_ERRORS:
        if words in low:
            return meaning
    node = re.match(r"ComfyUI error in node '([^']*)'", error)
    if node:
        return "A step of the workflow failed on the render server ({}).".format(node.group(1))
    return ""


def for_user(error):
    """The reason a job failed, as the person whose job it was reads it: the plain meaning when it is known, or a
    general one; never ComfyUI's own words, which name nodes and files."""
    return explain(error) or ("Something went wrong on the render server while it was making this." if error else "")
