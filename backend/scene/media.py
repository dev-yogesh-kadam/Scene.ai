"""Video and audio helpers built on ffmpeg: last frame of a clip, joining clips, cutting audio, timeline export.

ffmpeg comes from the imageio-ffmpeg package (a bundled binary for macOS, Windows and Linux),
or from the system if that package is missing.
"""

import asyncio
import glob
import weakref
import re
import shutil
from pathlib import Path

FPS = 24


class MediaError(Exception):
    pass


def ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if not found:
            raise MediaError("ffmpeg is not installed. Run the start script again to install the packages.")
        return found


async def _ffmpeg(*args, check=True, cwd=None):
    """Run ffmpeg and return what it said. cwd: the folder it runs in, so a filter can name its files (subtitles, a
    font) without the escaping a full Windows path needs inside a filter."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-hide_banner", "-y", *[str(a) for a in args],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, cwd=cwd)
    try:
        _, stderr = await process.communicate()
    except asyncio.CancelledError:   # the job this was for was cancelled: don't leave ffmpeg running
        process.kill()
        raise
    text = stderr.decode("utf-8", "replace")
    if check and process.returncode != 0:
        raise MediaError("ffmpeg failed: " + text.strip()[-400:])
    return text


async def probe(path):
    """Length in seconds, frame size (0 if unknown) and whether the file has an audio stream."""
    text = await _ffmpeg("-i", path, check=False)
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)) if match else 0.0
    size = re.search(r"Stream #\S+.*Video:.*?\b(\d{2,5})x(\d{2,5})\b", text)
    return {"seconds": seconds, "audio": bool(re.search(r"Stream #\S+.*Audio:", text)),
            "width": int(size.group(1)) if size else 0, "height": int(size.group(2)) if size else 0}


async def last_frame(video, target):
    """Save the last frame of a video as an image."""
    await _ffmpeg("-loglevel", "error", "-sseof", "-1", "-i", video, "-update", "1", "-q:v", "1", target)
    return target


POSTER_WIDTH = 960


def poster_path(video):
    """Where a video's poster is kept: next to it, in a folder of its own."""
    return video.parent / ".posters" / (video.name + ".jpg")


# Posters made at once, at most: a canvas of new pictures asks for all of theirs together. One limit per event loop.
POSTERS_AT_ONCE = 3
_poster_gates = weakref.WeakKeyDictionary()


def _poster_gate():
    loop = asyncio.get_running_loop()
    if loop not in _poster_gates:
        _poster_gates[loop] = asyncio.Semaphore(POSTERS_AT_ONCE)
    return _poster_gates[loop]


async def poster(video):
    """A small still from the start of a video, or a small copy of a picture, for its thumbnail. Made once and kept."""
    target = poster_path(video)
    if target.is_file() and target.stat().st_mtime >= video.stat().st_mtime:
        return target
    async with _poster_gate():
        if target.is_file() and target.stat().st_mtime >= video.stat().st_mtime:   # made while this one waited
            return target
        return await _make_poster(video, target)


def remove_result(path):
    """Delete a finished file and what was made from it for its thumbnail: its poster and a video's keyframes."""
    path = Path(path)
    path.unlink(missing_ok=True)
    posters = path.parent / ".posters"
    if posters.is_dir():
        for made in posters.glob(glob.escape(path.name) + "*.jpg"):   # <name>.jpg and <name>.<tenth>.jpg
            made.unlink(missing_ok=True)


async def make_poster_soon(path):
    """Make a new result's poster now, so its thumbnail is ready when the page asks. Best effort."""
    try:
        await poster(path)
    except (MediaError, OSError):
        pass


async def _make_poster(video, target):
    target.parent.mkdir(exist_ok=True)
    target.unlink(missing_ok=True)
    scale = "scale='min({},iw)':-2".format(POSTER_WIDTH)
    for start in ("0.1", "0"):   # a clip shorter than 0.1 s has no frame there
        await _ffmpeg("-loglevel", "error", "-ss", start, "-i", video, "-frames:v", "1", "-vf", scale, "-q:v", "3",
                      "-update", "1", target, check=False)
        if target.is_file() and target.stat().st_size:
            return target
    raise MediaError("That video can't be read.")


async def frame_at(video, seconds, target, width=POSTER_WIDTH):
    """Save the frame of a video at `seconds` as a JPEG no wider than `width`. Returns the target, or None when the
    video has no frame there."""
    target.unlink(missing_ok=True)
    await _ffmpeg("-loglevel", "error", "-ss", "{:.3f}".format(max(0.0, seconds)), "-i", video, "-frames:v", "1",
                  "-vf", "scale='min({},iw)':-2".format(width), "-q:v", "3", "-update", "1", target, check=False)
    return target if target.is_file() and target.stat().st_size else None


async def cut_audio(source, start, seconds, target):
    """Save a piece of an audio (or video) file's sound as a WAV file."""
    await _ffmpeg("-loglevel", "error", "-ss", "{:.3f}".format(start), "-t", "{:.3f}".format(seconds),
                  "-i", source, "-vn", "-c:a", "pcm_s16le", target)
    return target


async def join(clips, target):
    """Join chained clips into one video.

    Each clip after the first starts on the last frame of the clip before it, so that repeated
    frame (and its 1/24 s of sound) is dropped.
    """
    with_audio = all([(await probe(clip))["audio"] for clip in clips])
    args, filters, labels = ["-loglevel", "error"], [], ""
    for i, clip in enumerate(clips):
        args += ["-i", clip]
        skip = "trim=start_frame=1," if i else ""
        filters.append("[{0}:v]{1}setpts=PTS-STARTPTS[v{0}]".format(i, skip))
        labels += "[v{}]".format(i)
        if with_audio:
            askip = "atrim=start={:.5f},".format(1 / FPS) if i else ""
            filters.append("[{0}:a]{1}asetpts=PTS-STARTPTS[a{0}]".format(i, askip))
            labels += "[a{}]".format(i)
    filters.append("{}concat=n={}:v=1:a={}[v]{}".format(labels, len(clips), int(with_audio), "[a]" if with_audio else ""))
    args += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if with_audio:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", target]
    await _ffmpeg(*args)
    return target


STILL_BITRATE = 60   # kb/s: a picture this thin may be one frame held still; anything richer is a real video

# A sound kept as it is, in the file type its codec belongs in; any other sound is made AAC in an .m4a.
SOUND_FILES = {"aac": ".m4a", "mp3": ".mp3", "flac": ".flac", "opus": ".ogg", "vorbis": ".ogg", "pcm_s16le": ".wav", "pcm_s24le": ".wav"}


async def sound_only(path):
    """Whether a video file is really a sound: it has sound, and its picture is cover art, or one frame that never
    changes from start to end (what some apps make when they export audio "as a video")."""
    text = await _ffmpeg("-i", path, check=False)
    if not re.search(r"Stream #\S+.*Audio:", text):
        return False
    video = re.search(r"Stream #\S+.*Video:.*", text)
    if not video:
        return True
    if "(attached pic)" in video.group(0):
        return True
    rate = re.search(r"(\d+) kb/s", video.group(0))
    if not rate or int(rate.group(1)) > STILL_BITRATE:
        return False
    # Thin enough to be a still: check that the picture really never moves.
    seconds = (await probe(path))["seconds"]
    said = await _ffmpeg("-i", path, "-map", "0:v:0", "-vf", "freezedetect=n=0.003:d=0.5", "-f", "null", "-", check=False)
    starts = [float(s) for s in re.findall(r"freeze_start: ([\d.]+)", said)]
    ends = [float(s) for s in re.findall(r"freeze_end: ([\d.]+)", said)]
    return bool(starts) and starts[0] <= 0.1 and (not ends or ends[-1] >= seconds - 0.2)


async def keep_sound(path, stem):
    """The sound of a file, without its picture, as a file of its own next to it: its codec copied when it fits a sound
    file, made AAC otherwise. stem: the new file's name without its type. Returns the new path."""
    text = await _ffmpeg("-i", path, check=False)
    codec = re.search(r"Stream #\S+.*Audio: (\w+)", text)
    suffix = SOUND_FILES.get(codec.group(1) if codec else "", ".m4a")
    target = Path(path).with_name(stem + suffix)
    copy = codec and codec.group(1) in SOUND_FILES
    await _ffmpeg("-loglevel", "error", "-i", path, "-map", "0:a:0", "-vn", *(["-c:a", "copy"] if copy else ["-c:a", "aac", "-b:a", "192k"]), target)
    return target


MUSIC_UNDER = 0.35   # how loud added music is against the video's own sound


async def add_sound(video, sound, target, replace=False):
    """Put a sound on a video and save the result as `target`. Returns its length in seconds.

    The picture is copied as it is, not encoded again. The sound is looped if it is shorter than the video,
    cut to the video's length, and faded out at the end. With replace it takes the place of the video's own
    sound; otherwise it is mixed under it (music under speech and effects)."""
    info = await probe(video)
    if not info["seconds"]:
        raise MediaError("That video can't be read.")
    length = info["seconds"]
    fade = "afade=t=in:d=0.3,afade=t=out:st={:.3f}:d=0.8".format(max(0.0, length - 0.8))
    if info["audio"] and not replace:
        mix = ("[1:a]volume={},{}[under];[0:a][under]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
               .format(MUSIC_UNDER, fade))
    else:
        mix = "[1:a]{}[a]".format(fade)
    await _ffmpeg("-loglevel", "error", "-i", video, "-stream_loop", "-1", "-i", sound, "-filter_complex", mix,
                  "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-t", "{:.3f}".format(length), "-movflags", "+faststart", target)
    return length


async def sequence(parts, target):
    """Join any videos into one, each cut to its (start, end) seconds. Returns the length in seconds.

    Unlike join, the clips need not match: every clip is fitted into the frame of the first one,
    and a clip without sound gets silence when any other clip has sound.
    """
    infos = [await probe(path) for path, _, _ in parts]
    width, height = (infos[0]["width"] or 1280) // 2 * 2, (infos[0]["height"] or 720) // 2 * 2
    with_audio = any(info["audio"] for info in infos)
    args, filters, labels, total = ["-loglevel", "error"], [], "", 0.0
    for i, ((path, start, end), info) in enumerate(zip(parts, infos)):
        if not info["seconds"]:
            raise MediaError("{} can't be read as a video.".format(path.name))
        end = min(end or info["seconds"], info["seconds"])
        start = max(0.0, min(start or 0.0, end))
        if end - start < 1 / FPS:
            raise MediaError("A clip on the timeline is cut down to nothing.")
        total += end - start
        args += ["-i", path]
        filters.append(
            "[{i}:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,fps={fps},"
            "scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
            .format(i=i, s=start, e=end, fps=FPS, w=width, h=height))
        labels += "[v{}]".format(i)
        if with_audio:
            sound = ("[{i}:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,".format(i=i, s=start, e=end)
                     if info["audio"] else "anullsrc=r=48000:cl=stereo,atrim=duration={:.3f},".format(end - start))
            filters.append(sound + "aresample=48000,aformat=channel_layouts=stereo[a{}]".format(i))
            labels += "[a{}]".format(i)
    filters.append("{}concat=n={}:v=1:a={}[v]{}".format(labels, len(parts), int(with_audio), "[a]" if with_audio else ""))
    args += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if with_audio:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", target]
    await _ffmpeg(*args)
    return total
