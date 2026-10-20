"""Transcripts and the clock of a film made on its audio.

parse(): a transcript file — the JSON a transcription workflow writes ({"segments": [{"start", "end", "speaker",
"text"}]}) or an .srt — as its lines, with their times exactly as the file gives them. grid(): the frames of every
shot of a plan, from the line (or sound, or wordless gap) each shot starts on, by the rules of Pocket Motion's step
5.3. Both are worked out here, never by the model: a time is copied, not retyped.
"""

import json
import re

FPS = 24
GAP_TAIL = 0.5      # a line keeps this much of the silence after it before a wordless gap's own shots begin
SHORTEST = 1.2      # a shot under this does not read
LONGEST = 3.5       # a shot past this breaks the pace (a wordless gap's shots and an opening wide excepted)

SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
SPEAKER = re.compile(r"^\s*([A-Za-z][\w .'-]{0,40}):\s+(.+)$", re.S)


class TranscriptError(ValueError):
    pass


def _seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse(text):
    """[{"start", "end", "speaker", "text"}] in file order, times in seconds (3 decimals)."""
    text = text.lstrip("﻿").strip()
    if not text:
        raise TranscriptError("The transcript is empty.")
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except ValueError:
            raise TranscriptError("The transcript is not valid JSON.")
        segments = data.get("segments") if isinstance(data, dict) else data
        if not isinstance(segments, list):
            raise TranscriptError('A JSON transcript holds "segments": a list of {start, end, speaker, text}.')
        lines = []
        for seg in segments:
            if not isinstance(seg, dict) or not isinstance(seg.get("start"), (int, float)) or not isinstance(seg.get("end"), (int, float)):
                continue
            words = " ".join(str(seg.get("text") or "").split())
            if words:
                lines.append({"start": round(float(seg["start"]), 3), "end": round(float(seg["end"]), 3),
                              "speaker": str(seg.get("speaker") or "")[:60], "text": words})
    else:
        lines = []
        for block in re.split(r"\n\s*\n", text.replace("\r", "")):
            found = SRT_TIME.search(block)
            if not found:
                continue
            words = " ".join(block[found.end():].split())
            speaker = ""
            named = SPEAKER.match(words)
            if named:
                speaker, words = named.group(1).strip(), named.group(2).strip()
            if words:
                g = found.groups()
                lines.append({"start": round(_seconds(*g[:4]), 3), "end": round(_seconds(*g[4:]), 3), "speaker": speaker, "text": words})
    if not lines:
        raise TranscriptError("No timed lines were found in the transcript.")
    return lines


FROM = re.compile(r"^(?:L(\d+)|sfx@(\d+(?:\.\d+)?)|gap@L(\d+)|gap@start|gap@end)$")


def grid(units, lines, speech, length):
    """The frames of every shot: {unit: {"f_in", "f_out"}}, and the problems found [str].

    units: [{"id", "from"}] in plan order, "from" being L<n> (the line it starts on), sfx@<seconds> (a sound),
    gap@L<n> (a wordless gap after line n), gap@start or gap@end. lines: {n: {"start", "end"}}. speech: {n: [s, e]},
    the measured speech of character lines, which wins over the line's own times. length: the master's seconds.

    A shot starts on its line's measured start; the first starts at 0. Shots meet with no gap and the last ends at
    the master's end. The shots of one wordless gap share it evenly, from GAP_TAIL after the line before it to the
    next line's start (gap@start from 0, gap@end to the end)."""
    problems = []
    starts = {n: float((speech.get(n) or [l["start"]])[0]) for n, l in lines.items()}
    ends = {n: float((speech.get(n) or [None, l["end"]])[1]) for n, l in lines.items()}
    order = sorted(lines)
    after = {n: next((m for m in order if m > n), None) for n in order}
    gaps = {}   # which gap a unit is in -> the units in it, in order
    tc = {}
    for unit in units:
        found = FROM.match(str(unit.get("from") or ""))
        if not found:
            problems.append("{}: its from “{}” is not L<n>, sfx@<s>, gap@L<n>, gap@start or gap@end.".format(unit["id"], unit.get("from")))
            continue
        line, sound, gap_after = found.group(1), found.group(2), found.group(3)
        if line:
            n = int(line)
            if n not in starts:
                problems.append("{}: line L{} is not in the transcript.".format(unit["id"], n))
                continue
            tc[unit["id"]] = starts[n]
        elif sound:
            tc[unit["id"]] = float(sound)
        else:
            key = "start" if unit["from"] == "gap@start" else "end" if unit["from"] == "gap@end" else int(gap_after)
            if isinstance(key, int) and key not in starts:
                problems.append("{}: line L{} is not in the transcript.".format(unit["id"], key))
                continue
            gaps.setdefault(key, []).append(unit["id"])
    for key, members in gaps.items():
        if key == "start":
            a, b = 0.0, starts[order[0]] if order else length
        elif key == "end":
            a, b = (ends[order[-1]] + GAP_TAIL if order else 0.0), length
        else:
            a, b = ends[key] + GAP_TAIL, starts[after[key]] if after[key] is not None else length
        if b <= a:
            problems.append("The gap after {} has no room for its shots ({} to {} s).".format(key, round(a, 3), round(b, 3)))
            continue
        for i, unit_id in enumerate(members):
            tc[unit_id] = a + (b - a) * i / len(members)
    placed = [u["id"] for u in units if u["id"] in tc]
    if not placed:
        return {}, problems or ["No shot could be placed."]
    frames = {}
    total = round(length * FPS)
    for i, unit_id in enumerate(placed):
        f_in = 0 if i == 0 else round(tc[unit_id] * FPS)
        f_out = total if i == len(placed) - 1 else round(tc[placed[i + 1]] * FPS)
        frames[unit_id] = {"f_in": f_in, "f_out": f_out}
        if f_out <= f_in:
            problems.append("{} starts after the shot that follows it: check their from lines.".format(unit_id))
    opening = {u["id"] for u in units if str(u.get("from") or "").startswith("gap@")}
    for unit_id, f in frames.items():
        seconds = (f["f_out"] - f["f_in"]) / FPS
        if 0 < seconds < SHORTEST:
            problems.append("{} lasts {:.2f} s, under {} s: merge it into a neighbour.".format(unit_id, seconds, SHORTEST))
        elif seconds > LONGEST and unit_id not in opening and unit_id != placed[0]:
            problems.append("{} lasts {:.2f} s, over {} s: split it at its next clause.".format(unit_id, seconds, LONGEST))
    return frames, problems
