"""Video and audio helpers built on ffmpeg: last frame of a clip, joining clips, cutting audio, timeline export.

ffmpeg comes from the imageio-ffmpeg package (a bundled binary for macOS, Windows and Linux),
or from the system if that package is missing.
"""

import asyncio
import re
import shutil

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


async def _ffmpeg(*args, check=True):
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-hide_banner", "-y", *[str(a) for a in args],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, stderr = await process.communicate()
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
